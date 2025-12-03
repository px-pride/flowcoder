"""
Command Model for FlowCoder

Represents a named command with its flowchart and metadata.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict
import uuid
import copy
import shlex
from .flowchart import Flowchart
from .command_argument import CommandArgument


@dataclass
class CommandMetadata:
    """Metadata about a command."""
    created: datetime
    modified: datetime
    version: str = "1.0"
    author: Optional[str] = None
    tags: list = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "created": self.created.isoformat(),
            "modified": self.modified.isoformat(),
            "version": self.version,
            "author": self.author,
            "tags": self.tags
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'CommandMetadata':
        """Create from dictionary."""
        return cls(
            created=datetime.fromisoformat(data["created"]),
            modified=datetime.fromisoformat(data["modified"]),
            version=data.get("version", "1.0"),
            author=data.get("author"),
            tags=data.get("tags", [])
        )


@dataclass
class Command:
    """A named command containing a flowchart."""
    id: str
    name: str
    description: str
    flowchart: Flowchart
    metadata: CommandMetadata
    arguments: List[CommandArgument] = field(default_factory=list)

    def __post_init__(self):
        """Validate command after initialization."""
        if not self.id:
            self.id = str(uuid.uuid4())
        if not self.name:
            raise ValueError("Command name is required")
        if not self.flowchart:
            self.flowchart = Flowchart()
        if not self.metadata:
            now = datetime.now()
            self.metadata = CommandMetadata(created=now, modified=now)

    def update_modified(self) -> None:
        """Update the modified timestamp."""
        self.metadata.modified = datetime.now()

    def create_execution_copy(self) -> Flowchart:
        """
        Create a deep copy of the flowchart for execution.

        This allows the execution controller to modify the flowchart copy
        (for highlighting, state updates, etc.) without affecting the
        original flowchart in the Commands tab.

        Returns:
            Deep copy of the command's flowchart
        """
        return copy.deepcopy(self.flowchart)

    def parse_arguments(self, arg_string: str) -> Dict[str, str]:
        """
        Parse command-line style arguments and map to positional variables.

        Uses shell-style parsing with shlex to support quoted strings.
        Maps arguments to $1, $2, $3, etc. positional variables.

        Like bash, accepts indefinite arguments - any extra arguments beyond
        those defined in self.arguments are still available as $N variables.

        Args:
            arg_string: Space-separated argument string (may contain quotes)

        Returns:
            Dictionary mapping positional variables ($1, $2, etc.) to values.
            Also includes named keys for defined arguments.

        Raises:
            ValueError: If required arguments are missing or parsing fails

        Examples:
            >>> cmd.arguments = [
            ...     CommandArgument("file", required=True),
            ...     CommandArgument("mode", required=False, default="strict")
            ... ]
            >>> cmd.parse_arguments("utils.py verbose")
            {'$1': 'utils.py', 'file': 'utils.py', '$2': 'verbose', 'mode': 'verbose'}
            >>> cmd.parse_arguments("utils.py")
            {'$1': 'utils.py', 'file': 'utils.py', '$2': 'strict', 'mode': 'strict'}
            >>> cmd.arguments = []  # No defined arguments
            >>> cmd.parse_arguments("arg1 arg2 arg3")
            {'$1': 'arg1', '$2': 'arg2', '$3': 'arg3'}  # All available as $N
        """
        # Parse argument string using shell-style parsing
        try:
            parsed_args = shlex.split(arg_string) if arg_string.strip() else []
        except ValueError as e:
            raise ValueError(f"Failed to parse arguments: {e}")

        # Create result dictionary
        result = {}

        # Map parsed arguments to defined arguments (if any)
        for i, arg_def in enumerate(self.arguments):
            position = i + 1
            positional_key = f"${position}"

            if i < len(parsed_args):
                # Use provided argument
                value = parsed_args[i]
            elif arg_def.default is not None:
                # Use default value
                value = arg_def.default
            elif arg_def.required:
                # Missing required argument
                raise ValueError(
                    f"Missing required argument: {arg_def.name} (position {position})"
                )
            else:
                # Optional argument with no default - skip
                continue

            # Add to result with both positional and named keys
            result[positional_key] = value
            result[arg_def.name] = value

        # Add any extra arguments as positional variables (bash-like behavior)
        # This allows commands to accept indefinite arguments
        for i in range(len(self.arguments), len(parsed_args)):
            position = i + 1
            positional_key = f"${position}"
            result[positional_key] = parsed_args[i]

        return result

    def validate(self) -> 'ValidationResult':
        """Validate the command's flowchart."""
        from .flowchart import ValidationResult

        # First validate the flowchart
        result = self.flowchart.validate()

        # Add command-level validations
        errors = list(result.errors)
        warnings = list(result.warnings)

        # Check name
        if not self.name.strip():
            errors.append("Command name cannot be empty")

        # Check name format (for slash commands)
        if not self.name.replace("-", "").replace("_", "").isalnum():
            warnings.append(
                "Command name should only contain letters, numbers, hyphens, and underscores"
            )

        if " " in self.name:
            errors.append("Command name cannot contain spaces (use hyphens or underscores)")

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "flowchart": self.flowchart.to_dict(),
            "metadata": self.metadata.to_dict(),
            "arguments": [arg.to_dict() for arg in self.arguments]
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Command':
        """Create Command from dictionary."""
        arguments = [
            CommandArgument.from_dict(arg_data)
            for arg_data in data.get("arguments", [])
        ]
        return cls(
            id=data["id"],
            name=data["name"],
            description=data.get("description", ""),
            flowchart=Flowchart.from_dict(data["flowchart"]),
            metadata=CommandMetadata.from_dict(data["metadata"]),
            arguments=arguments
        )

    def __repr__(self) -> str:
        """String representation."""
        return f"Command(name='{self.name}', blocks={len(self.flowchart.blocks)})"
