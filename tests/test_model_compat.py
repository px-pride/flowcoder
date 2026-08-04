"""Tests for model compatibility layer.

Tests conversion between old dataclass models and new Pydantic models.
Covers all 11 GUI block types, type normalization, structural mismatches,
and bidirectional roundtrips.
"""

import sys

sys.path.insert(0, "packages/flowcoder-flowchart/src")
sys.path.insert(0, ".")

import pytest

from src.models import (
    Block,
    BlockType,
    StartBlock,
    PromptBlock,
    EndBlock,
    BranchBlock,
    VariableBlock,
    BashBlock,
    CommandBlock,
    Connection,
    Flowchart,
    Command,
    CommandMetadata,
)
from src.models.blocks import (
    RefreshBlock,
    ExitBlock,
    SpawnBlock,
    WaitBlock,
    Position,
    WaitEntry,
)
from src.models.compat import (
    flowchart_to_pydantic,
    flowchart_from_pydantic,
    command_to_pydantic,
    _adapt_block_fields_old_to_new,
    _adapt_block_fields_new_to_old,
)

import flowcoder_flowchart as fc
from flowcoder_flowchart.blocks import VariableType
from datetime import datetime


class TestFlowchartConversion:
    """Test old Flowchart <-> Pydantic Flowchart conversion."""

    def _make_flowchart(self):
        """Create a simple old-style flowchart."""
        fc_old = Flowchart()
        fc_old.blocks.clear()

        s = StartBlock()
        s.name = "Start"
        p = PromptBlock()
        p.name = "Ask"
        p.prompt = "Hello"
        e = EndBlock()
        e.name = "End"

        fc_old.blocks[s.id] = s
        fc_old.blocks[p.id] = p
        fc_old.blocks[e.id] = e
        fc_old.connections = [
            Connection(id="c1", source_block_id=s.id, target_block_id=p.id),
            Connection(id="c2", source_block_id=p.id, target_block_id=e.id),
        ]
        fc_old.start_block_id = s.id
        return fc_old

    def test_to_pydantic(self):
        """Convert old flowchart to Pydantic."""
        old = self._make_flowchart()
        pyd = flowchart_to_pydantic(old)

        assert isinstance(pyd, fc.Flowchart)
        assert len(pyd.blocks) == 3
        assert len(pyd.connections) == 2

        # Check connection field names
        assert hasattr(pyd.connections[0], "source_id")
        assert hasattr(pyd.connections[0], "target_id")

    def test_roundtrip(self):
        """Convert old -> pydantic -> old preserves structure."""
        old = self._make_flowchart()
        pyd = flowchart_to_pydantic(old)
        back = flowchart_from_pydantic(pyd)

        assert len(back.blocks) == len(old.blocks)
        assert len(back.connections) == len(old.connections)

        # Check connection field names restored
        for conn in back.connections:
            assert hasattr(conn, "source_block_id")
            assert hasattr(conn, "target_block_id")

    def test_block_types_preserved(self):
        """Block types survive roundtrip."""
        old = self._make_flowchart()
        pyd = flowchart_to_pydantic(old)

        types = {b.type.value for b in pyd.blocks.values()}
        assert "start" in types
        assert "prompt" in types
        assert "end" in types

    def test_branch_flowchart(self):
        """Convert flowchart with branch block."""
        fc_old = Flowchart()
        fc_old.blocks.clear()

        s = StartBlock()
        b = BranchBlock()
        b.condition = "flag"
        e1 = EndBlock()
        e2 = EndBlock()

        fc_old.blocks[s.id] = s
        fc_old.blocks[b.id] = b
        fc_old.blocks[e1.id] = e1
        fc_old.blocks[e2.id] = e2
        fc_old.connections = [
            Connection(id="c1", source_block_id=s.id, target_block_id=b.id),
            Connection(id="c2", source_block_id=b.id, target_block_id=e1.id, is_true_path=True),
            Connection(id="c3", source_block_id=b.id, target_block_id=e2.id, is_true_path=False),
        ]
        fc_old.start_block_id = s.id

        pyd = flowchart_to_pydantic(fc_old)
        assert len(pyd.blocks) == 4

        # Check branch paths (filter to connections FROM the branch block)
        branch_id = b.id
        branch_conns = [c for c in pyd.connections if c.source_id == branch_id]
        true_conns = [c for c in branch_conns if c.is_true_path is True]
        false_conns = [c for c in branch_conns if c.is_true_path is False]
        assert len(true_conns) == 1
        assert len(false_conns) == 1


class TestCommandConversion:
    """Test old Command -> Pydantic Command conversion."""

    def test_basic_command(self):
        """Convert a simple command."""
        fc_old = Flowchart()

        now = datetime.now()
        cmd = Command(
            id="test-id",
            name="test-cmd",
            description="A test command",
            flowchart=fc_old,
            metadata=CommandMetadata(created=now, modified=now),
        )

        pyd = command_to_pydantic(cmd)
        assert isinstance(pyd, fc.Command)
        assert pyd.name == "test-cmd"
        assert pyd.description == "A test command"


class TestPydanticDiscriminatedUnion:
    """Test that our extended Block union works correctly."""

    def test_all_block_types_deserialize(self):
        """All 11 block types can be created and serialized."""
        blocks = {
            "s": {"id": "s", "type": "start"},
            "e": {"id": "e", "type": "end"},
            "p": {"id": "p", "type": "prompt", "prompt": "hi"},
            "b": {"id": "b", "type": "branch", "condition": "flag"},
            "v": {"id": "v", "type": "variable", "variable_name": "x"},
            "ba": {"id": "ba", "type": "bash", "command": "echo hi"},
            "c": {"id": "c", "type": "command", "command_name": "test"},
            "r": {"id": "r", "type": "refresh"},
            "sp": {"id": "sp", "type": "spawn", "agent_name": "w", "command_name": "run"},
            "w": {"id": "w", "type": "wait"},
            "x": {"id": "x", "type": "exit", "exit_code": 0},
        }

        flowchart = fc.Flowchart(
            blocks=blocks,
            connections=[],
        )

        assert len(flowchart.blocks) == 11
        assert isinstance(flowchart.blocks["sp"], fc.SpawnBlock)
        assert isinstance(flowchart.blocks["w"], fc.WaitBlock)
        assert isinstance(flowchart.blocks["x"], fc.ExitBlock)

    def test_block_roundtrip_json(self):
        """Blocks survive JSON roundtrip via Pydantic."""
        blocks = {
            "sp": {"id": "sp", "type": "spawn", "agent_name": "w", "command_name": "deploy"},
            "x": {"id": "x", "type": "exit", "exit_code": 42, "exit_message": "done"},
        }
        flowchart = fc.Flowchart(blocks=blocks, connections=[])

        # Serialize and deserialize
        json_data = flowchart.model_dump(mode="json")
        restored = fc.Flowchart.model_validate(json_data)

        sp = restored.blocks["sp"]
        assert isinstance(sp, fc.SpawnBlock)
        assert sp.agent_name == "w"
        assert sp.command_name == "deploy"

        ex = restored.blocks["x"]
        assert isinstance(ex, fc.ExitBlock)
        assert ex.exit_code == 42
        assert ex.exit_message == "done"


# -- WaitBlock conversion --


class TestWaitBlockConversion:
    """Test WaitBlock entries <-> wait_for conversion."""

    def test_entries_to_wait_for(self):
        """GUI WaitEntry objects become engine wait_for string list."""
        d = {
            "type": "wait",
            "entries": [
                {"agent_name": "worker-1", "kill_session": True},
                {"agent_name": "worker-2", "kill_session": False},
            ],
        }
        _adapt_block_fields_old_to_new(d)
        assert d["wait_for"] == ["worker-1", "worker-2"]
        assert "entries" not in d

    def test_wait_for_to_entries(self):
        """Engine wait_for list becomes GUI WaitEntry dicts."""
        d = {
            "type": "wait",
            "wait_for": ["alpha", "beta"],
            "timeout_seconds": 120,
        }
        _adapt_block_fields_new_to_old(d)
        assert len(d["entries"]) == 2
        assert d["entries"][0]["agent_name"] == "alpha"
        assert d["entries"][1]["agent_name"] == "beta"
        assert "wait_for" not in d
        assert "timeout_seconds" not in d

    def test_wait_block_full_roundtrip(self):
        """WaitBlock survives GUI → engine → GUI roundtrip."""
        pos = Position(10, 20)
        gui_wait = WaitBlock(
            id="w1", position=pos,
            entries=[WaitEntry("agent-a"), WaitEntry("agent-b", kill_session=True)],
        )

        fc_old = Flowchart()
        fc_old.blocks.clear()
        s = StartBlock(id="s")
        fc_old.blocks["s"] = s
        fc_old.blocks["w1"] = gui_wait
        fc_old.connections = [
            Connection(id="c1", source_block_id="s", target_block_id="w1"),
        ]
        fc_old.start_block_id = "s"

        engine = flowchart_to_pydantic(fc_old)
        ewb = engine.blocks["w1"]
        assert isinstance(ewb, fc.WaitBlock)
        assert ewb.wait_for == ["agent-a", "agent-b"]

        gui_back = flowchart_from_pydantic(engine)
        gwb = gui_back.blocks["w1"]
        assert isinstance(gwb, WaitBlock)
        assert len(gwb.entries) == 2
        assert gwb.entries[0].agent_name == "agent-a"
        assert gwb.entries[1].agent_name == "agent-b"


# -- VariableType normalization --


class TestVariableTypeNormalization:
    """Test int/float → number normalization via engine validators."""

    def test_int_becomes_number(self):
        """GUI variable_type='int' becomes engine VariableType.NUMBER."""
        pos = Position(0, 0)
        gui_var = VariableBlock(
            id="v1", position=pos,
            variable_name="count", variable_value="0", variable_type="int",
        )
        fc_old = Flowchart()
        fc_old.blocks.clear()
        s = StartBlock(id="s")
        fc_old.blocks["s"] = s
        fc_old.blocks["v1"] = gui_var
        fc_old.start_block_id = "s"
        fc_old.connections = []

        engine = flowchart_to_pydantic(fc_old)
        evb = engine.blocks["v1"]
        assert evb.variable_type == VariableType.NUMBER

    def test_float_becomes_number(self):
        """GUI variable_type='float' becomes engine VariableType.NUMBER."""
        pos = Position(0, 0)
        gui_var = VariableBlock(
            id="v1", position=pos,
            variable_name="ratio", variable_value="0.5", variable_type="float",
        )
        fc_old = Flowchart()
        fc_old.blocks.clear()
        s = StartBlock(id="s")
        fc_old.blocks["s"] = s
        fc_old.blocks["v1"] = gui_var
        fc_old.start_block_id = "s"
        fc_old.connections = []

        engine = flowchart_to_pydantic(fc_old)
        assert engine.blocks["v1"].variable_type == VariableType.NUMBER

    def test_string_stays_string(self):
        """GUI variable_type='string' stays VariableType.STRING."""
        pos = Position(0, 0)
        gui_var = VariableBlock(
            id="v1", position=pos,
            variable_name="label", variable_value="hi", variable_type="string",
        )
        fc_old = Flowchart()
        fc_old.blocks.clear()
        s = StartBlock(id="s")
        fc_old.blocks["s"] = s
        fc_old.blocks["v1"] = gui_var
        fc_old.start_block_id = "s"
        fc_old.connections = []

        engine = flowchart_to_pydantic(fc_old)
        assert engine.blocks["v1"].variable_type == VariableType.STRING

    def test_bash_output_type_float_becomes_number(self):
        """BashBlock output_type='float' becomes VariableType.NUMBER."""
        pos = Position(0, 0)
        gui_bash = BashBlock(
            id="b1", position=pos, command="echo 3.14", output_type="float",
        )
        fc_old = Flowchart()
        fc_old.blocks.clear()
        s = StartBlock(id="s")
        fc_old.blocks["s"] = s
        fc_old.blocks["b1"] = gui_bash
        fc_old.start_block_id = "s"
        fc_old.connections = []

        engine = flowchart_to_pydantic(fc_old)
        assert engine.blocks["b1"].output_type == VariableType.NUMBER


# -- Empty string → None conversion --


class TestEmptyStringToNone:
    """Test that GUI empty-string defaults become None in engine models."""

    def test_bash_empty_optional_fields(self):
        """BashBlock empty strings → None for Optional fields."""
        d = {
            "type": "bash",
            "command": "ls",
            "output_variable": "",
            "working_directory": "",
            "exit_code_variable": "",
        }
        _adapt_block_fields_old_to_new(d)
        assert d["output_variable"] is None
        assert d["working_directory"] is None
        assert d["exit_code_variable"] is None

    def test_bash_nonempty_fields_preserved(self):
        """BashBlock non-empty values are not converted to None."""
        d = {
            "type": "bash",
            "command": "ls",
            "output_variable": "result",
            "working_directory": "/tmp",
            "exit_code_variable": "ec",
        }
        _adapt_block_fields_old_to_new(d)
        assert d["output_variable"] == "result"
        assert d["working_directory"] == "/tmp"
        assert d["exit_code_variable"] == "ec"

    def test_spawn_empty_optional_fields(self):
        """SpawnBlock empty strings → None for Optional fields."""
        d = {
            "type": "spawn",
            "agent_name": "w",
            "command_name": "run",
            "exit_code_variable": "",
            "config_file": "",
        }
        _adapt_block_fields_old_to_new(d)
        assert d["exit_code_variable"] is None
        assert d["config_file"] is None

    def test_reverse_none_to_empty(self):
        """Engine None → GUI empty string for BashBlock fields."""
        d = {
            "type": "bash",
            "command": "ls",
            "output_variable": None,
            "working_directory": None,
            "exit_code_variable": None,
            "session": "default",
        }
        _adapt_block_fields_new_to_old(d)
        assert d["output_variable"] == ""
        assert d["working_directory"] == ""
        assert d["exit_code_variable"] == ""
        assert "session" not in d


# -- GUI-only field stripping --


class TestGUIOnlyFieldStripping:
    """Test that GUI-only fields are stripped by engine's extra='ignore'."""

    def test_prompt_gui_fields_stripped(self):
        """PromptBlock sound_effect, disable_auto_git, git_tag are stripped."""
        pos = Position(0, 0)
        gui_prompt = PromptBlock(
            id="p1", position=pos, prompt="test",
            sound_effect="ding", disable_auto_git=True, git_tag="v1",
        )
        fc_old = Flowchart()
        fc_old.blocks.clear()
        s = StartBlock(id="s")
        fc_old.blocks["s"] = s
        fc_old.blocks["p1"] = gui_prompt
        fc_old.start_block_id = "s"
        fc_old.connections = []

        engine = flowchart_to_pydantic(fc_old)
        epb = engine.blocks["p1"]
        assert epb.prompt == "test"
        # GUI-only fields should not exist on the engine model
        assert not hasattr(epb, "sound_effect")
        assert not hasattr(epb, "disable_auto_git")
        assert not hasattr(epb, "git_tag")

    def test_prompt_output_schema_preserved(self):
        """PromptBlock output_schema is preserved (exists in both models)."""
        pos = Position(0, 0)
        gui_prompt = PromptBlock(
            id="p1", position=pos, prompt="test",
            output_schema={"type": "object", "properties": {"x": {"type": "number"}}},
        )
        fc_old = Flowchart()
        fc_old.blocks.clear()
        s = StartBlock(id="s")
        fc_old.blocks["s"] = s
        fc_old.blocks["p1"] = gui_prompt
        fc_old.start_block_id = "s"
        fc_old.connections = []

        engine = flowchart_to_pydantic(fc_old)
        assert engine.blocks["p1"].output_schema == {
            "type": "object",
            "properties": {"x": {"type": "number"}},
        }


# -- Connection conversion --


class TestConnectionConversion:
    """Test connection field mapping and GUI-only field stripping."""

    def test_source_block_id_mapped(self):
        """GUI source_block_id becomes engine source_id."""
        fc_old = Flowchart()
        fc_old.blocks.clear()
        s = StartBlock(id="s")
        e = EndBlock(id="e")
        fc_old.blocks["s"] = s
        fc_old.blocks["e"] = e
        fc_old.connections = [
            Connection(id="c1", source_block_id="s", target_block_id="e",
                       source_port="bottom", target_port="top"),
        ]
        fc_old.start_block_id = "s"

        engine = flowchart_to_pydantic(fc_old)
        ec = engine.connections[0]
        assert ec.source_id == "s"
        assert ec.target_id == "e"
        # GUI-only port fields should not exist
        assert not hasattr(ec, "source_port")
        assert not hasattr(ec, "target_port")

    def test_is_true_path_preserved(self):
        """Connection is_true_path survives conversion."""
        fc_old = Flowchart()
        fc_old.blocks.clear()
        s = StartBlock(id="s")
        e = EndBlock(id="e")
        fc_old.blocks["s"] = s
        fc_old.blocks["e"] = e
        fc_old.connections = [
            Connection(id="c1", source_block_id="s", target_block_id="e",
                       is_true_path=False),
        ]
        fc_old.start_block_id = "s"

        engine = flowchart_to_pydantic(fc_old)
        assert engine.connections[0].is_true_path is False

    def test_connection_roundtrip(self):
        """Connection survives GUI → engine → GUI roundtrip."""
        fc_old = Flowchart()
        fc_old.blocks.clear()
        s = StartBlock(id="s")
        e = EndBlock(id="e")
        fc_old.blocks["s"] = s
        fc_old.blocks["e"] = e
        fc_old.connections = [
            Connection(id="c1", source_block_id="s", target_block_id="e",
                       source_port="right", target_port="left", is_true_path=False),
        ]
        fc_old.start_block_id = "s"

        engine = flowchart_to_pydantic(fc_old)
        gui_back = flowchart_from_pydantic(engine)

        bc = gui_back.connections[0]
        assert bc.source_block_id == "s"
        assert bc.target_block_id == "e"
        assert bc.is_true_path is False
        # Port info is lost in roundtrip (engine doesn't store it),
        # defaults are applied on the way back
        assert bc.source_port == "bottom"
        assert bc.target_port == "top"


# -- Engine-only field stripping (engine → GUI) --


class TestEngineOnlyFieldStripping:
    """Test that engine-only fields are removed when converting back to GUI."""

    def test_session_field_removed(self):
        """Engine's session field is stripped for all block types."""
        d = {"type": "start", "session": "custom"}
        _adapt_block_fields_new_to_old(d)
        assert "session" not in d

    def test_prompt_output_variable_removed(self):
        """Engine PromptBlock.output_variable is removed (GUI doesn't have it)."""
        d = {"type": "prompt", "prompt": "hi", "output_variable": "result"}
        _adapt_block_fields_new_to_old(d)
        assert "output_variable" not in d

    def test_refresh_target_session_removed(self):
        """Engine RefreshBlock.target_session is removed."""
        d = {"type": "refresh", "target_session": "agent-1"}
        _adapt_block_fields_new_to_old(d)
        assert "target_session" not in d

    def test_exit_message_removed(self):
        """Engine ExitBlock.exit_message is removed."""
        d = {"type": "exit", "exit_code": 1, "exit_message": "failed"}
        _adapt_block_fields_new_to_old(d)
        assert "exit_message" not in d
        assert d["exit_code"] == 1

    def test_spawn_model_backend_removed(self):
        """Engine SpawnBlock.model and .backend are removed."""
        d = {
            "type": "spawn",
            "agent_name": "w", "command_name": "run",
            "model": "claude-sonnet-4-5-20250929", "backend": "claude",
            "exit_code_variable": None, "config_file": None,
        }
        _adapt_block_fields_new_to_old(d)
        assert "model" not in d
        assert "backend" not in d
        assert d["exit_code_variable"] == ""
        assert d["config_file"] == ""


# -- Full 11-type flowchart roundtrip --


class TestAllBlockTypesRoundtrip:
    """Test a flowchart with all 11 GUI block types survives roundtrip."""

    def _make_full_flowchart(self):
        pos = Position(0, 0)
        blocks = {
            "s": StartBlock(id="s", position=pos),
            "p": PromptBlock(id="p", position=pos, prompt="Hello"),
            "b": BranchBlock(id="b", position=pos, condition="x > 5"),
            "v": VariableBlock(id="v", position=pos, variable_name="x",
                               variable_value="10", variable_type="int"),
            "ba": BashBlock(id="ba", position=pos, command="echo hi",
                            output_variable="out", output_type="string"),
            "c": CommandBlock(id="c", position=pos, command_name="sub",
                              arguments="a b", inherit_variables=True),
            "r": RefreshBlock(id="r", position=pos),
            "x": ExitBlock(id="x", position=pos, exit_code=1),
            "sp": SpawnBlock(id="sp", position=pos, agent_name="worker",
                             command_name="task"),
            "w": WaitBlock(id="w", position=pos,
                           entries=[WaitEntry("worker")]),
            "e": EndBlock(id="e", position=pos),
        }

        fc_old = Flowchart()
        fc_old.blocks = blocks
        fc_old.connections = [
            Connection(id="c1", source_block_id="s", target_block_id="p"),
        ]
        fc_old.start_block_id = "s"
        return fc_old

    def test_all_types_convert_to_engine(self):
        """All 11 GUI block types convert to engine without error."""
        fc_old = self._make_full_flowchart()
        engine = flowchart_to_pydantic(fc_old)
        assert len(engine.blocks) == 11

        # Verify each block got the right engine type
        assert isinstance(engine.blocks["s"], fc.StartBlock)
        assert isinstance(engine.blocks["p"], fc.PromptBlock)
        assert isinstance(engine.blocks["b"], fc.BranchBlock)
        assert isinstance(engine.blocks["v"], fc.VariableBlock)
        assert isinstance(engine.blocks["ba"], fc.BashBlock)
        assert isinstance(engine.blocks["c"], fc.CommandBlock)
        assert isinstance(engine.blocks["r"], fc.RefreshBlock)
        assert isinstance(engine.blocks["x"], fc.ExitBlock)
        assert isinstance(engine.blocks["sp"], fc.SpawnBlock)
        assert isinstance(engine.blocks["w"], fc.WaitBlock)
        assert isinstance(engine.blocks["e"], fc.EndBlock)

    def test_all_types_roundtrip(self):
        """All 11 block types survive GUI → engine → GUI roundtrip."""
        fc_old = self._make_full_flowchart()
        engine = flowchart_to_pydantic(fc_old)
        gui_back = flowchart_from_pydantic(engine)

        assert len(gui_back.blocks) == 11

        # Verify block types survived
        for bid in ("s", "p", "b", "v", "ba", "c", "r", "x", "sp", "w", "e"):
            assert bid in gui_back.blocks, f"Block {bid} missing after roundtrip"
            assert gui_back.blocks[bid].type == fc_old.blocks[bid].type

    def test_field_values_survive_roundtrip(self):
        """Key field values survive the roundtrip."""
        fc_old = self._make_full_flowchart()
        engine = flowchart_to_pydantic(fc_old)
        gui_back = flowchart_from_pydantic(engine)

        assert gui_back.blocks["p"].prompt == "Hello"
        assert gui_back.blocks["b"].condition == "x > 5"
        assert gui_back.blocks["v"].variable_name == "x"
        assert gui_back.blocks["v"].variable_value == "10"
        assert gui_back.blocks["ba"].command == "echo hi"
        assert gui_back.blocks["ba"].output_variable == "out"
        assert gui_back.blocks["c"].command_name == "sub"
        assert gui_back.blocks["c"].inherit_variables is True
        assert gui_back.blocks["x"].exit_code == 1
        assert gui_back.blocks["sp"].agent_name == "worker"
        assert gui_back.blocks["w"].entries[0].agent_name == "worker"
