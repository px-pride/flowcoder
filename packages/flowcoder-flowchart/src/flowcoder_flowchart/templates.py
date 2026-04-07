"""Template parsing for variable references in flowchart strings.

Parses templates like "Deploy $1 to {{env}}" into structured parts.
This module only parses — evaluation is the engine's responsibility.

Also supports conditional sections: <if BOOLVAR>content</if>
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Literal:
    text: str


@dataclass(frozen=True)
class ArgRef:
    index: int  # $1 -> 1


@dataclass(frozen=True)
class VarRef:
    name: str  # {{env}} -> "env"


@dataclass(frozen=True)
class Conditional:
    """Conditional section: <if BOOLVAR>content parts</if>"""

    variable: str
    parts: list[TemplatePart]


TemplatePart = Literal | ArgRef | VarRef | Conditional

# Matches $1, $2, etc. (positional args) or {{varname}} (variable refs)
_TOKEN_RE = re.compile(r"\$(\d+)|\{\{(\w+)\}\}")

# Matches <if VARNAME>...</if> (non-escaped, non-greedy)
_CONDITIONAL_RE = re.compile(
    r"(?<!\\)<if\s+([a-zA-Z_][a-zA-Z0-9_.\-]*)\s*>(.*?)(?<!\\)</if>",
    re.DOTALL,
)


def parse_template(text: str) -> list[TemplatePart]:
    """Parse a template string into a list of parts.

    Examples:
        >>> parse_template("Deploy $1 to {{env}}")
        [Literal('Deploy '), ArgRef(1), Literal(' to '), VarRef('env')]

        >>> parse_template("plain text")
        [Literal('plain text')]

        >>> parse_template("<if debug>extra info</if>")
        [Conditional('debug', [Literal('extra info')])]
    """
    return _parse_segment(text)


def _parse_segment(text: str) -> list[TemplatePart]:
    """Parse a text segment, handling conditionals first then tokens."""
    parts: list[TemplatePart] = []
    last_end = 0

    for match in _CONDITIONAL_RE.finditer(text):
        if match.start() > last_end:
            parts.extend(_parse_tokens(text[last_end : match.start()]))

        var_name = match.group(1)
        inner_text = match.group(2)
        inner_parts = _parse_segment(inner_text)
        parts.append(Conditional(variable=var_name, parts=inner_parts))

        last_end = match.end()

    if last_end < len(text):
        parts.extend(_parse_tokens(text[last_end:]))

    return parts


def _parse_tokens(text: str) -> list[TemplatePart]:
    """Parse $N and {{var}} tokens from a text segment (no conditionals)."""
    parts: list[TemplatePart] = []
    last_end = 0

    for match in _TOKEN_RE.finditer(text):
        if match.start() > last_end:
            parts.append(Literal(text[last_end : match.start()]))

        if match.group(1) is not None:
            parts.append(ArgRef(int(match.group(1))))
        else:
            parts.append(VarRef(match.group(2)))

        last_end = match.end()

    if last_end < len(text):
        parts.append(Literal(text[last_end:]))

    return parts


def validate_conditionals(text: str) -> list[str]:
    """Validate that <if></if> tags are properly balanced.

    Returns a list of error messages (empty if valid).
    """
    errors: list[str] = []

    opens = list(re.finditer(r"(?<!\\)<if\s+[a-zA-Z_][a-zA-Z0-9_.\-]*\s*>", text))
    closes = list(re.finditer(r"(?<!\\)</if>", text))

    if len(opens) != len(closes):
        errors.append(
            f"Mismatched conditional tags: {len(opens)} <if> vs {len(closes)} </if>"
        )

    bad_opens = re.findall(r"(?<!\\)<if\s*>", text)
    if bad_opens:
        errors.append("Found <if> tag without variable name")

    return errors
