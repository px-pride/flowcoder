"""
Model compatibility layer — conversions between old dataclass models and new Pydantic models.

The old models (src.models) use dataclass serialization with source_block_id/target_block_id.
The new models (flowcoder_flowchart) use Pydantic with source_id/target_id.

This module provides bidirectional conversion so the adapter layer, storage service,
and migration scripts can work with both formats seamlessly.
"""

from __future__ import annotations

from typing import Any, Dict

import flowcoder_flowchart as fc

from . import blocks as old_blocks
from .connection import Connection as OldConnection
from .flowchart import Flowchart as OldFlowchart
from .command import Command as OldCommand, CommandMetadata as OldCommandMetadata


# ── Flowchart conversion ──────────────────────────────────────────────


def flowchart_to_pydantic(flowchart: OldFlowchart) -> fc.Flowchart:
    """Convert an old-style dataclass Flowchart to a Pydantic Flowchart."""
    data = flowchart.to_dict()

    # Adapt connection field names
    for conn in data.get("connections", []):
        if "source_block_id" in conn:
            conn["source_id"] = conn.pop("source_block_id")
        if "target_block_id" in conn:
            conn["target_id"] = conn.pop("target_block_id")
        # Remove port fields (not in Pydantic model)
        conn.pop("source_port", None)
        conn.pop("target_port", None)
        # Remove deprecated condition field
        conn.pop("condition", None)

    # Ensure blocks is a dict (should already be)
    if isinstance(data.get("blocks"), list):
        blocks_dict = {}
        for b in data["blocks"]:
            blocks_dict[b["id"]] = b
        data["blocks"] = blocks_dict

    # Map old block field names to new ones where needed
    for bid, block_data in data.get("blocks", {}).items():
        _adapt_block_fields_old_to_new(block_data)

    # Remove start_block_id (Pydantic model doesn't have it)
    data.pop("start_block_id", None)

    return fc.Flowchart.model_validate(data)


def flowchart_from_pydantic(pyd_flowchart: fc.Flowchart) -> OldFlowchart:
    """Convert a Pydantic Flowchart back to an old-style dataclass Flowchart."""
    data = pyd_flowchart.model_dump(mode="json")

    # Adapt connection field names back
    for conn in data.get("connections", []):
        if "source_id" in conn:
            conn["source_block_id"] = conn.pop("source_id")
        if "target_id" in conn:
            conn["target_block_id"] = conn.pop("target_id")
        # Add default port fields
        conn.setdefault("source_port", "bottom")
        conn.setdefault("target_port", "top")

    # Map new block fields back to old
    for bid, block_data in data.get("blocks", {}).items():
        _adapt_block_fields_new_to_old(block_data)

    return OldFlowchart.from_dict(data)


# ── Command conversion ────────────────────────────────────────────────


def command_to_pydantic(command: OldCommand) -> fc.Command:
    """Convert an old Command to a Pydantic Command."""
    data = command.to_dict()

    # Convert flowchart
    pyd_flowchart = flowchart_to_pydantic(command.flowchart)

    # Build arguments list
    arguments = []
    for arg in command.arguments:
        arg_data = arg.to_dict() if hasattr(arg, 'to_dict') else {"name": str(arg)}
        arguments.append(fc.Argument(
            name=arg_data.get("name", ""),
            description=arg_data.get("description", ""),
            required=arg_data.get("required", True),
            default=arg_data.get("default"),
        ))

    return fc.Command(
        id=command.id,
        name=command.name,
        description=getattr(command, 'description', ''),
        flowchart=pyd_flowchart,
        arguments=arguments,
        metadata=fc.CommandMetadata(
            created=command.metadata.created,
            modified=command.metadata.modified,
            version=command.metadata.version,
            author=command.metadata.author,
            tags=command.metadata.tags,
            description=getattr(command, 'description', ''),
        ),
    )


# ── Block field adapters ──────────────────────────────────────────────


def _adapt_block_fields_old_to_new(block_data: dict) -> None:
    """Adapt old block field names/formats to match the Pydantic models.

    Handles:
    - WaitBlock entries → wait_for string list
    - VariableBlock entries list → single variable fields
    - BranchBlock dict condition → string condition
    - Empty strings → None for Optional engine fields
    - Old position formats → {x, y} dict
    """
    block_type = block_data.get("type", "")

    # Variable block: entries -> single variable
    if block_type == "variable":
        # Old format may have "entries" list; new format has single variable_name/value
        entries = block_data.pop("entries", None)
        if entries and isinstance(entries, list) and len(entries) > 0:
            first = entries[0]
            block_data.setdefault("variable_name", first.get("variable_name", ""))
            block_data.setdefault("variable_value", first.get("variable_value", ""))
            vtype = first.get("variable_type", "string")
            block_data.setdefault("variable_type", vtype)

    # Branch block: condition may be a dict in old format
    if block_type == "branch":
        cond = block_data.get("condition", "")
        if isinstance(cond, dict):
            # Old BranchCondition format: {variable, operator, value}
            block_data["condition"] = cond.get("variable", "")

    # WaitBlock: GUI uses entries (list of {agent_name, kill_session}),
    # engine uses wait_for (flat list of agent name strings).
    if block_type == "wait":
        entries = block_data.pop("entries", None)
        if entries and isinstance(entries, list):
            block_data["wait_for"] = [e["agent_name"] for e in entries]

    # BashBlock: GUI defaults Optional fields to "", engine expects None.
    if block_type == "bash":
        for key in ("output_variable", "working_directory", "exit_code_variable"):
            if block_data.get(key) == "":
                block_data[key] = None

    # SpawnBlock: same empty-string → None conversion.
    if block_type == "spawn":
        for key in ("exit_code_variable", "config_file"):
            if block_data.get(key) == "":
                block_data[key] = None

    # Remove fields not in Pydantic model
    block_data.pop("position_x", None)
    block_data.pop("position_y", None)

    # Convert old position format to Pydantic Position
    if "position_x" not in block_data and "position" not in block_data:
        # Check if x/y are at top level
        x = block_data.pop("x", None)
        y = block_data.pop("y", None)
        if x is not None and y is not None:
            block_data["position"] = {"x": x, "y": y}


def _adapt_block_fields_new_to_old(block_data: dict) -> None:
    """Adapt Pydantic block fields back to old format."""
    block_type = block_data.get("type", "")

    # Variable block: wrap single variable as entries list
    if block_type == "variable":
        if "variable_name" in block_data and "entries" not in block_data:
            block_data["entries"] = [{
                "variable_name": block_data.get("variable_name", ""),
                "variable_value": block_data.get("variable_value", ""),
                "variable_type": block_data.get("variable_type", "string"),
            }]

    # WaitBlock: engine uses wait_for (list[str]), GUI uses entries (list of dicts).
    if block_type == "wait":
        wait_for = block_data.pop("wait_for", None)
        if wait_for and isinstance(wait_for, list):
            block_data["entries"] = [
                {"agent_name": name, "kill_session": False}
                for name in wait_for
            ]
        # Remove engine-only field
        block_data.pop("timeout_seconds", None)

    # BashBlock: None → "" for fields that are str in GUI.
    if block_type == "bash":
        for key in ("output_variable", "working_directory", "exit_code_variable"):
            if block_data.get(key) is None:
                block_data[key] = ""

    # SpawnBlock: None → "" for fields that are str in GUI.
    if block_type == "spawn":
        for key in ("exit_code_variable", "config_file"):
            if block_data.get(key) is None:
                block_data[key] = ""
        # Remove engine-only fields
        block_data.pop("model", None)
        block_data.pop("backend", None)

    # Remove engine-only fields not present in GUI blocks
    block_data.pop("session", None)
    if block_type == "prompt":
        block_data.pop("output_variable", None)
    if block_type == "refresh":
        block_data.pop("target_session", None)
    if block_type == "exit":
        block_data.pop("exit_message", None)
