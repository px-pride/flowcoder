"""Transport abstraction for Session subprocess I/O.

Defines the SessionTransport protocol and implementations:
- DirectTransport: local PTY subprocess (default)
- SDKTransport: wraps existing ClaudeAgentService/CodexService SDK calls

Separating transport from session logic allows alternative backends.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tty
from asyncio.subprocess import PIPE
from typing import Any, Callable, Protocol, runtime_checkable


@runtime_checkable
class SessionTransport(Protocol):
    """What Session needs from its subprocess I/O layer."""

    async def start(self, cmd: list[str], env: dict[str, str]) -> None: ...
    async def write(self, data: bytes) -> None: ...
    async def readline(self) -> bytes: ...
    async def stop(self) -> None: ...

    @property
    def is_running(self) -> bool: ...


class DirectTransport:
    """Spawns Claude as a local subprocess with PTY stdout.

    This is the default transport — extracted from Session.start()/stop().
    """

    def __init__(self) -> None:
        self._proc: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._pty_reader: asyncio.StreamReader | None = None
        self._pty_transport: asyncio.BaseTransport | None = None

    async def start(self, cmd: list[str], env: dict[str, str]) -> None:
        """Spawn the subprocess with a PTY for stdout."""
        master_fd, slave_fd = os.openpty()
        tty.setraw(master_fd)

        self._proc = await asyncio.create_subprocess_exec(
            *cmd, stdin=PIPE, stdout=slave_fd, stderr=PIPE, env=env,
        )
        os.close(slave_fd)

        loop = asyncio.get_running_loop()
        self._pty_reader = asyncio.StreamReader()
        self._pty_transport, _ = await loop.connect_read_pipe(
            lambda: asyncio.StreamReaderProtocol(self._pty_reader),
            os.fdopen(master_fd, "rb", 0),
        )

        self._stderr_task = asyncio.create_task(self._forward_stderr())

    async def write(self, data: bytes) -> None:
        """Write to the subprocess stdin."""
        assert self._proc and self._proc.stdin
        self._proc.stdin.write(data)
        await self._proc.stdin.drain()

    async def readline(self) -> bytes:
        """Read a line from PTY stdout."""
        assert self._pty_reader
        return await self._pty_reader.readline()

    async def stop(self) -> None:
        """Terminate the subprocess and clean up PTY."""
        if self._pty_transport:
            self._pty_transport.close()
            self._pty_transport = None
            self._pty_reader = None

        if self._proc:
            try:
                if self._proc.stdin:
                    self._proc.stdin.close()
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except (ProcessLookupError, asyncio.TimeoutError):
                if self._proc.returncode is None:
                    self._proc.kill()
            finally:
                self._proc = None

        if self._stderr_task:
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except asyncio.CancelledError:
                pass

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def _forward_stderr(self) -> None:
        """Forward inner claude's stderr to our stderr."""
        assert self._proc and self._proc.stderr
        while True:
            line = await self._proc.stderr.readline()
            if not line:
                break
            sys.stderr.write(line.decode())
            sys.stderr.flush()


class SDKTransport:
    """Transport that wraps an existing SDK client (ClaudeAgentService or CodexService).

    Instead of spawning a subprocess, this transport delegates to the SDK's
    prompt/response methods. Used for embedding FlowCoder in external apps
    or for the Axi integration.
    """

    def __init__(
        self,
        send_fn: Callable[[str], Any],
        receive_fn: Callable[[], Any],
        stop_fn: Callable[[], Any] | None = None,
    ) -> None:
        self._send_fn = send_fn
        self._receive_fn = receive_fn
        self._stop_fn = stop_fn
        self._running = False
        self._buffer: asyncio.Queue[bytes] = asyncio.Queue()

    async def start(self, cmd: list[str], env: dict[str, str]) -> None:
        """SDK transport doesn't spawn — just mark as running."""
        self._running = True

    async def write(self, data: bytes) -> None:
        """Send data through the SDK send function."""
        if self._send_fn:
            result = self._send_fn(data.decode())
            if asyncio.iscoroutine(result):
                await result

    async def readline(self) -> bytes:
        """Receive data through the SDK receive function."""
        if self._receive_fn:
            result = self._receive_fn()
            if asyncio.iscoroutine(result):
                result = await result
            if isinstance(result, str):
                return result.encode()
            if isinstance(result, bytes):
                return result
        return b""

    async def stop(self) -> None:
        """Stop the SDK transport."""
        self._running = False
        if self._stop_fn:
            result = self._stop_fn()
            if asyncio.iscoroutine(result):
                await result

    @property
    def is_running(self) -> bool:
        return self._running
