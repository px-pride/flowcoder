"""Tests for CodexSession with a mock Node.js process."""

from __future__ import annotations

import asyncio
import json
import textwrap

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

    def test_with_model_returns_clone(self):
        session = CodexSession("test")
        new = session.with_model("gpt-4o")
        assert new is not session
        assert new.name == "test"


class TestCodexSessionWithMockProcess:
    """Test CodexSession by wiring up a fake Node process that speaks the JSON protocol."""

    @pytest.fixture
    async def session_with_mock(self):
        """Create a CodexSession and replace its subprocess with a mock bash script."""
        session = CodexSession("test-codex")

        # Create a mock process that speaks the Codex wrapper protocol
        script = textwrap.dedent("""\
            import sys, json
            # Send ready message
            print(json.dumps({"type": "ready", "threadId": "mock-thread-1"}), flush=True)
            # Read commands from stdin and respond
            for line in sys.stdin:
                cmd = json.loads(line.strip())
                if cmd.get("type") == "run":
                    print(json.dumps({
                        "type": "response",
                        "commandId": cmd["commandId"],
                        "success": True,
                        "response": f"Codex says: {cmd['prompt']}"
                    }), flush=True)
        """)

        proc = await asyncio.create_subprocess_exec(
            "python", "-c", script,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Wait for ready
        ready_line = await asyncio.wait_for(proc.stdout.readline(), timeout=5)
        ready_msg = json.loads(ready_line.decode())
        assert ready_msg["type"] == "ready"

        session._process = proc
        session._session_id = ready_msg.get("threadId")
        session._stderr_task = asyncio.create_task(session._forward_stderr())

        yield session

        # Cleanup
        await session.stop()

    @pytest.mark.asyncio
    async def test_query_returns_response(self, session_with_mock):
        session = session_with_mock
        result = await session.query("Hello Codex")
        assert result.response_text == "Codex says: Hello Codex"

    @pytest.mark.asyncio
    async def test_query_multiple(self, session_with_mock):
        session = session_with_mock
        r1 = await session.query("First")
        r2 = await session.query("Second")
        assert r1.response_text == "Codex says: First"
        assert r2.response_text == "Codex says: Second"

    @pytest.mark.asyncio
    async def test_is_running(self, session_with_mock):
        session = session_with_mock
        assert session.is_running is True

    @pytest.mark.asyncio
    async def test_stop(self, session_with_mock):
        session = session_with_mock
        await session.stop()
        assert session.is_running is False

    @pytest.mark.asyncio
    async def test_session_id_set(self, session_with_mock):
        session = session_with_mock
        assert session.session_id == "mock-thread-1"


class TestCodexSessionErrorHandling:
    @pytest.fixture
    async def error_session(self):
        """Mock process that returns errors for queries."""
        session = CodexSession("error-test")

        script = textwrap.dedent("""\
            import sys, json
            print(json.dumps({"type": "ready", "threadId": "err-thread"}), flush=True)
            for line in sys.stdin:
                cmd = json.loads(line.strip())
                print(json.dumps({
                    "type": "error",
                    "commandId": cmd.get("commandId"),
                    "error": "Something went wrong"
                }), flush=True)
        """)

        proc = await asyncio.create_subprocess_exec(
            "python", "-c", script,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        ready_line = await asyncio.wait_for(proc.stdout.readline(), timeout=5)
        ready_msg = json.loads(ready_line.decode())
        assert ready_msg["type"] == "ready"

        session._process = proc
        session._session_id = ready_msg.get("threadId")
        session._stderr_task = asyncio.create_task(session._forward_stderr())

        yield session
        await session.stop()

    @pytest.mark.asyncio
    async def test_error_response(self, error_session):
        result = await error_session.query("Will fail")
        assert "Codex error" in result.response_text
        assert "Something went wrong" in result.response_text
