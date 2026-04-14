"""
Command Validator for FlowCoder

Validates command flowcharts, including circular dependency detection.
"""

import re
import logging
from typing import Dict, Optional, Set
from src.models.command import Command
from src.models.flowchart import Flowchart
from src.models.blocks import CommandBlock

logger = logging.getLogger(__name__)

# Patterns that indicate a dynamic command name (resolved at runtime)
_VARIABLE_PATTERN = re.compile(r'\{\{[a-zA-Z_]')
_POSITIONAL_PATTERN = re.compile(r'\$\d')


def _is_dynamic_command_name(name: str) -> bool:
    """Check if a command name contains variable substitution syntax."""
    return bool(_VARIABLE_PATTERN.search(name) or _POSITIONAL_PATTERN.search(name))


class CommandValidator:
    """Validator for command flowcharts."""

    @staticmethod
    def check_circular_dependencies(
        command_name: str,
        flowchart: Flowchart,
        all_commands: Dict[str, Command],
        visited: Optional[Set[str]] = None
    ) -> Optional[str]:
        """
        Check for circular dependencies in command invocations.

        This detects both direct recursion (command calls itself) and
        indirect recursion (command A calls B which calls A).

        Dynamic command names (containing {{varname}} or $N) are skipped
        since they cannot be statically resolved. Runtime protection via
        call_stack and max_depth handles those cases.

        Args:
            command_name: Name of command being checked
            flowchart: Flowchart to check
            all_commands: Dictionary of all available commands
            visited: Set of command names already visited (for recursion detection)

        Returns:
            Error message if circular dependency found, None otherwise

        Examples:
            Direct recursion:
                Command "A" has CommandBlock that calls "A"
                Returns: "Circular dependency detected: A calls itself"

            Indirect recursion:
                Command "A" calls "B", "B" calls "C", "C" calls "A"
                Returns: "A -> B -> C -> Circular dependency detected: A calls itself"

            Dynamic name:
                Command "A" has CommandBlock with command_name "{{tool}}"
                Skipped (cannot resolve statically)
        """
        if visited is None:
            visited = set()

        # Check if we've already visited this command (circular!)
        if command_name in visited:
            return f"Circular dependency detected: {command_name} calls itself"

        # Add current command to visited set
        visited.add(command_name)

        # Check all command blocks in flowchart
        for block in flowchart.blocks.values():
            if isinstance(block, CommandBlock):
                target_command_name = block.command_name

                # Skip dynamic command names — cannot resolve statically
                if _is_dynamic_command_name(target_command_name):
                    logger.debug(
                        f"Skipping circular dependency check for dynamic "
                        f"command name '{target_command_name}' in '{command_name}'"
                    )
                    continue

                # Skip if target command doesn't exist
                # (will be caught by different validation)
                if target_command_name not in all_commands:
                    continue

                # Recursively check target command
                target_command = all_commands[target_command_name]
                error = CommandValidator.check_circular_dependencies(
                    target_command_name,
                    target_command.flowchart,
                    all_commands,
                    visited.copy()  # Copy to avoid polluting parent's visited set
                )

                if error:
                    # Prepend current command to error chain
                    return f"{command_name} -> {error}"

        return None  # No circular dependency found
