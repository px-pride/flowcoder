"""Tests for block types and discriminated union."""

import pytest
from flowcoder_flowchart import (
    BashBlock,
    Block,
    BlockType,
    BranchBlock,
    CommandBlock,
    EndBlock,
    Position,
    PromptBlock,
    RefreshBlock,
    StartBlock,
    VariableBlock,
    VariableType,
)
from pydantic import TypeAdapter

BlockAdapter = TypeAdapter(Block)


class TestBlockCreation:
    def test_start_block(self):
        b = StartBlock(name="Start")
        assert b.type == BlockType.START
        assert b.name == "Start"
        assert b.session == "default"
        assert b.id  # auto-generated

    def test_end_block(self):
        b = EndBlock(name="End")
        assert b.type == BlockType.END

    def test_prompt_block(self):
        b = PromptBlock(name="Ask", prompt="Hello $1")
        assert b.type == BlockType.PROMPT
        assert b.prompt == "Hello $1"
        assert b.output_schema is None

    def test_prompt_block_with_schema(self):
        schema = {"valid": "boolean", "reason": "string"}
        b = PromptBlock(name="Check", prompt="Is this valid?", output_schema=schema)
        assert b.output_schema == schema

    def test_branch_block(self):
        b = BranchBlock(name="Check", condition="is_valid")
        assert b.type == BlockType.BRANCH
        assert b.condition == "is_valid"

    def test_variable_block(self):
        b = VariableBlock(
            name="Set X",
            variable_name="x",
            variable_value="42",
            variable_type=VariableType.NUMBER,
        )
        assert b.type == BlockType.VARIABLE
        assert b.variable_type == VariableType.NUMBER

    def test_bash_block(self):
        b = BashBlock(
            name="Run",
            command="echo hello",
            output_variable="result",
            exit_code_variable="rc",
            working_directory="/tmp",
        )
        assert b.type == BlockType.BASH
        assert b.capture_output is True
        assert b.continue_on_error is False
        assert b.working_directory == "/tmp"
        assert b.exit_code_variable == "rc"

    def test_command_block(self):
        b = CommandBlock(
            name="Call Sub",
            command_name="sub-flow",
            arguments="arg1 arg2",
            inherit_variables=True,
            merge_output=True,
        )
        assert b.type == BlockType.COMMAND
        assert b.command_name == "sub-flow"

    def test_refresh_block(self):
        b = RefreshBlock(name="Reset", target_session="reviewer")
        assert b.type == BlockType.REFRESH
        assert b.target_session == "reviewer"

    def test_refresh_block_default_session(self):
        b = RefreshBlock(name="Reset")
        assert b.target_session is None

    def test_position(self):
        b = StartBlock(name="Start", position=Position(x=100, y=200))
        assert b.position.x == 100
        assert b.position.y == 200

    def test_custom_session(self):
        b = PromptBlock(name="Ask", prompt="hi", session="reviewer")
        assert b.session == "reviewer"

    def test_custom_id(self):
        b = StartBlock(id="my-id", name="Start")
        assert b.id == "my-id"


class TestBlockDiscriminatedUnion:
    def test_deserialize_start(self):
        b = BlockAdapter.validate_python({"type": "start", "name": "S"})
        assert isinstance(b, StartBlock)

    def test_deserialize_end(self):
        b = BlockAdapter.validate_python({"type": "end", "name": "E"})
        assert isinstance(b, EndBlock)

    def test_deserialize_prompt(self):
        b = BlockAdapter.validate_python(
            {"type": "prompt", "name": "P", "prompt": "Hello"}
        )
        assert isinstance(b, PromptBlock)
        assert b.prompt == "Hello"

    def test_deserialize_branch(self):
        b = BlockAdapter.validate_python(
            {"type": "branch", "name": "B", "condition": "x"}
        )
        assert isinstance(b, BranchBlock)

    def test_deserialize_variable(self):
        b = BlockAdapter.validate_python(
            {"type": "variable", "name": "V", "variable_name": "x"}
        )
        assert isinstance(b, VariableBlock)

    def test_deserialize_bash(self):
        b = BlockAdapter.validate_python(
            {"type": "bash", "name": "B", "command": "ls"}
        )
        assert isinstance(b, BashBlock)

    def test_deserialize_command(self):
        b = BlockAdapter.validate_python(
            {"type": "command", "name": "C", "command_name": "sub"}
        )
        assert isinstance(b, CommandBlock)

    def test_deserialize_refresh(self):
        b = BlockAdapter.validate_python({"type": "refresh", "name": "R"})
        assert isinstance(b, RefreshBlock)

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError, match="invalid"):
            BlockAdapter.validate_python({"type": "invalid", "name": "X"})

    def test_roundtrip(self):
        original = PromptBlock(
            id="p1",
            name="Ask",
            prompt="Hello $1",
            session="reviewer",
            output_schema={"answer": "string"},
        )
        data = original.model_dump()
        restored = BlockAdapter.validate_python(data)
        assert isinstance(restored, PromptBlock)
        assert restored.id == "p1"
        assert restored.prompt == "Hello $1"
        assert restored.session == "reviewer"
        assert restored.output_schema == {"answer": "string"}

    def test_roundtrip_json(self):
        original = BashBlock(
            id="b1",
            name="Run",
            command="echo hi",
            working_directory="/tmp",
            exit_code_variable="rc",
        )
        json_str = original.model_dump_json()
        restored = BlockAdapter.validate_json(json_str)
        assert isinstance(restored, BashBlock)
        assert restored.working_directory == "/tmp"
        assert restored.exit_code_variable == "rc"
