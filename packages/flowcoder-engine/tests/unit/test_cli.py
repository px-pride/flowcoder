"""Tests for CLI argument parsing."""

import pytest

from flowcoder_flowchart import Argument

from flowcoder_engine.cli import build_variables, parse_args, parse_extra_args


class TestParseArgs:
    def test_command_mode(self):
        args = parse_args(["--command", "review"])
        assert args.command == "review"
        assert args.flowchart is None

    def test_flowchart_mode(self):
        args = parse_args(["--flowchart", "/path/to/flow.json"])
        assert args.flowchart == "/path/to/flow.json"
        assert args.command is None

    def test_no_command_or_flowchart(self):
        """Engine can start without a command or flowchart (persistent mode)."""
        args = parse_args([])
        assert args.command is None
        assert args.flowchart is None

    def test_with_args(self):
        args = parse_args(["--command", "review", "--args", "src/main.py strict"])
        assert args.args == "src/main.py strict"

    def test_with_claude_path(self):
        args = parse_args([
            "--command", "test",
            "--claude-path", "/usr/local/bin/claude",
        ])
        assert args.claude_path == "/usr/local/bin/claude"

    def test_with_search_paths(self):
        args = parse_args([
            "--command", "test",
            "--search-path", "/path1",
            "--search-path", "/path2",
        ])
        assert args.search_paths == ["/path1", "/path2"]

    def test_max_blocks(self):
        args = parse_args(["--command", "test", "--max-blocks", "500"])
        assert args.max_blocks == 500

    def test_extra_args(self):
        args = parse_args([
            "--command", "test",
            "--arg-file", "main.py",
            "--arg-mode", "strict",
        ])
        assert args.extra == {"file": "main.py", "mode": "strict"}


class TestParseExtraArgs:
    def test_basic(self):
        result = parse_extra_args(["--arg-file", "main.py", "--arg-mode", "strict"])
        assert result == {"file": "main.py", "mode": "strict"}

    def test_empty(self):
        result = parse_extra_args([])
        assert result == {}

    def test_unknown_args_ignored(self):
        result = parse_extra_args(["--unknown", "value", "--arg-x", "y"])
        assert result == {"x": "y"}


class TestBuildVariables:
    def test_from_args_string(self):
        declared = [Argument(name="file"), Argument(name="mode", required=False, default="strict")]
        result = build_variables("main.py", {}, declared)
        assert result["$1"] == "main.py"
        assert result["file"] == "main.py"
        assert result["$2"] == "strict"
        assert result["mode"] == "strict"

    def test_from_extra_args(self):
        declared = [Argument(name="file")]
        result = build_variables("main.py", {"file": "main.py"}, declared)
        assert result["file"] == "main.py"

    def test_missing_required(self):
        declared = [Argument(name="file")]
        with pytest.raises(ValueError, match="Missing required"):
            build_variables("", {}, declared)

    def test_empty_no_args(self):
        result = build_variables("", {}, [])
        assert result == {}

    def test_quoted_args(self):
        declared = [Argument(name="msg")]
        result = build_variables('"hello world"', {}, declared)
        assert result["$1"] == "hello world"
        assert result["msg"] == "hello world"
