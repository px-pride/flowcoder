"""Tests for Spawn, Wait, and Exit block types.

Tests the new block types added to the walker:
- ExitBlock: explicit exit with code
- SpawnBlock: launch background agent sessions
- WaitBlock: wait for spawned sessions
"""

import pytest

from flowcoder_flowchart import (
    Connection,
    EndBlock,
    ExitBlock,
    Flowchart,
    PromptBlock,
    SpawnBlock,
    StartBlock,
    VariableBlock,
    VariableType,
    WaitBlock,
)
from flowcoder_engine.walker import GraphWalker

# Import test fixtures from engine tests
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "packages" / "flowcoder-engine" / "tests"))
from conftest import MockSession, MockProtocol


class TestExitBlock:
    """Test ExitBlock execution."""

    @pytest.mark.asyncio
    async def test_exit_with_code(self):
        """Exit block sets exit_code on result."""
        fc = Flowchart(
            blocks={
                "s": StartBlock(id="s", name="Start"),
                "x": ExitBlock(id="x", name="Exit", exit_code=42, exit_message="Done"),
            },
            connections=[Connection(source_id="s", target_id="x")],
        )

        walker = GraphWalker(fc, MockSession(), {}, MockProtocol())
        result = await walker.run()

        assert result.status == "exited"
        assert result.exit_code == 42

    @pytest.mark.asyncio
    async def test_exit_zero_is_success(self):
        """Exit with code 0 still counts as exited."""
        fc = Flowchart(
            blocks={
                "s": StartBlock(id="s", name="Start"),
                "x": ExitBlock(id="x", name="Exit", exit_code=0),
            },
            connections=[Connection(source_id="s", target_id="x")],
        )

        walker = GraphWalker(fc, MockSession(), {}, MockProtocol())
        result = await walker.run()

        assert result.status == "completed"  # exit_code=0 maps to completed
        assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_exit_with_template_message(self):
        """Exit message supports template evaluation."""
        fc = Flowchart(
            blocks={
                "s": StartBlock(id="s", name="Start"),
                "v": VariableBlock(
                    id="v", name="Set Reason",
                    variable_name="reason", variable_value="timeout",
                ),
                "x": ExitBlock(id="x", name="Exit", exit_code=1, exit_message="Failed: {{reason}}"),
            },
            connections=[
                Connection(source_id="s", target_id="v"),
                Connection(source_id="v", target_id="x"),
            ],
        )

        walker = GraphWalker(fc, MockSession(), {}, MockProtocol())
        result = await walker.run()

        assert result.status == "exited"
        assert result.exit_code == 1
        # Check that the exit message was evaluated
        exit_entry = [e for e in result.log if e.block_type == "exit"]
        assert len(exit_entry) == 1
        assert "timeout" in exit_entry[0].result.output

    @pytest.mark.asyncio
    async def test_exit_stops_execution(self):
        """Exit block prevents subsequent blocks from executing."""
        fc = Flowchart(
            blocks={
                "s": StartBlock(id="s", name="Start"),
                "x": ExitBlock(id="x", name="Exit", exit_code=1),
                "p": PromptBlock(id="p", name="Never", prompt="should not run"),
                "e": EndBlock(id="e", name="End"),
            },
            connections=[
                Connection(source_id="s", target_id="x"),
                Connection(source_id="x", target_id="p"),
                Connection(source_id="p", target_id="e"),
            ],
        )

        walker = GraphWalker(fc, MockSession(), {}, MockProtocol())
        result = await walker.run()

        # Should not have executed the prompt block
        block_types = [e.block_type for e in result.log]
        assert "prompt" not in block_types


class TestHaltMechanism:
    """Test walker halt/resume."""

    @pytest.mark.asyncio
    async def test_halt_stops_execution(self):
        """Calling halt() stops the walker after current block."""
        fc = Flowchart(
            blocks={
                "s": StartBlock(id="s", name="Start"),
                "p1": PromptBlock(id="p1", name="First", prompt="hello"),
                "p2": PromptBlock(id="p2", name="Second", prompt="world"),
                "e": EndBlock(id="e", name="End"),
            },
            connections=[
                Connection(source_id="s", target_id="p1"),
                Connection(source_id="p1", target_id="p2"),
                Connection(source_id="p2", target_id="e"),
            ],
        )

        walker = GraphWalker(fc, MockSession(), {}, MockProtocol())
        # Halt immediately
        walker.halt()
        result = await walker.run()

        assert result.status == "halted"
        # Should only have start block (halt before first real block)
        assert len(result.log) <= 1


class TestExitBlockValidation:
    """Test validation of exit blocks in flowcharts."""

    def test_exit_block_creation(self):
        """ExitBlock can be created with valid fields."""
        block = ExitBlock(exit_code=0, exit_message="ok")
        assert block.type.value == "exit"
        assert block.exit_code == 0
        assert block.exit_message == "ok"

    def test_spawn_block_creation(self):
        """SpawnBlock can be created with valid fields."""
        block = SpawnBlock(
            agent_name="worker",
            command_name="deploy",
            arguments="prod",
            inherit_variables=True,
        )
        assert block.type.value == "spawn"
        assert block.agent_name == "worker"
        assert block.command_name == "deploy"

    def test_wait_block_creation(self):
        """WaitBlock can be created with valid fields."""
        block = WaitBlock(
            wait_for=["worker1", "worker2"],
            timeout_seconds=60,
        )
        assert block.type.value == "wait"
        assert block.wait_for == ["worker1", "worker2"]
        assert block.timeout_seconds == 60

    def test_wait_block_empty_wait_for(self):
        """WaitBlock with empty wait_for waits for all spawned."""
        block = WaitBlock()
        assert block.wait_for == []


class TestProtocolCallbacks:
    """Test that walker emits block events through the protocol."""

    @pytest.mark.asyncio
    async def test_block_complete_emitted_for_each_block(self):
        """Protocol receives emit_block_complete for each executed block."""
        fc = Flowchart(
            blocks={
                "s": StartBlock(id="s", name="Start"),
                "p": PromptBlock(id="p", name="Ask", prompt="hi"),
                "e": EndBlock(id="e", name="End"),
            },
            connections=[
                Connection(source_id="s", target_id="p"),
                Connection(source_id="p", target_id="e"),
            ],
        )

        protocol = MockProtocol()
        walker = GraphWalker(fc, MockSession(), {}, protocol)
        result = await walker.run()

        assert result.status == "completed"
        # Filter block_complete messages from protocol
        completes = [
            m["data"] for m in protocol.messages
            if m.get("subtype") == "block_complete"
        ]
        assert len(completes) == 3
        block_ids = [c["block_id"] for c in completes]
        assert "s" in block_ids
        assert "p" in block_ids
        assert "e" in block_ids
