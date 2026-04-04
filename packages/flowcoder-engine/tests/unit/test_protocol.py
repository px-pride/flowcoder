"""Tests for ProtocolHandler --- specifically the status_request feature."""

from __future__ import annotations

import asyncio
import io
import json
import sys
from unittest.mock import patch

import pytest

from flowcoder_engine.protocol import ProtocolHandler


class TestStatusRequest:
    """Tests for the status_request / status_response mechanism."""

    def test_busy_defaults_to_false(self):
        """New ProtocolHandler has busy=False."""
        p = ProtocolHandler()
        assert p.busy is False

    def test_busy_can_be_set(self):
        p = ProtocolHandler()
        p.busy = True
        assert p.busy is True
        p.busy = False
        assert p.busy is False

    @pytest.mark.asyncio
    async def test_status_request_emits_response(self):
        """_read_loop handles status_request by emitting status_response on stdout."""
        p = ProtocolHandler()

        # Feed a status_request message into a fake stdin
        msg = json.dumps({"type": "status_request"}) + "\n"
        fake_stdin = asyncio.StreamReader()
        fake_stdin.feed_data(msg.encode())
        fake_stdin.feed_eof()
        p._stdin_reader = fake_stdin

        # Capture stdout
        captured = io.StringIO()
        with patch.object(sys, "stdout", captured):
            await p._read_loop()

        # Parse the emitted response
        output = captured.getvalue().strip()
        assert output, "No output emitted"
        response = json.loads(output)
        assert response["type"] == "status_response"
        assert response["busy"] is False

    @pytest.mark.asyncio
    async def test_status_request_reflects_busy_state(self):
        """status_response reflects current busy flag."""
        p = ProtocolHandler()
        p.busy = True

        msg = json.dumps({"type": "status_request"}) + "\n"
        fake_stdin = asyncio.StreamReader()
        fake_stdin.feed_data(msg.encode())
        fake_stdin.feed_eof()
        p._stdin_reader = fake_stdin

        captured = io.StringIO()
        with patch.object(sys, "stdout", captured):
            await p._read_loop()

        response = json.loads(captured.getvalue().strip())
        assert response["type"] == "status_response"
        assert response["busy"] is True

    @pytest.mark.asyncio
    async def test_status_request_not_queued_to_inbox(self):
        """status_request is handled in _read_loop, not put in inbox."""
        p = ProtocolHandler()

        # Feed status_request + a normal message + EOF
        lines = (
            json.dumps({"type": "status_request"}) + "\n"
            + json.dumps({"type": "user", "message": {"content": "hi"}}) + "\n"
        )
        fake_stdin = asyncio.StreamReader()
        fake_stdin.feed_data(lines.encode())
        fake_stdin.feed_eof()
        p._stdin_reader = fake_stdin

        captured = io.StringIO()
        with patch.object(sys, "stdout", captured):
            await p._read_loop()

        # Only the user message should be in inbox
        assert p._inbox.qsize() == 1
        msg = p._inbox.get_nowait()
        assert msg["type"] == "user"

        # status_response was emitted to stdout
        response = json.loads(captured.getvalue().strip())
        assert response["type"] == "status_response"
