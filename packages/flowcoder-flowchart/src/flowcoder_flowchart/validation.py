"""Graph-level structural validation for flowcharts.

Field-level validation is handled by pydantic on the models.
This module checks structural correctness across the whole graph.
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from .blocks import BlockType, BranchBlock, CommandBlock, PromptBlock

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

    # At least one end block
    end_blocks = [
        bid for bid, b in flowchart.blocks.items() if b.type == BlockType.END
    ]
    if len(end_blocks) == 0:
        warnings.append("Flowchart has no end block")

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

    # Non-branch, non-end blocks should have at least one outgoing connection
    for bid, block in flowchart.blocks.items():
        if block.type == BlockType.END:
            continue
        outgoing = [c for c in flowchart.connections if c.source_id == bid]
        if len(outgoing) == 0 and block.type != BlockType.END:
            warnings.append(
                f"Block '{block.name or bid}' has no outgoing connections"
            )

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )


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
