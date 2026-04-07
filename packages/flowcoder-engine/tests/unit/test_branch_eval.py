"""Tests for branch condition evaluation: _evaluate_condition, _coerce_numeric.

Covers negation, comparison operators (numeric and string), template-resolved
conditions through the walker, and edge cases.
"""

import pytest

from flowcoder_flowchart import (
    BranchBlock,
    Connection,
    EndBlock,
    Flowchart,
    PromptBlock,
    StartBlock,
    VariableBlock,
)

from flowcoder_engine.walker import (
    GraphWalker,
    _coerce_numeric,
    _evaluate_condition,
)
from tests.conftest import MockProtocol, MockSession


# ── _coerce_numeric unit tests ────────────────────────────────────────


class TestCoerceNumeric:
    def test_integer_string(self):
        assert _coerce_numeric("42") == 42.0

    def test_float_string(self):
        assert _coerce_numeric("3.14") == 3.14

    def test_negative(self):
        assert _coerce_numeric("-7") == -7.0

    def test_zero(self):
        assert _coerce_numeric("0") == 0.0

    def test_non_numeric_returns_string(self):
        assert _coerce_numeric("hello") == "hello"

    def test_empty_string(self):
        assert _coerce_numeric("") == ""

    def test_none_returns_string(self):
        # TypeError path
        assert _coerce_numeric(None) == None


# ── _evaluate_condition unit tests ────────────────────────────────────


class TestEvaluateConditionTruthiness:
    """Simple variable lookup — delegates to _is_truthy."""

    def test_truthy_bool(self):
        assert _evaluate_condition("flag", {"flag": True}) is True

    def test_falsy_bool(self):
        assert _evaluate_condition("flag", {"flag": False}) is False

    def test_truthy_string(self):
        assert _evaluate_condition("flag", {"flag": "yes"}) is True

    def test_falsy_string_false(self):
        assert _evaluate_condition("flag", {"flag": "false"}) is False

    def test_falsy_string_zero(self):
        assert _evaluate_condition("flag", {"flag": "0"}) is False

    def test_missing_var_is_falsy(self):
        assert _evaluate_condition("flag", {}) is False

    def test_none_is_falsy(self):
        assert _evaluate_condition("flag", {"flag": None}) is False

    def test_nonzero_number_is_truthy(self):
        assert _evaluate_condition("x", {"x": 42}) is True

    def test_zero_is_falsy(self):
        assert _evaluate_condition("x", {"x": 0}) is False

    def test_whitespace_stripped(self):
        assert _evaluate_condition("  flag  ", {"flag": True}) is True


class TestEvaluateConditionNegation:
    """!varname — negated truthiness."""

    def test_negate_true(self):
        assert _evaluate_condition("!flag", {"flag": True}) is False

    def test_negate_false(self):
        assert _evaluate_condition("!flag", {"flag": False}) is True

    def test_negate_missing(self):
        assert _evaluate_condition("!flag", {}) is True

    def test_negate_truthy_string(self):
        assert _evaluate_condition("!status", {"status": "active"}) is False

    def test_negate_falsy_string(self):
        assert _evaluate_condition("!status", {"status": "false"}) is True

    def test_negate_with_spaces(self):
        assert _evaluate_condition("! flag", {"flag": True}) is False


class TestEvaluateConditionNumericComparison:
    """Comparison operators with numeric coercion."""

    def test_eq_numeric(self):
        assert _evaluate_condition("x == 0", {"x": 0}) is True

    def test_eq_numeric_mismatch(self):
        assert _evaluate_condition("x == 0", {"x": 1}) is False

    def test_neq_numeric(self):
        assert _evaluate_condition("x != 0", {"x": 1}) is True

    def test_neq_numeric_equal(self):
        assert _evaluate_condition("x != 0", {"x": 0}) is False

    def test_gt(self):
        assert _evaluate_condition("x > 5", {"x": 10}) is True

    def test_gt_equal(self):
        assert _evaluate_condition("x > 5", {"x": 5}) is False

    def test_lt(self):
        assert _evaluate_condition("x < 5", {"x": 3}) is True

    def test_lt_equal(self):
        assert _evaluate_condition("x < 5", {"x": 5}) is False

    def test_gte_greater(self):
        assert _evaluate_condition("x >= 5", {"x": 6}) is True

    def test_gte_equal(self):
        assert _evaluate_condition("x >= 5", {"x": 5}) is True

    def test_gte_less(self):
        assert _evaluate_condition("x >= 5", {"x": 4}) is False

    def test_lte_less(self):
        assert _evaluate_condition("x <= 5", {"x": 4}) is True

    def test_lte_equal(self):
        assert _evaluate_condition("x <= 5", {"x": 5}) is True

    def test_lte_greater(self):
        assert _evaluate_condition("x <= 5", {"x": 6}) is False

    def test_float_comparison(self):
        assert _evaluate_condition("x > 3.14", {"x": 4.0}) is True

    def test_string_numeric_coercion(self):
        """String value "10" should be coerced to 10.0 for comparison."""
        assert _evaluate_condition("x > 5", {"x": "10"}) is True

    def test_integer_vs_float_eq(self):
        """3 == 3.0 should be true after coercion."""
        assert _evaluate_condition("x == 3", {"x": 3.0}) is True


class TestEvaluateConditionStringComparison:
    """String fallback when at least one side is non-numeric."""

    def test_eq_string(self):
        assert _evaluate_condition('status == "done"', {"status": "done"}) is True

    def test_eq_string_mismatch(self):
        assert _evaluate_condition('status == "done"', {"status": "running"}) is False

    def test_neq_string(self):
        assert _evaluate_condition('status != "error"', {"status": "ok"}) is True

    def test_single_quotes(self):
        assert _evaluate_condition("status == 'done'", {"status": "done"}) is True

    def test_string_gt_lexicographic(self):
        assert _evaluate_condition('x > "abc"', {"x": "bcd"}) is True

    def test_missing_var_uses_raw_lhs(self):
        """If lhs isn't in variables, it falls through as the literal string."""
        assert _evaluate_condition('unknown == "unknown"', {}) is True


class TestEvaluateConditionEdgeCases:
    def test_empty_condition(self):
        # Empty string is not in variables, so _is_truthy(None) = False
        assert _evaluate_condition("", {}) is False

    def test_var_named_like_operator(self):
        """Variable names shouldn't be confused with operators."""
        assert _evaluate_condition("ready", {"ready": True}) is True

    def test_comparison_with_spaces(self):
        assert _evaluate_condition("  x  ==  0  ", {"x": 0}) is True


# ── Walker integration tests: branch conditions ──────────────────────


def _make_branch_flowchart(condition: str) -> Flowchart:
    """Helper: start -> branch(condition) -> OK (true) / Fail (false) -> end."""
    return Flowchart(
        blocks={
            "s": StartBlock(id="s", name="Start"),
            "b": BranchBlock(id="b", name="Branch", condition=condition),
            "ok": PromptBlock(id="ok", name="OK", prompt="ok"),
            "fail": PromptBlock(id="fail", name="Fail", prompt="fail"),
            "e": EndBlock(id="e", name="End"),
        },
        connections=[
            Connection(source_id="s", target_id="b"),
            Connection(source_id="b", target_id="ok", label="true", is_true_path=True),
            Connection(source_id="b", target_id="fail", label="false", is_true_path=False),
            Connection(source_id="ok", target_id="e"),
            Connection(source_id="fail", target_id="e"),
        ],
    )


class TestBranchEvalIntegration:
    """Run full flowcharts through GraphWalker with various branch conditions."""

    @pytest.fixture
    def mock_session(self):
        return MockSession()

    @pytest.fixture
    def mock_protocol(self):
        return MockProtocol()

    async def test_negation_true_path(self, mock_session, mock_protocol):
        fc = _make_branch_flowchart("!hasErrors")
        walker = GraphWalker(fc, mock_session, {"hasErrors": False}, mock_protocol)
        result = await walker.run()
        names = [e.block_name for e in result.log]
        assert "OK" in names
        assert "Fail" not in names

    async def test_negation_false_path(self, mock_session, mock_protocol):
        fc = _make_branch_flowchart("!hasErrors")
        walker = GraphWalker(fc, mock_session, {"hasErrors": True}, mock_protocol)
        result = await walker.run()
        names = [e.block_name for e in result.log]
        assert "Fail" in names
        assert "OK" not in names

    async def test_numeric_eq_true(self, mock_session, mock_protocol):
        fc = _make_branch_flowchart("exitCode == 0")
        walker = GraphWalker(fc, mock_session, {"exitCode": 0}, mock_protocol)
        result = await walker.run()
        names = [e.block_name for e in result.log]
        assert "OK" in names

    async def test_numeric_eq_false(self, mock_session, mock_protocol):
        fc = _make_branch_flowchart("exitCode == 0")
        walker = GraphWalker(fc, mock_session, {"exitCode": 1}, mock_protocol)
        result = await walker.run()
        names = [e.block_name for e in result.log]
        assert "Fail" in names

    async def test_numeric_gt(self, mock_session, mock_protocol):
        fc = _make_branch_flowchart("count > 3")
        walker = GraphWalker(fc, mock_session, {"count": 5}, mock_protocol)
        result = await walker.run()
        names = [e.block_name for e in result.log]
        assert "OK" in names

    async def test_string_eq(self, mock_session, mock_protocol):
        fc = _make_branch_flowchart('status == "ready"')
        walker = GraphWalker(fc, mock_session, {"status": "ready"}, mock_protocol)
        result = await walker.run()
        names = [e.block_name for e in result.log]
        assert "OK" in names

    async def test_template_in_condition(self, mock_session, mock_protocol):
        """Branch condition with {{var}} template gets resolved before eval."""
        fc = Flowchart(
            blocks={
                "s": StartBlock(id="s", name="Start"),
                "v": VariableBlock(
                    id="v", name="SetThreshold",
                    variable_name="threshold", variable_value="5",
                ),
                "b": BranchBlock(
                    id="b", name="Branch",
                    condition="{{threshold}} > 3",
                ),
                "ok": PromptBlock(id="ok", name="OK", prompt="ok"),
                "fail": PromptBlock(id="fail", name="Fail", prompt="fail"),
                "e": EndBlock(id="e", name="End"),
            },
            connections=[
                Connection(source_id="s", target_id="v"),
                Connection(source_id="v", target_id="b"),
                Connection(source_id="b", target_id="ok", label="true", is_true_path=True),
                Connection(source_id="b", target_id="fail", label="false", is_true_path=False),
                Connection(source_id="ok", target_id="e"),
                Connection(source_id="fail", target_id="e"),
            ],
        )
        walker = GraphWalker(fc, mock_session, {}, mock_protocol)
        result = await walker.run()
        names = [e.block_name for e in result.log]
        assert "OK" in names
        assert "Fail" not in names

    async def test_template_comparison_false(self, mock_session, mock_protocol):
        """Template condition that evaluates to false takes false path."""
        fc = Flowchart(
            blocks={
                "s": StartBlock(id="s", name="Start"),
                "v": VariableBlock(
                    id="v", name="SetVal",
                    variable_name="val", variable_value="1",
                ),
                "b": BranchBlock(
                    id="b", name="Branch",
                    condition="{{val}} > 10",
                ),
                "ok": PromptBlock(id="ok", name="OK", prompt="ok"),
                "fail": PromptBlock(id="fail", name="Fail", prompt="fail"),
                "e": EndBlock(id="e", name="End"),
            },
            connections=[
                Connection(source_id="s", target_id="v"),
                Connection(source_id="v", target_id="b"),
                Connection(source_id="b", target_id="ok", label="true", is_true_path=True),
                Connection(source_id="b", target_id="fail", label="false", is_true_path=False),
                Connection(source_id="ok", target_id="e"),
                Connection(source_id="fail", target_id="e"),
            ],
        )
        walker = GraphWalker(fc, mock_session, {}, mock_protocol)
        result = await walker.run()
        names = [e.block_name for e in result.log]
        assert "Fail" in names
        assert "OK" not in names
