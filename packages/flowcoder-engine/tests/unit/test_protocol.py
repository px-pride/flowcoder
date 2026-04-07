"""Tests for ProtocolHandler output methods."""

from __future__ import annotations

import io
import json
import sys
from unittest.mock import patch

from flowcoder_engine.protocol import ProtocolHandler


class TestEmit:
    def test_emit_writes_json_line(self):
        p = ProtocolHandler()
        captured = io.StringIO()
        with patch.object(sys, "stdout", captured):
            p.emit({"type": "test", "data": 42})
        line = captured.getvalue().strip()
        assert json.loads(line) == {"type": "test", "data": 42}

    def test_emit_system(self):
        p = ProtocolHandler()
        captured = io.StringIO()
        with patch.object(sys, "stdout", captured):
            p.emit_system("block_start", {"block_id": "b1"})
        msg = json.loads(captured.getvalue().strip())
        assert msg["type"] == "system"
        assert msg["subtype"] == "block_start"
        assert msg["data"]["block_id"] == "b1"

    def test_emit_flowchart_start(self):
        p = ProtocolHandler()
        captured = io.StringIO()
        with patch.object(sys, "stdout", captured):
            p.emit_flowchart_start("story", "dragons", 5)
        msg = json.loads(captured.getvalue().strip())
        assert msg["type"] == "system"
        assert msg["subtype"] == "flowchart_start"
        assert msg["data"]["command"] == "story"
        assert msg["data"]["block_count"] == 5

    def test_emit_flowchart_complete(self):
        p = ProtocolHandler()
        captured = io.StringIO()
        with patch.object(sys, "stdout", captured):
            p.emit_flowchart_complete("completed", duration_ms=1000, cost_usd=0.05, blocks_executed=3)
        msg = json.loads(captured.getvalue().strip())
        assert msg["subtype"] == "flowchart_complete"
        assert msg["data"]["status"] == "completed"

    def test_emit_forwarded_with_provenance(self):
        """emit_forwarded wraps the inner message with session/block context."""
        p = ProtocolHandler()
        inner = {"type": "assistant", "message": {"content": "hello"}}
        captured = io.StringIO()
        with patch.object(sys, "stdout", captured):
            p.emit_forwarded(inner, "main", "b1", "Block1")
        msg = json.loads(captured.getvalue().strip())
        assert msg["type"] == "system"
        assert msg["subtype"] == "session_message"
        assert msg["data"]["session"] == "main"
        assert msg["data"]["block_id"] == "b1"
        assert msg["data"]["block_name"] == "Block1"
        assert msg["data"]["message"] == inner

    def test_emit_result(self):
        p = ProtocolHandler()
        captured = io.StringIO()
        with patch.object(sys, "stdout", captured):
            p.emit_result("done", is_error=False, duration_ms=500)
        msg = json.loads(captured.getvalue().strip())
        assert msg["type"] == "result"
        assert msg["result"] == "done"
        assert msg["is_error"] is False
