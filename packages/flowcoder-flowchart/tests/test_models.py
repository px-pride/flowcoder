"""Tests for core models: Connection, Argument, SessionConfig, Flowchart."""

import pytest
from flowcoder_flowchart import (
    Argument,
    Connection,
    EndBlock,
    Flowchart,
    PromptBlock,
    SessionConfig,
    StartBlock,
)


class TestConnection:
    def test_basic(self):
        c = Connection(source_id="a", target_id="b")
        assert c.source_id == "a"
        assert c.target_id == "b"
        assert c.id  # auto-generated
        assert c.label is None
        assert c.is_true_path is None

    def test_branch_connection(self):
        c = Connection(source_id="a", target_id="b", is_true_path=True, label="yes")
        assert c.is_true_path is True
        assert c.label == "yes"

    def test_roundtrip(self):
        c = Connection(
            id="c1", source_id="a", target_id="b", is_true_path=False, label="no"
        )
        data = c.model_dump()
        restored = Connection.model_validate(data)
        assert restored.id == "c1"
        assert restored.is_true_path is False


class TestArgument:
    def test_required(self):
        a = Argument(name="file", description="Input file")
        assert a.required is True
        assert a.default is None

    def test_optional_with_default(self):
        a = Argument(name="mode", required=False, default="strict")
        assert a.required is False
        assert a.default == "strict"

    def test_optional_no_default(self):
        a = Argument(name="verbose", required=False)
        assert a.default is None

    def test_required_with_default_raises(self):
        with pytest.raises(ValueError, match="cannot be both required"):
            Argument(name="x", required=True, default="bad")

    def test_roundtrip(self):
        a = Argument(name="file", description="Input file", required=True)
        data = a.model_dump()
        restored = Argument.model_validate(data)
        assert restored.name == "file"
        assert restored.required is True


class TestSessionConfig:
    def test_basic(self):
        sc = SessionConfig(model="opus")
        assert sc.model == "opus"
        assert sc.system_prompt is None
        assert sc.tools is None

    def test_full(self):
        sc = SessionConfig(
            model="sonnet",
            system_prompt="Be concise.",
            tools=["bash", "read"],
        )
        assert sc.system_prompt == "Be concise."
        assert sc.tools == ["bash", "read"]

    def test_extra_fields_allowed(self):
        sc = SessionConfig(model="opus", temperature=0.5, max_tokens=1000)
        assert sc.model_extra["temperature"] == 0.5
        assert sc.model_extra["max_tokens"] == 1000

    def test_roundtrip_with_extras(self):
        sc = SessionConfig(model="opus", custom_field="value")
        data = sc.model_dump()
        assert data["custom_field"] == "value"
        restored = SessionConfig.model_validate(data)
        assert restored.model_extra["custom_field"] == "value"


class TestFlowchart:
    def _simple_flowchart(self) -> Flowchart:
        return Flowchart(
            name="test",
            blocks={
                "b1": StartBlock(id="b1", name="Start"),
                "b2": PromptBlock(id="b2", name="Ask", prompt="Hello"),
                "b3": EndBlock(id="b3", name="End"),
            },
            connections=[
                Connection(source_id="b1", target_id="b2"),
                Connection(source_id="b2", target_id="b3"),
            ],
        )

    def test_basic(self):
        fc = self._simple_flowchart()
        assert fc.name == "test"
        assert len(fc.blocks) == 3
        assert len(fc.connections) == 2

    def test_empty_defaults(self):
        fc = Flowchart(blocks={})
        assert fc.connections == []
        assert fc.sessions == {}
        assert fc.arguments == []
        assert fc.metadata == {}
        assert fc.name == ""

    def test_with_sessions(self):
        fc = Flowchart(
            blocks={"b1": StartBlock(id="b1")},
            sessions={
                "default": SessionConfig(model="opus"),
                "reviewer": SessionConfig(model="sonnet", system_prompt="Be brief."),
            },
        )
        assert "default" in fc.sessions
        assert fc.sessions["reviewer"].system_prompt == "Be brief."

    def test_with_arguments(self):
        fc = Flowchart(
            blocks={"b1": StartBlock(id="b1")},
            arguments=[
                Argument(name="file", description="Input file"),
                Argument(name="mode", required=False, default="strict"),
            ],
        )
        assert len(fc.arguments) == 2
        assert fc.arguments[0].name == "file"
        assert fc.arguments[1].default == "strict"

    def test_with_metadata(self):
        fc = Flowchart(
            blocks={"b1": StartBlock(id="b1")},
            metadata={"version": "1.0", "author": "test"},
        )
        assert fc.metadata["version"] == "1.0"

    def test_roundtrip(self):
        fc = self._simple_flowchart()
        data = fc.model_dump()
        restored = Flowchart.model_validate(data)
        assert restored.name == "test"
        assert len(restored.blocks) == 3
        assert isinstance(restored.blocks["b1"], StartBlock)
        assert isinstance(restored.blocks["b2"], PromptBlock)
        assert isinstance(restored.blocks["b3"], EndBlock)

    def test_roundtrip_json(self):
        fc = self._simple_flowchart()
        json_str = fc.model_dump_json()
        restored = Flowchart.model_validate_json(json_str)
        assert restored.name == fc.name
        assert len(restored.blocks) == len(fc.blocks)

    def test_multi_session_roundtrip(self):
        fc = Flowchart(
            name="deploy",
            blocks={
                "b1": StartBlock(id="b1"),
                "b2": PromptBlock(id="b2", prompt="Deploy", session="deployer"),
                "b3": PromptBlock(id="b3", prompt="Review", session="reviewer"),
                "b4": EndBlock(id="b4"),
            },
            connections=[
                Connection(source_id="b1", target_id="b2"),
                Connection(source_id="b2", target_id="b3"),
                Connection(source_id="b3", target_id="b4"),
            ],
            sessions={
                "deployer": SessionConfig(model="opus"),
                "reviewer": SessionConfig(model="sonnet"),
            },
        )
        data = fc.model_dump()
        restored = Flowchart.model_validate(data)
        assert restored.blocks["b2"].session == "deployer"
        assert restored.blocks["b3"].session == "reviewer"
        assert restored.sessions["deployer"].model == "opus"
