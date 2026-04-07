"""Subprocess manager for the inner Claude CLI.

Spawns claude as a child process with PIPE for stdin and stdout.
Claude CLI with --output-format stream-json writes JSON lines to stdout.
Provides sequential read/write — no event queues, no async generators.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from asyncio.subprocess import DEVNULL, PIPE
from typing import Any

log = logging.getLogger(__name__)


def find_claude() -> str:
    """Find the claude CLI binary on PATH.

    Raises FileNotFoundError if not found.
    """
    path = shutil.which("claude")
    if path:
        return path
    raise FileNotFoundError(
        "Could not find 'claude' CLI on PATH. "
        "Install it or pass --claude-path explicitly."
    )


class ClaudeProcess:
    """A single Claude CLI subprocess.

    Claude CLI with --output-format stream-json writes JSON lines to stdout.
    Sequential interface: call read() in a loop to get one JSON message
    at a time.  No background tasks, no queues.
    """

    def __init__(self) -> None:
        self._proc: asyncio.subprocess.Process | None = None

    async def start(self, cmd: list[str], env: dict[str, str], cwd: str) -> None:
        """Spawn the subprocess."""
        self._proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=PIPE,
            stdout=PIPE,
            stderr=DEVNULL,
            env=env,
            cwd=cwd or None,
            limit=10 * 1024 * 1024,  # 10 MB — Claude stream-json lines can be large
        )

    async def write(self, msg: dict[str, Any]) -> None:
        """Write a JSON message to stdin."""
        assert self._proc is not None
        assert self._proc.stdin is not None
        self._proc.stdin.write((json.dumps(msg) + "\n").encode())
        await self._proc.stdin.drain()

    async def read(self) -> dict[str, Any] | None:
        """Read one JSON message from stdout.

        Returns None on EOF (process exited).  Skips non-JSON lines.
        """
        assert self._proc is not None
        assert self._proc.stdout is not None
        while True:
            line_bytes = await self._proc.stdout.readline()
            if not line_bytes:
                return None
            line = line_bytes.decode().strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue

    async def stop(self) -> None:
        """Terminate the subprocess and clean up."""
        if self._proc:
            try:
                if self._proc.stdin:
                    self._proc.stdin.close()
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except (ProcessLookupError, TimeoutError):
                if self._proc.returncode is None:
                    self._proc.kill()
            finally:
                self._proc = None

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None
