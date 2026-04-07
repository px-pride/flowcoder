"""Tests for _format_value and float formatting in template evaluation."""

from flowcoder_engine.templates import _format_value, evaluate_template


class TestFormatValue:
    """Unit tests for the _format_value helper."""

    def test_whole_float_renders_as_int(self):
        assert _format_value(3.0) == "3"

    def test_fractional_float_keeps_decimal(self):
        assert _format_value(3.5) == "3.5"

    def test_zero_float_renders_as_int(self):
        assert _format_value(0.0) == "0"

    def test_negative_whole_float(self):
        assert _format_value(-5.0) == "-5"

    def test_negative_fractional_float(self):
        assert _format_value(-2.7) == "-2.7"

    def test_large_whole_float(self):
        assert _format_value(1000000.0) == "1000000"

    def test_int_unchanged(self):
        assert _format_value(42) == "42"

    def test_string_unchanged(self):
        assert _format_value("hello") == "hello"

    def test_bool_unchanged(self):
        assert _format_value(True) == "True"

    def test_none_unchanged(self):
        assert _format_value(None) == "None"

    def test_empty_string(self):
        assert _format_value("") == ""


class TestFloatInTemplates:
    """Integration: float formatting flows through evaluate_template."""

    def test_argref_whole_float(self):
        assert evaluate_template("echo $(($1+1))", {"$1": 3.0}) == "echo $((3+1))"

    def test_argref_fractional_float(self):
        assert evaluate_template("val=$1", {"$1": 3.5}) == "val=3.5"

    def test_varref_whole_float(self):
        assert evaluate_template("count={{n}}", {"n": 10.0}) == "count=10"

    def test_varref_fractional_float(self):
        assert evaluate_template("ratio={{r}}", {"r": 0.75}) == "ratio=0.75"
