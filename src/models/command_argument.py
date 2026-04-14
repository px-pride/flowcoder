"""
Command Argument Model for FlowCoder

Defines command argument metadata for shell-style argument parsing.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class CommandArgument:
    """
    Metadata for a command argument.

    Supports shell-style argument parsing with positional mapping ($1, $2, $3).
    """
    name: str
    description: str = ""
    required: bool = True
    default: Optional[str] = None

    def validate(self) -> list[str]:
        """
        Validate the argument definition.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        if not self.name:
            errors.append("Argument name is required")

        if not self.name.replace("-", "").replace("_", "").isalnum():
            errors.append(
                f"Argument name '{self.name}' should only contain "
                "letters, numbers, hyphens, and underscores"
            )

        if self.required and self.default is not None:
            errors.append(
                f"Argument '{self.name}' cannot be required and have a default value"
            )

        return errors

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "description": self.description,
            "required": self.required,
            "default": self.default
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'CommandArgument':
        """Create CommandArgument from dictionary."""
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            required=data.get("required", True),
            default=data.get("default")
        )

    def __repr__(self) -> str:
        """String representation."""
        req_str = "required" if self.required else "optional"
        default_str = f", default={self.default}" if self.default else ""
        return f"CommandArgument({self.name}, {req_str}{default_str})"
