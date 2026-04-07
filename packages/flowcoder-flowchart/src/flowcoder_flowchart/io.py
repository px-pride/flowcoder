"""File I/O helpers for flowcharts and commands.

Pydantic handles serialization — these are thin wrappers for file operations.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .command import Command
from .models import Flowchart


def load(source: str | Path | dict[str, Any]) -> Flowchart:
    """Load a flowchart from a JSON file path, JSON string, or dict."""
    if isinstance(source, dict):
        return Flowchart.model_validate(source)

    path = Path(source)
    if path.exists():
        return Flowchart.model_validate_json(path.read_text())

    # Assume JSON string
    if isinstance(source, str):
        return Flowchart.model_validate_json(source)

    raise ValueError(f"Cannot load flowchart from: {source}")


def dump(flowchart: Flowchart) -> dict[str, Any]:
    """Serialize a flowchart to a JSON-compatible dict."""
    return flowchart.model_dump(mode="json")


def save(flowchart: Flowchart, path: str | Path) -> None:
    """Save a flowchart to a JSON file."""
    Path(path).write_text(flowchart.model_dump_json(indent=2))


def load_command(source: str | Path | dict[str, Any]) -> Command:
    """Load a command from a JSON file path, JSON string, or dict."""
    if isinstance(source, dict):
        return Command.model_validate(source)

    path = Path(source)
    if path.exists():
        return Command.model_validate_json(path.read_text())

    if isinstance(source, str):
        return Command.model_validate_json(source)

    raise ValueError(f"Cannot load command from: {source}")


def dump_command(command: Command) -> dict[str, Any]:
    """Serialize a command to a JSON-compatible dict."""
    return command.model_dump(mode="json")


def save_command(command: Command, path: str | Path) -> None:
    """Save a command to a JSON file."""
    Path(path).write_text(command.model_dump_json(indent=2))
