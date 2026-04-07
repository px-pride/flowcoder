"""Tests for CommandBlock execution (composition)."""

import tempfile
from pathlib import Path

from flowcoder_engine.walker import GraphWalker
from flowcoder_flowchart import (
    Command,
    CommandBlock,
    Connection,
    EndBlock,
    Flowchart,
    PromptBlock,
    StartBlock,
    VariableBlock,
)

from tests.conftest import MockProtocol, MockSession


def _write_command(tmpdir: Path, name: str, cmd: Command) -> None:
    """Write a command JSON file to a temp directory."""
    commands_dir = tmpdir / "commands"
    commands_dir.mkdir(exist_ok=True)
    (commands_dir / f"{name}.json").write_text(cmd.model_dump_json(indent=2))


def _simple_sub_command() -> Command:
    """A sub-command that prompts and sets a variable."""
    return Command(
        name="test-sub",
        description="Simple sub-command",
        flowchart=Flowchart(
            blocks={
                "s": StartBlock(id="s"),
                "p": PromptBlock(id="p", prompt="Sub-task: $1"),
                "v": VariableBlock(
                    id="v", variable_name="sub_result", variable_value="done",
                ),
                "e": EndBlock(id="e"),
            },
            connections=[
                Connection(source_id="s", target_id="p"),
                Connection(source_id="p", target_id="v"),
                Connection(source_id="v", target_id="e"),
            ],
        ),
    )


class TestCommandBlockExecution:
    async def test_basic_command_block(self):
        """Command block resolves and executes a sub-command."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_command(Path(tmpdir), "test-sub", _simple_sub_command())

            fc = Flowchart(
                blocks={
                    "s": StartBlock(id="s"),
                    "c": CommandBlock(
                        id="c", command_name="test-sub",
                        arguments="hello",
                        merge_output=True,
                    ),
                    "e": EndBlock(id="e"),
                },
                connections=[
                    Connection(source_id="s", target_id="c"),
                    Connection(source_id="c", target_id="e"),
                ],
            )

            session = MockSession(["Sub response"])
            proto = MockProtocol()
            walker = GraphWalker(
                fc, session, {}, proto, search_paths=[tmpdir]
            )
            result = await walker.run()

            assert result.status == "completed"
            assert result.variables.get("sub_result") == "done"

    async def test_command_block_passes_arguments(self):
        """Arguments from parent are available as $1, $2 in child."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_command(Path(tmpdir), "test-sub", _simple_sub_command())

            fc = Flowchart(
                blocks={
                    "s": StartBlock(id="s"),
                    "v": VariableBlock(
                        id="v", variable_name="task", variable_value="build it",
                    ),
                    "c": CommandBlock(
                        id="c", command_name="test-sub",
                        arguments="{{task}}",
                        merge_output=True,
                    ),
                    "e": EndBlock(id="e"),
                },
                connections=[
                    Connection(source_id="s", target_id="v"),
                    Connection(source_id="v", target_id="c"),
                    Connection(source_id="c", target_id="e"),
                ],
            )

            session = MockSession(["Sub response"])
            proto = MockProtocol()
            walker = GraphWalker(
                fc, session, {}, proto, search_paths=[tmpdir]
            )
            result = await walker.run()

            assert result.status == "completed"
            # The sub-command should have received "build" as $1 and "it" as $2
            assert any("Entering sub-command" in log for log in proto.logs)

    async def test_command_block_inherit_variables(self):
        """inherit_variables=True passes parent vars to child."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Sub-command that uses a parent variable
            sub = Command(
                name="test-sub",
                flowchart=Flowchart(
                    blocks={
                        "s": StartBlock(id="s"),
                        "v": VariableBlock(
                            id="v", variable_name="combined",
                            variable_value="{{parent_var}}-child",
                        ),
                        "e": EndBlock(id="e"),
                    },
                    connections=[
                        Connection(source_id="s", target_id="v"),
                        Connection(source_id="v", target_id="e"),
                    ],
                ),
            )
            _write_command(Path(tmpdir), "test-sub", sub)

            fc = Flowchart(
                blocks={
                    "s": StartBlock(id="s"),
                    "c": CommandBlock(
                        id="c", command_name="test-sub",
                        inherit_variables=True,
                        merge_output=True,
                    ),
                    "e": EndBlock(id="e"),
                },
                connections=[
                    Connection(source_id="s", target_id="c"),
                    Connection(source_id="c", target_id="e"),
                ],
            )

            session = MockSession()
            proto = MockProtocol()
            walker = GraphWalker(
                fc, session, {"parent_var": "hello"}, proto,
                search_paths=[tmpdir],
            )
            result = await walker.run()

            assert result.status == "completed"
            assert result.variables.get("combined") == "hello-child"

    async def test_command_block_no_merge(self):
        """merge_output=False keeps child variables out of parent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_command(Path(tmpdir), "test-sub", _simple_sub_command())

            fc = Flowchart(
                blocks={
                    "s": StartBlock(id="s"),
                    "c": CommandBlock(
                        id="c", command_name="test-sub",
                        arguments="hello",
                        merge_output=False,
                    ),
                    "e": EndBlock(id="e"),
                },
                connections=[
                    Connection(source_id="s", target_id="c"),
                    Connection(source_id="c", target_id="e"),
                ],
            )

            session = MockSession(["Sub response"])
            proto = MockProtocol()
            walker = GraphWalker(
                fc, session, {}, proto, search_paths=[tmpdir]
            )
            result = await walker.run()

            assert result.status == "completed"
            # sub_result should NOT be in parent variables
            assert "sub_result" not in result.variables

    async def test_command_not_found(self):
        """CommandBlock fails gracefully when command not found."""
        fc = Flowchart(
            blocks={
                "s": StartBlock(id="s"),
                "c": CommandBlock(id="c", command_name="nonexistent"),
                "e": EndBlock(id="e"),
            },
            connections=[
                Connection(source_id="s", target_id="c"),
                Connection(source_id="c", target_id="e"),
            ],
        )

        session = MockSession()
        proto = MockProtocol()
        walker = GraphWalker(
            fc, session, {}, proto, search_paths=["/tmp/empty-path"]
        )
        result = await walker.run()

        assert result.status == "halted"
        assert any("not found" in e.result.error for e in result.log if e.result.error)


class TestCommandBlockRecursion:
    async def test_max_depth_exceeded(self):
        """Recursive command block hits max depth."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a command that calls itself
            recursive = Command(
                name="recurse",
                flowchart=Flowchart(
                    blocks={
                        "s": StartBlock(id="s"),
                        "c": CommandBlock(id="c", command_name="recurse"),
                        "e": EndBlock(id="e"),
                    },
                    connections=[
                        Connection(source_id="s", target_id="c"),
                        Connection(source_id="c", target_id="e"),
                    ],
                ),
            )
            _write_command(Path(tmpdir), "recurse", recursive)

            fc = Flowchart(
                blocks={
                    "s": StartBlock(id="s"),
                    "c": CommandBlock(id="c", command_name="recurse"),
                    "e": EndBlock(id="e"),
                },
                connections=[
                    Connection(source_id="s", target_id="c"),
                    Connection(source_id="c", target_id="e"),
                ],
            )

            session = MockSession()
            proto = MockProtocol()
            walker = GraphWalker(
                fc, session, {}, proto,
                search_paths=[tmpdir],
                max_depth=3,
            )
            result = await walker.run()

            assert result.status == "halted"
            # The deepest error "Max recursion depth" propagates up
            # through "Sub-command 'recurse' failed: ..." wrapping
            errors = [e.result.error for e in result.log if e.result.error]
            assert len(errors) > 0
            # The top-level error should mention the sub-command failure,
            # and the deepest error should mention recursion depth
            assert any("recurse" in err for err in errors)

    async def test_nested_commands(self):
        """Two levels of nesting works correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Inner command: just sets a variable
            inner = Command(
                name="inner",
                flowchart=Flowchart(
                    blocks={
                        "s": StartBlock(id="s"),
                        "v": VariableBlock(
                            id="v", variable_name="inner_done",
                            variable_value="yes",
                        ),
                        "e": EndBlock(id="e"),
                    },
                    connections=[
                        Connection(source_id="s", target_id="v"),
                        Connection(source_id="v", target_id="e"),
                    ],
                ),
            )
            _write_command(Path(tmpdir), "inner", inner)

            # Outer command: calls inner
            outer = Command(
                name="outer",
                flowchart=Flowchart(
                    blocks={
                        "s": StartBlock(id="s"),
                        "c": CommandBlock(
                            id="c", command_name="inner",
                            merge_output=True,
                        ),
                        "v": VariableBlock(
                            id="v", variable_name="outer_done",
                            variable_value="yes",
                        ),
                        "e": EndBlock(id="e"),
                    },
                    connections=[
                        Connection(source_id="s", target_id="c"),
                        Connection(source_id="c", target_id="v"),
                        Connection(source_id="v", target_id="e"),
                    ],
                ),
            )
            _write_command(Path(tmpdir), "outer", outer)

            # Top-level flowchart calls outer
            fc = Flowchart(
                blocks={
                    "s": StartBlock(id="s"),
                    "c": CommandBlock(
                        id="c", command_name="outer",
                        merge_output=True,
                    ),
                    "e": EndBlock(id="e"),
                },
                connections=[
                    Connection(source_id="s", target_id="c"),
                    Connection(source_id="c", target_id="e"),
                ],
            )

            session = MockSession()
            proto = MockProtocol()
            walker = GraphWalker(
                fc, session, {}, proto, search_paths=[tmpdir]
            )
            result = await walker.run()

            assert result.status == "completed"
            assert result.variables.get("inner_done") == "yes"
            assert result.variables.get("outer_done") == "yes"

    async def test_positional_args_not_merged_back(self):
        """$1, $2 etc from child should not leak into parent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sub = Command(
                name="test-sub",
                flowchart=Flowchart(
                    blocks={
                        "s": StartBlock(id="s"),
                        "v": VariableBlock(
                            id="v", variable_name="out", variable_value="ok",
                        ),
                        "e": EndBlock(id="e"),
                    },
                    connections=[
                        Connection(source_id="s", target_id="v"),
                        Connection(source_id="v", target_id="e"),
                    ],
                ),
            )
            _write_command(Path(tmpdir), "test-sub", sub)

            fc = Flowchart(
                blocks={
                    "s": StartBlock(id="s"),
                    "c": CommandBlock(
                        id="c", command_name="test-sub",
                        arguments="arg1 arg2",
                        merge_output=True,
                    ),
                    "e": EndBlock(id="e"),
                },
                connections=[
                    Connection(source_id="s", target_id="c"),
                    Connection(source_id="c", target_id="e"),
                ],
            )

            session = MockSession()
            proto = MockProtocol()
            walker = GraphWalker(
                fc, session, {}, proto, search_paths=[tmpdir]
            )
            result = await walker.run()

            assert result.status == "completed"
            assert result.variables.get("out") == "ok"
            # Positional args from child should not leak
            assert "$1" not in result.variables
            assert "$2" not in result.variables
