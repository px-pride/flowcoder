"""Tests for CodexSession using the codex-app-server-sdk Python SDK."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from flowcoder_engine.codex_session import CodexSession
from flowcoder_engine.session import BaseSession


class TestCodexSessionInit:
    def test_implements_base_session(self):
        session = CodexSession("test")
        assert isinstance(session, BaseSession)

    def test_not_running_before_start(self):
        session = CodexSession("test")
        assert session.is_running is False

    def test_properties_before_start(self):
        session = CodexSession("test")
        assert session.name == "test"
        assert session.session_id is None
        assert session.total_cost == 0.0


class TestCodexSessionClone:
    def test_clone_creates_new_session(self):
        session = CodexSession("original", cwd="/tmp")
        cloned = session.clone("worker")
        assert cloned.name == "worker"
        assert cloned._cwd == "/tmp"
        assert cloned is not session

    def test_clone_preserves_model(self):
        session = CodexSession("test", model="gpt-4o")
        cloned = session.clone("worker")
        assert cloned._model == "gpt-4o"

    def test_with_model_sets_model(self):
        session = CodexSession("test")
        new = session.with_model("gpt-4o")
        assert new._model == "gpt-4o"
        assert new is not session
        assert new.name == "test"

    def test_with_model_replaces_existing(self):
        session = CodexSession("test", model="gpt-4o")
        new = session.with_model("o3")
        assert new._model == "o3"
        assert session._model == "gpt-4o"


class MockStep:
    """Mimics codex_app_server_sdk.ConversationStep."""

    def __init__(
        self,
        step_type: str = "codex",
        item_type: str | None = "agentMessage",
        text: str | None = None,
        data: dict | None = None,
    ):
        self.step_type = step_type
        self.item_type = item_type
        self.text = text
        self.data = data or {}


def _make_chat_iterator(*steps):
    """Create an async iterator that yields MockStep objects."""

    async def _iter(prompt):
        for step in steps:
            yield step

    return _iter


class TestCodexSessionWithMock:
    """Test CodexSession by mocking the codex_app_server_sdk.

    NOTE: These are API-contract tests only (query returns QueryResult,
    clone preserves params, etc.).  They do NOT verify real Codex behavior.
    Integration tests against a real backend are required for that.
    """

    @pytest.fixture
    async def session_with_mock(self):
        """Create a CodexSession with mocked CodexClient and ThreadHandle."""
        session = CodexSession("test-codex")

        # Create mock thread handle
        mock_thread = MagicMock()
        mock_thread.thread_id = "mock-thread-123"
        mock_thread.chat = _make_chat_iterator(
            MockStep(step_type="codex", text="Codex says hello"),
        )

        # Create mock client
        mock_client = AsyncMock()
        mock_client.start = AsyncMock(return_value=mock_client)
        mock_client.start_thread = AsyncMock(return_value=mock_thread)
        mock_client.close = AsyncMock(return_value=None)

        # Wire up (simulate what start() would set)
        session._client = mock_client
        session._thread = mock_thread
        session._session_id = mock_thread.thread_id

        yield session, mock_thread, mock_client

    @pytest.mark.asyncio
    async def test_query_returns_response(self, session_with_mock):
        session, mock_thread, _ = session_with_mock
        result = await session.query("Hello Codex")
        assert result.response_text == "Codex says hello"

    @pytest.mark.asyncio
    async def test_query_with_no_codex_step(self, session_with_mock):
        session, mock_thread, _ = session_with_mock
        mock_thread.chat = _make_chat_iterator(
            MockStep(step_type="thinking", text="Let me think..."),
        )
        result = await session.query("Hello")
        assert result.response_text == ""

    @pytest.mark.asyncio
    async def test_query_multiple(self, session_with_mock):
        session, mock_thread, _ = session_with_mock
        call_count = 0

        def _make_iter(prompt):
            nonlocal call_count
            call_count += 1
            texts = ["First answer", "Second answer"]
            return _make_chat_iterator(
                MockStep(step_type="codex", text=texts[call_count - 1]),
            )(prompt)

        mock_thread.chat = _make_iter
        r1 = await session.query("First")
        r2 = await session.query("Second")
        assert r1.response_text == "First answer"
        assert r2.response_text == "Second answer"

    @pytest.mark.asyncio
    async def test_is_running(self, session_with_mock):
        session, _, _ = session_with_mock
        assert session.is_running is True

    @pytest.mark.asyncio
    async def test_stop(self, session_with_mock):
        session, _, mock_client = session_with_mock
        await session.stop()
        assert session.is_running is False
        mock_client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_session_id(self, session_with_mock):
        session, _, _ = session_with_mock
        assert session.session_id == "mock-thread-123"

    @pytest.mark.asyncio
    async def test_clear_creates_new_thread(self, session_with_mock):
        session, _, mock_client = session_with_mock
        new_thread = AsyncMock()
        new_thread.thread_id = "new-thread-456"
        mock_client.start_thread.return_value = new_thread

        await session.clear()

        assert session._thread is new_thread
        assert session.session_id == "new-thread-456"
        mock_client.start_thread.await_count == 1
