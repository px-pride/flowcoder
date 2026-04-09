"""CodexSession — wraps the codex-app-server-sdk Python package.

Uses CodexClient.connect_stdio() to spawn the codex app-server process,
then communicates via ThreadHandle.chat_once().
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from .session import BaseSession, QueryResult

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from codex_app_server_sdk import CodexClient, ThreadHandle


class CodexSession(BaseSession):
    """A Codex session using the native Python SDK."""

    def __init__(
        self,
        name: str,
        model: str | None = None,
        cwd: str | None = None,
    ) -> None:
        self._name = name
        self._model = model
        self._cwd = cwd or os.getcwd()
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
        )

    def with_model(self, model: str) -> CodexSession:
        return CodexSession(
            name=self._name,
            model=model,
            cwd=self._cwd,
        )

    async def start(self) -> None:
        """Start the Codex app-server and create a thread."""
        from codex_app_server_sdk import CodexClient, ThreadConfig

        self._client = CodexClient.connect_stdio(cwd=self._cwd)
        await self._client.start()
        await self._client.initialize()

        config = ThreadConfig(
            model=self._model,
            sandbox="danger-full-access",
            cwd=self._cwd,
        )
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
        """Send a prompt to the Codex thread and return the result."""
        assert self._thread is not None, "CodexSession not started"

        result = await self._thread.chat_once(prompt)

        return QueryResult(
            response_text=result.final_text or "",
        )

    async def clear(self) -> None:
        """Clear conversation by creating a new thread."""
        assert self._client is not None, "CodexSession not started"
        from codex_app_server_sdk import ThreadConfig

        config = ThreadConfig(
            model=self._model,
            sandbox="danger-full-access",
            cwd=self._cwd,
        )
        self._thread = await self._client.start_thread(config)
        self._session_id = self._thread.thread_id
        log.info("CodexSession '%s' cleared (new thread=%s)", self._name, self._session_id)

    async def stop(self) -> None:
        """Shut down the Codex app-server."""
        if self._client is not None:
            await self._client.close()
            self._client = None
        self._thread = None
