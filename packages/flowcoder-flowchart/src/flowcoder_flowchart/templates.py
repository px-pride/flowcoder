"""Template parsing for variable references in flowchart strings.

Parses templates like "Deploy $1 to {{env}}" into structured parts.
This module only parses — evaluation is the engine's responsibility.
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


TemplatePart = Literal | ArgRef | VarRef

# Matches $1, $2, etc. (positional args) or {{varname}} (variable refs)
_TOKEN_RE = re.compile(r"\$(\d+)|\{\{(\w+)\}\}")


def parse_template(text: str) -> list[TemplatePart]:
    """Parse a template string into a list of parts.

    Examples:
        >>> parse_template("Deploy $1 to {{env}}")
        [Literal('Deploy '), ArgRef(1), Literal(' to '), VarRef('env')]

        >>> parse_template("plain text")
        [Literal('plain text')]

        >>> parse_template("$1")
        [ArgRef(1)]
    """
    parts: list[TemplatePart] = []
    last_end = 0

    for match in _TOKEN_RE.finditer(text):
        # Add any literal text before this match
        if match.start() > last_end:
            parts.append(Literal(text[last_end : match.start()]))

        if match.group(1) is not None:
            # $N positional arg
            parts.append(ArgRef(int(match.group(1))))
        else:
            # {{varname}}
            parts.append(VarRef(match.group(2)))

        last_end = match.end()

    # Trailing literal
    if last_end < len(text):
        parts.append(Literal(text[last_end:]))

    return parts
