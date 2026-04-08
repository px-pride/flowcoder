"""Tests for Session extensions: clone() and stderr forwarding."""

from __future__ import annotations

import asyncio

import pytest
from flowcoder_engine.session import ClaudeSession as Session
from tests.conftest import MockProtocol


class TestClone:
    def test_clone_preserves_config(self):
        proto = MockProtocol()
        original = Session(
            name="original",
            claude_cmd=["claude", "--model", "opus"],
            protocol=proto,
        )
        cloned = original.clone("worker-1")

        assert cloned.name == "worker-1"
        assert cloned._claude_cmd == ["claude", "--model", "opus"]
        assert cloned._protocol is proto

    def test_clone_independent_state(self):
        original = Session(name="original", claude_cmd=["claude"])
        original._total_cost = 5.0
        original._session_id = "abc"

        cloned = original.clone("worker")
        assert cloned.total_cost == 0.0
        assert cloned.session_id is None

    def test_clone_does_not_share_cmd_list(self):
        original = Session(name="original", claude_cmd=["claude", "--verbose"])
        cloned = original.clone("worker")

        cloned._claude_cmd.append("--extra")
        assert "--extra" not in original._claude_cmd

    def test_clone_with_control_callback(self):
        async def cb(req):
            return {"type": "control_response"}

        original = Session(
            name="original",
            claude_cmd=["claude"],
            control_callback=cb,
        )
        cloned = original.clone("worker")
        assert cloned._control_callback is cb


class TestWithModel:
    def test_with_model_appends_flag(self):
        """with_model() adds --model to a session that has none."""
        session = Session(name="test", claude_cmd=["claude", "-p"])
        new = session.with_model("haiku")
        assert new._claude_cmd == ["claude", "-p", "--model", "haiku"]
        assert new.name == "test"

    def test_with_model_replaces_existing(self):
        """with_model() replaces an existing --model flag."""
        session = Session(name="test", claude_cmd=["claude", "--model", "opus", "-p"])
        new = session.with_model("sonnet")
        assert new._claude_cmd == ["claude", "--model", "sonnet", "-p"]

    def test_with_model_does_not_mutate_original(self):
        """with_model() returns a new session, original unchanged."""
        session = Session(name="test", claude_cmd=["claude", "-p"])
        new = session.with_model("haiku")
        assert "--model" not in session._claude_cmd
        assert new is not session

    def test_with_model_preserves_protocol(self):
        proto = MockProtocol()
        session = Session(name="test", claude_cmd=["claude"], protocol=proto)
        new = session.with_model("haiku")
        assert new._protocol is proto


class TestStderrForwarding:
    @pytest.mark.asyncio
    async def test_stderr_forwarded_to_protocol(self):
        proto = MockProtocol()
        session = Session(name="test", claude_cmd=["echo"], protocol=proto)

        # Simulate: create a process that writes to stderr
        proc = await asyncio.create_subprocess_exec(
            "bash", "-c", "echo 'error line 1' >&2; echo 'error line 2' >&2",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Manually wire up the session's stderr forwarding
        from flowcoder_engine.subprocess import ClaudeProcess

        cp = ClaudeProcess()
        cp._proc = proc
        session._process = cp
        session._stderr_task = asyncio.create_task(session._forward_stderr())

        await asyncio.wait_for(session._stderr_task, timeout=5.0)

        assert len(proto.stderr_lines) == 2
        assert proto.stderr_lines[0] == {"session": "test", "line": "error line 1"}
        assert proto.stderr_lines[1] == {"session": "test", "line": "error line 2"}

        await cp.stop()

    @pytest.mark.asyncio
    async def test_stderr_without_protocol_logs(self):
        session = Session(name="test", claude_cmd=["echo"])

        proc = await asyncio.create_subprocess_exec(
            "bash", "-c", "echo 'debug msg' >&2",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        from flowcoder_engine.subprocess import ClaudeProcess

        cp = ClaudeProcess()
        cp._proc = proc
        session._process = cp
        session._stderr_task = asyncio.create_task(session._forward_stderr())

        # Should complete without error (logs to debug instead of protocol)
        await asyncio.wait_for(session._stderr_task, timeout=5.0)
        await cp.stop()
