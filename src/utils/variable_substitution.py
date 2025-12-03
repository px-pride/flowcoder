"""
Variable Substitution Utility for FlowCoder

Handles substitution of positional arguments ($1, $2, $3) and
structured output variables ({{varname}}) in prompt templates.
"""

import re
import json
from typing import Dict, List, Tuple, Any


class VariableSubstitution:
    """Handles variable substitution in prompt templates."""

    # Regex pattern for positional arguments ($1, $2, etc.)
    ARG_PATTERN = re.compile(r'\$(\d+)')

    # Regex pattern for structured output variables ({{varname}})
    VAR_PATTERN = re.compile(r'\{\{([a-zA-Z_][a-zA-Z0-9_.\[\]]*)\}\}')

    @classmethod
    def substitute_arguments(
        cls,
        text: str,
        arguments: Dict[str, str]
    ) -> str:
        """
        Substitute command arguments ($1, $2, etc.) in text.

        Args:
            text: Template text with $N placeholders
            arguments: Dictionary mapping $1, $2, etc. to values

        Returns:
            Text with all $N placeholders replaced with argument values

        Raises:
            ValueError: If a required argument ($N) is not found in arguments dict

        Examples:
            >>> args = {'$1': 'utils.py', '$2': 'strict'}
            >>> VariableSubstitution.substitute_arguments("Analyze $1 with mode $2", args)
            'Analyze utils.py with mode strict'
        """
        def replacer(match):
            positional_key = match.group(0)  # Full match like "$1"
            arg_num = int(match.group(1))  # Numeric value like 0, 1, 2, etc.

            # Skip $0 - it's never a valid flowchart argument (they start at $1)
            # This allows bash/AWK to use $0 without escaping
            if arg_num < 1:
                return positional_key

            if positional_key not in arguments:
                raise ValueError(
                    f"Missing required argument: {positional_key} (argument {arg_num})"
                )

            # Convert value to string and return
            value = arguments[positional_key]
            return str(value)

        # Replace all $N patterns
        return cls.ARG_PATTERN.sub(replacer, text)

    @classmethod
    def find_argument_references(cls, text: str) -> List[str]:
        """
        Find all $N argument references in text.

        Args:
            text: Text to search for argument references

        Returns:
            List of unique argument references found (e.g., ['$1', '$2'])
            Sorted in numeric order

        Examples:
            >>> VariableSubstitution.find_argument_references("Use $1 and $2, then $1 again")
            ['$1', '$2']
        """
        matches = cls.ARG_PATTERN.findall(text)
        # Convert to $N format and remove duplicates
        unique_refs = sorted(set(f"${num}" for num in matches), key=lambda x: int(x[1:]))
        return unique_refs

    @classmethod
    def validate_argument_syntax(cls, text: str) -> List[str]:
        """
        Validate argument syntax in text and return warnings.

        Checks for:
        - Argument references that skip numbers (e.g., $1 and $3 but no $2)
        - $0 references (arguments start at $1)

        Args:
            text: Text to validate

        Returns:
            List of warning messages (empty if valid)

        Examples:
            >>> VariableSubstitution.validate_argument_syntax("Use $1 and $3")
            ['Argument reference skips $2 (found $1, $3)']
        """
        warnings = []
        refs = cls.find_argument_references(text)

        if not refs:
            return warnings

        # Note: $0 is now allowed (used by bash/AWK), so no warning needed
        # Flowchart arguments start at $1

        # Check for skipped argument numbers (only check $1 and above)
        arg_numbers = [int(ref[1:]) for ref in refs if int(ref[1:]) >= 1]
        if arg_numbers:
            expected = list(range(1, max(arg_numbers) + 1))
            missing = [f"${n}" for n in expected if n not in arg_numbers]
            if missing:
                # Only report refs $1 and above
                valid_refs = [ref for ref in refs if int(ref[1:]) >= 1]
                found_str = ', '.join(valid_refs)
                missing_str = ', '.join(missing)
                warnings.append(
                    f"Argument reference skips {missing_str} (found {found_str})"
                )

        return warnings

    @classmethod
    def escape_dollar_signs(cls, text: str) -> str:
        """
        Escape literal dollar signs in text.

        Converts $$ to $ (literal dollar sign).

        Args:
            text: Text with potential escaped dollar signs

        Returns:
            Text with $$ converted to $

        Examples:
            >>> VariableSubstitution.escape_dollar_signs("Price is $$10")
            'Price is $10'
        """
        return text.replace('$$', '$')

    @classmethod
    def preprocess_text(cls, text: str) -> Tuple[str, Dict[str, str]]:
        """
        Preprocess text by extracting escaped dollar signs.

        This allows $$ to be preserved as literal $ during substitution.

        Args:
            text: Original text

        Returns:
            Tuple of (processed_text, replacements_dict)

        Examples:
            >>> VariableSubstitution.preprocess_text("Price $$10, use $1")
            ('Price __ESC_0__, use $1', {'__ESC_0__': '$10'})
        """
        # For now, simple implementation - just track escaped sequences
        # More sophisticated version would use placeholders

        # Replace $$ with a temporary placeholder
        escapes = {}
        counter = 0

        result = text
        while '$$' in result:
            placeholder = f"__ESC_{counter}__"
            escapes[placeholder] = '$'
            result = result.replace('$$', placeholder, 1)
            counter += 1

        return result, escapes

    @classmethod
    def postprocess_text(cls, text: str, escapes: Dict[str, str]) -> str:
        """
        Restore escaped sequences after substitution.

        Args:
            text: Text after substitution
            escapes: Dictionary of placeholders to restore

        Returns:
            Text with placeholders replaced by original escaped content
        """
        result = text
        for placeholder, value in escapes.items():
            result = result.replace(placeholder, value)
        return result

    @staticmethod
    def _resolve_variable_path(path: str, variables: Dict[str, Any]) -> Any:
        """
        Resolve nested variable path like "user.name" or "files[0]".

        Supports:
        - Simple variables: "status"
        - Nested access: "user.name", "results.passed"
        - Array indexing: "files[0]", "data[1]"
        - Combined: "results.items[0].name"

        Args:
            path: Variable path (e.g., "user.name", "results.passed", "files[0]")
            variables: Dictionary of variables

        Returns:
            Resolved value

        Raises:
            KeyError: If path cannot be resolved

        Examples:
            >>> _resolve_variable_path("status", {"status": "ok"})
            'ok'
            >>> _resolve_variable_path("user.name", {"user": {"name": "Alice"}})
            'Alice'
            >>> _resolve_variable_path("files[0]", {"files": ["a.txt", "b.txt"]})
            'a.txt'
        """
        # Split path by dots and brackets
        # "user.name" -> ["user", "name"]
        # "files[0]" -> ["files", "0"]
        # "data[1].value" -> ["data", "1", "value"]
        parts = path.replace('[', '.').replace(']', '').split('.')

        value = variables

        for part in parts:
            if isinstance(value, dict):
                if part not in value:
                    raise KeyError(f"Key '{part}' not found in {list(value.keys())}")
                value = value[part]
            elif isinstance(value, list):
                try:
                    index = int(part)
                    if index < 0 or index >= len(value):
                        raise KeyError(f"Index {index} out of range for list of length {len(value)}")
                    value = value[index]
                except ValueError:
                    raise KeyError(f"Invalid list index: '{part}' (must be an integer)")
            else:
                raise KeyError(f"Cannot access '{part}' on {type(value).__name__}")

        return value

    @classmethod
    def substitute_variables(
        cls,
        text: str,
        variables: Dict[str, Any]
    ) -> str:
        """
        Substitute structured output variables ({{varname}}) in text.

        Supports:
        - Simple variables: {{status}}
        - Nested access: {{user.name}}, {{results.passed}}
        - Array indexing: {{files[0]}}
        - Complex objects converted to JSON strings

        Args:
            text: Template text with {{varname}} placeholders
            variables: Dictionary of variables from execution context

        Returns:
            Text with all {{varname}} placeholders replaced with values

        Raises:
            ValueError: If a required variable is missing or path cannot be resolved

        Examples:
            >>> vars = {"status": "completed", "results": {"passed": 45, "failed": 2}}
            >>> VariableSubstitution.substitute_variables(
            ...     "Status: {{status}}, Passed: {{results.passed}}",
            ...     vars
            ... )
            'Status: completed, Passed: 45'
        """
        def replace_var(match):
            var_path = match.group(1)  # e.g., "status" or "results.passed"

            try:
                value = cls._resolve_variable_path(var_path, variables)
            except KeyError as e:
                raise ValueError(
                    f"Variable not found: {{{{{var_path}}}}} - {str(e)}. "
                    f"Available variables: {list(variables.keys())}"
                )

            # Convert to string
            if isinstance(value, (dict, list)):
                return json.dumps(value)
            else:
                return str(value)

        return cls.VAR_PATTERN.sub(replace_var, text)

    @classmethod
    def substitute_all(
        cls,
        text: str,
        arguments: Dict[str, str],
        variables: Dict[str, Any]
    ) -> str:
        """
        Perform both argument and variable substitution.

        Order: $1, $2, etc. first, then {{varname}}

        Args:
            text: Template text
            arguments: Command arguments ($1, $2, etc.)
            variables: Structured output variables ({{varname}})

        Returns:
            Fully substituted text

        Examples:
            >>> VariableSubstitution.substitute_all(
            ...     "Analyze $1 with status {{status}}",
            ...     {"$1": "utils.py"},
            ...     {"status": "ready"}
            ... )
            'Analyze utils.py with status ready'
        """
        # Step 1: Substitute arguments ($1, $2, etc.)
        if arguments:
            text = cls.substitute_arguments(text, arguments)

        # Step 2: Substitute variables ({{varname}})
        # Always call if there are {{varname}} patterns, even if variables is empty
        # This ensures we get proper error messages for missing variables
        if cls.VAR_PATTERN.search(text):
            text = cls.substitute_variables(text, variables if variables else {})

        return text
