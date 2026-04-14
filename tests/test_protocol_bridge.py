"""Tests for GUIProtocolBridge — verifies engine events route to GUI callbacks."""

import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, "packages/flowcoder-engine/src")
sys.path.insert(0, "packages/flowcoder-flowchart/src")
sys.path.insert(0, ".")

from src.adapters.protocol_bridge import GUIProtocolBridge, _extract_text
from src.models.blocks import (
    BashBlock,
    EndBlock,
    Position,
    PromptBlock,
    StartBlock,
)
from src.models.execution import (
    BlockResult,
    ExecutionContext,
    ExecutionStatus,
)
from src.models.flowchart import Flowchart


# -- Helpers --


def _make_flowchart():
    """Create a simple flowchart with start, prompt, end blocks."""
    pos = Position(0, 0)
    fc = Flowchart()
    fc.blocks.clear()
    fc.blocks["s"] = StartBlock(id="s", position=pos)
    fc.blocks["p"] = PromptBlock(id="p", position=pos, prompt="Hello")
    fc.blocks["e"] = EndBlock(id="e", position=pos)
    fc.start_block_id = "s"
    return fc


def _make_context():
    return ExecutionContext(command_id="test-cmd", command_name="test")


def _make_bridge(flowchart=None, context=None, **callbacks):
    return GUIProtocolBridge(
        flowchart=flowchart or _make_flowchart(),
        context=context or _make_context(),
        **callbacks,
    )


# -- Block lifecycle --


class TestBlockStart:
    def test_calls_on_block_start_with_block_and_context(self):
        cb = MagicMock()
        fc = _make_flowchart()
        ctx = _make_context()
        bridge = _make_bridge(fc, ctx, on_block_start=cb)

        bridge.emit_block_start("p", "Prompt", "prompt")

        cb.assert_called_once()
        block_arg, ctx_arg = cb.call_args[0]
        assert block_arg is fc.blocks["p"]
        assert ctx_arg is ctx

    def test_updates_context_current_block_id(self):
        ctx = _make_context()
        bridge = _make_bridge(context=ctx)

        bridge.emit_block_start("p", "Prompt", "prompt")

        assert ctx.current_block_id == "p"

    def test_ignores_unknown_block_id(self):
        cb = MagicMock()
        bridge = _make_bridge(on_block_start=cb)

        bridge.emit_block_start("nonexistent", "Ghost", "prompt")

        cb.assert_not_called()

    def test_no_callback_no_error(self):
        bridge = _make_bridge()
        bridge.emit_block_start("p", "Prompt", "prompt")


class TestBlockComplete:
    def test_calls_on_block_complete_with_result(self):
        cb = MagicMock()
        fc = _make_flowchart()
        ctx = _make_context()
        bridge = _make_bridge(fc, ctx, on_block_complete=cb)

        bridge.emit_block_complete("p", "Prompt", True)

        cb.assert_called_once()
        block_arg, result_arg, ctx_arg = cb.call_args[0]
        assert block_arg is fc.blocks["p"]
        assert isinstance(result_arg, BlockResult)
        assert result_arg.success is True
        assert ctx_arg is ctx

    def test_failure_result(self):
        cb = MagicMock()
        bridge = _make_bridge(on_block_complete=cb)

        bridge.emit_block_complete("p", "Prompt", False)

        result_arg = cb.call_args[0][1]
        assert result_arg.success is False

    def test_ignores_unknown_block_id(self):
        cb = MagicMock()
        bridge = _make_bridge(on_block_complete=cb)

        bridge.emit_block_complete("nonexistent", "Ghost", True)

        cb.assert_not_called()


# -- Flowchart lifecycle --


class TestFlowchartStart:
    def test_calls_on_execution_start(self):
        cb = MagicMock()
        ctx = _make_context()
        bridge = _make_bridge(context=ctx, on_execution_start=cb)

        bridge.emit_flowchart_start("my-cmd", "arg1 arg2", 5)

        cb.assert_called_once_with("my-cmd", ctx)

    def test_sets_context_running(self):
        ctx = _make_context()
        bridge = _make_bridge(context=ctx)

        bridge.emit_flowchart_start("cmd", "", 3)

        assert ctx.status == ExecutionStatus.RUNNING
        assert ctx.start_time is not None


class TestFlowchartComplete:
    def test_calls_on_execution_complete_success(self):
        cb = MagicMock()
        ctx = _make_context()
        bridge = _make_bridge(context=ctx, on_execution_complete=cb)

        bridge.emit_flowchart_complete("success", duration_ms=500)

        cb.assert_called_once_with(ctx)
        assert ctx.status == ExecutionStatus.COMPLETED
        assert ctx.end_time is not None

    def test_error_status(self):
        ctx = _make_context()
        bridge = _make_bridge(context=ctx)

        bridge.emit_flowchart_complete("error")

        assert ctx.status == ExecutionStatus.ERROR


# -- Streaming / forwarded messages --


class TestEmitForwarded:
    def test_routes_text_content_to_stream_callback(self):
        cb = MagicMock()
        bridge = _make_bridge(on_prompt_stream=cb)

        bridge.emit_forwarded(
            {"content": "Hello world"},
            session_name="default",
            block_id="p",
            block_name="Prompt",
        )

        cb.assert_called_once_with("Prompt", "Hello world")

    def test_routes_content_blocks_to_stream_callback(self):
        cb = MagicMock()
        bridge = _make_bridge(on_prompt_stream=cb)

        bridge.emit_forwarded(
            {"content": [{"type": "text", "text": "foo"}, {"type": "text", "text": "bar"}]},
            session_name="default",
            block_id="p",
            block_name="Prompt",
        )

        cb.assert_called_once_with("Prompt", "foobar")

    def test_ignores_empty_content(self):
        cb = MagicMock()
        bridge = _make_bridge(on_prompt_stream=cb)

        bridge.emit_forwarded({}, "default", "p", "Prompt")

        cb.assert_not_called()

    def test_no_callback_no_error(self):
        bridge = _make_bridge()
        bridge.emit_forwarded({"content": "hi"}, "default", "p", "Prompt")


# -- Stderr --


class TestEmitStderr:
    def test_routes_to_stderr_callback(self):
        cb = MagicMock()
        bridge = _make_bridge(on_stderr=cb)

        bridge.emit_stderr("error line", "default")

        cb.assert_called_once_with("error line")

    def test_no_callback_no_error(self):
        bridge = _make_bridge()
        bridge.emit_stderr("error line", "default")


# -- emit() override --


class TestEmitOverride:
    def test_emit_does_not_write_stdout(self, capsys):
        bridge = _make_bridge()

        bridge.emit({"type": "system", "subtype": "block_start"})

        captured = capsys.readouterr()
        assert captured.out == ""

    def test_emit_routes_result_messages(self):
        cb = MagicMock()
        ctx = _make_context()
        ctx.current_block_id = "p"
        bridge = _make_bridge(context=ctx, on_prompt_stream=cb)

        bridge.emit({"type": "result", "result": "Done!"})

        cb.assert_called_once_with("p", "Done!")


# -- Lifecycle no-ops --


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_is_noop(self):
        bridge = _make_bridge()
        await bridge.start()

    @pytest.mark.asyncio
    async def test_stop_is_noop(self):
        bridge = _make_bridge()
        await bridge.stop()


# -- forward_control_request --


class TestForwardControl:
    @pytest.mark.asyncio
    async def test_raises_not_implemented(self):
        bridge = _make_bridge()
        with pytest.raises(NotImplementedError):
            await bridge.forward_control_request({"type": "control"})


# -- _extract_text helper --


class TestExtractText:
    def test_string_content(self):
        assert _extract_text({"content": "hello"}) == "hello"

    def test_content_blocks(self):
        msg = {"content": [
            {"type": "text", "text": "foo"},
            {"type": "tool_use", "id": "t1"},
            {"type": "text", "text": "bar"},
        ]}
        assert _extract_text(msg) == "foobar"

    def test_result_field(self):
        assert _extract_text({"result": "done"}) == "done"

    def test_empty_message(self):
        assert _extract_text({}) == ""

    def test_non_text_content_blocks(self):
        msg = {"content": [{"type": "tool_use", "id": "t1"}]}
        assert _extract_text(msg) == ""
