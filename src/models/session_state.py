"""
Session State - Enum for session execution states.

Tracks the current state of a Claude Code session during execution.
"""

from enum import Enum


class SessionState(Enum):
    """
    Session execution state.

    States:
        IDLE: Session is idle, ready for new commands
        EXECUTING: Session is executing a command
        HALTED: Execution was halted by user
        ERROR: Session encountered an error
    """

    IDLE = "idle"
    EXECUTING = "executing"
    HALTED = "halted"
    ERROR = "error"

    def __str__(self):
        """Return string value of state."""
        return self.value

    def __repr__(self):
        """Return representation of state."""
        return f"SessionState.{self.name}"
