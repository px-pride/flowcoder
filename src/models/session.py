"""
Session - Data model for AI agent sessions.

Each session represents an independent AI agent execution environment with:
- Working directory
- Agent service instance
- Execution controller
- Chat history
- Execution history
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Any, Dict
from pathlib import Path

from .session_state import SessionState


@dataclass
class Message:
    """
    Chat message in a session.

    Represents a single message in the chat history between user and Claude.
    """

    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize message to dictionary."""
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat()
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'Message':
        """Deserialize message from dictionary."""
        return Message(
            role=data["role"],
            content=data["content"],
            timestamp=datetime.fromisoformat(data["timestamp"])
        )

    def __repr__(self) -> str:
        """String representation of message."""
        preview = self.content[:50] + "..." if len(self.content) > 50 else self.content
        return f"Message(role='{self.role}', content='{preview}')"


@dataclass
class ExecutionRun:
    """
    Record of a command execution.

    Tracks the execution of a single command within a session.
    """

    command_name: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    status: str = "running"  # "running", "completed", "error", "halted"
    blocks_executed: List[str] = field(default_factory=list)
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize execution run to dictionary."""
        return {
            "command_name": self.command_name,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "status": self.status,
            "blocks_executed": self.blocks_executed,
            "error_message": self.error_message
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'ExecutionRun':
        """Deserialize execution run from dictionary."""
        return ExecutionRun(
            command_name=data["command_name"],
            started_at=datetime.fromisoformat(data["started_at"]),
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            status=data["status"],
            blocks_executed=data.get("blocks_executed", []),
            error_message=data.get("error_message")
        )

    def __repr__(self) -> str:
        """String representation of execution run."""
        return f"ExecutionRun(command='{self.command_name}', status='{self.status}')"


@dataclass
class Session:
    """
    Represents an AI agent session.

    Each session has its own:
    - Working directory
    - AI service instance (Claude, Codex, or Mock)
    - Execution controller
    - Chat history
    - Execution history
    """

    name: str
    working_directory: str
    system_prompt: str = ""
    service_type: str = "claude"  # "claude", "codex", or "mock"
    created_at: datetime = field(default_factory=datetime.now)
    state: SessionState = SessionState.IDLE
    agent_service: Optional[Any] = None  # BaseService instance (avoid circular import)
    execution_controller: Optional[Any] = None  # ExecutionController
    chat_history: List[Message] = field(default_factory=list)
    execution_history: List[ExecutionRun] = field(default_factory=list)
    current_flowchart: Optional[Any] = None  # Flowchart
    git_repo_url: str = ""
    git_branch: str = ""
    git_auto_push: bool = False

    # Halted execution state (for resume functionality)
    halted_command: Optional[Any] = None  # Command that was halted
    halted_context: Optional[Any] = None  # ExecutionContext from halt point
    halted_flowchart: Optional[Any] = None  # Flowchart that was being executed

    def __post_init__(self):
        """Validate session after initialization."""
        # Ensure working directory is absolute path
        self.working_directory = str(Path(self.working_directory).resolve())

        # Validate working directory exists
        if not Path(self.working_directory).exists():
            raise ValueError(f"Working directory does not exist: {self.working_directory}")

        if not Path(self.working_directory).is_dir():
            raise ValueError(f"Working directory is not a directory: {self.working_directory}")

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize session to dictionary (for JSON storage).

        Note: Does not serialize agent_service, execution_controller, or current_flowchart
        as these are runtime objects that should be recreated on load.
        """
        return {
            "name": self.name,
            "working_directory": self.working_directory,
            "system_prompt": self.system_prompt,
            "service_type": self.service_type,
            "created_at": self.created_at.isoformat(),
            "state": self.state.value,
            "chat_history": [msg.to_dict() for msg in self.chat_history],
            "execution_history": [run.to_dict() for run in self.execution_history],
            "git_repo_url": self.git_repo_url,
            "git_branch": self.git_branch,
            "git_auto_push": self.git_auto_push,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'Session':
        """
        Deserialize session from dictionary.

        Note: Runtime objects (agent_service, execution_controller, current_flowchart)
        must be set separately after deserialization.
        """
        return Session(
            name=data["name"],
            working_directory=data["working_directory"],
            system_prompt=data.get("system_prompt", ""),
            service_type=data.get("service_type", "claude"),  # Default to "claude" for backward compatibility
            created_at=datetime.fromisoformat(data["created_at"]),
            state=SessionState(data["state"]),
            chat_history=[Message.from_dict(msg) for msg in data.get("chat_history", [])],
            execution_history=[ExecutionRun.from_dict(run) for run in data.get("execution_history", [])],
            git_repo_url=data.get("git_repo_url", ""),
            git_branch=data.get("git_branch", ""),
            git_auto_push=data.get("git_auto_push", False),
        )

    def add_message(self, role: str, content: str) -> Message:
        """
        Add a message to chat history.

        Args:
            role: "user" or "assistant"
            content: Message content

        Returns:
            The created Message object
        """
        message = Message(role=role, content=content)
        self.chat_history.append(message)
        return message

    def start_execution(self, command_name: str) -> ExecutionRun:
        """
        Start a new execution run.

        Clears any previous halted state - starting a new execution
        discards the ability to resume a previously halted command.

        Args:
            command_name: Name of command being executed

        Returns:
            The created ExecutionRun object
        """
        # Clear any previous halted state when starting new execution
        self.clear_halted_state()

        run = ExecutionRun(command_name=command_name, started_at=datetime.now())
        self.execution_history.append(run)
        self.state = SessionState.EXECUTING
        return run

    def complete_execution(self, success: bool = True, error_message: Optional[str] = None):
        """
        Complete the current execution run.

        Args:
            success: Whether execution completed successfully
            error_message: Error message if execution failed
        """
        if self.execution_history:
            current_run = self.execution_history[-1]
            current_run.completed_at = datetime.now()
            current_run.status = "completed" if success else "error"
            if error_message:
                current_run.error_message = error_message

        self.state = SessionState.IDLE if success else SessionState.ERROR
        self.current_flowchart = None

    def halt_execution(self):
        """
        Halt the current execution.

        Note: Does NOT clear halted state - that must be done explicitly
        via clear_halted_state() to preserve resume capability.
        """
        if self.execution_history:
            current_run = self.execution_history[-1]
            current_run.completed_at = datetime.now()
            current_run.status = "halted"

        self.state = SessionState.HALTED
        # Keep current_flowchart for resume - don't clear it

    def clear_halted_state(self):
        """Clear halted execution state (called after resume or when discarding halted execution)."""
        self.halted_command = None
        self.halted_context = None
        self.halted_flowchart = None
        self.current_flowchart = None

    def __repr__(self) -> str:
        """String representation of session."""
        return f"Session(name='{self.name}', state={self.state}, dir='{self.working_directory}')"
