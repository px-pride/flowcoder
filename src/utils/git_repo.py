"""Helpers for initializing git repositories in user workspaces."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


class GitInitializationError(RuntimeError):
    """Raised when a git operation invoked by FlowCoder fails."""


@dataclass
class GitInitResult:
    """Represents the outcome of attempting to initialize a git repo."""

    initialized: bool
    already_initialized: bool
    stdout: str = ""
    stderr: str = ""


class GitRepoInitializer:
    """Utility for detecting/initializing git repositories."""

    def __init__(self, working_directory: str | Path, git_executable: str = "git") -> None:
        self.working_directory = Path(working_directory)
        self.git_executable = git_executable

    def is_git_repository(self) -> bool:
        """Return True if the working directory already contains a git repo."""
        return (self.working_directory / ".git").is_dir()

    def ensure_repository(self) -> GitInitResult:
        """Initialize a git repository if it does not already exist."""
        if self.is_git_repository():
            return GitInitResult(initialized=False, already_initialized=True)

        result = self._run_git_command(["init"])
        if result[0] != 0:
            raise GitInitializationError(result[2] or "git init failed")

        return GitInitResult(
            initialized=True,
            already_initialized=False,
            stdout=result[1],
            stderr=result[2],
        )

    def _run_git_command(self, args: list[str]) -> tuple[int, str, str]:
        completed = subprocess.run(  # noqa: S603,S607 - intended system call
            [self.git_executable, *args],
            cwd=self.working_directory,
            capture_output=True,
            text=True,
            check=False,
        )
        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()
        logger.debug(
            "git command finished",
            extra={
                "cwd": str(self.working_directory),
                "args": args,
                "returncode": completed.returncode,
                "stdout": stdout,
                "stderr": stderr,
            },
        )
        return completed.returncode, stdout, stderr

