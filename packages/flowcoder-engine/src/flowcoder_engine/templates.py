"""Template evaluation — resolves template parts against variables.

The flowchart lib parses templates; this module evaluates them.
"""

from __future__ import annotations

from typing import Any

from flowcoder_flowchart.templates import ArgRef, Literal, VarRef, parse_template


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
    """
    parts = parse_template(text)
    result: list[str] = []

    for part in parts:
        if isinstance(part, Literal):
            result.append(part.text)
        elif isinstance(part, ArgRef):
            key = f"${part.index}"
            result.append(_format_value(variables.get(key, "")))
        elif isinstance(part, VarRef):
            result.append(_format_value(variables.get(part.name, "")))

    return "".join(result)
