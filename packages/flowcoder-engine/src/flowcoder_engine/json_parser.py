"""Extract JSON from Claude's text responses.

Claude may wrap JSON in markdown code blocks or include extra text.
This module extracts the first valid JSON object from the response.
"""

from __future__ import annotations

import json
import re
from typing import Any


def parse_json_from_response(text: str) -> dict[str, Any] | None:
    """Extract the first JSON object from a response string.

    Tries in order:
    1. The entire text as JSON
    2. JSON from a markdown code block (```json ... ```)
    3. First { ... } substring

    Returns None if no valid JSON found.
    """
    # Try the whole string
    parsed = _try_parse(text.strip())
    if parsed is not None:
        return parsed

    # Try markdown code blocks
    code_block = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if code_block:
        parsed = _try_parse(code_block.group(1).strip())
        if parsed is not None:
            return parsed

    # Try first { ... } match (greedy from first { to last })
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        parsed = _try_parse(brace_match.group(0))
        if parsed is not None:
            return parsed

    return None


def _try_parse(text: str) -> dict[str, Any] | None:
    """Try to parse text as JSON dict. Returns None on failure."""
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except (json.JSONDecodeError, ValueError):
        pass
    return None
