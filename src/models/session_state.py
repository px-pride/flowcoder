"""
Session State - Enum for session execution states.

Tracks the current state of a Claude Code session during execution.
"""

from enum import Enum


class SessionState(Enum):
    """
    Session execution state.

    States:
        AGENT_OFF: Base agent is turned off (initial state)
        IDLE: Agent on, session idle, ready for new commands
        EXECUTING: Session is executing a command
        HALTED: Execution was halted by user (can resume or drop)
        WAITING_HALT: Waiting for current block to finish before halting
        WAITING_STOP: Waiting for current block to finish before stopping
        WAITING_REFRESH: Waiting for current block to finish before refreshing
        ERROR: Session encountered an error
    """

    AGENT_OFF = "agent_off"
    IDLE = "idle"
    EXECUTING = "executing"
    HALTED = "halted"
    WAITING_HALT = "waiting_halt"
    WAITING_STOP = "waiting_stop"
    WAITING_REFRESH = "waiting_refresh"
    ERROR = "error"

    def __str__(self):
        """Return string value of state."""
        return self.value

    def __repr__(self):
        """Return representation of state."""
        return f"SessionState.{self.name}"
