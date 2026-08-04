"""Tests for GUISessionAdapter — verifies the BaseSession bridge works correctly."""

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure engine packages are importable
sys.path.insert(0, "packages/flowcoder-engine/src")
sys.path.insert(0, ".")

from flowcoder_engine.session import BaseSession, QueryResult
from src.services.exceptions import PromptResult


# -- Mock ClaudeEngineService for tests --

def _make_mock_service(**overrides):
    """Create a mock ClaudeEngineService with sensible defaults."""
    svc = MagicMock()
    svc.cwd = "/tmp/test"
    svc.system_prompt = "You are a test agent."
    svc.permission_mode = "plan"
    svc.max_retries = 3
    svc.timeout_seconds = 300
    svc.stderr_callback = None
    svc.model = "claude-sonnet-4-5-20250929"
    svc.extra_env = {}
    svc._session_active = True

    svc.start_session = AsyncMock()
    svc.end_session = AsyncMock()
    svc.reset_session = AsyncMock()
    svc.execute_prompt = AsyncMock(return_value=PromptResult(
        raw_response="Hello from Claude",
        structured_output=None,
        duration_ms=150,
    ))

    for k, v in overrides.items():
        setattr(svc, k, v)
    return svc


def _make_adapter(name="test", **svc_overrides):
    from src.adapters.gui_session import GUISessionAdapter
    return GUISessionAdapter(_make_mock_service(**svc_overrides), name=name)


# -- Properties --

class TestProperties:
    def test_name(self):
        adapter = _make_adapter(name="my-session")
        assert adapter.name == "my-session"

    def test_session_id_initially_none(self):
        adapter = _make_adapter()
        assert adapter.session_id is None

    def test_total_cost_initially_zero(self):
        adapter = _make_adapter()
        assert adapter.total_cost == 0.0

    def test_is_running_reflects_service(self):
        adapter = _make_adapter()
        assert adapter.is_running is True
        adapter._service._session_active = False
        assert adapter.is_running is False

    def test_is_subclass_of_base_session(self):
        adapter = _make_adapter()
        assert isinstance(adapter, BaseSession)


# -- query() --

class TestQuery:
    @pytest.mark.asyncio
    async def test_query_returns_query_result(self):
        adapter = _make_adapter()
        result = await adapter.query("What is 2+2?")

        assert isinstance(result, QueryResult)
        assert result.response_text == "Hello from Claude"
        assert result.cost_usd == 0.0
        adapter._service.execute_prompt.assert_called_once_with("What is 2+2?")

    @pytest.mark.asyncio
    async def test_query_uses_service_duration(self):
        adapter = _make_adapter()
        result = await adapter.query("test")
        assert result.duration_ms == 150

    @pytest.mark.asyncio
    async def test_query_falls_back_to_wall_clock_when_no_service_duration(self):
        adapter = _make_adapter()
        adapter._service.execute_prompt = AsyncMock(return_value=PromptResult(
            raw_response="ok",
            duration_ms=None,
        ))
        result = await adapter.query("test")
        # Wall clock duration should be >= 0
        assert result.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_query_passes_structured_output(self):
        adapter = _make_adapter()
        adapter._service.execute_prompt = AsyncMock(return_value=PromptResult(
            raw_response='{"answer": 4}',
            structured_output={"answer": 4},
            duration_ms=100,
        ))
        result = await adapter.query("test")
        assert result.structured_output == {"answer": 4}

    @pytest.mark.asyncio
    async def test_query_ignores_block_id_and_name(self):
        """block_id and block_name are part of BaseSession interface but
        ClaudeEngineService doesn't use them — verify they don't cause errors."""
        adapter = _make_adapter()
        result = await adapter.query("test", block_id="b1", block_name="prompt_0")
        assert result.response_text == "Hello from Claude"


# -- clone() --

class TestClone:
    def test_clone_returns_new_adapter(self):
        adapter = _make_adapter(name="original")

        with patch("src.services.claude_engine_service.ClaudeEngineService") as MockCls:
            MockCls.return_value = _make_mock_service()
            cloned = adapter.clone("spawned-1")

        assert cloned is not adapter
        assert cloned.name == "spawned-1"
        assert cloned._service is not adapter._service

    def test_clone_preserves_config(self):
        adapter = _make_adapter(
            model="claude-haiku-4-5-20251001",
            permission_mode="bypassPermissions",
        )

        with patch("src.services.claude_engine_service.ClaudeEngineService") as MockCls:
            MockCls.return_value = _make_mock_service()
            cloned = adapter.clone("child")

        MockCls.assert_called_once_with(
            cwd="/tmp/test",
            system_prompt="You are a test agent.",
            permission_mode="bypassPermissions",
            max_retries=3,
            timeout_seconds=300,
            stderr_callback=None,
            model="claude-haiku-4-5-20251001",
            extra_env={},
        )

    def test_clone_has_independent_cost(self):
        adapter = _make_adapter()
        adapter._total_cost = 1.50

        with patch("src.services.claude_engine_service.ClaudeEngineService") as MockCls:
            MockCls.return_value = _make_mock_service()
            cloned = adapter.clone("child")

        assert cloned.total_cost == 0.0


# -- with_model() --

class TestWithModel:
    def test_with_model_returns_new_adapter_with_different_model(self):
        adapter = _make_adapter()

        with patch("src.services.claude_engine_service.ClaudeEngineService") as MockCls:
            MockCls.return_value = _make_mock_service()
            new = adapter.with_model("claude-haiku-4-5-20251001")

        assert new is not adapter
        assert new.name == adapter.name
        MockCls.assert_called_once()
        call_kwargs = MockCls.call_args[1]
        assert call_kwargs["model"] == "claude-haiku-4-5-20251001"


# -- Lifecycle: start, clear, stop --

class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_calls_start_session(self):
        adapter = _make_adapter()
        await adapter.start()
        adapter._service.start_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_clear_calls_reset_session(self):
        adapter = _make_adapter()
        await adapter.clear()
        adapter._service.reset_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_calls_end_session(self):
        adapter = _make_adapter()
        await adapter.stop()
        adapter._service.end_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_full_lifecycle(self):
        """start → query → clear → query → stop — no errors."""
        adapter = _make_adapter()
        adapter._service._session_active = False

        await adapter.start()
        assert adapter._service.start_session.called

        adapter._service._session_active = True
        r1 = await adapter.query("first")
        assert r1.response_text == "Hello from Claude"

        await adapter.clear()
        assert adapter._service.reset_session.called

        r2 = await adapter.query("second")
        assert r2.response_text == "Hello from Claude"

        await adapter.stop()
        assert adapter._service.end_session.called
