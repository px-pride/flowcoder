"""Tests for variable substitution utilities.

Covers the VariableSubstitution class in src/utils/variable_substitution.py.
"""

import pytest

from src.utils.variable_substitution import VariableSubstitution


class TestSubstituteArguments:
    """Test positional argument ($N) substitution."""

    def test_basic_substitution(self):
        result = VariableSubstitution.substitute_arguments(
            "Analyze $1 with $2",
            {"$1": "file.py", "$2": "strict"}
        )
        assert result == "Analyze file.py with strict"

    def test_missing_argument_raises(self):
        with pytest.raises(ValueError, match="Missing required argument"):
            VariableSubstitution.substitute_arguments(
                "Use $1 and $2",
                {"$1": "hello"}
            )

    def test_dollar_zero_passthrough(self):
        """$0 is never a flowchart argument — should pass through unchanged."""
        result = VariableSubstitution.substitute_arguments(
            "echo $0",
            {"$1": "arg"}
        )
        assert result == "echo $0"


class TestSubstituteAll:
    """Test the full substitution pipeline."""

    def test_arguments_and_variables(self):
        result = VariableSubstitution.substitute_all(
            "Analyze $1 with status {{status}}",
            arguments={"$1": "utils.py"},
            variables={"status": "ready"}
        )
        assert result == "Analyze utils.py with status ready"

    def test_empty_arguments(self):
        result = VariableSubstitution.substitute_all(
            "Status: {{status}}",
            arguments={},
            variables={"status": "ok"}
        )
        assert result == "Status: ok"

    def test_empty_variables(self):
        result = VariableSubstitution.substitute_all(
            "Analyze $1",
            arguments={"$1": "file.py"},
            variables={}
        )
        assert result == "Analyze file.py"

    def test_dollar_ref_passthrough_when_no_declared_args(self):
        """$1 in prompt text should pass through when command has no declared arguments.

        First iteration: context.variables is empty, so substitute_arguments
        is skipped entirely. $1 passes through as literal text.
        """
        result = VariableSubstitution.substitute_all(
            "Tell the user about $1 feature",
            arguments={},
            variables={}
        )
        assert result == "Tell the user about $1 feature"

    def test_dollar_ref_passthrough_with_structured_outputs(self):
        """$1 should still pass through after loop iterations add structured outputs.

        This is the core bug scenario: a flowchart with no declared arguments
        uses $1 as literal text in a prompt. On the second loop iteration,
        context.variables has structured outputs from previous blocks
        (has_card=True, card_id="abc"). The old code would pass this non-empty
        dict to substitute_arguments, which would find $1 in the text, look
        for it in the dict, fail to find it, and raise ValueError.
        """
        # Simulates second iteration: structured outputs present, no $N keys
        variables = {
            "has_card": True,
            "card_id": "abc-123",
            "card_text": "Some card text",
        }
        result = VariableSubstitution.substitute_all(
            "Tell the user about $1 feature",
            arguments=variables,
            variables=variables
        )
        assert result == "Tell the user about $1 feature"

    def test_mixed_arg_keys_and_structured_outputs(self):
        """When both $N keys and structured outputs exist, $N should be substituted."""
        variables = {
            "$1": "deploy",
            "has_card": True,
            "card_id": "abc-123",
        }
        result = VariableSubstitution.substitute_all(
            "Run $1 with card {{card_id}}",
            arguments=variables,
            variables=variables
        )
        assert result == "Run deploy with card abc-123"

    def test_conditionals_with_structured_outputs(self):
        """Conditional blocks should still work with structured outputs."""
        variables = {
            "has_card": True,
            "card_text": "My task",
        }
        result = VariableSubstitution.substitute_all(
            "Hello<if has_card> Card: {{card_text}}</if>!",
            arguments=variables,
            variables=variables
        )
        assert result == "Hello Card: My task!"

    def test_conditionals_false_with_dollar_ref(self):
        """Conditional false + $1 passthrough should both work."""
        variables = {
            "has_card": False,
        }
        result = VariableSubstitution.substitute_all(
            "Process $1<if has_card> with card</if>",
            arguments=variables,
            variables=variables
        )
        assert result == "Process $1"


class TestSubstituteVariables:
    """Test {{varname}} substitution."""

    def test_simple_variable(self):
        result = VariableSubstitution.substitute_variables(
            "Status: {{status}}",
            {"status": "ok"}
        )
        assert result == "Status: ok"

    def test_nested_variable(self):
        result = VariableSubstitution.substitute_variables(
            "Name: {{user.name}}",
            {"user": {"name": "Alice"}}
        )
        assert result == "Name: Alice"

    def test_missing_variable_raises(self):
        with pytest.raises(ValueError, match="Variable not found"):
            VariableSubstitution.substitute_variables(
                "{{missing}}",
                {}
            )


class TestProcessConditionals:
    """Test <if BOOLVAR>content</if> processing."""

    def test_truthy_keeps_content(self):
        result = VariableSubstitution.process_conditionals(
            "<if debug>extra</if>",
            {"debug": True}
        )
        assert result == "extra"

    def test_falsy_removes_content(self):
        result = VariableSubstitution.process_conditionals(
            "<if debug>extra</if>",
            {"debug": False}
        )
        assert result == ""

    def test_missing_var_removes(self):
        result = VariableSubstitution.process_conditionals(
            "<if debug>extra</if>",
            {}
        )
        assert result == ""
