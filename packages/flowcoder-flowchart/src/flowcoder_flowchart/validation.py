"""Graph-level structural validation for flowcharts.

Field-level validation is handled by pydantic on the models.
This module checks structural correctness across the whole graph.
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from .blocks import (
    BashBlock,
    BlockType,
    BranchBlock,
    CommandBlock,
    ExitBlock,
    PromptBlock,
    SpawnBlock,
    WaitBlock,
)
from .templates import validate_conditionals

if TYPE_CHECKING:
    from .models import Flowchart


class ValidationResult(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def validate(flowchart: Flowchart) -> ValidationResult:
    """Check structural correctness of a flowchart."""
    errors: list[str] = []
    warnings: list[str] = []

    # Exactly one start block
    start_blocks = [
        bid for bid, b in flowchart.blocks.items() if b.type == BlockType.START
    ]
    if len(start_blocks) == 0:
        errors.append("Flowchart must have exactly one start block")
    elif len(start_blocks) > 1:
        errors.append(
            f"Flowchart has {len(start_blocks)} start blocks, expected exactly one"
        )

    # At least one end or exit block
    end_blocks = [
        bid for bid, b in flowchart.blocks.items()
        if b.type in (BlockType.END, BlockType.EXIT)
    ]
    if len(end_blocks) == 0:
        warnings.append("Flowchart has no end or exit block")

    # All connections reference existing blocks
    block_ids = set(flowchart.blocks.keys())
    for conn in flowchart.connections:
        if conn.source_id not in block_ids:
            errors.append(
                f"Connection {conn.id} references non-existent source block: "
                f"{conn.source_id}"
            )
        if conn.target_id not in block_ids:
            errors.append(
                f"Connection {conn.id} references non-existent target block: "
                f"{conn.target_id}"
            )

    # Reachability from start
    if len(start_blocks) == 1:
        reachable = _get_reachable(flowchart, start_blocks[0])
        unreachable = block_ids - reachable
        if unreachable:
            names = [
                flowchart.blocks[bid].name or bid for bid in unreachable
            ]
            warnings.append(f"Unreachable blocks: {', '.join(names)}")

    # Branch blocks: exactly one true and one false outgoing connection
    for bid, block in flowchart.blocks.items():
        if block.type == BlockType.BRANCH:
            outgoing = [c for c in flowchart.connections if c.source_id == bid]
            true_paths = [c for c in outgoing if c.is_true_path is True]
            false_paths = [c for c in outgoing if c.is_true_path is False]

            if len(true_paths) != 1:
                errors.append(
                    f"Branch block '{block.name or bid}' has {len(true_paths)} "
                    f"true paths, expected exactly 1"
                )
            if len(false_paths) != 1:
                errors.append(
                    f"Branch block '{block.name or bid}' has {len(false_paths)} "
                    f"false paths, expected exactly 1"
                )

    # Prompt blocks: non-empty prompt
    for bid, block in flowchart.blocks.items():
        if isinstance(block, PromptBlock) and not block.prompt.strip():
            errors.append(f"Prompt block '{block.name or bid}' has empty prompt")

    # Branch blocks: non-empty condition
    for bid, block in flowchart.blocks.items():
        if isinstance(block, BranchBlock) and not block.condition.strip():
            errors.append(
                f"Branch block '{block.name or bid}' has empty condition"
            )

    # Command blocks: non-empty command_name
    for bid, block in flowchart.blocks.items():
        if isinstance(block, CommandBlock) and not block.command_name.strip():
            errors.append(
                f"Command block '{block.name or bid}' has empty command_name"
            )

    # Spawn blocks: non-empty agent_name and command_name
    for bid, block in flowchart.blocks.items():
        if isinstance(block, SpawnBlock):
            if not block.agent_name.strip():
                errors.append(
                    f"Spawn block '{block.name or bid}' has empty agent_name"
                )
            if not block.command_name.strip():
                errors.append(
                    f"Spawn block '{block.name or bid}' has empty command_name"
                )

    # Wait blocks: non-empty wait_for
    for bid, block in flowchart.blocks.items():
        if isinstance(block, WaitBlock) and len(block.wait_for) == 0:
            errors.append(
                f"Wait block '{block.name or bid}' has empty wait_for list"
            )

    # Exit blocks: validate exit code range
    for bid, block in flowchart.blocks.items():
        if isinstance(block, ExitBlock):
            if block.exit_code < 0 or block.exit_code > 255:
                errors.append(
                    f"Exit block '{block.name or bid}' has invalid exit_code "
                    f"{block.exit_code} (must be 0-255)"
                )

    # Non-branch, non-end, non-exit blocks should have at least one outgoing connection
    for bid, block in flowchart.blocks.items():
        if block.type in (BlockType.END, BlockType.EXIT):
            continue
        outgoing = [c for c in flowchart.connections if c.source_id == bid]
        if len(outgoing) == 0:
            warnings.append(
                f"Block '{block.name or bid}' has no outgoing connections"
            )

    # Spawn-wait path checking
    _check_spawn_wait_paths(flowchart, errors, warnings)

    # Conditional syntax checking in prompt/bash templates
    _check_conditional_syntax(flowchart, errors)

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )


def _check_spawn_wait_paths(
    flowchart: Flowchart,
    errors: list[str],
    warnings: list[str],
) -> None:
    """Check that spawn blocks have corresponding wait blocks on all paths."""
    adj: dict[str, list[str]] = {bid: [] for bid in flowchart.blocks}
    for conn in flowchart.connections:
        if conn.source_id in adj:
            adj[conn.source_id].append(conn.target_id)

    spawn_blocks = [
        (bid, block)
        for bid, block in flowchart.blocks.items()
        if isinstance(block, SpawnBlock)
    ]

    for spawn_id, spawn_block in spawn_blocks:
        queue: deque[str] = deque()
        visited: set[str] = set()

        for next_id in adj.get(spawn_id, []):
            queue.append(next_id)

        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)

            block = flowchart.blocks.get(current)
            if not block:
                continue

            if isinstance(block, WaitBlock):
                continue
            if block.type in (BlockType.END, BlockType.EXIT):
                warnings.append(
                    f"Spawn block '{spawn_block.name or spawn_id}' has path "
                    f"to {block.type.value} without wait"
                )
                continue
            if isinstance(block, SpawnBlock) and current != spawn_id:
                errors.append(
                    f"Spawn block '{spawn_block.name or spawn_id}' reaches "
                    f"spawn block '{block.name or current}' without an "
                    f"intervening wait"
                )
                continue

            for next_id in adj.get(current, []):
                if next_id not in visited:
                    queue.append(next_id)


def _check_conditional_syntax(
    flowchart: Flowchart, errors: list[str]
) -> None:
    """Validate <if></if> syntax in prompt and bash block templates."""
    for bid, block in flowchart.blocks.items():
        texts_to_check: list[tuple[str, str]] = []

        if isinstance(block, PromptBlock):
            texts_to_check.append(
                (block.prompt, f"Prompt block '{block.name or bid}'")
            )
        elif isinstance(block, BashBlock):
            texts_to_check.append(
                (block.command, f"Bash block '{block.name or bid}'")
            )

        for text, label in texts_to_check:
            issues = validate_conditionals(text)
            for issue in issues:
                errors.append(f"{label}: {issue}")


def _get_reachable(flowchart: Flowchart, start_id: str) -> set[str]:
    """BFS from start to find all reachable block IDs."""
    visited: set[str] = set()
    queue: deque[str] = deque([start_id])

    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)

        for conn in flowchart.connections:
            if conn.source_id == current and conn.target_id not in visited:
                queue.append(conn.target_id)

    return visited
