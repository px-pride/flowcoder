"""Tests for template evaluation."""

from flowcoder_engine.templates import evaluate_template


class TestEvaluateTemplate:
    def test_plain_text(self):
        assert evaluate_template("hello", {}) == "hello"

    def test_arg_ref(self):
        assert evaluate_template("Hi $1", {"$1": "World"}) == "Hi World"

    def test_var_ref(self):
        assert evaluate_template("Hi {{name}}", {"name": "Alice"}) == "Hi Alice"

    def test_mixed(self):
        result = evaluate_template(
            "Deploy $1 to {{env}}",
            {"$1": "main", "env": "staging"},
        )
        assert result == "Deploy main to staging"

    def test_missing_arg_empty(self):
        assert evaluate_template("Hi $1", {}) == "Hi "

    def test_missing_var_empty(self):
        assert evaluate_template("Hi {{name}}", {}) == "Hi "

    def test_number_value(self):
        assert evaluate_template("Count: $1", {"$1": 42}) == "Count: 42"

    def test_empty_template(self):
        assert evaluate_template("", {"$1": "x"}) == ""

    def test_multiple_same_ref(self):
        assert evaluate_template("$1 and $1", {"$1": "x"}) == "x and x"
