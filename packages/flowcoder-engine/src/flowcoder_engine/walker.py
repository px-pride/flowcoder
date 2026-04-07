"""Graph walker — executes a flowchart by walking blocks."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shlex
import time
from asyncio.subprocess import PIPE
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from flowcoder_flowchart import (
    BashBlock,
    BlockBase,
    BlockType,
    BranchBlock,
    CommandBlock,
    Flowchart,
    PromptBlock,
    RefreshBlock,
    VariableBlock,
    VariableType,
)
from opentelemetry import trace

from .json_parser import parse_json_from_response
from .resolver import CommandNotFoundError, resolve_command
from .templates import evaluate_template

if TYPE_CHECKING:
    from pathlib import Path

    from .protocol import ProtocolHandler
    from .session import Session

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)

SOFT_TIMEOUT_SECONDS = 300  # 5 minutes — log warning, don't kill
MAX_RECURSION_DEPTH = 10


class ExecutionError(Exception):
    pass


@dataclass
class BlockResult:
    success: bool = True
    output: str = ""
    error: str = ""
    branch_taken: bool | None = None

    @classmethod
    def ok(cls, output: str = "", branch_taken: bool | None = None) -> BlockResult:
        return cls(success=True, output=output, branch_taken=branch_taken)

    @classmethod
    def fail(cls, error: str) -> BlockResult:
        return cls(success=False, error=error)


@dataclass
class LogEntry:
    block_id: str
    block_name: str
    block_type: str
    result: BlockResult
    duration_ms: int = 0


@dataclass
class ExecutionResult:
    variables: dict[str, Any]
    log: list[LogEntry]
    status: str  # "completed" | "halted" | "error"
    duration_ms: int = 0


_COMPARISON_RE = re.compile(
    r"^\s*(.+?)\s+(==|!=|>=|<=|>|<)\s+(.+?)\s*$"
)


def _is_truthy(value: Any) -> bool:
    """Test truthiness the same way Pride does."""
    if value is None:
        return False
    s = str(value).lower().strip()
    return bool(value) and s not in ("false", "0", "no", "")


def _coerce_numeric(s: str) -> float | str:
    """Try to interpret a string as a number; return as-is on failure."""
    try:
        return float(s)
    except (ValueError, TypeError):
        return s


def _evaluate_condition(condition: str, variables: dict[str, Any]) -> bool:
    """Evaluate a branch condition string.

    Supports:
    - Simple variable truthiness: ``fullyImplemented``
    - Negation: ``!hasErrors``
    - Comparison: ``exitCode == 0``, ``count > 5``, ``status != "done"``

    Template substitution (``{{var}}``, ``$N``) should be done *before*
    calling this function so that comparison values are already resolved.
    """
    cond = condition.strip()

    # Negation: !varname
    if cond.startswith("!"):
        inner = cond[1:].strip()
        return not _is_truthy(variables.get(inner))

    # Comparison operators
    m = _COMPARISON_RE.match(cond)
    if m:
        lhs_raw, op, rhs_raw = m.group(1), m.group(2), m.group(3)

        # Strip surrounding quotes from RHS if present
        rhs_str = rhs_raw.strip("\"'")

        # Resolve LHS from variables (could be a variable name or literal)
        lhs_val = variables.get(lhs_raw, lhs_raw)

        # Coerce both sides for numeric comparison
        lhs_num = _coerce_numeric(str(lhs_val))
        rhs_num = _coerce_numeric(rhs_str)

        # If both are numbers, compare numerically
        if isinstance(lhs_num, float) and isinstance(rhs_num, float):
            match op:
                case "==": return lhs_num == rhs_num
                case "!=": return lhs_num != rhs_num
                case ">":  return lhs_num > rhs_num
                case "<":  return lhs_num < rhs_num
                case ">=": return lhs_num >= rhs_num
                case "<=": return lhs_num <= rhs_num

        # String comparison fallback
        lhs_s = str(lhs_val)
        match op:
            case "==": return lhs_s == rhs_str
            case "!=": return lhs_s != rhs_str
            case ">":  return lhs_s > rhs_str
            case "<":  return lhs_s < rhs_str
            case ">=": return lhs_s >= rhs_str
            case "<=": return lhs_s <= rhs_str

    # Simple variable lookup (original behavior)
    return _is_truthy(variables.get(cond))


class GraphWalker:
    """Walks a flowchart graph, executing blocks."""

    def __init__(
        self,
        flowchart: Flowchart,
        session: Session,
        variables: dict[str, Any],
        protocol: ProtocolHandler,
        max_blocks: int = 1000,
        call_stack: list[str] | None = None,
        max_depth: int = MAX_RECURSION_DEPTH,
        search_paths: list[str | Path] | None = None,
    ) -> None:
        self._flowchart = flowchart
        self._session = session
        self._variables = variables
        self._protocol = protocol
        self._log: list[LogEntry] = []
        self._halted = False
        self._blocks_executed = 0
        self._max_blocks = max_blocks
        self._call_stack = call_stack or []
        self._max_depth = max_depth
        self._search_paths = search_paths or []

    async def run(self) -> ExecutionResult:
        """Execute the flowchart from start to end."""
        with _tracer.start_as_current_span(
            "flowchart.run",
            attributes={
                "flowchart.name": self._flowchart.name,
                "flowchart.block_count": len(self._flowchart.blocks),
            },
        ) as run_span:
            start_time = time.monotonic()
            current = self._find_start_block()

            while current and not self._halted:
                if self._blocks_executed >= self._max_blocks:
                    raise ExecutionError(
                        f"Safety limit: exceeded {self._max_blocks} blocks"
                    )

                self._blocks_executed += 1
                self._protocol.emit_block_start(
                    current.id, current.name, current.type
                )
                self._protocol.log(
                    f"Executing block \"{current.name}\" "
                    f"({current.type}, session={current.session})"
                )

                block_start = time.monotonic()
                result = await self._execute_block(current)
                block_ms = int((time.monotonic() - block_start) * 1000)

                # Soft timeout warning
                if block_ms > SOFT_TIMEOUT_SECONDS * 1000:
                    self._protocol.log(
                        f"WARNING: Block \"{current.name}\" took {block_ms}ms "
                        f"(>{SOFT_TIMEOUT_SECONDS}s soft timeout)"
                    )

                entry = LogEntry(
                    block_id=current.id,
                    block_name=current.name,
                    block_type=current.type,
                    result=result,
                    duration_ms=block_ms,
                )
                self._log.append(entry)

                self._protocol.emit_block_complete(
                    current.id, current.name, result.success
                )

                if not result.success:
                    self._halted = True
                    break

                current = self._next_block(current, result)

            total_ms = int((time.monotonic() - start_time) * 1000)
            status = "completed" if not self._halted else "halted"
            run_span.set_attributes({"flowchart.status": status, "flowchart.duration_ms": total_ms})
            return ExecutionResult(
                variables=self._variables,
                log=self._log,
                status=status,
                duration_ms=total_ms,
            )

    async def _execute_block(self, block: BlockBase) -> BlockResult:
        """Dispatch to the appropriate handler based on block type."""
        with _tracer.start_as_current_span(
            "flowchart.block",
            attributes={"block.id": block.id, "block.name": block.name, "block.type": block.type},
        ):
            match block.type:
                case BlockType.START:
                    return BlockResult.ok()
                case BlockType.END:
                    return BlockResult.ok()
                case BlockType.PROMPT:
                    assert isinstance(block, PromptBlock)
                    return await self._exec_prompt(block)
                case BlockType.BRANCH:
                    assert isinstance(block, BranchBlock)
                    return self._exec_branch(block)
                case BlockType.VARIABLE:
                    assert isinstance(block, VariableBlock)
                    return self._exec_variable(block)
                case BlockType.BASH:
                    assert isinstance(block, BashBlock)
                    return await self._exec_bash(block)
                case BlockType.COMMAND:
                    assert isinstance(block, CommandBlock)
                    return await self._exec_command(block)
                case BlockType.REFRESH:
                    assert isinstance(block, RefreshBlock)
                    return await self._exec_refresh(block)
                case _:
                    return BlockResult.fail(f"Unknown block type: {block.type}")

    async def _exec_prompt(self, block: PromptBlock) -> BlockResult:
        """Execute a prompt block: resolve template, send to session, collect response."""
        with _tracer.start_as_current_span("flowchart.exec_prompt", attributes={"block.name": block.name}):
            prompt_text = evaluate_template(block.prompt, self._variables)

            if block.session != "default":
                self._protocol.log(
                    f"WARNING: Multi-session not yet supported, "
                    f"block \"{block.name}\" requests session \"{block.session}\" "
                    f"— using main session"
                )

            # Append output schema instructions if specified
            if block.output_schema:
                schema_str = json.dumps(block.output_schema, indent=2)
                prompt_text += (
                    f"\n\nRespond with JSON matching this schema:\n"
                    f"```json\n{schema_str}\n```"
                )

            result = await self._session.query(
                prompt_text, block_id=block.id, block_name=block.name
            )

            # Save raw output to variable if requested
            if block.output_variable and result.response_text:
                self._variables[block.output_variable] = result.response_text

            # Parse structured output
            if block.output_schema and result.response_text:
                parsed = parse_json_from_response(result.response_text)
                if parsed:
                    self._variables.update(parsed)

            return BlockResult.ok(output=result.response_text)

    def _exec_branch(self, block: BranchBlock) -> BlockResult:
        """Evaluate a branch condition against variables.

        Supports:
        - Simple variable truthiness: ``fullyImplemented``
        - Negation: ``!hasErrors``
        - Comparison operators: ``exitCode == 0``, ``i < 3``, ``status != "done"``
        - Template refs in conditions: ``i < {{max}}``
        """
        # Resolve any {{var}} / $N templates in the condition text first
        condition = evaluate_template(block.condition, self._variables)
        truthy = _evaluate_condition(condition, self._variables)
        self._protocol.log(
            f"Branch \"{block.name}\": {block.condition} -> {truthy}"
        )
        return BlockResult.ok(branch_taken=truthy)

    def _exec_variable(self, block: VariableBlock) -> BlockResult:
        """Set a variable with type coercion."""
        raw = evaluate_template(block.variable_value, self._variables)

        try:
            match block.variable_type:
                case VariableType.STRING:
                    value: Any = raw
                case VariableType.NUMBER:
                    value = float(raw)
                case VariableType.BOOLEAN:
                    value = raw.lower() in ("true", "1", "yes")
                case VariableType.JSON:
                    value = json.loads(raw)
                case _:
                    value = raw
        except (ValueError, json.JSONDecodeError) as e:
            return BlockResult.fail(
                f"Variable '{block.variable_name}' type coercion failed: {e}"
            )

        self._variables[block.variable_name] = value
        return BlockResult.ok()

    async def _exec_bash(self, block: BashBlock) -> BlockResult:
        """Execute a shell command."""
        cmd = evaluate_template(block.command, self._variables)
        with _tracer.start_as_current_span(
            "flowchart.exec_bash",
            attributes={"block.name": block.name, "bash.command": cmd[:200]},
        ) as span:
            cwd = block.working_directory or None

            try:
                proc = await asyncio.create_subprocess_shell(
                    cmd, stdout=PIPE, stderr=PIPE, cwd=cwd
                )
                stdout, stderr = await proc.communicate()
            except Exception as e:
                span.set_status(trace.StatusCode.ERROR, str(e))
                return BlockResult.fail(f"Failed to run command: {e}")

            exit_code = proc.returncode or 0
            stdout_str = stdout.decode() if stdout else ""
            stderr_str = stderr.decode() if stderr else ""
            span.set_attribute("bash.exit_code", exit_code)

            # Store exit code variable
            if block.exit_code_variable:
                self._variables[block.exit_code_variable] = exit_code

            # Check exit code
            if exit_code != 0 and not block.continue_on_error:
                return BlockResult.fail(
                    f"Exit code {exit_code}: {stderr_str or stdout_str}"
                )

            # Capture output
            if block.capture_output and block.output_variable:
                output = stdout_str.strip()
                try:
                    match block.output_type:
                        case VariableType.NUMBER:
                            self._variables[block.output_variable] = float(output)
                        case VariableType.BOOLEAN:
                            self._variables[block.output_variable] = output.lower() in (
                                "true", "1", "yes",
                            )
                        case VariableType.JSON:
                            self._variables[block.output_variable] = json.loads(output)
                        case _:
                            self._variables[block.output_variable] = output
                except (ValueError, json.JSONDecodeError):
                    self._variables[block.output_variable] = output

            return BlockResult.ok(output=stdout_str)

    async def _exec_refresh(self, block: RefreshBlock) -> BlockResult:
        """Clear conversation history by restarting the session."""
        _tracer.start_span("flowchart.exec_refresh", attributes={"block.name": block.name}).end()
        await self._session.clear()
        self._protocol.log("Session cleared (conversation history reset)")
        return BlockResult.ok()

    async def _exec_command(self, block: CommandBlock) -> BlockResult:
        """Execute a sub-command (composition).

        Resolves the command by name, creates a child walker with scoped
        variables, and runs it. Recursion is tracked via the call stack.
        """
        depth = len(self._call_stack)
        with _tracer.start_as_current_span(
            "flowchart.exec_command",
            attributes={"command.name": block.command_name, "command.depth": depth},
        ) as span:
            if depth >= self._max_depth:
                return BlockResult.fail(
                    f"Max recursion depth ({self._max_depth}) exceeded. "
                    f"Call stack: {' -> '.join(self._call_stack)}"
                )

            # Check for direct recursion (same command already in stack)
            if block.command_name in self._call_stack:
                self._protocol.log(
                    f"WARNING: Recursive call to '{block.command_name}' "
                    f"(depth {depth}). Stack: {' -> '.join(self._call_stack)}"
                )

            # Resolve the command
            try:
                cmd = resolve_command(block.command_name, search_paths=self._search_paths)
            except CommandNotFoundError as e:
                span.set_status(trace.StatusCode.ERROR, str(e))
                return BlockResult.fail(str(e))

            # Build child variables
            child_vars: dict[str, Any] = {}
            if block.inherit_variables:
                child_vars = dict(self._variables)

            # Parse arguments and map to $1, $2, etc.
            if block.arguments:
                arg_text = evaluate_template(block.arguments, self._variables)
                try:
                    parts = shlex.split(arg_text)
                except ValueError:
                    parts = arg_text.split()
                for i, part in enumerate(parts, 1):
                    child_vars[f"${i}"] = part

            self._protocol.log(
                f"Entering sub-command '{block.command_name}' (depth {depth + 1})"
            )

            # Create child walker sharing the same session and protocol
            child_walker = GraphWalker(
                cmd.flowchart,
                self._session,
                child_vars,
                self._protocol,
                max_blocks=self._max_blocks,
                call_stack=[*self._call_stack, block.command_name],
                max_depth=self._max_depth,
                search_paths=self._search_paths,
            )

            child_result = await child_walker.run()

            self._protocol.log(
                f"Sub-command '{block.command_name}' finished: {child_result.status}"
            )

            if child_result.status != "completed":
                # Include the child's error for better diagnostics
                child_errors = [
                    e.result.error for e in child_result.log if e.result.error
                ]
                detail = child_errors[-1] if child_errors else child_result.status
                span.set_status(trace.StatusCode.ERROR, detail)
                return BlockResult.fail(
                    f"Sub-command '{block.command_name}' failed: {detail}"
                )

            # Merge output variables back into parent scope
            if block.merge_output:
                # Don't merge positional args ($1, $2, etc.) back
                for k, v in child_result.variables.items():
                    if not k.startswith("$"):
                        self._variables[k] = v

            return BlockResult.ok(output=json.dumps(child_result.variables))

    def _find_start_block(self) -> BlockBase | None:
        """Find the start block in the flowchart."""
        for block in self._flowchart.blocks.values():
            if block.type == BlockType.START:
                return block
        return None

    def _next_block(self, current: BlockBase, result: BlockResult) -> BlockBase | None:
        """Find the next block to execute based on connections."""
        if current.type == BlockType.END:
            return None

        outgoing = [
            c for c in self._flowchart.connections if c.source_id == current.id
        ]

        if current.type == BlockType.BRANCH:
            for conn in outgoing:
                if conn.is_true_path == result.branch_taken:
                    return self._flowchart.blocks.get(conn.target_id)
            return None

        # Non-branch: take the first (only) connection
        if outgoing:
            return self._flowchart.blocks.get(outgoing[0].target_id)
        return None
