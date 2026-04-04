"""Tests for the transport abstraction (transport.py).

Verifies that:
- DirectTransport conforms to SessionTransport protocol
- Session uses DirectTransport by default
- Session accepts an injected transport
- MockSession (existing test fixture) is unchanged
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from flowcoder_engine.transport import DirectTransport, SessionTransport
from flowcoder_engine.session import Session


class TestSessionTransportProtocol:
    def test_direct_transport_is_session_transport(self):
        """DirectTransport implements SessionTransport protocol."""
        assert isinstance(DirectTransport(), SessionTransport)


class TestSessionDefaultTransport:
    def test_session_uses_direct_transport_by_default(self):
        """Session() without transport arg uses DirectTransport."""
        session = Session("test", "/usr/bin/claude", {})
        assert isinstance(session._transport, DirectTransport)


class TestSessionInjectedTransport:
    @pytest.mark.asyncio
    async def test_session_uses_injected_transport(self):
        """Custom transport is used for start/query/stop."""
        mock_transport = AsyncMock(spec=SessionTransport)
        mock_transport.is_running = True

        # readline returns a result message then EOF
        import json
        result_line = json.dumps({
            "type": "result",
            "result": "hello",
            "total_cost_usd": 0.01,
            "duration_ms": 100,
            "session_id": "test-session-123",
        }).encode() + b"\n"
        mock_transport.readline = AsyncMock(side_effect=[result_line, b""])

        session = Session("test", "/usr/bin/claude", {}, transport=mock_transport)

        await session.start()
        mock_transport.start.assert_called_once()

        result = await session.query("Hello")
        assert result.response_text == "hello"
        assert result.cost_usd == 0.01

        mock_transport.write.assert_called()

        await session.stop()
        mock_transport.stop.assert_called_once()

    def test_session_is_running_delegates_to_transport(self):
        """is_running property delegates to transport."""
        mock_transport = MagicMock()
        type(mock_transport).is_running = PropertyMock(return_value=True)

        session = Session("test", "/usr/bin/claude", {}, transport=mock_transport)
        assert session.is_running is True

        type(mock_transport).is_running = PropertyMock(return_value=False)
        assert session.is_running is False


class TestMockSessionUnchanged:
    """Verify that MockSession (from conftest) still works as before."""

    @pytest.mark.asyncio
    async def test_mock_session_query(self):
        from tests.conftest import MockSession
        from flowcoder_engine.session import QueryResult

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
