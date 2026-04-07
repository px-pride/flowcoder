"""Integration tests with real claude binary.

These tests spawn actual claude processes and make real API calls.
They are skipped if claude is not available on PATH.
Uses haiku model for speed and cost.

Run with: pytest tests/integration/ -v
"""

from __future__ import annotations

import os
import shutil

import pytest
from flowcoder_engine.session import Session
from flowcoder_engine.walker import GraphWalker
from flowcoder_flowchart import (
    Connection,
    EndBlock,
    Flowchart,
    PromptBlock,
    StartBlock,
    VariableBlock,
)

from tests.conftest import MockProtocol

# ── Skip if claude not available ──────────────────────────────────────

_CLAUDE_PATH = shutil.which("claude")
_SKIP_REASON = "claude CLI not found on PATH"

# Also skip if inside a nested claude session where spawning fails
_IN_CLAUDE_SESSION = bool(os.environ.get("CLAUDECODE"))

pytestmark = [
    pytest.mark.skipif(not _CLAUDE_PATH, reason=_SKIP_REASON),
    pytest.mark.integration,
]

# Common opts for all test sessions
_TEST_OPTS = {
    "model": "haiku",
    "max_budget_usd": "0.05",
}


# ── Session-level tests ──────────────────────────────────────────────


class TestRealSession:
    """Tests that spawn a real claude session and send queries."""

    async def test_basic_query(self):
        """Session can send a prompt and get a response."""
        session = Session("test", _CLAUDE_PATH, _TEST_OPTS)
        try:
            await session.start()
            assert session.is_running

            result = await session.query(
                "Reply with exactly the word PONG and nothing else."
            )
            assert result.response_text
            assert "PONG" in result.response_text.upper()
            assert result.cost_usd > 0
            assert session.session_id is not None
        finally:
            await session.stop()
            assert not session.is_running

    async def test_session_tracks_cost(self):
        """Session accumulates total_cost across queries."""
        session = Session("test", _CLAUDE_PATH, _TEST_OPTS)
        try:
            await session.start()
            await session.query("Reply with the number 1")
            cost_after_one = session.total_cost
            assert cost_after_one > 0

            await session.query("Reply with the number 2")
            assert session.total_cost > cost_after_one
        finally:
            await session.stop()

    async def test_message_forwarding(self):
        """Protocol receives forwarded assistant messages."""
        proto = MockProtocol()
        session = Session("test", _CLAUDE_PATH, _TEST_OPTS, protocol=proto)
        try:
            await session.start()
            await session.query(
                "Reply with the word HELLO",
                block_id="b1",
                block_name="TestBlock",
            )
            # Should have forwarded at least one assistant message
            assert len(proto.forwarded) > 0
            fwd = proto.forwarded[0]
            assert fwd["session"] == "test"
            assert fwd["block_id"] == "b1"
            assert fwd["block_name"] == "TestBlock"
            assert fwd["message"]["type"] == "assistant"
        finally:
            await session.stop()

    async def test_system_prompt(self):
        """Session respects system_prompt option."""
        opts = {
            **_TEST_OPTS,
            "system_prompt": "You are a calculator. Only output numbers. No text.",
        }
        session = Session("calc", _CLAUDE_PATH, opts)
        try:
            await session.start()
            result = await session.query("What is 2 + 3?")
            # Should contain "5" somewhere
            assert "5" in result.response_text
        finally:
            await session.stop()


# ── Walker-level tests ────────────────────────────────────────────────


class TestRealWalker:
    """Tests that run flowcharts through the walker with real claude."""

    async def test_simple_flowchart(self):
        """start -> prompt -> end with real claude."""
        fc = Flowchart(
            blocks={
                "s": StartBlock(id="s"),
                "p": PromptBlock(
                    id="p", name="Ask",
                    prompt="What is 1+1? Reply with just the number.",
                ),
                "e": EndBlock(id="e"),
            },
            connections=[
                Connection(source_id="s", target_id="p"),
                Connection(source_id="p", target_id="e"),
            ],
        )

        proto = MockProtocol()
        session = Session("test", _CLAUDE_PATH, _TEST_OPTS, protocol=proto)
        try:
            await session.start()
            walker = GraphWalker(fc, session, {}, proto)
            result = await walker.run()
            assert result.status == "completed"
            assert len(result.log) == 3  # start, prompt, end
            assert result.log[1].result.output  # prompt block produced output
            assert "2" in result.log[1].result.output
        finally:
            await session.stop()

    async def test_variable_then_prompt(self):
        """start -> set var -> prompt using var -> end."""
        fc = Flowchart(
            blocks={
                "s": StartBlock(id="s"),
                "v": VariableBlock(
                    id="v", variable_name="color", variable_value="blue",
                ),
                "p": PromptBlock(
                    id="p", name="Ask",
                    prompt=(
                        "The color is {{color}}. "
                        "Reply with just the color name in uppercase."
                    ),
                ),
                "e": EndBlock(id="e"),
            },
            connections=[
                Connection(source_id="s", target_id="v"),
                Connection(source_id="v", target_id="p"),
                Connection(source_id="p", target_id="e"),
            ],
        )

        proto = MockProtocol()
        session = Session("test", _CLAUDE_PATH, _TEST_OPTS, protocol=proto)
        try:
            await session.start()
            walker = GraphWalker(fc, session, {}, proto)
            result = await walker.run()
            assert result.status == "completed"
            assert "BLUE" in result.log[2].result.output.upper()
        finally:
            await session.stop()

    async def test_argument_substitution(self):
        """Positional args ($1) get resolved in prompts."""
        fc = Flowchart(
            blocks={
                "s": StartBlock(id="s"),
                "p": PromptBlock(
                    id="p", name="Echo",
                    prompt="Repeat this word exactly: $1",
                ),
                "e": EndBlock(id="e"),
            },
            connections=[
                Connection(source_id="s", target_id="p"),
                Connection(source_id="p", target_id="e"),
            ],
        )

        proto = MockProtocol()
        session = Session("test", _CLAUDE_PATH, _TEST_OPTS, protocol=proto)
        try:
            await session.start()
            walker = GraphWalker(fc, session, {"$1": "FLAMINGO"}, proto)
            result = await walker.run()
            assert result.status == "completed"
            assert "FLAMINGO" in result.log[1].result.output.upper()
        finally:
            await session.stop()

    async def test_block_events_emitted(self):
        """Protocol receives block_start and block_complete events."""
        fc = Flowchart(
            blocks={
                "s": StartBlock(id="s", name="Start"),
                "p": PromptBlock(id="p", name="Ask", prompt="Say hello"),
                "e": EndBlock(id="e", name="End"),
            },
            connections=[
                Connection(source_id="s", target_id="p"),
                Connection(source_id="p", target_id="e"),
            ],
        )

        proto = MockProtocol()
        session = Session("test", _CLAUDE_PATH, _TEST_OPTS, protocol=proto)
        try:
            await session.start()
            walker = GraphWalker(fc, session, {}, proto)
            await walker.run()

            starts = [
                m for m in proto.messages if m.get("subtype") == "block_start"
            ]
            completes = [
                m for m in proto.messages if m.get("subtype") == "block_complete"
            ]
            assert len(starts) == 3
            assert len(completes) == 3
            assert all(m["data"]["success"] for m in completes)

            # Forwarded messages should include session context
            assert len(proto.forwarded) > 0
        finally:
            await session.stop()
