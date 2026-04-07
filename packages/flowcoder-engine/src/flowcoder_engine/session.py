"""Session — a single claude CLI subprocess.

Manages the lifecycle of one claude process: start, query, stop.
Forwards inner claude messages (assistant, stream_event) to the outer
protocol handler, and relays control_request/control_response bidirectionally.

Extended with:
- from_client() classmethod for external SDK clients (Axi embedding)
- Codex transport support
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .transport import DirectTransport, SDKTransport, SessionTransport

if TYPE_CHECKING:
    from .protocol import ProtocolHandler


@dataclass
class QueryResult:
    """Result from a session query."""
    response_text: str = ""
    structured_output: dict[str, Any] | None = None
    cost_usd: float = 0.0
    duration_ms: int = 0


# Message types we forward to the outer consumer
_FORWARDED_TYPES = {"assistant", "stream_event"}

def _clean_env() -> dict[str, str]:
    """Return a copy of os.environ for the inner Claude CLI.

    Strips CLAUDECODE to prevent nested-session rejection, but preserves
    (or sets) CLAUDE_AGENT_SDK_VERSION and CLAUDE_CODE_ENTRYPOINT so the
    inner CLI uses the SDK control protocol for tool permissions and MCP.
    """
    env = dict(os.environ)
    env.pop("CLAUDECODE", None)
    env.setdefault("CLAUDE_CODE_ENTRYPOINT", "sdk-py")
    env.setdefault("CLAUDE_AGENT_SDK_VERSION", "flowcoder-engine")
    return env


class Session:
    """A single claude CLI subprocess speaking stream-json protocol."""

    def __init__(
        self,
        name: str,
        claude_path: str,
        opts: dict[str, Any],
        protocol: ProtocolHandler | None = None,
        transport: SessionTransport | None = None,
    ) -> None:
        self.name = name
        self.session_id: str | None = None
        self.total_cost: float = 0.0
        self._claude_path = claude_path
        self._opts = opts
        self._protocol = protocol
        self._transport: SessionTransport = transport or DirectTransport()
        self._initialized = False

    @classmethod
    def from_client(
        cls,
        name: str,
        send_fn: Any,
        receive_fn: Any,
        stop_fn: Any = None,
        protocol: ProtocolHandler | None = None,
    ) -> Session:
        """Create a Session backed by an SDK client instead of a subprocess.

        Used for embedding FlowCoder in external applications (e.g. Axi).
        """
        transport = SDKTransport(
            send_fn=send_fn,
            receive_fn=receive_fn,
            stop_fn=stop_fn,
        )
        return cls(
            name=name,
            claude_path="",  # Not used with SDK transport
            opts={},
            protocol=protocol,
            transport=transport,
        )

    async def start(self) -> None:
        """Spawn the claude subprocess."""
        cmd = [
            self._claude_path,
            "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
            "--dangerously-skip-permissions",
        ]
        cmd += self._build_opts_args()
        await self._transport.start(cmd, _clean_env())

    def _build_opts_args(self) -> list[str]:
        """Convert opts dict to CLI arguments."""
        args: list[str] = []
        if "model" in self._opts:
            args += ["--model", self._opts["model"]]
        if "system_prompt" in self._opts:
            args += ["--system-prompt", self._opts["system_prompt"]]
        if "max_turns" in self._opts:
            args += ["--max-turns", str(self._opts["max_turns"])]
        if "cwd" in self._opts:
            args += ["--cwd", self._opts["cwd"]]
        if "allowed_tools" in self._opts:
            for tool in self._opts["allowed_tools"]:
                args += ["--allowedTools", tool]
        if "max_budget_usd" in self._opts:
            args += ["--max-budget-usd", str(self._opts["max_budget_usd"])]
        if "append_system_prompt" in self._opts:
            args += ["--append-system-prompt", self._opts["append_system_prompt"]]
        return args

    async def query(
        self,
        prompt: str,
        block_id: str = "",
        block_name: str = "",
    ) -> QueryResult:
        """Send a prompt and collect the full response.

        Forwards assistant/stream_event messages to the protocol handler
        and relays control_request/control_response through it.
        """
        # Send user message in stream-json format
        msg = {
            "type": "user",
            "message": {
                "role": "user",
                "content": prompt,
            },
        }
        await self._transport.write((json.dumps(msg) + "\n").encode())

        # Collect response
        response_parts: list[str] = []
        result = QueryResult()

        while True:
            try:
                line_bytes = await self._transport.readline()
            except Exception:
                break
            if not line_bytes:
                break
            line = line_bytes.decode().strip()
            if not line:
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg_type = data.get("type")

            if msg_type == "system":
                continue

            elif msg_type == "assistant":
                message = data.get("message", {})
                content = message.get("content", [])
                if isinstance(content, str):
                    response_parts.append(content)
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            response_parts.append(block.get("text", ""))
                elif "content" in data and data["content"] != content:
                    flat = data["content"]
                    if isinstance(flat, str):
                        response_parts.append(flat)

                if self._protocol:
                    self._protocol.emit_forwarded(
                        data, self.name, block_id, block_name
                    )

            elif msg_type == "stream_event":
                if self._protocol:
                    self._protocol.emit_forwarded(
                        data, self.name, block_id, block_name
                    )

            elif msg_type == "rate_limit_event":
                continue

            elif msg_type == "control_request":
                await self._handle_control_request(data)

            elif msg_type == "result":
                result.response_text = (
                    "\n".join(response_parts)
                    if response_parts
                    else data.get("result", "")
                )
                result.cost_usd = data.get("total_cost_usd", 0.0)
                result.duration_ms = data.get("duration_ms", 0)
                self.total_cost += result.cost_usd

                if data.get("session_id"):
                    self.session_id = data["session_id"]
                break

        if not result.response_text and response_parts:
            result.response_text = "\n".join(response_parts)

        return result

    async def _handle_control_request(self, request: dict[str, Any]) -> None:
        """Relay a control request from inner claude through the protocol handler."""
        if not self._protocol:
            deny = {
                "type": "control_response",
                "response": {
                    "request_id": request.get("request_id", ""),
                    "allowed": False,
                },
            }
            await self._transport.write((json.dumps(deny) + "\n").encode())
            return

        response = await self._protocol.forward_control_request(request)
        await self._transport.write((json.dumps(response) + "\n").encode())

    async def clear(self) -> None:
        """Clear conversation history by restarting the subprocess."""
        await self.stop()
        await self.start()

    async def stop(self) -> None:
        """Terminate the subprocess and clean up."""
        await self._transport.stop()

    @property
    def is_running(self) -> bool:
        return self._transport.is_running
