"""CodexSession — wraps the codex-app-server-sdk Python package.

Uses CodexClient.connect_stdio() to spawn the codex app-server process,
then communicates via ThreadHandle.chat() streaming iterator.
"""

from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING, Any

from opentelemetry import trace

from .session import BaseSession, QueryResult

log = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)

if TYPE_CHECKING:
    from codex_app_server_sdk import CodexClient, ThreadHandle

    from .protocol import ProtocolHandler

# Map Claude CLI permission modes to Codex approval policies.
_PERMISSION_TO_APPROVAL: dict[str, str] = {
    "bypassPermissions": "never",
    "default": "untrusted",
}

_DEFAULT_BASE_INSTRUCTIONS = """\
You are operating inside a flowchart execution system. You have filesystem and \
shell access for work tasks.

Some prompts you receive reference services that are NOT available in this \
environment (Discord API, MCP tools, custom CLIs like set_channel_status or \
minflow). If a prompt asks you to call a tool or service that is not available:
- Do NOT run shell commands to approximate the unavailable tool.
- Instead, output exactly: {"status": "skipped", "reason": "tool not available"}
- If the prompt says "do not output any text" but the requested tool is \
unavailable, override that restriction and output the JSON above anyway.

For all other requests, respond normally.\
"""


class CodexSession(BaseSession):
    """A Codex session using the native Python SDK."""

    def __init__(
        self,
        name: str,
        model: str | None = None,
        cwd: str | None = None,
        base_instructions: str | None = None,
        sandbox: str | None = None,
        approval_policy: str | None = None,
        protocol: ProtocolHandler | None = None,
    ) -> None:
        self._name = name
        self._model = model
        self._cwd = cwd or os.getcwd()
        self._base_instructions = base_instructions or _DEFAULT_BASE_INSTRUCTIONS
        self._sandbox: str = sandbox or "danger-full-access"
        self._approval_policy = approval_policy
        self._protocol = protocol
        self._session_id: str | None = None
        self._total_cost: float = 0.0
        self._client: CodexClient | None = None
        self._thread: ThreadHandle | None = None

    # -- BaseSession properties --

    @property
    def name(self) -> str:
        return self._name

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def total_cost(self) -> float:
        return self._total_cost

    @property
    def is_running(self) -> bool:
        return self._client is not None and self._thread is not None

    # -- BaseSession methods --

    def clone(self, name: str) -> CodexSession:
        return CodexSession(
            name=name,
            model=self._model,
            cwd=self._cwd,
            base_instructions=self._base_instructions,
            sandbox=self._sandbox,
            approval_policy=self._approval_policy,
            protocol=self._protocol,
        )

    def with_model(self, model: str) -> CodexSession:
        return CodexSession(
            name=self._name,
            model=model,
            cwd=self._cwd,
            base_instructions=self._base_instructions,
            sandbox=self._sandbox,
            approval_policy=self._approval_policy,
            protocol=self._protocol,
        )

    def _build_thread_config(self) -> Any:
        """Build a ThreadConfig from current session settings."""
        from codex_app_server_sdk import ThreadConfig

        return ThreadConfig(
            model=self._model,
            sandbox=self._sandbox,
            cwd=self._cwd,
            base_instructions=self._base_instructions,
            approval_policy=self._approval_policy,
        )

    async def start(self) -> None:
        """Start the Codex app-server and create a thread."""
        with _tracer.start_as_current_span(
            "session.start", attributes={"session.name": self.name},
        ):
            from codex_app_server_sdk import CodexClient

            self._client = CodexClient.connect_stdio(cwd=self._cwd)
            await self._client.start()
            await self._client.initialize()

            config = self._build_thread_config()
            self._thread = await self._client.start_thread(config)
            self._session_id = self._thread.thread_id
            log.info(
                "CodexSession '%s' started (thread=%s, model=%s)",
                self._name, self._session_id, self._model or "default",
            )

    async def query(
        self,
        prompt: str,
        block_id: str = "",
        block_name: str = "",
    ) -> QueryResult:
        """Send a prompt and stream ConversationStep events until complete."""
        with _tracer.start_as_current_span(
            "session.query",
            attributes={
                "session.name": self.name,
                "block.id": block_id,
                "block.name": block_name,
            },
        ) as span:
            assert self._thread is not None, "CodexSession not started"

            start_time = time.monotonic()
            try:
                from codex_app_server_sdk import CodexError

                final_text = ""
                async for step in self._thread.chat(prompt):
                    # Forward each step to the protocol handler for
                    # streaming visibility (thinking, exec, tool, etc.)
                    if self._protocol:
                        self._protocol.emit_forwarded(
                            _step_to_message(step),
                            self.name,
                            block_id,
                            block_name,
                        )

                    # Capture the last agentMessage as the final response
                    if step.step_type == "codex" and step.text:
                        final_text = step.text

            except CodexError as e:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                span.set_status(trace.StatusCode.ERROR, str(e))
                span.set_attributes({"session.duration_ms": duration_ms})
                return QueryResult(
                    response_text=f"Error: {type(e).__name__}: {e}",
                    duration_ms=duration_ms,
                )

            duration_ms = int((time.monotonic() - start_time) * 1000)
            span.set_attributes({"session.duration_ms": duration_ms})
            return QueryResult(
                response_text=final_text,
                duration_ms=duration_ms,
            )

    async def set_permission_mode(self, mode: str) -> None:
        """Change the approval policy on the running Codex thread."""
        if self._thread is None:
            return
        from codex_app_server_sdk import ThreadConfig

        approval_policy = _PERMISSION_TO_APPROVAL.get(mode)
        if approval_policy is None:
            log.warning(
                "CodexSession: unsupported permission mode %r, ignoring", mode,
            )
            return
        self._approval_policy = approval_policy
        await self._thread.update_defaults(
            ThreadConfig(approval_policy=approval_policy),
        )

    async def clear(self) -> None:
        """Clear conversation by creating a new thread."""
        with _tracer.start_as_current_span(
            "session.clear", attributes={"session.name": self.name},
        ):
            assert self._client is not None, "CodexSession not started"

            config = self._build_thread_config()
            self._thread = await self._client.start_thread(config)
            self._session_id = self._thread.thread_id
            log.info(
                "CodexSession '%s' cleared (new thread=%s)",
                self._name, self._session_id,
            )

    async def stop(self) -> None:
        """Shut down the Codex app-server."""
        _tracer.start_span(
            "session.stop", attributes={"session.name": self.name},
        ).end()
        if self._client is not None:
            await self._client.close()
            self._client = None
        self._thread = None


def _step_to_message(step: Any) -> dict[str, Any]:
    """Convert a ConversationStep to a synthetic message for emit_forwarded.

    Produces a format compatible with the protocol handler's session_message
    wrapper.  The step_type field ("thinking", "exec", "codex", "tool",
    "file") lets consumers distinguish step kinds.
    """
    if step.step_type == "codex":
        # Final assistant response — format like a Claude assistant message
        # so existing protocol consumers can parse it.
        return {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": step.text or ""}],
            },
        }
    # All other step types (thinking, exec, tool, file)
    return {
        "type": "stream_event",
        "step_type": step.step_type,
        "item_type": step.item_type,
        "text": step.text or "",
    }
