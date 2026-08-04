"""Git remote/branch helpers for FlowCoder."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger(__name__)


class GitRemoteError(RuntimeError):
    """Raised when a git remote/branch operation fails."""

    def __init__(self, command: str, returncode: int, stdout: str, stderr: str):
        message = stderr or stdout or f"git {command} failed"
        super().__init__(message)
        self.command = command
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    def is_auth_error(self) -> bool:
        payload = f"{self.stdout}\n{self.stderr}".lower()
        auth_keywords = [
            "permission denied",
            "authentication failed",
            "could not read from remote repository",
            "please make sure you have the correct access rights",
            "password authentication",
            "fatal: could not read username",
        ]
        return any(keyword in payload for keyword in auth_keywords)


@dataclass
class GitRemoteResult:
    command: str
    stdout: str
    stderr: str


class GitRemoteManager:
    """Utility for configuring remotes and fetching branches."""

    def __init__(self, working_directory: str | Path, git_executable: str = "git") -> None:
        self.working_directory = Path(working_directory)
        self.git_executable = git_executable

    def list_remotes(self) -> dict[str, str]:
        code, stdout, stderr = self._run(["remote", "-v"])
        if code != 0:
            raise GitRemoteError(stderr or "git remote -v failed")

        remotes: dict[str, str] = {}
        for line in stdout.splitlines():
            if not line:
                continue
            name, url, *_ = line.split()
            remotes[name] = url
        return remotes

    def ensure_remote(self, name: str, url: str) -> GitRemoteResult:
        remotes = self.list_remotes()
        if name in remotes:
            if remotes[name] == url:
                return GitRemoteResult("remote existing", "", "")
            self._run_check(["remote", "remove", name])

        return self._run_check(["remote", "add", name, url])

    def fetch(self, remote: str, refs: Optional[Iterable[str]] = None) -> GitRemoteResult:
        args = ["fetch", remote]
        if refs:
            args.extend(refs)
        return self._run_check(args)

    def checkout_branch(self, branch: str, remote: str | None = None) -> GitRemoteResult:
        if self._branch_exists(branch):
            return self._run_check(["checkout", branch])

        if remote:
            self.fetch(remote, [branch])

        if self._remote_branch_exists(remote, branch):
            return self._run_check(["checkout", "-b", branch, f"{remote}/{branch}"])

        # No remote branch; create locally
        return self._run_check(["checkout", "-b", branch])

    def _branch_exists(self, branch: str) -> bool:
        code, _, _ = self._run(["rev-parse", "--verify", branch])
        return code == 0

    def _remote_branch_exists(self, remote: Optional[str], branch: str) -> bool:
        if not remote:
            return False
        code, _, _ = self._run(["ls-remote", "--heads", remote, branch])
        return code == 0

    def _run(self, args: list[str]) -> tuple[int, str, str]:
        proc = subprocess.run(  # noqa: S603,S607
            [self.git_executable, *args],
            cwd=self.working_directory,
            capture_output=True,
            text=True,
            check=False,
        )
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()
        logger.debug(
            "git %s -> %s",
            " ".join(args),
            proc.returncode,
            extra={"stdout": stdout, "stderr": stderr},
        )
        return proc.returncode, stdout, stderr

    def _run_check(self, args: list[str]) -> GitRemoteResult:
        code, stdout, stderr = self._run(args)
        if code != 0:
            raise GitRemoteError(" ".join(args), code, stdout, stderr)
        return GitRemoteResult(" ".join(args), stdout, stderr)
