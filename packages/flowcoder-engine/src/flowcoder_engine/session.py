"""Session — a single Claude CLI subprocess.

Manages the lifecycle of one Claude process: start, query, stop.
Forwards inner claude messages (assistant, stream_event) to the outer
protocol handler.

Uses the inline ClaudeProcess for subprocess management.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from opentelemetry import trace

from .subprocess import ClaudeProcess

_tracer = trace.get_tracer(__name__)

if TYPE_CHECKING:
    from .protocol import ProtocolHandler

# Async callback that the proxy core provides for relaying control requests.
# Takes a control_request dict, returns the control_response dict.
ControlCallback = Callable[
    [dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]
]


class QueryResult:
    """Result from a session query."""

    __slots__ = ("cost_usd", "duration_ms", "response_text", "structured_output")

    def __init__(
        self,
        response_text: str = "",
        structured_output: dict[str, Any] | None = None,
        cost_usd: float = 0.0,
        duration_ms: int = 0,
    ) -> None:
        self.response_text = response_text
        self.structured_output = structured_output
        self.cost_usd = cost_usd
        self.duration_ms = duration_ms


def _clean_env() -> dict[str, str]:
    """Return a copy of os.environ for the inner Claude CLI.

    Sets the env vars that make inner Claude use the SDK control protocol
    (for tool permissions and MCP), without depending on the full
    claude-code-sdk package.
    """
    from .cli import SDK_VERSION

    env = dict(os.environ)
    env.pop("CLAUDECODE", None)
    env["CLAUDE_CODE_ENTRYPOINT"] = "sdk-py"
    env["CLAUDE_AGENT_SDK_VERSION"] = SDK_VERSION
    return env


class Session:
    """A single Claude CLI subprocess speaking stream-json protocol."""

    def __init__(
        self,
        name: str,
        claude_cmd: list[str],
        protocol: ProtocolHandler | None = None,
        control_callback: ControlCallback | None = None,
    ) -> None:
        self.name = name
        self.session_id: str | None = None
        self.total_cost: float = 0.0
        self._claude_cmd = claude_cmd
        self._protocol = protocol
        self._control_callback = control_callback
        self._process: ClaudeProcess | None = None

    async def start(self) -> None:
        """Spawn the claude subprocess."""
        _tracer.start_span("session.start", attributes={"session.name": self.name}).end()
        self._process = ClaudeProcess()
        await self._process.start(self._claude_cmd, _clean_env(), os.getcwd())

    async def query(
        self,
        prompt: str,
        block_id: str = "",
        block_name: str = "",
    ) -> QueryResult:
        """Send a prompt and collect the full response.

        Reads messages from the inner claude process until a 'result'
        message.  Forwards assistant/stream_event to the protocol handler.
        Relays control_request via the control_callback.
        """
        with _tracer.start_as_current_span(
            "session.query",
            attributes={"session.name": self.name, "block.id": block_id, "block.name": block_name},
        ) as span:
            assert self._process is not None

            msg = {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": prompt,
                },
            }
            await self._process.write(msg)

            response_parts: list[str] = []
            result = QueryResult()

            while True:
                data = await self._process.read()
                if data is None:
                    break

                msg_type = data.get("type")

                if msg_type == "system":
                    continue

                if msg_type == "assistant":
                    message = data.get("message", {})
                    content = message.get("content", [])
                    if isinstance(content, str):
                        response_parts.append(content)
                    elif isinstance(content, list):
                        response_parts.extend(
                            block.get("text", "")
                            for block in content
                            if isinstance(block, dict) and block.get("type") == "text"
                        )
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

            span.set_attributes({
                "session.cost_usd": result.cost_usd,
                "session.duration_ms": result.duration_ms,
            })
            return result

    async def _handle_control_request(self, request: dict[str, Any]) -> None:
        """Relay a control request from inner claude to the client."""
        assert self._process is not None

        if self._control_callback:
            response = await self._control_callback(request)
            await self._process.write(response)
        else:
            # No callback — deny the request
            deny = {
                "type": "control_response",
                "response": {
                    "request_id": request.get("request_id", ""),
                    "allowed": False,
                },
            }
            await self._process.write(deny)

    async def clear(self) -> None:
        """Clear conversation by restarting the subprocess.

        Cost tracking is preserved across restarts.
        """
        _tracer.start_span("session.clear", attributes={"session.name": self.name}).end()
        await self.stop()
        await self.start()

    async def stop(self) -> None:
        """Terminate the subprocess."""
        _tracer.start_span("session.stop", attributes={"session.name": self.name}).end()
        if self._process:
            await self._process.stop()
            self._process = None

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.is_running
