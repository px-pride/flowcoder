"""Git workflow orchestration utilities for auto commit/push flows."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class GitWorkflowResult:
    success: bool
    message: str
    changes_detected: bool
    pushed: bool = False
    commit_hash: str = ""
    stdout: str = ""
    stderr: str = ""


class GitWorkflowOrchestrator:
    """Stages, commits, and optionally pushes repo changes."""

    def __init__(self, working_directory: str | Path, git_executable: str = "git") -> None:
        self.working_directory = Path(working_directory)
        self.git_executable = git_executable

    def run(
        self,
        block_type: str,
        block_name: str,
        auto_push: bool,
        branch: str = "",
        remote: str = "origin"
    ) -> GitWorkflowResult:
        stage_proc = self._run_git(["add", "-A"])
        if stage_proc.returncode != 0:
            return GitWorkflowResult(
                success=False,
                message=stage_proc.stderr or "git add failed",
                changes_detected=False,
                stdout=stage_proc.stdout or "",
                stderr=stage_proc.stderr or ""
            )

        if not self._has_staged_changes():
            return GitWorkflowResult(
                success=True,
                message="No changes to commit",
                changes_detected=False
            )

        commit_message = self._build_commit_message(block_type, block_name)
        commit_proc = self._run_git(["commit", "-m", commit_message])
        if commit_proc.returncode != 0:
            stderr = commit_proc.stderr.lower()
            if "nothing to commit" in stderr:
                return GitWorkflowResult(
                    success=True,
                    message="No changes to commit",
                    changes_detected=False
                )
            return GitWorkflowResult(
                success=False,
                message=commit_proc.stderr or "git commit failed",
                changes_detected=True,
                stdout=commit_proc.stdout or "",
                stderr=commit_proc.stderr or ""
            )

        hash_proc = self._run_git(["rev-parse", "--short", "HEAD"])
        commit_hash = hash_proc.stdout.strip() if hash_proc.returncode == 0 else ""

        pushed = False
        if auto_push:
            branch_name = branch or self._current_branch()
            push_proc = self._run_git(["push", remote, branch_name])
            if push_proc.returncode != 0:
                message = push_proc.stderr or "git push failed"
                return GitWorkflowResult(
                    success=False,
                    message=message,
                    changes_detected=True,
                    pushed=False,
                    commit_hash=commit_hash,
                    stdout=push_proc.stdout or "",
                    stderr=push_proc.stderr or ""
                )
            pushed = True

        info_message = f"Committed changes ({commit_hash})" if commit_hash else "Committed changes"
        return GitWorkflowResult(
            success=True,
            message=info_message,
            changes_detected=True,
            pushed=pushed,
            commit_hash=commit_hash
        )

    def _has_staged_changes(self) -> bool:
        status_proc = self._run_git(["status", "--porcelain"])
        if status_proc.returncode != 0:
            return False
        return bool(status_proc.stdout.strip())

    def _current_branch(self) -> str:
        proc = self._run_git(["rev-parse", "--abbrev-ref", "HEAD"])
        if proc.returncode == 0:
            branch = proc.stdout.strip()
            return branch if branch else "HEAD"
        return "HEAD"

    def _build_commit_message(self, block_type: str, block_name: str) -> str:
        label = block_type.capitalize()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        safe_name = block_name or "Unnamed Block"
        return f"[{label}] {safe_name} ({timestamp})"

    def _run_git(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603, S607
            [self.git_executable, *args],
            cwd=self.working_directory,
            capture_output=True,
            text=True,
            check=False,
        )
