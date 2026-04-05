"""Flowchart — pure data library for defining flowchart workflows.

Extended with Spawn/Wait/Exit blocks, git per-block control,
conditional strings, and execution tracking helpers.
"""

from .blocks import (
    BashBlock,
    Block,
    BlockBase,
    BlockType,
    BranchBlock,
    CommandBlock,
    EndBlock,
    ExitBlock,
    InputBlock,
    Position,
    PromptBlock,
    RefreshBlock,
    SpawnBlock,
    StartBlock,
    VariableBlock,
    VariableType,
    WaitBlock,
)
from .command import Command, CommandMetadata
from .io import dump, dump_command, load, load_command, save, save_command
from .models import Argument, Connection, Flowchart, SessionConfig, VariableEntry, WaitEntry
from .templates import (
    ArgRef,
    Conditional,
    Literal,
    TemplatePart,
    VarRef,
    parse_template,
    validate_conditionals,
)
from .validation import ValidationResult, validate

__all__ = [
    # Blocks
    "Block",
    "BlockBase",
    "BlockType",
    "BashBlock",
    "BranchBlock",
    "CommandBlock",
    "EndBlock",
    "ExitBlock",
    "InputBlock",
    "Position",
    "PromptBlock",
    "RefreshBlock",
    "SpawnBlock",
    "StartBlock",
    "VariableBlock",
    "VariableType",
    "WaitBlock",
    # Models
    "Argument",
    "Connection",
    "Flowchart",
    "SessionConfig",
    "VariableEntry",
    "WaitEntry",
    # Command
    "Command",
    "CommandMetadata",
    # Templates
    "ArgRef",
    "Conditional",
    "Literal",
    "TemplatePart",
    "VarRef",
    "parse_template",
    "validate_conditionals",
    # Validation
    "ValidationResult",
    "validate",
    # I/O
    "dump",
    "dump_command",
    "load",
    "load_command",
    "save",
    "save_command",
]
