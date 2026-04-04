"""Tests for JSON extraction from text."""

from flowcoder_engine.json_parser import parse_json_from_response


class TestParseJsonFromResponse:
    def test_pure_json(self):
        result = parse_json_from_response('{"key": "value"}')
        assert result == {"key": "value"}

    def test_json_in_code_block(self):
        text = 'Here is the result:\n```json\n{"key": "value"}\n```'
        result = parse_json_from_response(text)
        assert result == {"key": "value"}

    def test_json_in_generic_code_block(self):
        text = 'Result:\n```\n{"key": "value"}\n```'
        result = parse_json_from_response(text)
        assert result == {"key": "value"}

    def test_json_with_surrounding_text(self):
        text = 'The answer is {"valid": true, "reason": "looks good"} and that is it.'
        result = parse_json_from_response(text)
        assert result == {"valid": True, "reason": "looks good"}

    def test_no_json(self):
        result = parse_json_from_response("just plain text")
        assert result is None

    def test_json_array_ignored(self):
        # We only want dicts
        result = parse_json_from_response("[1, 2, 3]")
        assert result is None

    def test_nested_json(self):
        text = '{"outer": {"inner": true}}'
        result = parse_json_from_response(text)
        assert result == {"outer": {"inner": True}}

    def test_whitespace_json(self):
        text = """
        {
            "key": "value",
            "num": 42
        }
        """
        result = parse_json_from_response(text)
        assert result == {"key": "value", "num": 42}

    def test_empty_string(self):
        result = parse_json_from_response("")
        assert result is None

    def test_invalid_json(self):
        result = parse_json_from_response("{bad json}")
        assert result is None
