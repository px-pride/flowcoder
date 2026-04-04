"""Block types for flowchart workflows.

Defines the BlockType enum, all block models, and the Block discriminated union.

Extended from leroux's flow-mono with:
- SpawnBlock, WaitBlock, ExitBlock for agent sub-sessions
- Git per-block control (disable_auto_git, git_tag) on Prompt/Bash/Command
- Additional config fields on CommandBlock (exit_code_variable, suppress_child_auto_git)
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class BlockType(str, Enum):
    START = "start"
    END = "end"
    PROMPT = "prompt"
    BRANCH = "branch"
    VARIABLE = "variable"
    BASH = "bash"
    COMMAND = "command"
    REFRESH = "refresh"
    SPAWN = "spawn"
    WAIT = "wait"
    EXIT = "exit"


class VariableType(str, Enum):
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    JSON = "json"


class Position(BaseModel):
    x: float
    y: float


class BlockBase(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = ""
    session: str = "default"
    position: Position | None = None


class StartBlock(BlockBase):
    type: Literal[BlockType.START] = BlockType.START


class EndBlock(BlockBase):
    type: Literal[BlockType.END] = BlockType.END


class PromptBlock(BlockBase):
    type: Literal[BlockType.PROMPT] = BlockType.PROMPT
    prompt: str
    output_variable: str | None = None
    output_schema: dict[str, Any] | None = None
    # Git per-block control
    disable_auto_git: bool = False
    git_tag: str | None = None


class BranchBlock(BlockBase):
    type: Literal[BlockType.BRANCH] = BlockType.BRANCH
    condition: str


class VariableBlock(BlockBase):
    type: Literal[BlockType.VARIABLE] = BlockType.VARIABLE
    variable_name: str
    variable_value: str = ""
    variable_type: VariableType = VariableType.STRING


class BashBlock(BlockBase):
    type: Literal[BlockType.BASH] = BlockType.BASH
    command: str
    capture_output: bool = True
    output_variable: str | None = None
    output_type: VariableType = VariableType.STRING
    continue_on_error: bool = False
    working_directory: str | None = None
    exit_code_variable: str | None = None
    # Git per-block control
    disable_auto_git: bool = False
    git_tag: str | None = None


class CommandBlock(BlockBase):
    type: Literal[BlockType.COMMAND] = BlockType.COMMAND
    command_name: str
    arguments: str = ""
    inherit_variables: bool = False
    merge_output: bool = False
    # Extended config
    exit_code_variable: str | None = None
    suppress_child_auto_git: bool = False
    git_tag: str | None = None


class RefreshBlock(BlockBase):
    type: Literal[BlockType.REFRESH] = BlockType.REFRESH
    target_session: str | None = None


class SpawnBlock(BlockBase):
    """Spawn a named agent sub-session running a command asynchronously."""
    type: Literal[BlockType.SPAWN] = BlockType.SPAWN
    agent_name: str = ""
    command_name: str = ""
    arguments: str = ""
    inherit_variables: bool = False
    exit_code_variable: str | None = None
    config_file: str | None = None
    model: str | None = None


class WaitBlock(BlockBase):
    """Wait for one or more spawned agent sessions to complete."""
    type: Literal[BlockType.WAIT] = BlockType.WAIT
    wait_for: list[str] = Field(default_factory=list)
    timeout_seconds: int | None = None


class ExitBlock(BlockBase):
    """Explicitly exit the flowchart with a given exit code."""
    type: Literal[BlockType.EXIT] = BlockType.EXIT
    exit_code: int = 0
    exit_message: str = ""


Block = Annotated[
    StartBlock
    | EndBlock
    | PromptBlock
    | BranchBlock
    | VariableBlock
    | BashBlock
    | CommandBlock
    | RefreshBlock
    | SpawnBlock
    | WaitBlock
    | ExitBlock,
    Field(discriminator="type"),
]
