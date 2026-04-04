"""Tests for template parsing."""

from flowcoder_flowchart import ArgRef, Literal, VarRef, parse_template


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
