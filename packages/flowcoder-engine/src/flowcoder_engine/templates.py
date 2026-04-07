"""Template evaluation — resolves template parts against variables.

The flowchart lib parses templates; this module evaluates them.

Extended with conditional string evaluation.
"""

from __future__ import annotations

from typing import Any

from flowcoder_flowchart.templates import (
    ArgRef,
    Conditional,
    Literal,
    VarRef,
    parse_template,
)


def _format_value(value: Any) -> str:
    """Format a variable value as a string for template substitution.

    Whole-number floats (e.g. 3.0) are rendered without the decimal
    so they work in contexts like bash arithmetic: echo $((3+1)).
    """
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def evaluate_template(text: str, variables: dict[str, Any]) -> str:
    """Resolve a template string against current variables.

    Args:
        text: Template string (e.g. "Deploy $1 to {{env}}")
        variables: Current variable state (e.g. {"$1": "main", "env": "staging"})

    Returns:
        Resolved string with all references substituted.
        Missing references are left as empty strings.
        Conditional sections are included only if their variable is truthy.
    """
    parts = parse_template(text)
    return _evaluate_parts(parts, variables)


def _evaluate_parts(parts: list, variables: dict[str, Any]) -> str:
    """Evaluate a list of template parts."""
    result: list[str] = []

    for part in parts:
        if isinstance(part, Literal):
            result.append(part.text)
        elif isinstance(part, ArgRef):
            key = f"${part.index}"
            result.append(_format_value(variables.get(key, "")))
        elif isinstance(part, VarRef):
            result.append(_format_value(variables.get(part.name, "")))
        elif isinstance(part, Conditional):
            # Evaluate the condition variable
            value = variables.get(part.variable)
            truthy = _is_truthy(value)
            if truthy:
                result.append(_evaluate_parts(part.parts, variables))

    return "".join(result)


def _is_truthy(value: Any) -> bool:
    """Check if a variable value is truthy for conditional evaluation."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    s = str(value).lower().strip()
    return s not in ("", "false", "0", "no", "none", "null")
