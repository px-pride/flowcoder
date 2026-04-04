"""Protocol handler for stdin/stdout JSON-lines communication.

Manages the stream-json protocol between the engine (as a CLI binary)
and the outer claude-code-sdk that spawned us.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any


class ProtocolHandler:
    """Reads from stdin, writes to stdout. JSON-lines protocol."""

    def __init__(self) -> None:
        self._stdin_reader: asyncio.StreamReader | None = None
        self._pending_control: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._stdin_task: asyncio.Task[None] | None = None
        self._inbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.busy: bool = False  # True while a flowchart is executing

    async def start(self) -> None:
        """Set up async stdin reader and start routing messages."""
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin.buffer)
        self._stdin_reader = reader
        self._stdin_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        """Read stdin lines, route control responses to futures, rest to inbox."""
        assert self._stdin_reader is not None
        while True:
            line = await self._stdin_reader.readline()
            if not line:
                break

            text = line.decode().strip()
            if not text:
                continue

            try:
                msg = json.loads(text)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")

            if msg_type == "control_response":
                req_id = msg.get("response", {}).get("request_id", "")
                if req_id in self._pending_control:
                    self._pending_control[req_id].set_result(msg)
            elif msg_type == "status_request":
                # Respond immediately — works even mid-flowchart since
                # _read_loop runs concurrently with the main task.
                self.emit({"type": "status_response", "busy": self.busy})
            else:
                await self._inbox.put(msg)

    async def read_message(self) -> dict[str, Any]:
        """Read next message from inbox (user, command, shutdown, etc.)."""
        return await self._inbox.get()

    def emit(self, msg: dict[str, Any]) -> None:
        """Write a JSON message to stdout (one line)."""
        sys.stdout.write(json.dumps(msg) + "\n")
        sys.stdout.flush()

    async def forward_control_request(self, inner_request: dict[str, Any]) -> dict[str, Any]:
        """Forward a control request from inner claude to outer SDK.

        Rewrites the request_id to avoid collisions, waits for the response,
        then returns it with the original request_id restored.
        """
        original_id = inner_request.get("request_id", "")
        outer_id = f"fc_{original_id}"
        inner_request["request_id"] = outer_id

        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending_control[outer_id] = future

        self.emit(inner_request)
        response = await future
        del self._pending_control[outer_id]

        # Restore original request_id in the response
        if "response" in response:
            response["response"]["request_id"] = original_id

        return response

    def emit_system(self, subtype: str, data: dict[str, Any] | None = None) -> None:
        """Emit a system message."""
        msg: dict[str, Any] = {"type": "system", "subtype": subtype}
        if data:
            msg["data"] = data
        self.emit(msg)

    def emit_block_start(self, block_id: str, block_name: str, block_type: str) -> None:
        """Emit block_start system message."""
        self.emit_system(
            "block_start",
            {"block_id": block_id, "block_name": block_name, "block_type": block_type},
        )

    def emit_block_complete(
        self, block_id: str, block_name: str, success: bool
    ) -> None:
        """Emit block_complete system message."""
        self.emit_system(
            "block_complete",
            {"block_id": block_id, "block_name": block_name, "success": success},
        )

    def emit_result(
        self,
        result_text: str,
        is_error: bool = False,
        duration_ms: int = 0,
        num_turns: int = 0,
        total_cost_usd: float = 0.0,
    ) -> None:
        """Emit the final result message."""
        self.emit(
            {
                "type": "result",
                "subtype": "error" if is_error else "complete",
                "session_id": "flowchart",
                "duration_ms": duration_ms,
                "is_error": is_error,
                "num_turns": num_turns,
                "total_cost_usd": total_cost_usd,
                "result": result_text,
            }
        )

    async def stop(self) -> None:
        """Cancel the stdin read loop."""
        if self._stdin_task:
            self._stdin_task.cancel()
            try:
                await self._stdin_task
            except asyncio.CancelledError:
                pass

    def emit_forwarded(
        self,
        inner_msg: dict[str, Any],
        session_name: str,
        block_id: str,
        block_name: str,
    ) -> None:
        """Forward an inner claude message to outer SDK, tagged with context.

        Wraps the inner message as a system/session_message so the consumer
        can display real-time output from inner sessions.
        """
        self.emit({
            "type": "system",
            "subtype": "session_message",
            "data": {
                "session": session_name,
                "block_id": block_id,
                "block_name": block_name,
                "message": inner_msg,
            },
        })

    def log(self, message: str) -> None:
        """Write a log line to stderr."""
        sys.stderr.write(f"[flowcoder] {message}\n")
        sys.stderr.flush()
