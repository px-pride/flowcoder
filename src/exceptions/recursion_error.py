"""
Recursion Error Exception

Custom exception for command recursion detection with detailed error reporting.
"""

from typing import List


class CommandRecursionError(Exception):
    """
    Raised when command recursion is detected.

    Provides detailed information about the recursion cycle, including
    the full call stack and a clear error message for debugging.

    Attributes:
        command_name: Name of the command that caused recursion
        call_stack: Full call stack showing the recursion cycle
    """

    def __init__(self, command_name: str, call_stack: List[str]):
        """
        Initialize CommandRecursionError.

        Args:
            command_name: Name of the command that caused recursion
            call_stack: List of command names in the execution chain
        """
        self.command_name = command_name
        self.call_stack = call_stack

        # Build detailed error message
        message = self._build_error_message()
        super().__init__(message)

    def _build_error_message(self) -> str:
        """
        Build detailed error message showing recursion cycle.

        Returns:
            Multi-line error message with call stack visualization
        """
        # Find where recursion starts (first occurrence of the command)
        first_occurrence = self.call_stack.index(self.command_name)
        recursive_cycle = self.call_stack[first_occurrence:]

        # Build message lines
        lines = [
            f"Recursive command invocation detected: {self.command_name}",
            "",
            "Call stack:",
        ]

        # Show full call stack with indentation and markers
        for i, cmd in enumerate(self.call_stack):
            indent = "  " * i
            marker = "⚠️  " if cmd == self.command_name else ""
            lines.append(f"{indent}{marker}{cmd}")

        lines.append("")
        lines.append(
            f"Recursive cycle: {' → '.join(recursive_cycle)}"
        )
        lines.append("")
        lines.append(
            "To fix this: Remove the recursive command block, "
            "or restructure your commands to avoid circular dependencies."
        )

        return "\n".join(lines)

    def get_recursive_cycle(self) -> List[str]:
        """
        Get the commands involved in the recursion cycle.

        Returns:
            List of command names forming the recursive cycle
        """
        first_occurrence = self.call_stack.index(self.command_name)
        return self.call_stack[first_occurrence:]

    def __str__(self) -> str:
        """Return the detailed error message."""
        return self._build_error_message()

    def __repr__(self) -> str:
        """Return a concise representation."""
        return (
            f"CommandRecursionError(command_name={self.command_name!r}, "
            f"call_stack={self.call_stack!r})"
        )
