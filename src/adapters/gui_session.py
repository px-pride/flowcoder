"""GUISessionAdapter — bridges ClaudeAgentService to engine's BaseSession.

Wraps the GUI's ClaudeAgentService so the engine's GraphWalker can use it
without knowing about the GUI's service layer.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from flowcoder_engine.session import BaseSession, QueryResult

if TYPE_CHECKING:
    from src.services.claude_service import ClaudeAgentService

log = logging.getLogger(__name__)


class GUISessionAdapter(BaseSession):
    """Adapts ClaudeAgentService to the engine's BaseSession interface.

    The GUI owns the ClaudeAgentService lifecycle (start/stop). This adapter
    translates engine query() calls into execute_prompt() calls on the
    underlying service.
    """

    def __init__(
        self,
        agent_service: ClaudeAgentService,
        name: str = "gui",
    ) -> None:
        self._service = agent_service
        self._name = name
        self._total_cost: float = 0.0
        self._session_id: str | None = None

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
        return self._service._session_active

    # -- BaseSession methods --

    def clone(self, name: str) -> GUISessionAdapter:
        """Create a new adapter with a fresh ClaudeAgentService copy."""
        from src.services.claude_service import ClaudeAgentService

        new_service = ClaudeAgentService(
            cwd=self._service.cwd,
            system_prompt=self._service.system_prompt,
            permission_mode=self._service.permission_mode,
            max_retries=self._service.max_retries,
            timeout_seconds=self._service.timeout_seconds,
            stderr_callback=self._service.stderr_callback,
            model=self._service.model,
        )
        return GUISessionAdapter(new_service, name=name)

    def with_model(self, model: str) -> GUISessionAdapter:
        """Return a new adapter configured for a different model."""
        from src.services.claude_service import ClaudeAgentService

        new_service = ClaudeAgentService(
            cwd=self._service.cwd,
            system_prompt=self._service.system_prompt,
            permission_mode=self._service.permission_mode,
            max_retries=self._service.max_retries,
            timeout_seconds=self._service.timeout_seconds,
            stderr_callback=self._service.stderr_callback,
            model=model,
        )
        return GUISessionAdapter(new_service, name=self._name)

    async def start(self) -> None:
        """Start the underlying ClaudeAgentService session."""
        await self._service.start_session()

    async def query(
        self,
        prompt: str,
        block_id: str = "",
        block_name: str = "",
    ) -> QueryResult:
        """Send a prompt via ClaudeAgentService and return a QueryResult."""
        start_ms = time.monotonic_ns() // 1_000_000

        result = await self._service.execute_prompt(prompt)

        duration_ms = (time.monotonic_ns() // 1_000_000) - start_ms
        # Use the service's own duration if available
        if result.duration_ms:
            duration_ms = result.duration_ms

        qr = QueryResult(
            response_text=result.raw_response,
            structured_output=result.structured_output,
            cost_usd=0.0,  # GUI SDK doesn't expose per-query cost
            duration_ms=duration_ms,
        )
        return qr

    async def clear(self) -> None:
        """Clear conversation by resetting the session."""
        await self._service.reset_session()

    async def stop(self) -> None:
        """Stop the underlying service session."""
        await self._service.end_session()
