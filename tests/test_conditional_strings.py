"""Tests for conditional string support in templates.

Tests the <if BOOLVAR>content</if> syntax added to the template system.
"""

import pytest

from flowcoder_flowchart.templates import (
    Conditional,
    Literal,
    VarRef,
    parse_template,
    validate_conditionals,
)
from flowcoder_engine.templates import evaluate_template


class TestParseConditionals:
    """Test parsing of <if> conditional blocks."""

    def test_simple_conditional(self):
        parts = parse_template("<if debug>extra info</if>")
        assert len(parts) == 1
        assert isinstance(parts[0], Conditional)
        assert parts[0].variable == "debug"
        assert len(parts[0].parts) == 1
        assert isinstance(parts[0].parts[0], Literal)
        assert parts[0].parts[0].text == "extra info"

    def test_conditional_with_surrounding_text(self):
        parts = parse_template("Hello<if debug> [DEBUG]</if> World")
        assert len(parts) == 3
        assert isinstance(parts[0], Literal)
        assert parts[0].text == "Hello"
        assert isinstance(parts[1], Conditional)
        assert parts[1].variable == "debug"
        assert isinstance(parts[2], Literal)
        assert parts[2].text == " World"

    def test_conditional_with_var_ref_inside(self):
        parts = parse_template("<if verbose>Level: {{level}}</if>")
        assert len(parts) == 1
        cond = parts[0]
        assert isinstance(cond, Conditional)
        assert cond.variable == "verbose"
        assert len(cond.parts) == 2
        assert isinstance(cond.parts[0], Literal)
        assert isinstance(cond.parts[1], VarRef)
        assert cond.parts[1].name == "level"

    def test_multiple_conditionals(self):
        parts = parse_template("<if a>A</if> and <if b>B</if>")
        assert len(parts) == 3
        assert isinstance(parts[0], Conditional)
        assert isinstance(parts[1], Literal)
        assert parts[1].text == " and "
        assert isinstance(parts[2], Conditional)

    def test_no_conditionals(self):
        parts = parse_template("plain text")
        assert len(parts) == 1
        assert isinstance(parts[0], Literal)

    def test_conditional_with_hyphen_in_var(self):
        parts = parse_template("<if my-flag>yes</if>")
        assert len(parts) == 1
        assert isinstance(parts[0], Conditional)
        assert parts[0].variable == "my-flag"


class TestEvaluateConditionals:
    """Test evaluation of conditional templates."""

    def test_truthy_includes_content(self):
        result = evaluate_template("<if debug>extra</if>", {"debug": True})
        assert result == "extra"

    def test_falsy_excludes_content(self):
        result = evaluate_template("<if debug>extra</if>", {"debug": False})
        assert result == ""

    def test_missing_var_excludes(self):
        result = evaluate_template("<if debug>extra</if>", {})
        assert result == ""

    def test_string_true_includes(self):
        result = evaluate_template("<if flag>yes</if>", {"flag": "true"})
        assert result == "yes"

    def test_string_false_excludes(self):
        result = evaluate_template("<if flag>yes</if>", {"flag": "false"})
        assert result == ""

    def test_zero_excludes(self):
        result = evaluate_template("<if count>nonzero</if>", {"count": 0})
        assert result == ""

    def test_nonzero_includes(self):
        result = evaluate_template("<if count>nonzero</if>", {"count": 42})
        assert result == "nonzero"

    def test_mixed_template(self):
        result = evaluate_template(
            "Hello{{name}}<if debug> [DEBUG]</if>!",
            {"name": " World", "debug": True},
        )
        assert result == "Hello World [DEBUG]!"

    def test_mixed_template_no_debug(self):
        result = evaluate_template(
            "Hello{{name}}<if debug> [DEBUG]</if>!",
            {"name": " World", "debug": False},
        )
        assert result == "Hello World!"

    def test_conditional_with_var_ref_inside(self):
        result = evaluate_template(
            "<if verbose>Level: {{level}}</if>",
            {"verbose": True, "level": "3"},
        )
        assert result == "Level: 3"

    def test_none_excludes(self):
        result = evaluate_template("<if x>content</if>", {"x": None})
        assert result == ""

    def test_empty_string_excludes(self):
        result = evaluate_template("<if x>content</if>", {"x": ""})
        assert result == ""


class TestValidateConditionals:
    """Test conditional syntax validation."""

    def test_valid(self):
        errors = validate_conditionals("<if debug>content</if>")
        assert errors == []

    def test_mismatched_tags(self):
        errors = validate_conditionals("<if debug>content")
        assert len(errors) > 0
        assert "mismatched" in errors[0].lower() or "Mismatched" in errors[0]

    def test_no_variable_name(self):
        errors = validate_conditionals("<if >content</if>")
        assert len(errors) > 0

    def test_nested_valid(self):
        errors = validate_conditionals("<if a><if b>inner</if></if>")
        assert errors == []

    def test_empty_string_valid(self):
        errors = validate_conditionals("")
        assert errors == []

    def test_no_conditionals_valid(self):
        errors = validate_conditionals("just plain text")
        assert errors == []
