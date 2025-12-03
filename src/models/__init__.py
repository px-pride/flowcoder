"""
Models package for FlowCoder

Exports all data models used throughout the application.
"""

from .blocks import (
    Block,
    BlockType,
    Position,
    BranchCondition,
    StartBlock,
    PromptBlock,
    VariableBlock,
    BashBlock,
    BranchBlock,
    CommandBlock,
    RefreshBlock,
    EndBlock,
    create_block
)

from .connection import Connection

from .flowchart import Flowchart, ValidationResult

from .command import Command, CommandMetadata

from .execution import (
    ExecutionContext,
    ExecutionLogEntry,
    BlockResult,
    ExecutionStatus,
    BlockExecutionStatus
)

from .session_state import SessionState

from .session import Session, Message, ExecutionRun

__all__ = [
    # Blocks
    'Block',
    'BlockType',
    'Position',
    'BranchCondition',
    'StartBlock',
    'PromptBlock',
    'VariableBlock',
    'BashBlock',
    'BranchBlock',
    'CommandBlock',
    'RefreshBlock',
    'EndBlock',
    'create_block',
    # Connection
    'Connection',
    # Flowchart
    'Flowchart',
    'ValidationResult',
    # Command
    'Command',
    'CommandMetadata',
    # Execution
    'ExecutionContext',
    'ExecutionLogEntry',
    'BlockResult',
    'ExecutionStatus',
    'BlockExecutionStatus',
    # Session
    'SessionState',
    'Session',
    'Message',
    'ExecutionRun',
]
