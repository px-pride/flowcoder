"""Shared fixtures for engine tests.

Extended with Spawn/Wait/Exit block fixtures and git callback mocks.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from flowcoder_flowchart import (
    BashBlock,
    BranchBlock,
    CommandBlock,
    Connection,
    EndBlock,
    ExitBlock,
    Flowchart,
    InputBlock,
    PromptBlock,
    RefreshBlock,
    SessionConfig,
    SpawnBlock,
    StartBlock,
    VariableBlock,
    VariableType,
    WaitBlock,
)

from flowcoder_engine.protocol import ProtocolHandler
from flowcoder_engine.session import QueryResult


class MockSession:
    """Mock session for unit testing the walker."""

    def __init__(self, responses: list[str] | None = None):
        self.name = "mock"
        self.session_id = "mock-session"
        self.total_cost = 0.0
        self._responses = list(responses or ["Mock response"])
        self._call_count = 0
        self._clear_count = 0

    async def query(
        self, prompt: str, block_id: str = "", block_name: str = ""
    ) -> QueryResult:
        idx = min(self._call_count, len(self._responses) - 1)
        text = self._responses[idx]
        self._call_count += 1
        return QueryResult(response_text=text, cost_usd=0.01)

    async def clear(self) -> None:
        """Mock clear — resets call count to simulate fresh history."""
        self._clear_count += 1

    async def stop(self) -> None:
        pass

    @property
    def is_running(self) -> bool:
        return True


class MockProtocol:
    """Mock protocol handler that records emitted messages."""

    def __init__(self):
        self.messages: list[dict] = []
        self.logs: list[str] = []
        self.forwarded: list[dict] = []
        self._inbox: asyncio.Queue[dict] = asyncio.Queue()

    def emit(self, msg: dict) -> None:
        self.messages.append(msg)

    async def read_message(self) -> dict:
        """Read next message from inbox queue."""
        return await self._inbox.get()

    def emit_system(self, subtype: str, data: dict | None = None) -> None:
        msg: dict = {"type": "system", "subtype": subtype}
        if data:
            msg["data"] = data
        self.messages.append(msg)

    def emit_block_start(self, block_id: str, block_name: str, block_type: str) -> None:
        self.messages.append({
            "type": "system",
            "subtype": "block_start",
            "data": {"block_id": block_id, "block_name": block_name, "block_type": block_type},
        })

    def emit_block_complete(self, block_id: str, block_name: str, success: bool) -> None:
        self.messages.append({
            "type": "system",
            "subtype": "block_complete",
            "data": {"block_id": block_id, "block_name": block_name, "success": success},
        })

    def emit_result(self, *args, **kwargs) -> None:
        self.messages.append({"type": "result", "args": args, "kwargs": kwargs})

    def emit_forwarded(
        self,
        inner_msg: dict,
        session_name: str,
        block_id: str,
        block_name: str,
    ) -> None:
        self.forwarded.append({
            "session": session_name,
            "block_id": block_id,
            "block_name": block_name,
            "message": inner_msg,
        })

    def log(self, message: str) -> None:
        self.logs.append(message)

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def forward_control_request(self, inner_request: dict) -> dict:
        """Mock: auto-allow control requests."""
        return {
            "type": "control_response",
            "response": {
                "request_id": inner_request.get("request_id", ""),
                "allowed": True,
            },
        }


@pytest.fixture
def simple_flowchart() -> Flowchart:
    """start -> prompt -> end"""
    return Flowchart(
        blocks={
            "s": StartBlock(id="s", name="Start"),
            "p": PromptBlock(id="p", name="Ask", prompt="Hello $1"),
            "e": EndBlock(id="e", name="End"),
        },
        connections=[
            Connection(source_id="s", target_id="p"),
            Connection(source_id="p", target_id="e"),
        ],
    )


@pytest.fixture
def branch_flowchart() -> Flowchart:
    """start -> branch -> (true: end_ok, false: end_fail)"""
    return Flowchart(
        blocks={
            "s": StartBlock(id="s", name="Start"),
            "b": BranchBlock(id="b", name="Check", condition="flag"),
            "ok": EndBlock(id="ok", name="OK"),
            "fail": EndBlock(id="fail", name="Fail"),
        },
        connections=[
            Connection(source_id="s", target_id="b"),
            Connection(source_id="b", target_id="ok", is_true_path=True),
            Connection(source_id="b", target_id="fail", is_true_path=False),
        ],
    )


@pytest.fixture
def variable_flowchart() -> Flowchart:
    """start -> set_var -> prompt (using var) -> end"""
    return Flowchart(
        blocks={
            "s": StartBlock(id="s", name="Start"),
            "v": VariableBlock(
                id="v", name="Set Name",
                variable_name="name", variable_value="World",
            ),
            "p": PromptBlock(id="p", name="Greet", prompt="Hello {{name}}"),
            "e": EndBlock(id="e", name="End"),
        },
        connections=[
            Connection(source_id="s", target_id="v"),
            Connection(source_id="v", target_id="p"),
            Connection(source_id="p", target_id="e"),
        ],
    )


@pytest.fixture
def bash_flowchart() -> Flowchart:
    """start -> bash -> end"""
    return Flowchart(
        blocks={
            "s": StartBlock(id="s", name="Start"),
            "b": BashBlock(
                id="b", name="Run",
                command="echo hello",
                capture_output=True,
                output_variable="result",
            ),
            "e": EndBlock(id="e", name="End"),
        },
        connections=[
            Connection(source_id="s", target_id="b"),
            Connection(source_id="b", target_id="e"),
        ],
    )


@pytest.fixture
def multi_session_flowchart() -> Flowchart:
    """Two sessions: deployer and reviewer (both use main session now)."""
    return Flowchart(
        blocks={
            "s": StartBlock(id="s", name="Start"),
            "d": PromptBlock(id="d", name="Deploy", prompt="Deploy $1", session="deployer"),
            "r": PromptBlock(id="r", name="Review", prompt="Review deployment", session="reviewer"),
            "e": EndBlock(id="e", name="End"),
        },
        connections=[
            Connection(source_id="s", target_id="d"),
            Connection(source_id="d", target_id="r"),
            Connection(source_id="r", target_id="e"),
        ],
        sessions={
            "deployer": SessionConfig(model="opus"),
            "reviewer": SessionConfig(model="sonnet"),
        },
    )


@pytest.fixture
def refresh_flowchart() -> Flowchart:
    """start -> prompt -> refresh -> prompt -> end"""
    return Flowchart(
        blocks={
            "s": StartBlock(id="s", name="Start"),
            "p1": PromptBlock(id="p1", name="Ask1", prompt="First"),
            "rf": RefreshBlock(id="rf", name="Reset", target_session="default"),
            "p2": PromptBlock(id="p2", name="Ask2", prompt="Second"),
            "e": EndBlock(id="e", name="End"),
        },
        connections=[
            Connection(source_id="s", target_id="p1"),
            Connection(source_id="p1", target_id="rf"),
            Connection(source_id="rf", target_id="p2"),
            Connection(source_id="p2", target_id="e"),
        ],
    )


@pytest.fixture
def loop_flowchart() -> Flowchart:
    """start -> set_counter -> prompt -> inc_counter -> branch -> (true: end, false: prompt loop)"""
    return Flowchart(
        blocks={
            "s": StartBlock(id="s", name="Start"),
            "init": VariableBlock(
                id="init", name="Init",
                variable_name="counter", variable_value="0",
                variable_type=VariableType.NUMBER,
            ),
            "p": PromptBlock(id="p", name="Work", prompt="Iteration {{counter}}"),
            "inc": VariableBlock(
                id="inc", name="Increment",
                variable_name="done", variable_value="true",
                variable_type=VariableType.BOOLEAN,
            ),
            "check": BranchBlock(id="check", name="Done?", condition="done"),
            "e": EndBlock(id="e", name="End"),
        },
        connections=[
            Connection(source_id="s", target_id="init"),
            Connection(source_id="init", target_id="p"),
            Connection(source_id="p", target_id="inc"),
            Connection(source_id="inc", target_id="check"),
            Connection(source_id="check", target_id="e", is_true_path=True),
            Connection(source_id="check", target_id="p", is_true_path=False),
        ],
    )


@pytest.fixture
def command_flowchart() -> Flowchart:
    """start -> command block -> end"""
    return Flowchart(
        blocks={
            "s": StartBlock(id="s", name="Start"),
            "c": CommandBlock(
                id="c", name="SubCmd",
                command_name="test-sub",
                arguments="{{task}}",
                inherit_variables=False,
                merge_output=True,
            ),
            "e": EndBlock(id="e", name="End"),
        },
        connections=[
            Connection(source_id="s", target_id="c"),
            Connection(source_id="c", target_id="e"),
        ],
    )


# ── New fixtures for extended block types ────────────────────────────


@pytest.fixture
def exit_flowchart() -> Flowchart:
    """start -> exit(code=42)"""
    return Flowchart(
        blocks={
            "s": StartBlock(id="s", name="Start"),
            "x": ExitBlock(id="x", name="Bail", exit_code=42, exit_message="Explicit exit"),
            "e": EndBlock(id="e", name="End"),  # unreachable
        },
        connections=[
            Connection(source_id="s", target_id="x"),
            Connection(source_id="x", target_id="e"),
        ],
    )


@pytest.fixture
def git_tag_flowchart() -> Flowchart:
    """start -> prompt (with git_tag) -> end"""
    return Flowchart(
        blocks={
            "s": StartBlock(id="s", name="Start"),
            "p": PromptBlock(
                id="p", name="Deploy",
                prompt="Deploy to production",
                git_tag="deploy-{{version}}",
            ),
            "e": EndBlock(id="e", name="End"),
        },
        connections=[
            Connection(source_id="s", target_id="p"),
            Connection(source_id="p", target_id="e"),
        ],
    )


@pytest.fixture
def conditional_prompt_flowchart() -> Flowchart:
    """start -> set_debug -> prompt (with conditional) -> end"""
    return Flowchart(
        blocks={
            "s": StartBlock(id="s", name="Start"),
            "v": VariableBlock(
                id="v", name="Set Debug",
                variable_name="debug", variable_value="true",
                variable_type=VariableType.BOOLEAN,
            ),
            "p": PromptBlock(
                id="p", name="Ask",
                prompt="Hello<if debug> [DEBUG MODE]</if> World",
            ),
            "e": EndBlock(id="e", name="End"),
        },
        connections=[
            Connection(source_id="s", target_id="v"),
            Connection(source_id="v", target_id="p"),
            Connection(source_id="p", target_id="e"),
        ],
    )
