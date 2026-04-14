"""End-to-end tests for ExecutionController with engine delegation.

Verifies that execute() correctly delegates to GraphWalker via the
adapter layer (GUISessionAdapter, GUIProtocolBridge, model compat).
"""

import sys
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, "packages/flowcoder-engine/src")
sys.path.insert(0, "packages/flowcoder-flowchart/src")
sys.path.insert(0, ".")

from src.controllers.execution_controller import ExecutionController
from src.models.blocks import (
    BashBlock,
    BranchBlock,
    EndBlock,
    Position,
    PromptBlock,
    StartBlock,
    VariableBlock,
)
from src.models.command import Command, CommandMetadata
from src.models.connection import Connection
from src.models.execution import ExecutionContext, ExecutionStatus
from src.models.flowchart import Flowchart
from src.services.claude_service import PromptResult


# -- Helpers --


def _make_mock_service(**overrides):
    """Create a mock ClaudeAgentService."""
    svc = MagicMock()
    svc.cwd = "/tmp/test"
    svc.system_prompt = "test agent"
    svc.permission_mode = "plan"
    svc.max_retries = 3
    svc.timeout_seconds = 300
    svc.stderr_callback = None
    svc.model = "claude-sonnet-4-5-20250929"
    svc._session_active = True
    svc.start_session = AsyncMock()
    svc.end_session = AsyncMock()
    svc.reset_session = AsyncMock()
    svc.execute_prompt = AsyncMock(
        return_value=PromptResult(
            raw_response="Hello from Claude",
            structured_output=None,
            duration_ms=100,
        )
    )
    for k, v in overrides.items():
        setattr(svc, k, v)
    return svc


def _make_command(flowchart, name="test-cmd"):
    now = datetime.now()
    return Command(
        id="cmd-1",
        name=name,
        description="test",
        flowchart=flowchart,
        metadata=CommandMetadata(created=now, modified=now),
    )


def _make_linear_flowchart():
    """Start → Prompt → End."""
    pos = Position(0, 0)
    fc = Flowchart()
    fc.blocks.clear()
    fc.blocks["s"] = StartBlock(id="s", position=pos)
    fc.blocks["p"] = PromptBlock(id="p", position=pos, prompt="Say hello")
    fc.blocks["e"] = EndBlock(id="e", position=pos)
    fc.connections = [
        Connection(id="c1", source_block_id="s", target_block_id="p"),
        Connection(id="c2", source_block_id="p", target_block_id="e"),
    ]
    fc.start_block_id = "s"
    return fc


# -- Basic execution --


class TestBasicExecution:
    @pytest.mark.asyncio
    async def test_linear_flowchart_completes(self):
        """Start → Prompt → End executes and returns COMPLETED."""
        svc = _make_mock_service()
        controller = ExecutionController(svc)
        fc = _make_linear_flowchart()
        cmd = _make_command(fc)

        ctx = await controller.execute(cmd)

        assert ctx.status == ExecutionStatus.COMPLETED
        svc.execute_prompt.assert_called_once()

    @pytest.mark.asyncio
    async def test_prompt_response_in_log(self):
        """Prompt block's response appears in execution log."""
        svc = _make_mock_service()
        controller = ExecutionController(svc)
        fc = _make_linear_flowchart()
        cmd = _make_command(fc)

        ctx = await controller.execute(cmd)

        # Should have log entries for start, prompt, end
        assert len(ctx.execution_log) >= 1
        # At least one entry should have the prompt response
        responses = [e.raw_response for e in ctx.execution_log if e.raw_response]
        assert any("Hello from Claude" in r for r in responses)

    @pytest.mark.asyncio
    async def test_arguments_available_as_variables(self):
        """Command arguments are passed to the execution context."""
        svc = _make_mock_service()
        controller = ExecutionController(svc)
        fc = _make_linear_flowchart()
        cmd = _make_command(fc)

        ctx = await controller.execute(cmd, arguments={"$1": "world"})

        assert "$1" in ctx.variables or "world" in str(ctx.variables)


# -- Variable blocks --


class TestVariableBlock:
    @pytest.mark.asyncio
    async def test_variable_block_sets_value(self):
        """Variable block sets a variable in context."""
        svc = _make_mock_service()
        controller = ExecutionController(svc)

        pos = Position(0, 0)
        fc = Flowchart()
        fc.blocks.clear()
        fc.blocks["s"] = StartBlock(id="s", position=pos)
        fc.blocks["v"] = VariableBlock(
            id="v", position=pos, variable_name="greeting", variable_value="hello"
        )
        fc.blocks["e"] = EndBlock(id="e", position=pos)
        fc.connections = [
            Connection(id="c1", source_block_id="s", target_block_id="v"),
            Connection(id="c2", source_block_id="v", target_block_id="e"),
        ]
        fc.start_block_id = "s"

        cmd = _make_command(fc)
        ctx = await controller.execute(cmd)

        assert ctx.status == ExecutionStatus.COMPLETED
        assert ctx.variables.get("greeting") == "hello"


# -- Branch blocks --


class TestBranchBlock:
    @pytest.mark.asyncio
    async def test_branch_true_path(self):
        """Branch evaluates condition and follows true path."""
        svc = _make_mock_service()
        controller = ExecutionController(svc)

        pos = Position(0, 0)
        fc = Flowchart()
        fc.blocks.clear()
        fc.blocks["s"] = StartBlock(id="s", position=pos)
        fc.blocks["v"] = VariableBlock(
            id="v", position=pos, variable_name="flag", variable_value="true",
            variable_type="boolean",
        )
        fc.blocks["b"] = BranchBlock(id="b", position=pos, condition="flag == true")
        fc.blocks["e1"] = EndBlock(id="e1", name="TrueEnd", position=pos)
        fc.blocks["e2"] = EndBlock(id="e2", name="FalseEnd", position=pos)
        fc.connections = [
            Connection(id="c1", source_block_id="s", target_block_id="v"),
            Connection(id="c2", source_block_id="v", target_block_id="b"),
            Connection(id="c3", source_block_id="b", target_block_id="e1", is_true_path=True),
            Connection(id="c4", source_block_id="b", target_block_id="e2", is_true_path=False),
        ]
        fc.start_block_id = "s"

        cmd = _make_command(fc)
        ctx = await controller.execute(cmd)

        assert ctx.status == ExecutionStatus.COMPLETED


# -- Bash blocks --


class TestBashBlock:
    @pytest.mark.asyncio
    async def test_bash_block_captures_output(self):
        """Bash block runs a command and captures output."""
        svc = _make_mock_service()
        controller = ExecutionController(svc)

        pos = Position(0, 0)
        fc = Flowchart()
        fc.blocks.clear()
        fc.blocks["s"] = StartBlock(id="s", position=pos)
        fc.blocks["ba"] = BashBlock(
            id="ba", position=pos, command="echo hello",
            output_variable="result",
        )
        fc.blocks["e"] = EndBlock(id="e", position=pos)
        fc.connections = [
            Connection(id="c1", source_block_id="s", target_block_id="ba"),
            Connection(id="c2", source_block_id="ba", target_block_id="e"),
        ]
        fc.start_block_id = "s"

        cmd = _make_command(fc)
        ctx = await controller.execute(cmd)

        assert ctx.status == ExecutionStatus.COMPLETED
        assert ctx.variables.get("result") == "hello"


# -- Callbacks --


class TestCallbacks:
    @pytest.mark.asyncio
    async def test_on_execution_start_fired(self):
        """on_execution_start callback fires with command name."""
        cb = MagicMock()
        svc = _make_mock_service()
        controller = ExecutionController(svc, on_execution_start=cb)
        fc = _make_linear_flowchart()
        cmd = _make_command(fc)

        await controller.execute(cmd)

        cb.assert_called_once()
        name_arg, ctx_arg = cb.call_args[0]
        assert name_arg == "test-cmd"
        assert isinstance(ctx_arg, ExecutionContext)

    @pytest.mark.asyncio
    async def test_on_execution_complete_fired(self):
        """on_execution_complete callback fires after execution."""
        cb = MagicMock()
        svc = _make_mock_service()
        controller = ExecutionController(svc, on_execution_complete=cb)
        fc = _make_linear_flowchart()
        cmd = _make_command(fc)

        await controller.execute(cmd)

        cb.assert_called_once()
        ctx_arg = cb.call_args[0][0]
        assert ctx_arg.status == ExecutionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_on_block_start_fired_for_each_block(self):
        """on_block_start fires for each executed block."""
        cb = MagicMock()
        svc = _make_mock_service()
        controller = ExecutionController(svc, on_block_start=cb)
        fc = _make_linear_flowchart()
        cmd = _make_command(fc)

        await controller.execute(cmd)

        # Should fire for start, prompt, end = 3 blocks
        assert cb.call_count == 3

    @pytest.mark.asyncio
    async def test_on_block_complete_fired_for_each_block(self):
        """on_block_complete fires for each executed block."""
        cb = MagicMock()
        svc = _make_mock_service()
        controller = ExecutionController(svc, on_block_complete=cb)
        fc = _make_linear_flowchart()
        cmd = _make_command(fc)

        await controller.execute(cmd)

        assert cb.call_count == 3


# -- Error handling --


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_invalid_flowchart_raises(self):
        """Flowchart without start block raises error."""
        svc = _make_mock_service()
        controller = ExecutionController(svc)

        fc = Flowchart()
        fc.blocks.clear()
        fc.blocks["e"] = EndBlock(id="e", position=Position(0, 0))
        fc.connections = []
        fc.start_block_id = None

        cmd = _make_command(fc)

        from src.controllers.execution_controller import ExecutionControllerError
        with pytest.raises(ExecutionControllerError, match="validation failed"):
            await controller.execute(cmd)

    @pytest.mark.asyncio
    async def test_context_cleared_after_execution(self):
        """current_context is None after execution completes."""
        svc = _make_mock_service()
        controller = ExecutionController(svc)
        fc = _make_linear_flowchart()
        cmd = _make_command(fc)

        await controller.execute(cmd)

        assert controller.current_context is None
