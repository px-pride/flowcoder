"""Flowchart syntax analyzer for Commands tab syntax check.

Performs static analysis on flowcharts to detect errors and warnings:
- Errors: Botched <if></if> syntax, invalid exit codes, spawn-spawn without wait
- Warnings: Uninitialized variables, spawn-exit without wait
"""

import re
from dataclasses import dataclass
from typing import List, Set, Tuple, Dict, Optional

from src.models import (
    Flowchart,
    Block,
    BlockType,
    PromptBlock,
    VariableBlock,
    BashBlock,
    BranchBlock,
    CommandBlock,
    ExitBlock,
    SpawnBlock,
    WaitBlock,
)
from src.utils.variable_substitution import VariableSubstitution


@dataclass
class SyntaxIssue:
    level: str  # 'error' or 'warning'
    message: str
    block_id: str
    block_name: str


class FlowchartSyntaxAnalyzer:
    """Analyzes a flowchart for syntax errors and warnings.

    Checks (errors):
    - Botched <if></if> conditional syntax
    - Invalid exit codes in Exit blocks
    - Spawn to Spawn with same agent name without intervening Wait

    Checks (warnings):
    - Variables referenced before initialization
    - Spawn to Exit without intervening Wait
    """

    def analyze(
        self,
        flowchart: Flowchart,
        storage_service=None,
        visited_commands: Optional[Set[str]] = None,
    ) -> List[SyntaxIssue]:
        """Analyze flowchart for syntax issues.

        Args:
            flowchart: The flowchart to analyze
            storage_service: Optional storage service for recursive command analysis
            visited_commands: Set of already-visited command names (prevents infinite recursion)

        Returns:
            List of SyntaxIssue objects
        """
        issues: List[SyntaxIssue] = []
        defined_vars = self._collect_defined_variables(flowchart, issues)

        for block in flowchart.blocks.values():
            # Check variable references
            refs = self._collect_variable_references(block)
            undefined = refs - defined_vars
            if undefined:
                msg = (
                    "Uninitialized variables used: "
                    + ", ".join(sorted(undefined))
                )
                issues.append(SyntaxIssue(
                    level='warning',
                    message=msg,
                    block_id=block.id,
                    block_name=block.name
                ))

            # Check conditional syntax in all text fields
            self._check_conditional_syntax(block, issues)

            # Check Exit block validity
            if isinstance(block, ExitBlock):
                if not isinstance(block.exit_code, int):
                    issues.append(SyntaxIssue(
                        level='error',
                        message=f"Exit code must be an integer, got: {block.exit_code}",
                        block_id=block.id,
                        block_name=block.name,
                    ))

            # Check Spawn block validity
            if isinstance(block, SpawnBlock):
                if not block.agent_name:
                    issues.append(SyntaxIssue(
                        level='error',
                        message="Spawn block requires an agent name",
                        block_id=block.id,
                        block_name=block.name,
                    ))
                if not block.command_name:
                    issues.append(SyntaxIssue(
                        level='error',
                        message="Spawn block requires a command name",
                        block_id=block.id,
                        block_name=block.name,
                    ))

            # Check Wait block validity
            if isinstance(block, WaitBlock):
                if not block.entries:
                    issues.append(SyntaxIssue(
                        level='error',
                        message="Wait block requires at least one entry",
                        block_id=block.id,
                        block_name=block.name,
                    ))

        # Check spawn-spawn without wait (ERROR)
        self._check_spawn_wait_paths(flowchart, issues)

        # Recursively check command blocks if storage is available
        if storage_service and visited_commands is not None:
            for block in flowchart.blocks.values():
                if isinstance(block, CommandBlock) and block.command_name:
                    cmd_name = block.command_name
                    if cmd_name not in visited_commands:
                        visited_commands.add(cmd_name)
                        try:
                            cmd = storage_service.load_command(cmd_name)
                            child_issues = self.analyze(
                                cmd.flowchart,
                                storage_service=storage_service,
                                visited_commands=visited_commands,
                            )
                            # Prefix child issues with command name
                            for issue in child_issues:
                                issue.message = f"[/{cmd_name}] {issue.message}"
                            issues.extend(child_issues)
                        except Exception:
                            pass  # Command not found — separate issue

        return issues

    def _check_conditional_syntax(
        self, block: Block, issues: List[SyntaxIssue]
    ) -> None:
        """Check for botched <if></if> syntax in all text fields of a block."""
        texts = self._get_text_fields(block)
        for text in texts:
            if not text:
                continue
            errors = VariableSubstitution.validate_conditionals(text)
            for error in errors:
                issues.append(SyntaxIssue(
                    level='error',
                    message=f"Conditional syntax error: {error}",
                    block_id=block.id,
                    block_name=block.name,
                ))

    def _get_text_fields(self, block: Block) -> List[str]:
        """Get all text fields from a block that support variable substitution."""
        texts: List[str] = []
        if isinstance(block, PromptBlock):
            texts.append(block.prompt or '')
        elif isinstance(block, VariableBlock):
            texts.append(block.variable_value or '')
        elif isinstance(block, BashBlock):
            texts.append(block.command or '')
        elif isinstance(block, BranchBlock):
            texts.append(block.condition or '')
        elif isinstance(block, CommandBlock):
            texts.append(block.arguments or '')
            texts.append(block.command_name or '')
        elif isinstance(block, SpawnBlock):
            texts.append(block.arguments or '')
            texts.append(block.command_name or '')
            texts.append(block.agent_name or '')
        return texts

    def _check_spawn_wait_paths(
        self, flowchart: Flowchart, issues: List[SyntaxIssue]
    ) -> None:
        """Check for Spawn→Spawn (same agent) without Wait, and Spawn→Exit without Wait."""
        # Build adjacency list
        adjacency: Dict[str, List[str]] = {}
        for block_id in flowchart.blocks:
            adjacency[block_id] = []
        for conn in flowchart.connections:
            if conn.source_block_id in adjacency:
                adjacency[conn.source_block_id].append(conn.target_block_id)

        # Find all Spawn blocks and group by agent name
        spawn_blocks: Dict[str, List[SpawnBlock]] = {}
        for block in flowchart.blocks.values():
            if isinstance(block, SpawnBlock) and block.agent_name:
                spawn_blocks.setdefault(block.agent_name, []).append(block)

        # For each agent name with multiple spawns, check if there's a path
        # between spawns that doesn't pass through a Wait for that agent
        for agent_name, spawns in spawn_blocks.items():
            if len(spawns) < 2:
                continue

            # For each pair, check if reachable without Wait
            for spawn in spawns:
                wait_block_ids = {
                    b.id for b in flowchart.blocks.values()
                    if isinstance(b, WaitBlock) and
                    any(e.agent_name == agent_name for e in b.entries)
                }
                other_spawn_ids = {s.id for s in spawns if s.id != spawn.id}

                # BFS from spawn, blocking at Wait blocks for this agent
                reachable = self._bfs_reachable(
                    spawn.id, adjacency, blocking_ids=wait_block_ids
                )
                bad_targets = reachable & other_spawn_ids
                if bad_targets:
                    issues.append(SyntaxIssue(
                        level='error',
                        message=(
                            f"Spawn block for agent '{agent_name}' can reach "
                            f"another Spawn for the same agent without an "
                            f"intervening Wait block"
                        ),
                        block_id=spawn.id,
                        block_name=spawn.name,
                    ))

        # Check Spawn→Exit without Wait (WARNING)
        exit_block_ids = {
            b.id for b in flowchart.blocks.values()
            if b.type in (BlockType.EXIT, BlockType.END)
        }
        for agent_name, spawns in spawn_blocks.items():
            for spawn in spawns:
                wait_block_ids = {
                    b.id for b in flowchart.blocks.values()
                    if isinstance(b, WaitBlock) and
                    any(e.agent_name == agent_name for e in b.entries)
                }
                reachable = self._bfs_reachable(
                    spawn.id, adjacency, blocking_ids=wait_block_ids
                )
                if reachable & exit_block_ids:
                    issues.append(SyntaxIssue(
                        level='warning',
                        message=(
                            f"Spawn block for agent '{agent_name}' can reach "
                            f"an Exit/End block without an intervening Wait"
                        ),
                        block_id=spawn.id,
                        block_name=spawn.name,
                    ))

    def _bfs_reachable(
        self,
        start_id: str,
        adjacency: Dict[str, List[str]],
        blocking_ids: Set[str],
    ) -> Set[str]:
        """BFS from start_id, not traversing through blocking_ids.

        Returns set of reachable block IDs (excluding start and blocking nodes).
        """
        visited: Set[str] = set()
        queue = list(adjacency.get(start_id, []))  # Start from neighbors
        reachable: Set[str] = set()

        while queue:
            node = queue.pop(0)
            if node in visited:
                continue
            visited.add(node)
            reachable.add(node)
            if node not in blocking_ids:
                queue.extend(adjacency.get(node, []))

        return reachable

    def _collect_defined_variables(
        self,
        flowchart: Flowchart,
        issues: List[SyntaxIssue]
    ) -> Set[str]:
        defined: Set[str] = set()

        for block in flowchart.blocks.values():
            if isinstance(block, VariableBlock) and block.variable_name:
                defined.add(block.variable_name)

            if isinstance(block, BashBlock):
                if block.output_variable:
                    defined.add(block.output_variable.strip())
                if block.exit_code_variable:
                    defined.add(block.exit_code_variable.strip())

            if isinstance(block, CommandBlock):
                if block.exit_code_variable:
                    defined.add(block.exit_code_variable.strip())

            if isinstance(block, SpawnBlock):
                if block.exit_code_variable:
                    defined.add(block.exit_code_variable.strip())

            if isinstance(block, PromptBlock) and block.output_schema:
                schema_vars, warning = self._parse_prompt_schema(block)
                defined.update(schema_vars)
                if warning:
                    issues.append(warning)

        return defined

    def _collect_variable_references(self, block) -> Set[str]:
        texts = self._get_text_fields(block)

        refs: Set[str] = set()
        for text in texts:
            if text:
                refs.update(self._find_variable_refs(text))
        return refs

    def _find_variable_refs(self, text: str) -> Set[str]:
        return set(VariableSubstitution.VAR_PATTERN.findall(text))

    def _parse_prompt_schema(
        self,
        block: PromptBlock
    ) -> Tuple[Set[str], SyntaxIssue]:
        schema = block.output_schema
        if not isinstance(schema, dict):
            return set(), SyntaxIssue(
                level='warning',
                message='Structured output schema must be a JSON object.',
                block_id=block.id,
                block_name=block.name
            )

        schema_type = schema.get('type')
        props = schema.get('properties')
        if schema_type != 'object' or not isinstance(props, dict):
            return set(), SyntaxIssue(
                level='warning',
                message='Structured output schema should define type "object" with properties.',
                block_id=block.id,
                block_name=block.name
            )

        return set(props.keys()), None
