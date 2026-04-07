"""Tests for CLI argument parsing."""

import pytest
from flowcoder_engine.cli import build_variables, parse_args
from flowcoder_flowchart import Argument


class TestParseArgs:
    def test_no_args(self):
        """Engine starts with no arguments (proxy mode)."""
        args = parse_args([])
        assert args.claude_path is None
        assert args.search_paths is None
        assert args.max_blocks == 1000
        assert args.passthrough == []

    def test_with_claude_path(self):
        args = parse_args(["--claude-path", "/usr/local/bin/claude"])
        assert args.claude_path == "/usr/local/bin/claude"

    def test_with_search_paths(self):
        args = parse_args(["--search-path", "/path1", "--search-path", "/path2"])
        assert args.search_paths == ["/path1", "/path2"]

    def test_max_blocks(self):
        args = parse_args(["--max-blocks", "500"])
        assert args.max_blocks == 500

    def test_passthrough_args(self):
        """Unknown args are collected for pass-through to inner claude."""
        args = parse_args(["--model", "haiku", "--verbose"])
        assert "--model" in args.passthrough
        assert "haiku" in args.passthrough
        assert "--verbose" in args.passthrough

    def test_mixed_own_and_passthrough(self):
        args = parse_args([
            "--search-path", "/cmds",
            "--model", "opus",
            "--max-blocks", "50",
            "--system-prompt", "test",
        ])
        assert args.search_paths == ["/cmds"]
        assert args.max_blocks == 50
        assert "--model" in args.passthrough
        assert "opus" in args.passthrough
        assert "--system-prompt" in args.passthrough


class TestBuildVariables:
    def test_from_args_string(self):
        declared = [Argument(name="file"), Argument(name="mode", required=False, default="strict")]
        result = build_variables("main.py", declared)
        assert result["$1"] == "main.py"
        assert result["file"] == "main.py"
        assert result["$2"] == "strict"
        assert result["mode"] == "strict"

    def test_missing_required(self):
        declared = [Argument(name="file")]
        with pytest.raises(ValueError, match="Missing required"):
            build_variables("", declared)

    def test_empty_no_args(self):
        result = build_variables("", [])
        assert result == {}

    def test_quoted_args(self):
        declared = [Argument(name="msg")]
        result = build_variables('"hello world"', declared)
        assert result["$1"] == "hello world"
        assert result["msg"] == "hello world"

    def test_extra_positional(self):
        declared = [Argument(name="first")]
        result = build_variables("a b c", declared)
        assert result["$1"] == "a"
        assert result["first"] == "a"
        assert result["$2"] == "b"
        assert result["$3"] == "c"
