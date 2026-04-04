"""Locate the claude CLI binary."""

from __future__ import annotations

import shutil


def find_claude() -> str:
    """Find the claude CLI binary on PATH.

    Returns the path to the claude binary.
    Raises FileNotFoundError if not found.
    """
    path = shutil.which("claude")
    if path:
        return path

    raise FileNotFoundError(
        "Could not find 'claude' CLI on PATH. "
        "Install it or pass --claude-path explicitly."
    )
