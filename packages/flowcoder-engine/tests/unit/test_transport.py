"""Tests for Session and ClaudeProcess."""

from __future__ import annotations

import pytest
from flowcoder_engine.session import QueryResult, Session


class TestSessionInit:
    def test_session_initializes_without_process(self):
        """Session() creates process lazily on start()."""
        session = Session("test", ["/usr/bin/claude", "-p"])
        assert session._process is None

    def test_session_is_not_running_before_start(self):
        """is_running is False before start()."""
        session = Session("test", ["/usr/bin/claude", "-p"])
        assert session.is_running is False


class TestMockSessionUnchanged:
    """Verify that MockSession (from conftest) still works as before."""

    @pytest.mark.asyncio
    async def test_mock_session_query(self):
        from tests.conftest import MockSession

        ms = MockSession(responses=["Answer 1", "Answer 2"])
        result = await ms.query("test prompt")
        assert isinstance(result, QueryResult)
        assert result.response_text == "Answer 1"

        result2 = await ms.query("second prompt")
        assert result2.response_text == "Answer 2"

    @pytest.mark.asyncio
    async def test_mock_session_clear(self):
        from tests.conftest import MockSession

        ms = MockSession()
        await ms.clear()
        assert ms._clear_count == 1

    @pytest.mark.asyncio
    async def test_mock_session_stop(self):
        from tests.conftest import MockSession

        ms = MockSession()
        await ms.stop()  # should not raise

    def test_mock_session_is_running(self):
        from tests.conftest import MockSession

        ms = MockSession()
        assert ms.is_running is True
