"""
Execution Models for FlowCoder

Tracks execution state and history during command execution.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum


class ExecutionStatus(str, Enum):
    """Status of execution."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    HALTED = "halted"
    ERROR = "error"


class BlockExecutionStatus(str, Enum):
    """Status of a single block execution."""
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass
class ExecutionLogEntry:
    """A single entry in the execution log."""
    block_id: str
    block_name: str
    timestamp: datetime
    status: BlockExecutionStatus
    output: Optional[Dict[str, Any]] = None
    raw_response: Optional[str] = None
    error: Optional[str] = None
    duration_ms: Optional[int] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "block_id": self.block_id,
            "block_name": self.block_name,
            "timestamp": self.timestamp.isoformat(),
            "status": self.status.value,
            "output": self.output,
            "raw_response": self.raw_response,
            "error": self.error,
            "duration_ms": self.duration_ms
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'ExecutionLogEntry':
        """Create from dictionary."""
        return cls(
            block_id=data["block_id"],
            block_name=data["block_name"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            status=BlockExecutionStatus(data["status"]),
            output=data.get("output"),
            raw_response=data.get("raw_response"),
            error=data.get("error"),
            duration_ms=data.get("duration_ms")
        )


@dataclass
class ExecutionContext:
    """Context for a single execution of a command."""
    command_id: str
    command_name: str = ""
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    current_block_id: Optional[str] = None
    execution_log: List[ExecutionLogEntry] = field(default_factory=list)
    variables: Dict[str, Any] = field(default_factory=dict)  # Stores both arguments and structured outputs
    halt_requested: bool = False
    loop_counters: Dict[str, int] = field(default_factory=dict)
    status: ExecutionStatus = ExecutionStatus.PENDING

    # Hierarchical execution support (Phase 5.5)
    parent_context: Optional['ExecutionContext'] = None  # Parent context for nested execution
    depth: int = 0  # Nesting depth (0 = root, 1 = first child, etc.)
    max_depth: int = 10  # Maximum allowed nesting depth

    # Call stack tracking (Phase 5.6 - Recursion Protection)
    call_stack: List[str] = field(default_factory=list)  # Tracks command names in execution chain

    def add_log_entry(self, entry: ExecutionLogEntry) -> None:
        """Add an entry to the execution log."""
        self.execution_log.append(entry)

    def request_halt(self) -> None:
        """Request that execution be halted."""
        self.halt_requested = True

    def is_halted(self) -> bool:
        """Check if execution should halt."""
        return self.halt_requested

    def increment_loop_counter(self, loop_key: str) -> int:
        """
        Increment and return the loop counter for a specific loop.

        Returns current iteration count (0-indexed).
        First call returns 0, second returns 1, etc.
        """
        if loop_key not in self.loop_counters:
            self.loop_counters[loop_key] = -1  # Initialize to -1
        self.loop_counters[loop_key] += 1       # Increment to 0 on first call
        return self.loop_counters[loop_key]     # Returns 0 on first call

    def get_loop_count(self, loop_key: str) -> int:
        """Get the current loop count."""
        return self.loop_counters.get(loop_key, 0)

    def get_last_output(self) -> Optional[Dict[str, Any]]:
        """Get the output from the most recent block execution."""
        if self.execution_log:
            return self.execution_log[-1].output
        return None

    def complete(self, status: ExecutionStatus = ExecutionStatus.COMPLETED) -> None:
        """Mark execution as complete."""
        self.end_time = datetime.now()
        self.status = status
        self.current_block_id = None

    def get_duration_ms(self) -> Optional[int]:
        """Get total execution duration in milliseconds."""
        if self.end_time and self.start_time:
            delta = self.end_time - self.start_time
            return int(delta.total_seconds() * 1000)
        return None

    def can_nest_deeper(self) -> bool:
        """
        Check if execution can nest deeper (for command blocks).

        Returns:
            True if depth + 1 <= max_depth, False otherwise
        """
        return self.depth + 1 <= self.max_depth

    def get_variable(self, key: str, check_parent: bool = True) -> Optional[Any]:
        """
        Get variable value, optionally checking parent context.

        Args:
            key: Variable name
            check_parent: Whether to check parent context if not found locally

        Returns:
            Variable value, or None if not found
        """
        # Check local variables first
        if key in self.variables:
            return self.variables[key]

        # Check parent context if enabled and parent exists
        if check_parent and self.parent_context:
            return self.parent_context.get_variable(key, check_parent=True)

        return None

    def push_call_stack(self, command_name: str) -> None:
        """
        Add command to call stack.

        This method is used for recursion detection. It checks if the command
        is already in the call stack (indicating recursion) and raises an error
        if detected.

        Args:
            command_name: Name of command being executed

        Raises:
            CommandRecursionError: If command would cause recursion
        """
        from src.exceptions import CommandRecursionError

        # Check for direct/indirect recursion
        if command_name in self.call_stack:
            raise CommandRecursionError(
                command_name=command_name,
                call_stack=self.call_stack + [command_name]
            )

        # Add to call stack
        self.call_stack.append(command_name)

    def pop_call_stack(self) -> None:
        """
        Remove most recent command from call stack.

        This should be called after a command completes execution,
        whether successful or not.
        """
        if self.call_stack:
            self.call_stack.pop()

    def get_call_chain(self) -> str:
        """
        Get human-readable call chain.

        Returns:
            String representation of call chain

        Example:
            "deploy → run-tests → setup-env"
        """
        if not self.call_stack:
            return "(no calls)"
        return " → ".join(self.call_stack)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "command_id": self.command_id,
            "command_name": self.command_name,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "current_block_id": self.current_block_id,
            "execution_log": [entry.to_dict() for entry in self.execution_log],
            "variables": self.variables,
            "halt_requested": self.halt_requested,
            "loop_counters": self.loop_counters,
            "status": self.status.value,
            "duration_ms": self.get_duration_ms()
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'ExecutionContext':
        """Create from dictionary."""
        context = cls(
            command_id=data["command_id"],
            command_name=data["command_name"],
            start_time=datetime.fromisoformat(data["start_time"]),
            end_time=datetime.fromisoformat(data["end_time"]) if data.get("end_time") else None,
            current_block_id=data.get("current_block_id"),
            execution_log=[
                ExecutionLogEntry.from_dict(entry)
                for entry in data.get("execution_log", [])
            ],
            variables=data.get("variables", {}),
            halt_requested=data.get("halt_requested", False),
            loop_counters=data.get("loop_counters", {}),
            status=ExecutionStatus(data.get("status", "pending"))
        )
        return context


@dataclass
class BlockResult:
    """Result of executing a single block."""
    success: bool
    output: Optional[Dict[str, Any]] = None
    raw_response: Optional[str] = None
    error: Optional[str] = None
    duration_ms: Optional[int] = None

    @classmethod
    def success_result(
        cls,
        output: Optional[Dict[str, Any]] = None,
        raw_response: Optional[str] = None,
        duration_ms: Optional[int] = None
    ) -> 'BlockResult':
        """Create a successful result."""
        return cls(
            success=True,
            output=output,
            raw_response=raw_response,
            duration_ms=duration_ms
        )

    @classmethod
    def error_result(cls, error: str, duration_ms: Optional[int] = None) -> 'BlockResult':
        """Create an error result."""
        return cls(
            success=False,
            error=error,
            duration_ms=duration_ms
        )
