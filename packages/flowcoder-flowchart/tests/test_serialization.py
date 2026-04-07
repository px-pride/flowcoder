"""Tests for I/O: load, save, dump, roundtrip through files."""

import json
import tempfile
from pathlib import Path

import pytest
from flowcoder_flowchart import (
    Argument,
    Command,
    Connection,
    EndBlock,
    Flowchart,
    PromptBlock,
    StartBlock,
    dump,
    dump_command,
    load,
    load_command,
    save,
    save_command,
)

FIXTURES = Path(__file__).parent / "fixtures"


class TestLoadFlowchart:
    def test_load_from_file(self):
        fc = load(FIXTURES / "simple.json")
        assert fc.name == "simple-flow"
        assert len(fc.blocks) == 3

    def test_load_from_dict(self):
        data = json.loads((FIXTURES / "simple.json").read_text())
        fc = load(data)
        assert fc.name == "simple-flow"

    def test_load_from_json_string(self):
        json_str = (FIXTURES / "simple.json").read_text()
        # Need to make it not look like a file path
        fc = Flowchart.model_validate_json(json_str)
        assert fc.name == "simple-flow"

    def test_load_multi_session(self):
        fc = load(FIXTURES / "multi_session.json")
        assert "deployer" in fc.sessions
        assert "reviewer" in fc.sessions
        assert fc.sessions["deployer"].model == "opus"
        assert fc.sessions["reviewer"].system_prompt == "You are a code reviewer. Be concise."

    def test_load_preserves_block_types(self):
        fc = load(FIXTURES / "branching.json")
        assert isinstance(fc.blocks["b1"], StartBlock)
        assert isinstance(fc.blocks["b2"], PromptBlock)

    def test_load_preserves_connections(self):
        fc = load(FIXTURES / "branching.json")
        true_paths = [c for c in fc.connections if c.is_true_path is True]
        false_paths = [c for c in fc.connections if c.is_true_path is False]
        assert len(true_paths) == 1
        assert len(false_paths) == 1


class TestDumpFlowchart:
    def test_dump_to_dict(self):
        fc = load(FIXTURES / "simple.json")
        data = dump(fc)
        assert isinstance(data, dict)
        assert data["name"] == "simple-flow"
        assert "blocks" in data
        assert "connections" in data

    def test_dump_roundtrip(self):
        fc = load(FIXTURES / "multi_session.json")
        data = dump(fc)
        restored = load(data)
        assert restored.name == fc.name
        assert len(restored.blocks) == len(fc.blocks)
        assert len(restored.sessions) == len(fc.sessions)


class TestSaveFlowchart:
    def test_save_and_reload(self):
        fc = load(FIXTURES / "simple.json")
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = Path(f.name)

        try:
            save(fc, path)
            restored = load(path)
            assert restored.name == fc.name
            assert len(restored.blocks) == len(fc.blocks)
        finally:
            path.unlink()

    def test_save_multi_session(self):
        fc = load(FIXTURES / "multi_session.json")
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = Path(f.name)

        try:
            save(fc, path)
            restored = load(path)
            assert "deployer" in restored.sessions
            assert restored.sessions["reviewer"].model == "sonnet"
        finally:
            path.unlink()


class TestCommand:
    def _make_command(self) -> Command:
        fc = Flowchart(
            blocks={
                "b1": StartBlock(id="b1"),
                "b2": PromptBlock(id="b2", prompt="Hello $1"),
                "b3": EndBlock(id="b3"),
            },
            connections=[
                Connection(source_id="b1", target_id="b2"),
                Connection(source_id="b2", target_id="b3"),
            ],
        )
        return Command(
            name="greet",
            description="Say hello",
            flowchart=fc,
            arguments=[Argument(name="name", description="Who to greet")],
        )

    def test_command_creation(self):
        cmd = self._make_command()
        assert cmd.name == "greet"
        assert cmd.id  # auto-generated
        assert cmd.metadata.version == "1.0"

    def test_command_invalid_name_space(self):
        with pytest.raises(ValueError, match="no spaces"):
            Command(
                name="bad name",
                flowchart=Flowchart(blocks={}),
            )

    def test_command_invalid_name_empty(self):
        with pytest.raises(ValueError, match="non-empty"):
            Command(name="", flowchart=Flowchart(blocks={}))

    def test_command_valid_names(self):
        for name in ["greet", "my-command", "cmd_v2", "x"]:
            cmd = Command(name=name, flowchart=Flowchart(blocks={}))
            assert cmd.name == name

    def test_parse_arguments_list(self):
        cmd = self._make_command()
        result = cmd.parse_arguments(["World"])
        assert result["$1"] == "World"
        assert result["name"] == "World"

    def test_parse_arguments_string(self):
        cmd = self._make_command()
        result = cmd.parse_arguments("World")
        assert result["$1"] == "World"
        assert result["name"] == "World"

    def test_parse_arguments_quoted_string(self):
        cmd = self._make_command()
        result = cmd.parse_arguments('"John Doe"')
        assert result["$1"] == "John Doe"
        assert result["name"] == "John Doe"

    def test_parse_arguments_missing_required(self):
        cmd = self._make_command()
        with pytest.raises(ValueError, match="Missing required"):
            cmd.parse_arguments([])

    def test_parse_arguments_default(self):
        fc = Flowchart(blocks={})
        cmd = Command(
            name="test",
            flowchart=fc,
            arguments=[
                Argument(name="mode", required=False, default="strict"),
            ],
        )
        result = cmd.parse_arguments([])
        assert result["$1"] == "strict"
        assert result["mode"] == "strict"

    def test_parse_arguments_extra_positional(self):
        cmd = self._make_command()
        result = cmd.parse_arguments(["World", "extra1", "extra2"])
        assert result["$1"] == "World"
        assert result["$2"] == "extra1"
        assert result["$3"] == "extra2"

    def test_parse_arguments_empty_string(self):
        fc = Flowchart(blocks={})
        cmd = Command(name="test", flowchart=fc)  # no declared args
        result = cmd.parse_arguments("")
        assert result == {}

    def test_command_save_and_load(self):
        cmd = self._make_command()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = Path(f.name)

        try:
            save_command(cmd, path)
            restored = load_command(path)
            assert restored.name == cmd.name
            assert restored.description == cmd.description
            assert len(restored.flowchart.blocks) == 3
            assert len(restored.arguments) == 1
        finally:
            path.unlink()

    def test_command_dump_roundtrip(self):
        cmd = self._make_command()
        data = dump_command(cmd)
        restored = load_command(data)
        assert restored.name == cmd.name
        assert restored.arguments[0].name == "name"
