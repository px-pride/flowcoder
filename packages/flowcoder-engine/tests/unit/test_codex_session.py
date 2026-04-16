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

    def test_clone_preserves_control_callback(self):
        cb = AsyncMock()
        session = CodexSession("test", control_callback=cb)
        cloned = session.clone("worker")
        assert cloned._control_callback is cb

    def test_with_model_preserves_control_callback(self):
        cb = AsyncMock()
        session = CodexSession("test", control_callback=cb)
        new = session.with_model("gpt-4o")
        assert new._control_callback is cb


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


class TestCodexApprovalHandler:
    """Test _handle_approval translation between Codex and Claude formats.

    NOTE: These are API-contract tests only — they verify the translation
    logic using mock objects, not real Codex approval flow.
    """

    @pytest.fixture
    def session_with_callback(self):
        cb = AsyncMock()
        session = CodexSession("test-approval", control_callback=cb)
        session._cwd = "/work"
        return session, cb

    @pytest.mark.asyncio
    async def test_command_approval_accepted(self, session_with_callback):
        from codex_app_server_sdk import CommandApprovalRequest

        session, cb = session_with_callback
        cb.return_value = {"response": {"request_id": "1", "allowed": True}}

        req = CommandApprovalRequest(
            request_id=1,
            thread_id="t1",
            turn_id="turn1",
            item_id="item1",
            command="rm -rf /tmp/junk",
            cwd="/work",
            reason="cleanup",
        )
        decision = await session._handle_approval(req)

        assert decision == "accept"
        cb.assert_awaited_once()
        call_arg = cb.call_args[0][0]
        assert call_arg["type"] == "control_request"
        assert call_arg["request_id"] == "1"
        assert call_arg["request"]["subtype"] == "tool_permission_request"
        assert call_arg["request"]["command"] == "rm -rf /tmp/junk"

    @pytest.mark.asyncio
    async def test_command_approval_declined(self, session_with_callback):
        from codex_app_server_sdk import CommandApprovalRequest

        session, cb = session_with_callback
        cb.return_value = {"response": {"request_id": "2", "allowed": False}}

        req = CommandApprovalRequest(
            request_id=2,
            thread_id="t1",
            turn_id="turn1",
            item_id="item1",
            command="dangerous-cmd",
        )
        decision = await session._handle_approval(req)

        assert decision == "decline"

    @pytest.mark.asyncio
    async def test_file_change_approval_accepted(self, session_with_callback):
        from codex_app_server_sdk import FileChangeApprovalRequest

        session, cb = session_with_callback
        cb.return_value = {"response": {"request_id": "3", "allowed": True}}

        req = FileChangeApprovalRequest(
            request_id=3,
            thread_id="t1",
            turn_id="turn1",
            item_id="item1",
            grant_root="/home/user/project",
            reason="write config",
        )
        decision = await session._handle_approval(req)

        assert decision == "accept"
        call_arg = cb.call_args[0][0]
        assert call_arg["request"]["subtype"] == "file_change_permission_request"
        assert call_arg["request"]["grant_root"] == "/home/user/project"

    @pytest.mark.asyncio
    async def test_command_null_fields_use_defaults(self, session_with_callback):
        from codex_app_server_sdk import CommandApprovalRequest

        session, cb = session_with_callback
        cb.return_value = {"response": {"request_id": "4", "allowed": True}}

        req = CommandApprovalRequest(
            request_id=4,
            thread_id="t1",
            turn_id="turn1",
            item_id="item1",
        )
        await session._handle_approval(req)

        call_arg = cb.call_args[0][0]
        assert call_arg["request"]["command"] == ""
        assert call_arg["request"]["cwd"] == "/work"  # falls back to session cwd
