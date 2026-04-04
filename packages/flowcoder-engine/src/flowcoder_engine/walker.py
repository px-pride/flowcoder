"""Graph walker — executes a flowchart by walking blocks.

Extended from leroux's flow-mono with:
- SpawnBlock, WaitBlock, ExitBlock handlers
- Halt/resume mechanism (_halt_requested flag)
- Git callback hooks (on_block_complete, on_git_tag)
- Spawned session tracking
"""

from __future__ import annotations

import asyncio
import json
import logging
import shlex
import time
from asyncio.subprocess import PIPE
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from flowcoder_flowchart import (
    BashBlock,
    Block,
    BlockBase,
    BlockType,
    BranchBlock,
    CommandBlock,
    EndBlock,
    ExitBlock,
    Flowchart,
    PromptBlock,
    RefreshBlock,
    SpawnBlock,
    StartBlock,
    VariableBlock,
    VariableType,
    WaitBlock,
)

from .json_parser import parse_json_from_response
from .protocol import ProtocolHandler
from .resolver import CommandNotFoundError, resolve_command
from .session import Session
from .templates import evaluate_template

logger = logging.getLogger(__name__)

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
    exit_code: int | None = None  # Set by ExitBlock

    @classmethod
    def ok(cls, output: str = "", branch_taken: bool | None = None) -> BlockResult:
        return cls(success=True, output=output, branch_taken=branch_taken)

    @classmethod
    def fail(cls, error: str) -> BlockResult:
        return cls(success=False, error=error)

    @classmethod
    def exit(cls, code: int = 0, message: str = "") -> BlockResult:
        return cls(success=True, output=message, exit_code=code)


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
    status: str  # "completed" | "halted" | "error" | "exited"
    exit_code: int = 0
    duration_ms: int = 0


# Type alias for git callback hooks
GitCallback = Callable[[str, str, dict[str, Any]], None] | None


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
        # Callback hooks
        on_block_complete: GitCallback = None,
        on_git_tag: GitCallback = None,
    ) -> None:
        self._flowchart = flowchart
        self._session = session
        self._variables = variables
        self._protocol = protocol
        self._log: list[LogEntry] = []
        self._halted = False
        self._halt_requested = False
        self._blocks_executed = 0
        self._max_blocks = max_blocks
        self._call_stack = call_stack or []
        self._max_depth = max_depth
        self._search_paths = search_paths or []
        # Spawned sessions tracking
        self._spawned_sessions: dict[str, Session] = {}
        self._spawned_tasks: dict[str, asyncio.Task] = {}
        self._spawned_results: dict[str, ExecutionResult] = {}
        # Git callbacks
        self._on_block_complete = on_block_complete
        self._on_git_tag = on_git_tag

    def halt(self) -> None:
        """Request the walker to halt after the current block."""
        self._halt_requested = True

    def resume(self) -> None:
        """Clear the halt flag so execution can continue."""
        self._halt_requested = False
        self._halted = False

    async def run(self) -> ExecutionResult:
        """Execute the flowchart from start to end."""
        start_time = time.monotonic()
        current = self._find_start_block()
        exit_code = 0

        while current and not self._halted:
            # Check halt request
            if self._halt_requested:
                self._halted = True
                break

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

            # Post-block git callback
            if result.success and self._on_block_complete:
                self._on_block_complete(current.id, current.name, {
                    "block_type": current.type,
                    "variables": dict(self._variables),
                })

            # Git tag callback
            git_tag = getattr(current, 'git_tag', None)
            if git_tag and result.success and self._on_git_tag:
                tag_text = evaluate_template(git_tag, self._variables)
                self._on_git_tag(current.id, tag_text, {
                    "block_name": current.name,
                })

            # Check for exit block
            if result.exit_code is not None:
                exit_code = result.exit_code
                break

            if not result.success:
                self._halted = True
                break

            current = self._next_block(current, result)

        total_ms = int((time.monotonic() - start_time) * 1000)

        if exit_code != 0:
            status = "exited"
        elif self._halted:
            status = "halted"
        else:
            status = "completed"

        # Clean up spawned sessions
        await self._cleanup_spawned()

        return ExecutionResult(
            variables=self._variables,
            log=self._log,
            status=status,
            exit_code=exit_code,
            duration_ms=total_ms,
        )

    async def _execute_block(self, block: BlockBase) -> BlockResult:
        """Dispatch to the appropriate handler based on block type."""
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
            case BlockType.SPAWN:
                assert isinstance(block, SpawnBlock)
                return await self._exec_spawn(block)
            case BlockType.WAIT:
                assert isinstance(block, WaitBlock)
                return await self._exec_wait(block)
            case BlockType.EXIT:
                assert isinstance(block, ExitBlock)
                return self._exec_exit(block)
            case _:
                return BlockResult.fail(f"Unknown block type: {block.type}")

    async def _exec_prompt(self, block: PromptBlock) -> BlockResult:
        """Execute a prompt block: resolve template, send to session, collect response."""
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
        """Evaluate a branch condition against variables."""
        value = self._variables.get(block.condition)
        truthy = bool(value) and str(value).lower() not in ("false", "0", "no", "")
        self._protocol.log(
            f"Branch \"{block.name}\": {block.condition}={value!r} -> {truthy}"
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
        cwd = block.working_directory or None

        try:
            proc = await asyncio.create_subprocess_shell(
                cmd, stdout=PIPE, stderr=PIPE, cwd=cwd
            )
            stdout, stderr = await proc.communicate()
        except Exception as e:
            return BlockResult.fail(f"Failed to run command: {e}")

        exit_code = proc.returncode or 0
        stdout_str = stdout.decode() if stdout else ""
        stderr_str = stderr.decode() if stderr else ""

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
        await self._session.clear()
        self._protocol.log("Session cleared (conversation history reset)")
        return BlockResult.ok()

    async def _exec_command(self, block: CommandBlock) -> BlockResult:
        """Execute a sub-command (composition).

        Resolves the command by name, creates a child walker with scoped
        variables, and runs it. Recursion is tracked via the call stack.
        """
        depth = len(self._call_stack)
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

        # Propagate git callbacks, optionally suppressing auto-git
        child_on_block_complete = self._on_block_complete
        if block.suppress_child_auto_git:
            child_on_block_complete = None

        # Create child walker sharing the same session and protocol
        child_walker = GraphWalker(
            cmd.flowchart,
            self._session,
            child_vars,
            self._protocol,
            max_blocks=self._max_blocks,
            call_stack=self._call_stack + [block.command_name],
            max_depth=self._max_depth,
            search_paths=self._search_paths,
            on_block_complete=child_on_block_complete,
            on_git_tag=self._on_git_tag,
        )

        child_result = await child_walker.run()

        self._protocol.log(
            f"Sub-command '{block.command_name}' finished: {child_result.status}"
        )

        # Store exit code if requested
        if block.exit_code_variable:
            self._variables[block.exit_code_variable] = child_result.exit_code

        if child_result.status not in ("completed", "exited"):
            child_errors = [
                e.result.error for e in child_result.log if e.result.error
            ]
            detail = child_errors[-1] if child_errors else child_result.status
            return BlockResult.fail(
                f"Sub-command '{block.command_name}' failed: {detail}"
            )

        # Merge output variables back into parent scope
        if block.merge_output:
            for k, v in child_result.variables.items():
                if not k.startswith("$"):
                    self._variables[k] = v

        return BlockResult.ok(output=json.dumps(child_result.variables))

    async def _exec_spawn(self, block: SpawnBlock) -> BlockResult:
        """Spawn a named agent sub-session running a command asynchronously.

        The spawned session runs in the background as an asyncio task.
        Use WaitBlock to wait for it to complete.
        """
        agent_name = evaluate_template(block.agent_name, self._variables)

        if agent_name in self._spawned_sessions:
            return BlockResult.fail(
                f"Agent '{agent_name}' is already spawned. "
                f"Wait for it before spawning again."
            )

        # Resolve the command to run
        try:
            cmd = resolve_command(block.command_name, search_paths=self._search_paths)
        except CommandNotFoundError as e:
            return BlockResult.fail(str(e))

        # Build child variables
        child_vars: dict[str, Any] = {}
        if block.inherit_variables:
            child_vars = dict(self._variables)

        if block.arguments:
            arg_text = evaluate_template(block.arguments, self._variables)
            try:
                parts = shlex.split(arg_text)
            except ValueError:
                parts = arg_text.split()
            for i, part in enumerate(parts, 1):
                child_vars[f"${i}"] = part

        # Determine which session the child walker uses.
        # If a model is specified, create a dedicated session for this agent.
        child_session = self._session
        if block.model:
            self._protocol.log(
                f"Spawning agent '{agent_name}' with model '{block.model}' "
                f"running command '{block.command_name}'"
            )
            child_session = Session(
                name=agent_name,
                claude_path=self._session._claude_path,
                opts={**self._session._opts, "model": block.model},
                protocol=self._protocol,
            )
            await child_session.start()
        else:
            self._protocol.log(
                f"Spawning agent '{agent_name}' running command '{block.command_name}'"
            )

        child_walker = GraphWalker(
            cmd.flowchart,
            child_session,
            child_vars,
            self._protocol,
            max_blocks=self._max_blocks,
            call_stack=self._call_stack + [f"spawn:{block.command_name}"],
            max_depth=self._max_depth,
            search_paths=self._search_paths,
        )

        # Run in background
        task = asyncio.create_task(child_walker.run())
        self._spawned_tasks[agent_name] = task
        self._spawned_sessions[agent_name] = child_session

        return BlockResult.ok(output=f"Spawned agent '{agent_name}'")

    async def _exec_wait(self, block: WaitBlock) -> BlockResult:
        """Wait for spawned agent sessions to complete."""
        wait_for = block.wait_for if block.wait_for else list(self._spawned_tasks.keys())

        if not wait_for:
            self._protocol.log("Wait block: no spawned agents to wait for")
            return BlockResult.ok()

        errors: list[str] = []
        for agent_name in wait_for:
            task = self._spawned_tasks.get(agent_name)
            if not task:
                errors.append(f"No spawned agent named '{agent_name}'")
                continue

            try:
                if block.timeout_seconds:
                    result = await asyncio.wait_for(
                        task, timeout=block.timeout_seconds
                    )
                else:
                    result = await task
            except asyncio.TimeoutError:
                errors.append(
                    f"Agent '{agent_name}' timed out after {block.timeout_seconds}s"
                )
                task.cancel()
                continue
            except Exception as e:
                errors.append(f"Agent '{agent_name}' failed: {e}")
                continue

            self._spawned_results[agent_name] = result
            self._protocol.log(
                f"Agent '{agent_name}' completed: {result.status} "
                f"(exit_code={result.exit_code})"
            )

            # Store exit code variable from the spawn block
            # We need to find the original spawn block for this agent
            for bid, b in self._flowchart.blocks.items():
                if isinstance(b, SpawnBlock):
                    spawn_agent = evaluate_template(b.agent_name, self._variables)
                    if spawn_agent == agent_name and b.exit_code_variable:
                        self._variables[b.exit_code_variable] = result.exit_code

            # Clean up — stop dedicated sessions (not the shared parent)
            spawned_session = self._spawned_sessions.get(agent_name)
            if spawned_session and spawned_session is not self._session:
                await spawned_session.stop()
            self._spawned_tasks.pop(agent_name, None)
            self._spawned_sessions.pop(agent_name, None)

        if errors:
            return BlockResult.fail("; ".join(errors))

        return BlockResult.ok()

    def _exec_exit(self, block: ExitBlock) -> BlockResult:
        """Handle an explicit exit with a given exit code."""
        message = evaluate_template(block.exit_message, self._variables) if block.exit_message else ""
        self._protocol.log(
            f"Exit block '{block.name}': code={block.exit_code}, message={message}"
        )
        return BlockResult.exit(code=block.exit_code, message=message)

    async def _cleanup_spawned(self) -> None:
        """Cancel and clean up any remaining spawned tasks and sessions."""
        for agent_name, task in list(self._spawned_tasks.items()):
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        # Stop dedicated sessions (not the shared parent)
        for agent_name, session in list(self._spawned_sessions.items()):
            if session is not self._session:
                await session.stop()
        self._spawned_tasks.clear()
        self._spawned_sessions.clear()

    def _find_start_block(self) -> BlockBase | None:
        """Find the start block in the flowchart."""
        for block in self._flowchart.blocks.values():
            if block.type == BlockType.START:
                return block
        return None

    def _next_block(self, current: BlockBase, result: BlockResult) -> BlockBase | None:
        """Find the next block to execute based on connections."""
        if current.type in (BlockType.END, BlockType.EXIT):
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
