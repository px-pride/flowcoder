"""
Command Block Executor for FlowCoder

Executes command blocks (commands that invoke other commands).
Handles variable substitution, inheritance, and output merging.
"""

import logging
from typing import Dict, Any, Optional, TYPE_CHECKING
from datetime import datetime

from src.models.blocks import CommandBlock
from src.models.command import Command
from src.models.execution import ExecutionContext, ExecutionStatus
from src.services import StorageService
from src.utils.variable_substitution import VariableSubstitution
from src.exceptions import CommandRecursionError

# Avoid circular imports
if TYPE_CHECKING:
    from src.controllers.execution_controller import ExecutionController

logger = logging.getLogger(__name__)


class CommandBlockExecutorError(Exception):
    """Base exception for command block executor errors."""
    pass


class CommandNotFoundError(CommandBlockExecutorError):
    """Raised when target command is not found."""
    pass


class MaxRecursionDepthError(CommandBlockExecutorError):
    """Raised when maximum recursion depth is exceeded."""
    pass


class CommandBlockExecutor:
    """
    Executes command blocks (commands that invoke other commands).

    Handles:
    - Loading target command
    - Creating child execution context
    - Variable inheritance and scoping
    - Output merging back to parent
    """

    def __init__(
        self,
        storage_service: StorageService,
        execution_controller: 'ExecutionController'
    ):
        """
        Initialize command block executor.

        Args:
            storage_service: Storage service for loading commands
            execution_controller: Execution controller for running child commands
        """
        self.storage_service = storage_service
        self.execution_controller = execution_controller

    async def execute_command_block(
        self,
        block: CommandBlock,
        parent_context: ExecutionContext
    ) -> Dict[str, Any]:
        """
        Execute a command block.

        Args:
            block: The command block to execute
            parent_context: Parent execution context

        Returns:
            Dictionary of output variables from child execution

        Raises:
            CommandNotFoundError: If command not found
            MaxRecursionDepthError: If recursion depth exceeded
            CommandBlockExecutorError: If child execution fails
        """
        logger.info(
            f"Executing command block: {block.command_name} "
            f"(depth={parent_context.depth}, stack={parent_context.get_call_chain()})"
        )

        # Check recursion depth
        if not parent_context.can_nest_deeper():
            raise MaxRecursionDepthError(
                f"Maximum recursion depth ({parent_context.max_depth}) exceeded.\n"
                f"Call stack: {parent_context.get_call_chain()}\n"
                f"Cannot execute command: {block.command_name}"
            )

        # Load target command
        command = self._load_command(block.command_name)
        if not command:
            raise CommandNotFoundError(
                f"Command not found: {block.command_name}. "
                f"Ensure the command exists before invoking it."
            )

        # Check for recursion (Phase 5.6)
        try:
            parent_context.push_call_stack(command.name)
        except CommandRecursionError as e:
            logger.error(f"Recursion detected: {e}")
            raise

        # Substitute variables in arguments string
        substituted_args = self._substitute_arguments(
            block.arguments,
            parent_context
        )

        # Parse arguments for child command
        child_arguments = command.parse_arguments(substituted_args)

        # Create child execution context
        child_context = self._create_child_context(
            command=command,
            parent_context=parent_context,
            arguments=child_arguments,
            inherit_variables=block.inherit_variables
        )

        # Execute child command with the child context
        try:
            result_context = await self.execution_controller.execute(
                command=command,
                flowchart=None,  # Use command's flowchart
                context=child_context  # Pass our child context
            )
            # Update child_context reference to the returned context
            # (they should be the same object, but just to be safe)
            child_context = result_context
        except Exception as e:
            logger.error(
                f"Error executing command block {block.command_name}: {e}"
            )
            # Remove from call stack before re-raising (Phase 5.6)
            parent_context.pop_call_stack()
            raise CommandBlockExecutorError(
                f"Failed to execute command {block.command_name}: {e}"
            ) from e

        # Remove from call stack after successful execution (Phase 5.6)
        parent_context.pop_call_stack()

        # Merge child outputs into parent context
        if block.merge_output:
            self._merge_outputs(
                parent_context=parent_context,
                child_context=child_context
            )
            logger.info(
                f"Merged {len(child_context.variables)} variables "
                f"from child to parent"
            )

        # Return child outputs
        return child_context.variables

    def _load_command(self, command_name: str) -> Optional[Command]:
        """
        Load command by name.

        Args:
            command_name: Name of command to load (with or without leading /)

        Returns:
            Command object, or None if not found
        """
        # Strip leading slash if present
        name = command_name.lstrip('/')

        try:
            command = self.storage_service.load_command(name)
            logger.debug(f"Loaded command: {name}")
            return command
        except Exception as e:
            logger.warning(f"Command not found: {name} - {e}")
            return None

    def _substitute_arguments(
        self,
        arguments: str,
        context: ExecutionContext
    ) -> str:
        """
        Substitute variables in arguments string.

        Args:
            arguments: Raw arguments string (may contain $1, {{varname}}, etc.)
            context: Current execution context

        Returns:
            Arguments string with variables substituted

        Example:
            Input: "$1 --severity={{severity}}"
            Context: {"$1": "utils.py", "severity": "high"}
            Output: "utils.py --severity=high"
        """
        if not arguments:
            return ""

        try:
            return VariableSubstitution.substitute_all(
                text=arguments,
                arguments=context.variables,
                variables=context.variables
            )
        except ValueError as e:
            logger.error(f"Error substituting arguments: {e}")
            raise CommandBlockExecutorError(
                f"Cannot execute command block: {e}"
            ) from e

    def _create_child_context(
        self,
        command: Command,
        parent_context: ExecutionContext,
        arguments: Dict[str, str],
        inherit_variables: bool
    ) -> ExecutionContext:
        """
        Create child execution context.

        Args:
            command: Child command being executed
            parent_context: Parent execution context
            arguments: Parsed arguments for child command
            inherit_variables: Whether child inherits parent variables

        Returns:
            New execution context for child command
        """
        now = datetime.now()
        child_context = ExecutionContext(
            command_id=command.id,
            command_name=command.name,
            start_time=now,
            status=ExecutionStatus.RUNNING,
            variables=arguments.copy(),  # Start with arguments
            parent_context=parent_context if inherit_variables else None,
            depth=parent_context.depth + 1,
            max_depth=parent_context.max_depth,
            call_stack=parent_context.call_stack.copy()  # Copy call stack (Phase 5.6)
        )

        logger.debug(
            f"Created child context (depth={child_context.depth}, "
            f"inherit={inherit_variables}, args={len(arguments)})"
        )

        return child_context

    def _merge_outputs(
        self,
        parent_context: ExecutionContext,
        child_context: ExecutionContext
    ):
        """
        Merge child outputs into parent context.

        Args:
            parent_context: Parent execution context (modified in place)
            child_context: Child execution context (read only)

        Notes:
            - Child variables are copied to parent
            - Parent variables are NOT overwritten (child cannot modify parent)
            - Only non-argument variables are merged (skip $1, $2, etc.)
        """
        for key, value in child_context.variables.items():
            # Skip positional arguments (don't merge $1, $2 to parent)
            if key.startswith('$'):
                continue

            # Copy variable to parent scope
            parent_context.variables[key] = value

        logger.debug(
            f"Merged variables from child to parent: "
            f"{[k for k in child_context.variables.keys() if not k.startswith('$')]}"
        )
