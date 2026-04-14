"""
Block Models for FlowCoder

Defines all block types used in flowcharts:
- Block (base class)
- StartBlock
- PromptBlock
- BranchBlock
- EndBlock / ExitBlock
- VariableBlock
- BashBlock
- CommandBlock
- RefreshBlock
- SpawnBlock
- WaitBlock
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from enum import Enum
import uuid


class BlockType(str, Enum):
    """Enumeration of block types."""
    START = "start"
    PROMPT = "prompt"
    BRANCH = "branch"
    END = "end"
    COMMAND = "command"  # Invokes other commands
    VARIABLE = "variable"  # Sets a variable to a value
    BASH = "bash"  # Executes bash commands
    REFRESH = "refresh"  # Refreshes the agent session
    SPAWN = "spawn"  # Spawns an agent sub-session
    WAIT = "wait"  # Waits for spawned agent sessions
    EXIT = "exit"  # Exits flowchart with exit code


@dataclass
class VariableEntry:
    """A single variable entry for multi-entry VariableBlock."""
    variable_name: str
    variable_value: str
    variable_type: str = "string"  # string, int, float, boolean

    def to_dict(self) -> dict:
        return {
            "variable_name": self.variable_name,
            "variable_value": self.variable_value,
            "variable_type": self.variable_type,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'VariableEntry':
        return cls(
            variable_name=data["variable_name"],
            variable_value=data.get("variable_value", ""),
            variable_type=data.get("variable_type", "string"),
        )


@dataclass
class WaitEntry:
    """A single entry for WaitBlock — identifies an agent to wait on."""
    agent_name: str
    kill_session: bool = False

    def to_dict(self) -> dict:
        return {
            "agent_name": self.agent_name,
            "kill_session": self.kill_session,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'WaitEntry':
        return cls(
            agent_name=data["agent_name"],
            kill_session=data.get("kill_session", False),
        )


@dataclass
class Position:
    """Position of a block on the canvas."""
    x: float
    y: float

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {"x": self.x, "y": self.y}

    @classmethod
    def from_dict(cls, data: dict) -> 'Position':
        """Create from dictionary."""
        return cls(x=data["x"], y=data["y"])


@dataclass
class BranchCondition:
    """A single branch condition with its target."""
    condition: str  # e.g., "hasErrors == true"
    target_block_id: str
    label: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "condition": self.condition,
            "target_block_id": self.target_block_id,
            "label": self.label
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'BranchCondition':
        """Create from dictionary."""
        return cls(
            condition=data["condition"],
            target_block_id=data["target_block_id"],
            label=data.get("label")
        )


@dataclass
class Block:
    """Base class for all block types."""
    id: str
    type: BlockType
    name: str
    position: Position

    def __post_init__(self):
        """Validate block after initialization."""
        if not self.id:
            self.id = str(uuid.uuid4())
        if not self.name:
            self.name = f"{self.type.value.capitalize()} Block"

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "type": self.type.value,
            "name": self.name,
            "position": self.position.to_dict()
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Block':
        """Create block from dictionary.

        This is overridden in subclasses to handle type-specific fields.
        """
        block_type = BlockType(data["type"])
        position = Position.from_dict(data["position"])

        # Route to appropriate subclass
        if block_type == BlockType.START:
            return StartBlock.from_dict(data)
        elif block_type == BlockType.PROMPT:
            return PromptBlock.from_dict(data)
        elif block_type == BlockType.BRANCH:
            return BranchBlock.from_dict(data)
        elif block_type == BlockType.END:
            return EndBlock.from_dict(data)
        elif block_type == BlockType.VARIABLE:
            return VariableBlock.from_dict(data)
        elif block_type == BlockType.BASH:
            return BashBlock.from_dict(data)
        elif block_type == BlockType.COMMAND:
            return CommandBlock.from_dict(data)
        elif block_type == BlockType.REFRESH:
            return RefreshBlock.from_dict(data)
        elif block_type == BlockType.EXIT:
            return ExitBlock.from_dict(data)
        elif block_type == BlockType.SPAWN:
            return SpawnBlock.from_dict(data)
        elif block_type == BlockType.WAIT:
            return WaitBlock.from_dict(data)
        else:
            raise ValueError(f"Unknown block type: {block_type}")


@dataclass
class StartBlock(Block):
    """Start block - entry point of the flowchart."""

    def __init__(self, id: str = "", name: str = "Start", position: Position = None):
        if position is None:
            position = Position(100, 50)
        super().__init__(
            id=id or str(uuid.uuid4()),
            type=BlockType.START,
            name=name,
            position=position
        )

    @classmethod
    def from_dict(cls, data: dict) -> 'StartBlock':
        """Create StartBlock from dictionary."""
        return cls(
            id=data["id"],
            name=data["name"],
            position=Position.from_dict(data["position"])
        )


@dataclass
class PromptBlock(Block):
    """Prompt block - executes a prompt with Claude."""
    prompt: str = ""
    output_schema: Optional[Dict[str, Any]] = None
    sound_effect: Optional[str] = None
    disable_auto_git: bool = False
    git_tag: Optional[str] = None

    def __init__(
        self,
        id: str = "",
        name: str = "Prompt",
        position: Position = None,
        prompt: str = "",
        output_schema: Optional[Dict[str, Any]] = None,
        sound_effect: Optional[str] = None,
        disable_auto_git: bool = False,
        git_tag: Optional[str] = None,
    ):
        if position is None:
            position = Position(100, 150)
        super().__init__(
            id=id or str(uuid.uuid4()),
            type=BlockType.PROMPT,
            name=name,
            position=position
        )
        self.prompt = prompt
        self.output_schema = output_schema
        self.sound_effect = sound_effect
        self.disable_auto_git = disable_auto_git
        self.git_tag = git_tag

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        data = super().to_dict()
        data.update({
            "prompt": self.prompt,
            "output_schema": self.output_schema,
            "sound_effect": self.sound_effect,
            "disable_auto_git": self.disable_auto_git,
            "git_tag": self.git_tag,
        })
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'PromptBlock':
        """Create PromptBlock from dictionary."""
        return cls(
            id=data["id"],
            name=data["name"],
            position=Position.from_dict(data["position"]),
            prompt=data.get("prompt", ""),
            output_schema=data.get("output_schema"),
            sound_effect=data.get("sound_effect"),
            disable_auto_git=data.get("disable_auto_git", False),
            git_tag=data.get("git_tag"),
        )


@dataclass
class BranchBlock(Block):
    """Branch block - makes decisions based on previous output.

    Evaluates a condition and routes to:
    - True path: connection with label="True" (exits bottom, black arrow)
    - False path: connection with label="False" (exits right, blue arrow)
    """
    condition: str = ""  # e.g., "count > 5" or "status == 'success'"

    def __init__(
        self,
        id: str = "",
        name: str = "Branch",
        position: Position = None,
        condition: str = ""
    ):
        if position is None:
            position = Position(100, 250)
        super().__init__(
            id=id or str(uuid.uuid4()),
            type=BlockType.BRANCH,
            name=name,
            position=position
        )
        self.condition = condition

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        data = super().to_dict()
        data.update({
            "condition": self.condition
        })
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'BranchBlock':
        """Create BranchBlock from dictionary."""
        return cls(
            id=data["id"],
            name=data["name"],
            position=Position.from_dict(data["position"]),
            condition=data.get("condition", "")
        )


@dataclass
class EndBlock(Block):
    """End block - marks successful completion."""

    def __init__(self, id: str = "", name: str = "End", position: Position = None):
        if position is None:
            position = Position(100, 350)
        super().__init__(
            id=id or str(uuid.uuid4()),
            type=BlockType.END,
            name=name,
            position=position
        )

    @classmethod
    def from_dict(cls, data: dict) -> 'EndBlock':
        """Create EndBlock from dictionary."""
        return cls(
            id=data["id"],
            name=data["name"],
            position=Position.from_dict(data["position"])
        )


@dataclass
class VariableBlock(Block):
    """Variable block - sets a variable to a value with explicit type.

    This allows explicit variable initialization and manipulation.
    Both variable_name and variable_value support variable substitution.
    """
    variable_name: str = ""  # Name of the variable to set
    variable_value: str = ""  # Value to assign (supports variable substitution)
    variable_type: str = "string"  # Type of the variable (string, int, float, boolean)

    def __init__(
        self,
        id: str = "",
        name: str = "Variable",
        position: Position = None,
        variable_name: str = "",
        variable_value: str = "",
        variable_type: str = "string"
    ):
        if position is None:
            position = Position(100, 250)
        super().__init__(
            id=id or str(uuid.uuid4()),
            type=BlockType.VARIABLE,
            name=name,
            position=position
        )
        self.variable_name = variable_name
        self.variable_value = variable_value
        self.variable_type = variable_type

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        data = super().to_dict()
        data.update({
            "variable_name": self.variable_name,
            "variable_value": self.variable_value,
            "variable_type": self.variable_type
        })
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'VariableBlock':
        """Create VariableBlock from dictionary."""
        return cls(
            id=data["id"],
            name=data.get("name", "Variable"),
            position=Position.from_dict(data["position"]),
            variable_name=data.get("variable_name", ""),
            variable_value=data.get("variable_value", ""),
            variable_type=data.get("variable_type", "string")
        )

    def validate(self) -> List[str]:
        """Validate block configuration."""
        errors = []

        if not self.variable_name:
            errors.append("Variable name is required")
        elif not self.variable_name.replace("_", "").isalnum():
            errors.append("Variable name must be alphanumeric (underscores allowed)")

        return errors


@dataclass
class BashBlock(Block):
    """Bash block - executes bash commands.

    This allows executing system commands, running scripts, and
    interacting with the filesystem. Output can be captured and
    stored in variables.
    """
    command: str = ""  # Bash command to execute (supports variable substitution)
    capture_output: bool = True  # Whether to capture stdout/stderr
    output_variable: str = ""  # Optional variable name to store output
    output_type: str = "string"  # Type for output variable (string, int, float, boolean)
    working_directory: str = ""  # Optional override for working directory
    continue_on_error: bool = False  # Continue workflow even if command fails
    exit_code_variable: str = ""  # Optional variable name to store exit code
    disable_auto_git: bool = False  # Skip auto-git for this block
    git_tag: Optional[str] = None  # Optional git tag after execution

    def __init__(
        self,
        id: str = "",
        name: str = "Bash",
        position: Position = None,
        command: str = "",
        capture_output: bool = True,
        output_variable: str = "",
        output_type: str = "string",
        working_directory: str = "",
        continue_on_error: bool = False,
        exit_code_variable: str = "",
        disable_auto_git: bool = False,
        git_tag: Optional[str] = None,
    ):
        if position is None:
            position = Position(100, 250)
        super().__init__(
            id=id or str(uuid.uuid4()),
            type=BlockType.BASH,
            name=name,
            position=position
        )
        self.command = command
        self.capture_output = capture_output
        self.output_variable = output_variable
        self.output_type = output_type
        self.working_directory = working_directory
        self.continue_on_error = continue_on_error
        self.exit_code_variable = exit_code_variable
        self.disable_auto_git = disable_auto_git
        self.git_tag = git_tag

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        data = super().to_dict()
        data.update({
            "command": self.command,
            "capture_output": self.capture_output,
            "output_variable": self.output_variable,
            "output_type": self.output_type,
            "working_directory": self.working_directory,
            "continue_on_error": self.continue_on_error,
            "exit_code_variable": self.exit_code_variable,
            "disable_auto_git": self.disable_auto_git,
            "git_tag": self.git_tag,
        })
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'BashBlock':
        """Create BashBlock from dictionary."""
        return cls(
            id=data["id"],
            name=data.get("name", "Bash"),
            position=Position.from_dict(data["position"]),
            command=data.get("command", ""),
            capture_output=data.get("capture_output", True),
            output_variable=data.get("output_variable", ""),
            output_type=data.get("output_type", "string"),
            working_directory=data.get("working_directory", ""),
            continue_on_error=data.get("continue_on_error", False),
            exit_code_variable=data.get("exit_code_variable", ""),
            disable_auto_git=data.get("disable_auto_git", False),
            git_tag=data.get("git_tag"),
        )

    def validate(self) -> List[str]:
        """Validate block configuration."""
        errors = []

        if not self.command or not self.command.strip():
            errors.append("Bash command is required")

        # Validate output variable name if specified
        if self.output_variable and not self.output_variable.replace("_", "").isalnum():
            errors.append("Output variable name must be alphanumeric (underscores allowed)")

        # Validate exit code variable name if specified
        if self.exit_code_variable and not self.exit_code_variable.replace("_", "").isalnum():
            errors.append("Exit code variable name must be alphanumeric (underscores allowed)")

        # Validate output type
        if self.output_type not in ["string", "int", "float", "boolean"]:
            errors.append(f"Invalid output type: {self.output_type}")

        return errors


@dataclass
class CommandBlock(Block):
    """Command block - invokes another command.

    This allows commands to call other commands, enabling
    composition and reusability.

    The command_name field supports variable substitution ({{varname}}, $N),
    enabling dynamic dispatch — the command to invoke can be determined
    at runtime from execution context variables.
    """
    command_name: str = ""  # Name of command to execute (supports {{varname}} and $N)
    arguments: str = ""  # Arguments to pass (may contain variables)
    inherit_variables: bool = False  # Pass parent variables to child
    merge_output: bool = False  # Merge child output into parent scope
    exit_code_variable: str = ""  # Variable to store child exit code
    suppress_child_auto_git: bool = False  # Suppress auto-git in child flowchart
    git_tag: Optional[str] = None  # Optional git tag after execution

    def __init__(
        self,
        id: str = "",
        name: str = "Command",
        position: Position = None,
        command_name: str = "",
        arguments: str = "",
        inherit_variables: bool = False,
        merge_output: bool = False,
        exit_code_variable: str = "",
        suppress_child_auto_git: bool = False,
        git_tag: Optional[str] = None,
    ):
        if position is None:
            position = Position(100, 250)
        super().__init__(
            id=id or str(uuid.uuid4()),
            type=BlockType.COMMAND,
            name=name,
            position=position
        )
        self.command_name = command_name
        self.arguments = arguments
        self.inherit_variables = inherit_variables
        self.merge_output = merge_output
        self.exit_code_variable = exit_code_variable
        self.suppress_child_auto_git = suppress_child_auto_git
        self.git_tag = git_tag

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        data = super().to_dict()
        data.update({
            "command_name": self.command_name,
            "arguments": self.arguments,
            "inherit_variables": self.inherit_variables,
            "merge_output": self.merge_output,
            "exit_code_variable": self.exit_code_variable,
            "suppress_child_auto_git": self.suppress_child_auto_git,
            "git_tag": self.git_tag,
        })
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'CommandBlock':
        """Create CommandBlock from dictionary."""
        return cls(
            id=data["id"],
            name=data.get("name", "Command"),
            position=Position.from_dict(data["position"]),
            command_name=data.get("command_name", ""),
            arguments=data.get("arguments", ""),
            inherit_variables=data.get("inherit_variables", False),
            merge_output=data.get("merge_output", False),
            exit_code_variable=data.get("exit_code_variable", ""),
            suppress_child_auto_git=data.get("suppress_child_auto_git", False),
            git_tag=data.get("git_tag"),
        )

    def validate(self) -> List[str]:
        """Validate block configuration."""
        errors = []

        if not self.command_name:
            errors.append("Command name is required")

        # Note: Circular dependency check is done at flowchart level
        # (requires access to all commands)

        return errors


@dataclass
class RefreshBlock(Block):
    """Refresh block - triggers an agent refresh equivalent to the manual button."""

    def __init__(
        self,
        id: str = "",
        name: str = "Refresh",
        position: Position = None
    ):
        if position is None:
            position = Position(100, 250)
        super().__init__(
            id=id or str(uuid.uuid4()),
            type=BlockType.REFRESH,
            name=name,
            position=position
        )

    @classmethod
    def from_dict(cls, data: dict) -> 'RefreshBlock':
        """Create RefreshBlock from dictionary."""
        return cls(
            id=data["id"],
            name=data.get("name", "Refresh"),
            position=Position.from_dict(data["position"])
        )


@dataclass
class ExitBlock(Block):
    """Exit block - exits flowchart with an exit code.

    Unlike EndBlock (which simply marks completion), ExitBlock terminates
    the flowchart with a specific exit code and optionally tags the git state.
    This recursively kills all spawned agent sub-sessions.
    """
    exit_code: int = 0
    git_tag: Optional[str] = None

    def __init__(
        self,
        id: str = "",
        name: str = "Exit",
        position: Position = None,
        exit_code: int = 0,
        git_tag: Optional[str] = None,
    ):
        if position is None:
            position = Position(100, 350)
        super().__init__(
            id=id or str(uuid.uuid4()),
            type=BlockType.EXIT,
            name=name,
            position=position
        )
        self.exit_code = exit_code
        self.git_tag = git_tag

    def to_dict(self) -> dict:
        data = super().to_dict()
        data.update({
            "exit_code": self.exit_code,
            "git_tag": self.git_tag,
        })
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'ExitBlock':
        return cls(
            id=data["id"],
            name=data.get("name", "Exit"),
            position=Position.from_dict(data["position"]),
            exit_code=data.get("exit_code", 0),
            git_tag=data.get("git_tag"),
        )

    def validate(self) -> List[str]:
        errors = []
        if not isinstance(self.exit_code, int):
            errors.append("Exit code must be an integer")
        return errors


@dataclass
class SpawnBlock(Block):
    """Spawn block - spawns an agent sub-session running a command.

    Creates a new agent session in its own thread that executes
    the specified slash command. Throws an error if an agent
    sub-session with the same name is already executing.
    """
    agent_name: str = ""
    command_name: str = ""
    arguments: str = ""
    inherit_variables: bool = False
    exit_code_variable: str = ""
    config_file: str = ""  # .claudeconfig or .codexconfig to use

    def __init__(
        self,
        id: str = "",
        name: str = "Spawn",
        position: Position = None,
        agent_name: str = "",
        command_name: str = "",
        arguments: str = "",
        inherit_variables: bool = False,
        exit_code_variable: str = "",
        config_file: str = "",
    ):
        if position is None:
            position = Position(100, 250)
        super().__init__(
            id=id or str(uuid.uuid4()),
            type=BlockType.SPAWN,
            name=name,
            position=position
        )
        self.agent_name = agent_name
        self.command_name = command_name
        self.arguments = arguments
        self.inherit_variables = inherit_variables
        self.exit_code_variable = exit_code_variable
        self.config_file = config_file

    def to_dict(self) -> dict:
        data = super().to_dict()
        data.update({
            "agent_name": self.agent_name,
            "command_name": self.command_name,
            "arguments": self.arguments,
            "inherit_variables": self.inherit_variables,
            "exit_code_variable": self.exit_code_variable,
            "config_file": self.config_file,
        })
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'SpawnBlock':
        return cls(
            id=data["id"],
            name=data.get("name", "Spawn"),
            position=Position.from_dict(data["position"]),
            agent_name=data.get("agent_name", ""),
            command_name=data.get("command_name", ""),
            arguments=data.get("arguments", ""),
            inherit_variables=data.get("inherit_variables", False),
            exit_code_variable=data.get("exit_code_variable", ""),
            config_file=data.get("config_file", ""),
        )

    def validate(self) -> List[str]:
        errors = []
        if not self.agent_name:
            errors.append("Agent name is required")
        if not self.command_name:
            errors.append("Command name is required")
        return errors


@dataclass
class WaitBlock(Block):
    """Wait block - waits for spawned agent sessions to complete.

    For each agent session, merges variables into the main session's
    scope with "{agent_name}." prefix. Optionally kills the sessions.
    """
    entries: List[WaitEntry] = field(default_factory=list)

    def __init__(
        self,
        id: str = "",
        name: str = "Wait",
        position: Position = None,
        entries: Optional[List[WaitEntry]] = None,
    ):
        if position is None:
            position = Position(100, 250)
        super().__init__(
            id=id or str(uuid.uuid4()),
            type=BlockType.WAIT,
            name=name,
            position=position
        )
        self.entries = entries if entries is not None else []

    def to_dict(self) -> dict:
        data = super().to_dict()
        data.update({
            "entries": [e.to_dict() for e in self.entries],
        })
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'WaitBlock':
        entries = [WaitEntry.from_dict(e) for e in data.get("entries", [])]
        return cls(
            id=data["id"],
            name=data.get("name", "Wait"),
            position=Position.from_dict(data["position"]),
            entries=entries,
        )

    def validate(self) -> List[str]:
        errors = []
        if not self.entries:
            errors.append("At least one wait entry is required")
        for i, entry in enumerate(self.entries):
            if not entry.agent_name:
                errors.append(f"Entry {i+1}: agent name is required")
        return errors


# Factory function for creating blocks
def create_block(block_type: BlockType, **kwargs) -> Block:
    """Factory function to create blocks of the appropriate type."""
    if block_type == BlockType.START:
        return StartBlock(**kwargs)
    elif block_type == BlockType.PROMPT:
        return PromptBlock(**kwargs)
    elif block_type == BlockType.BRANCH:
        return BranchBlock(**kwargs)
    elif block_type == BlockType.END:
        return EndBlock(**kwargs)
    elif block_type == BlockType.VARIABLE:
        return VariableBlock(**kwargs)
    elif block_type == BlockType.BASH:
        return BashBlock(**kwargs)
    elif block_type == BlockType.COMMAND:
        return CommandBlock(**kwargs)
    elif block_type == BlockType.REFRESH:
        return RefreshBlock(**kwargs)
    elif block_type == BlockType.EXIT:
        return ExitBlock(**kwargs)
    elif block_type == BlockType.SPAWN:
        return SpawnBlock(**kwargs)
    elif block_type == BlockType.WAIT:
        return WaitBlock(**kwargs)
    else:
        raise ValueError(f"Unknown block type: {block_type}")
