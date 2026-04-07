"""Protocol handler for stdout JSON-lines output.

Writes stream-json messages to stdout.  Used by the proxy core
and by Session/GraphWalker during flowchart execution.  All output
goes to stdout; log messages go to stderr.
"""

from __future__ import annotations

import json
import sys
from typing import Any


class ProtocolHandler:
    """Writes JSON-lines to stdout."""

    def emit(self, msg: dict[str, Any]) -> None:
        """Write a JSON message to stdout (one line)."""
        sys.stdout.write(json.dumps(msg) + "\n")
        sys.stdout.flush()

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

    def emit_flowchart_start(
        self, command: str, args: str, block_count: int
    ) -> None:
        """Emit flowchart_start when entering takeover mode."""
        self.emit_system(
            "flowchart_start",
            {"command": command, "args": args, "block_count": block_count},
        )

    def emit_flowchart_complete(
        self,
        status: str,
        duration_ms: int = 0,
        cost_usd: float = 0.0,
        blocks_executed: int = 0,
    ) -> None:
        """Emit flowchart_complete when leaving takeover mode."""
        self.emit_system(
            "flowchart_complete",
            {
                "status": status,
                "duration_ms": duration_ms,
                "cost_usd": cost_usd,
                "blocks_executed": blocks_executed,
            },
        )

    def emit_result(
        self,
        result_text: str,
        is_error: bool = False,
        duration_ms: int = 0,
        num_turns: int = 0,
        total_cost_usd: float = 0.0,
    ) -> None:
        """Emit a result message (turn completion)."""
        self.emit(
            {
                "type": "result",
                "subtype": "error" if is_error else "complete",
                "session_id": "flowchart",
                "duration_ms": duration_ms,
                "duration_api_ms": 0,
                "is_error": is_error,
                "num_turns": num_turns,
                "total_cost_usd": total_cost_usd,
                "result": result_text,
            }
        )

    def emit_forwarded(
        self,
        inner_msg: dict[str, Any],
        session_name: str,
        block_id: str,
        block_name: str,
    ) -> None:
        """Forward an inner claude message to the client as-is (unwrapped).

        The client sees the same message format it would get from
        real Claude.  Block context is conveyed separately via
        block_start/block_complete events.
        """
        self.emit(inner_msg)

    def log(self, message: str) -> None:
        """Write a log line to stderr."""
        sys.stderr.write(f"[flowcoder] {message}\n")
        sys.stderr.flush()
