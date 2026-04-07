"""Command resolver — precedence-based command lookup."""

from __future__ import annotations

from pathlib import Path

from flowcoder_flowchart import Command, load_command


class CommandNotFoundError(Exception):
    pass


def resolve_command(
    name: str,
    search_paths: list[str | Path] | None = None,
) -> Command:
    """Resolve a command by name using precedence-based search.

    Search order:
    1. Current directory (commands/<name>.json)
    2. Each path in search_paths (path/<name>.json or path/commands/<name>.json)
    3. ~/.flowcoder/commands/<name>.json

    Raises CommandNotFoundError if not found.
    """
    candidates: list[Path] = []

    # 1. Current directory
    candidates.append(Path.cwd() / "commands" / f"{name}.json")
    candidates.append(Path.cwd() / f"{name}.json")

    # 2. Search paths
    if search_paths:
        for sp in search_paths:
            p = Path(sp)
            candidates.append(p / f"{name}.json")
            candidates.append(p / "commands" / f"{name}.json")

    # 3. Home directory
    candidates.append(Path.home() / ".flowcoder" / "commands" / f"{name}.json")

    for candidate in candidates:
        if candidate.exists():
            return load_command(candidate)

    searched = [str(c.parent) for c in candidates]
    raise CommandNotFoundError(
        f"Command '{name}' not found. Searched: {', '.join(dict.fromkeys(searched))}"
    )
