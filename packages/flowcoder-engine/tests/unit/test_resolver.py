"""Tests for command resolution."""

import tempfile
from pathlib import Path

import pytest
from flowcoder_engine.resolver import CommandNotFoundError, resolve_command
from flowcoder_flowchart import Command, Connection, EndBlock, Flowchart, PromptBlock, StartBlock


@pytest.fixture
def temp_commands_dir():
    """Create a temp directory with a command file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        commands_dir = Path(tmpdir) / "commands"
        commands_dir.mkdir()

        cmd = Command(
            name="test-cmd",
            description="A test command",
            flowchart=Flowchart(
                blocks={
                    "s": StartBlock(id="s"),
                    "p": PromptBlock(id="p", prompt="hi"),
                    "e": EndBlock(id="e"),
                },
                connections=[
                    Connection(source_id="s", target_id="p"),
                    Connection(source_id="p", target_id="e"),
                ],
            ),
        )
        (commands_dir / "test-cmd.json").write_text(cmd.model_dump_json(indent=2))
        yield tmpdir


class TestResolveCommand:
    def test_found_in_search_path(self, temp_commands_dir):
        cmd = resolve_command("test-cmd", search_paths=[temp_commands_dir])
        assert cmd.name == "test-cmd"
        assert len(cmd.flowchart.blocks) == 3

    def test_not_found(self):
        with pytest.raises(CommandNotFoundError, match="not found"):
            resolve_command("nonexistent", search_paths=["/tmp/empty"])

    def test_found_in_commands_subdir(self, temp_commands_dir):
        # The fixture puts it in commands/ subdir, so searching parent should work
        cmd = resolve_command("test-cmd", search_paths=[temp_commands_dir])
        assert cmd.name == "test-cmd"
