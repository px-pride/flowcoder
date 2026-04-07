"""Tests for graph-level validation."""

from pathlib import Path

from flowcoder_flowchart import (
    BranchBlock,
    Connection,
    EndBlock,
    Flowchart,
    PromptBlock,
    StartBlock,
    validate,
)

FIXTURES = Path(__file__).parent / "fixtures"


class TestValidFixtures:
    def test_simple(self):
        fc = Flowchart.model_validate_json((FIXTURES / "simple.json").read_text())
        result = validate(fc)
        assert result.valid is True
        assert result.errors == []

    def test_branching(self):
        fc = Flowchart.model_validate_json((FIXTURES / "branching.json").read_text())
        result = validate(fc)
        assert result.valid is True

    def test_multi_session(self):
        fc = Flowchart.model_validate_json(
            (FIXTURES / "multi_session.json").read_text()
        )
        result = validate(fc)
        assert result.valid is True


class TestInvalidFixtures:
    def test_no_start(self):
        fc = Flowchart.model_validate_json(
            (FIXTURES / "invalid" / "no_start.json").read_text()
        )
        result = validate(fc)
        assert result.valid is False
        assert any("start block" in e.lower() for e in result.errors)

    def test_unreachable(self):
        fc = Flowchart.model_validate_json(
            (FIXTURES / "invalid" / "unreachable.json").read_text()
        )
        result = validate(fc)
        # Unreachable is a warning, not an error
        assert result.valid is True
        assert any("unreachable" in w.lower() for w in result.warnings)

    def test_bad_branch(self):
        fc = Flowchart.model_validate_json(
            (FIXTURES / "invalid" / "bad_branch.json").read_text()
        )
        result = validate(fc)
        assert result.valid is False
        assert any("false path" in e.lower() for e in result.errors)


class TestValidationRules:
    def _make_fc(self, blocks, connections):
        return Flowchart(blocks=blocks, connections=connections)

    def test_no_start_block(self):
        fc = self._make_fc(
            {"b1": EndBlock(id="b1")},
            [],
        )
        result = validate(fc)
        assert not result.valid
        assert any("start block" in e.lower() for e in result.errors)

    def test_multiple_start_blocks(self):
        fc = self._make_fc(
            {
                "b1": StartBlock(id="b1"),
                "b2": StartBlock(id="b2"),
            },
            [],
        )
        result = validate(fc)
        assert not result.valid
        assert any("2 start blocks" in e for e in result.errors)

    def test_no_end_block_warning(self):
        fc = self._make_fc(
            {
                "b1": StartBlock(id="b1"),
                "b2": PromptBlock(id="b2", prompt="hi"),
            },
            [Connection(source_id="b1", target_id="b2")],
        )
        result = validate(fc)
        assert result.valid is True  # warning, not error
        assert any("no end block" in w.lower() for w in result.warnings)

    def test_connection_references_nonexistent_source(self):
        fc = self._make_fc(
            {"b1": StartBlock(id="b1")},
            [Connection(source_id="nonexistent", target_id="b1")],
        )
        result = validate(fc)
        assert not result.valid
        assert any("non-existent source" in e for e in result.errors)

    def test_connection_references_nonexistent_target(self):
        fc = self._make_fc(
            {"b1": StartBlock(id="b1")},
            [Connection(source_id="b1", target_id="nonexistent")],
        )
        result = validate(fc)
        assert not result.valid
        assert any("non-existent target" in e for e in result.errors)

    def test_empty_prompt(self):
        fc = self._make_fc(
            {
                "b1": StartBlock(id="b1"),
                "b2": PromptBlock(id="b2", name="Empty", prompt=""),
                "b3": EndBlock(id="b3"),
            },
            [
                Connection(source_id="b1", target_id="b2"),
                Connection(source_id="b2", target_id="b3"),
            ],
        )
        result = validate(fc)
        assert not result.valid
        assert any("empty prompt" in e.lower() for e in result.errors)

    def test_branch_missing_true_path(self):
        fc = self._make_fc(
            {
                "b1": StartBlock(id="b1"),
                "b2": BranchBlock(id="b2", condition="x"),
                "b3": EndBlock(id="b3"),
            },
            [
                Connection(source_id="b1", target_id="b2"),
                Connection(source_id="b2", target_id="b3", is_true_path=False),
            ],
        )
        result = validate(fc)
        assert not result.valid
        assert any("true path" in e.lower() for e in result.errors)

    def test_branch_missing_false_path(self):
        fc = self._make_fc(
            {
                "b1": StartBlock(id="b1"),
                "b2": BranchBlock(id="b2", condition="x"),
                "b3": EndBlock(id="b3"),
            },
            [
                Connection(source_id="b1", target_id="b2"),
                Connection(source_id="b2", target_id="b3", is_true_path=True),
            ],
        )
        result = validate(fc)
        assert not result.valid
        assert any("false path" in e.lower() for e in result.errors)

    def test_branch_both_paths_valid(self):
        fc = self._make_fc(
            {
                "b1": StartBlock(id="b1"),
                "b2": BranchBlock(id="b2", condition="x"),
                "b3": EndBlock(id="b3"),
                "b4": EndBlock(id="b4"),
            },
            [
                Connection(source_id="b1", target_id="b2"),
                Connection(source_id="b2", target_id="b3", is_true_path=True),
                Connection(source_id="b2", target_id="b4", is_true_path=False),
            ],
        )
        result = validate(fc)
        assert result.valid

    def test_empty_condition(self):
        fc = self._make_fc(
            {
                "b1": StartBlock(id="b1"),
                "b2": BranchBlock(id="b2", condition=""),
                "b3": EndBlock(id="b3"),
                "b4": EndBlock(id="b4"),
            },
            [
                Connection(source_id="b1", target_id="b2"),
                Connection(source_id="b2", target_id="b3", is_true_path=True),
                Connection(source_id="b2", target_id="b4", is_true_path=False),
            ],
        )
        result = validate(fc)
        assert not result.valid
        assert any("empty condition" in e.lower() for e in result.errors)

    def test_no_outgoing_warning(self):
        fc = self._make_fc(
            {
                "b1": StartBlock(id="b1"),
                "b2": PromptBlock(id="b2", prompt="hi"),
            },
            [Connection(source_id="b1", target_id="b2")],
        )
        result = validate(fc)
        # b2 has no outgoing — should warn
        assert any("no outgoing" in w.lower() for w in result.warnings)

    def test_valid_full_flow(self):
        fc = self._make_fc(
            {
                "b1": StartBlock(id="b1"),
                "b2": PromptBlock(id="b2", prompt="Hello $1"),
                "b3": EndBlock(id="b3"),
            },
            [
                Connection(source_id="b1", target_id="b2"),
                Connection(source_id="b2", target_id="b3"),
            ],
        )
        result = validate(fc)
        assert result.valid
        assert result.errors == []
