"""Tests for template parsing."""

from flowcoder_flowchart import (
    ArgRef,
    Conditional,
    Literal,
    VarRef,
    parse_template,
    validate_conditionals,
)


class TestParseTemplate:
    def test_plain_text(self):
        parts = parse_template("plain text")
        assert parts == [Literal("plain text")]

    def test_single_arg_ref(self):
        parts = parse_template("$1")
        assert parts == [ArgRef(1)]

    def test_single_var_ref(self):
        parts = parse_template("{{env}}")
        assert parts == [VarRef("env")]

    def test_mixed(self):
        parts = parse_template("Deploy $1 to {{env}}")
        assert parts == [
            Literal("Deploy "),
            ArgRef(1),
            Literal(" to "),
            VarRef("env"),
        ]

    def test_multiple_args(self):
        parts = parse_template("$1 and $2")
        assert parts == [ArgRef(1), Literal(" and "), ArgRef(2)]

    def test_multiple_vars(self):
        parts = parse_template("{{a}} + {{b}}")
        assert parts == [VarRef("a"), Literal(" + "), VarRef("b")]

    def test_adjacent_refs(self):
        parts = parse_template("$1{{env}}")
        assert parts == [ArgRef(1), VarRef("env")]

    def test_empty_string(self):
        parts = parse_template("")
        assert parts == []

    def test_no_refs(self):
        parts = parse_template("Hello, World!")
        assert parts == [Literal("Hello, World!")]

    def test_arg_ref_multi_digit(self):
        parts = parse_template("$10 and $99")
        assert parts == [ArgRef(10), Literal(" and "), ArgRef(99)]

    def test_leading_literal(self):
        parts = parse_template("prefix $1")
        assert parts == [Literal("prefix "), ArgRef(1)]

    def test_trailing_literal(self):
        parts = parse_template("$1 suffix")
        assert parts == [ArgRef(1), Literal(" suffix")]

    def test_only_literal_with_braces(self):
        # Single braces are not var refs
        parts = parse_template("{not_a_var}")
        assert parts == [Literal("{not_a_var}")]

    def test_dollar_without_number(self):
        # $x is not an arg ref (only $N with digits)
        parts = parse_template("$x")
        assert parts == [Literal("$x")]

    def test_nested_braces_not_supported(self):
        # {{{var}}} — the inner {{var}} should match
        parts = parse_template("{{{var}}}")
        assert parts == [Literal("{"), VarRef("var"), Literal("}")]


class TestConditionalTemplates:
    def test_simple_conditional(self):
        parts = parse_template("<if debug>extra info</if>")
        assert parts == [Conditional("debug", [Literal("extra info")])]

    def test_conditional_with_surrounding_text(self):
        parts = parse_template("before <if verbose>details</if> after")
        assert parts == [
            Literal("before "),
            Conditional("verbose", [Literal("details")]),
            Literal(" after"),
        ]

    def test_conditional_with_var_ref_inside(self):
        parts = parse_template("<if debug>value is {{x}}</if>")
        assert parts == [
            Conditional("debug", [Literal("value is "), VarRef("x")])
        ]

    def test_conditional_with_arg_ref_inside(self):
        parts = parse_template("<if verbose>arg: $1</if>")
        assert parts == [
            Conditional("verbose", [Literal("arg: "), ArgRef(1)])
        ]

    def test_multiple_conditionals(self):
        parts = parse_template("<if a>A</if> <if b>B</if>")
        assert parts == [
            Conditional("a", [Literal("A")]),
            Literal(" "),
            Conditional("b", [Literal("B")]),
        ]

    def test_conditional_empty_body(self):
        parts = parse_template("<if flag></if>")
        assert parts == [Conditional("flag", [])]

    def test_no_conditional(self):
        parts = parse_template("plain $1 {{var}}")
        assert parts == [Literal("plain "), ArgRef(1), Literal(" "), VarRef("var")]

    def test_conditional_var_with_dots_and_hyphens(self):
        parts = parse_template("<if my-var.name>yes</if>")
        assert parts == [Conditional("my-var.name", [Literal("yes")])]


class TestValidateConditionals:
    def test_balanced_tags(self):
        errors = validate_conditionals("<if x>content</if>")
        assert errors == []

    def test_missing_closing_tag(self):
        errors = validate_conditionals("<if x>content")
        assert len(errors) == 1
        assert "mismatched" in errors[0].lower()

    def test_missing_opening_tag(self):
        errors = validate_conditionals("content</if>")
        assert len(errors) == 1
        assert "mismatched" in errors[0].lower()

    def test_if_without_variable(self):
        errors = validate_conditionals("<if>content</if>")
        assert any("without variable" in e.lower() for e in errors)

    def test_valid_nested(self):
        errors = validate_conditionals("<if a><if b>inner</if></if>")
        assert errors == []

    def test_no_conditionals(self):
        errors = validate_conditionals("plain text {{var}} $1")
        assert errors == []
