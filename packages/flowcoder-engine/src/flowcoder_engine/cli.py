"""CLI argument parsing for the flowcoder-engine binary."""

from __future__ import annotations

import argparse
import shlex
from typing import Any

from flowcoder_flowchart import Argument


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        prog="flowcoder-engine",
        description="Execute flowchart workflows via Claude sessions",
    )

    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument(
        "--command",
        help="Command name to resolve and execute",
    )
    group.add_argument(
        "--flowchart",
        help="Path to a flowchart JSON file",
    )

    parser.add_argument(
        "--args",
        default="",
        help="Arguments to pass to the flowchart (shell-style string)",
    )
    parser.add_argument(
        "--claude-path",
        help="Path to the claude CLI binary (auto-detected if not specified)",
    )
    parser.add_argument(
        "--search-path",
        action="append",
        dest="search_paths",
        help="Additional search paths for command resolution (can specify multiple)",
    )
    parser.add_argument(
        "--max-blocks",
        type=int,
        default=1000,
        help="Maximum number of blocks to execute (safety limit)",
    )

    # Catch-all for extra args passed by claude-code-sdk
    args, remaining = parser.parse_known_args(argv)

    # Parse remaining as --arg-* key-value pairs
    extra = parse_extra_args(remaining)
    args.extra = extra

    return args


def parse_extra_args(remaining: list[str]) -> dict[str, str]:
    """Parse --arg-name value pairs from remaining args."""
    result: dict[str, str] = {}
    i = 0
    while i < len(remaining):
        arg = remaining[i]
        if arg.startswith("--arg-") and i + 1 < len(remaining):
            key = arg[6:]  # strip --arg-
            result[key] = remaining[i + 1]
            i += 2
        else:
            i += 1
    return result


def build_variables(
    args_string: str,
    extra_args: dict[str, str],
    declared_args: list[Argument],
) -> dict[str, Any]:
    """Build initial variable dict from CLI arguments."""
    if args_string.strip():
        parts = shlex.split(args_string)
    else:
        parts = []

    for key, value in extra_args.items():
        if key not in {a.name for a in declared_args}:
            parts.append(value)

    variables: dict[str, Any] = {}

    for i, arg_def in enumerate(declared_args):
        pos = i + 1
        if i < len(parts):
            variables[f"${pos}"] = parts[i]
            variables[arg_def.name] = parts[i]
        elif arg_def.default is not None:
            variables[f"${pos}"] = arg_def.default
            variables[arg_def.name] = arg_def.default
        elif arg_def.required:
            raise ValueError(
                f"Missing required argument: {arg_def.name} (position {pos})"
            )

    for i in range(len(declared_args), len(parts)):
        variables[f"${i + 1}"] = parts[i]

    for key, value in extra_args.items():
        variables[key] = value

    return variables
