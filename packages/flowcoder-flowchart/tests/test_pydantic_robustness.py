"""Tests for Pydantic robustness: extra=ignore, AliasChoices, type validators."""

import pytest
from pydantic import ValidationError

from flowcoder_flowchart.blocks import (
    BashBlock,
    BlockType,
    PromptBlock,
    StartBlock,
    VariableBlock,
    VariableType,
)
from flowcoder_flowchart.models import Connection, Flowchart


class TestExtraIgnore:
    """BlockBase, Connection, and Flowchart silently drop unknown fields."""

    def test_block_ignores_extra_fields(self):
        b = StartBlock.model_validate({"type": "start", "unknown_field": 123})
        assert b.type == BlockType.START
        assert not hasattr(b, "unknown_field")

    def test_prompt_block_ignores_extra(self):
        b = PromptBlock.model_validate({
            "type": "prompt",
            "prompt": "hello",
            "legacy_color": "#ff0000",
        })
        assert b.prompt == "hello"
        assert not hasattr(b, "legacy_color")

    def test_connection_ignores_extra_fields(self):
        c = Connection.model_validate({
            "source_id": "a",
            "target_id": "b",
            "old_weight": 5,
        })
        assert c.source_id == "a"
        assert not hasattr(c, "old_weight")

    def test_flowchart_ignores_extra_fields(self):
        fc = Flowchart.model_validate({
            "blocks": {"s": {"type": "start", "id": "s"}},
            "legacy_version": "1.0",
        })
        assert "s" in fc.blocks
        assert not hasattr(fc, "legacy_version")


class TestVariableTypeAliases:
    """'int' and 'float' are normalized to 'number'."""

    def test_int_alias_on_variable_block(self):
        b = VariableBlock.model_validate({
            "type": "variable",
            "variable_name": "x",
            "variable_type": "int",
        })
        assert b.variable_type == VariableType.NUMBER

    def test_float_alias_on_variable_block(self):
        b = VariableBlock.model_validate({
            "type": "variable",
            "variable_name": "x",
            "variable_type": "float",
        })
        assert b.variable_type == VariableType.NUMBER

    def test_number_still_works(self):
        b = VariableBlock(variable_name="x", variable_type=VariableType.NUMBER)
        assert b.variable_type == VariableType.NUMBER

    def test_string_still_works(self):
        b = VariableBlock(variable_name="x", variable_type=VariableType.STRING)
        assert b.variable_type == VariableType.STRING

    def test_int_alias_on_bash_output_type(self):
        b = BashBlock.model_validate({
            "type": "bash",
            "command": "echo 1",
            "output_type": "int",
        })
        assert b.output_type == VariableType.NUMBER

    def test_float_alias_on_bash_output_type(self):
        b = BashBlock.model_validate({
            "type": "bash",
            "command": "echo 1.5",
            "output_type": "float",
        })
        assert b.output_type == VariableType.NUMBER

    def test_invalid_type_still_rejected(self):
        with pytest.raises(ValidationError):
            VariableBlock.model_validate({
                "type": "variable",
                "variable_name": "x",
                "variable_type": "nonexistent",
            })


class TestConnectionAliasChoices:
    """Connection accepts both source_id/target_id and source_block_id/target_block_id."""

    def test_standard_field_names(self):
        c = Connection(source_id="a", target_id="b")
        assert c.source_id == "a"
        assert c.target_id == "b"

    def test_legacy_block_id_aliases(self):
        c = Connection.model_validate({
            "source_block_id": "x",
            "target_block_id": "y",
        })
        assert c.source_id == "x"
        assert c.target_id == "y"

    def test_serialization_uses_canonical_names(self):
        c = Connection.model_validate({
            "source_block_id": "x",
            "target_block_id": "y",
        })
        data = c.model_dump(by_alias=False)
        assert "source_id" in data
        assert "target_id" in data
        assert "source_block_id" not in data

    def test_roundtrip_with_aliases(self):
        raw = {"source_block_id": "a", "target_block_id": "b", "label": "yes"}
        c = Connection.model_validate(raw)
        data = c.model_dump()
        restored = Connection.model_validate(data)
        assert restored.source_id == "a"
        assert restored.target_id == "b"
        assert restored.label == "yes"
