"""
Command Controller for FlowCoder

Coordinates command operations, validation, and auto-save functionality.
"""

import logging
import re
from typing import Optional, List, Tuple
from datetime import datetime

from src.services import StorageService, StorageError, CommandAlreadyExistsError
from src.models import Command, Flowchart, CommandMetadata


logger = logging.getLogger(__name__)


class CommandControllerError(Exception):
    """Base exception for command controller errors."""
    pass


class InvalidCommandNameError(CommandControllerError):
    """Raised when command name is invalid."""
    pass


class CommandController:
    """
    Controller for managing commands.

    Responsibilities:
    - CRUD operations for commands
    - Command validation (name conflicts, invalid characters)
    - Auto-save functionality
    - Current command tracking
    - Dirty state management (unsaved changes)
    """

    # Valid command name pattern: alphanumeric, hyphens, underscores (no spaces)
    VALID_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+$')
    MIN_NAME_LENGTH = 1
    MAX_NAME_LENGTH = 100

    def __init__(self, storage_service: StorageService):
        """
        Initialize command controller.

        Args:
            storage_service: Storage service for persistence
        """
        self.storage_service = storage_service
        self.current_command: Optional[Command] = None
        self._auto_save_enabled = True
        self._dirty = False  # Tracks unsaved changes to current command

        logger.info("CommandController initialized")

    # ==================== CRUD Operations ====================

    def create_command(self, name: str, description: str = "") -> Command:
        """
        Create a new command with validation.

        Args:
            name: Command name
            description: Optional command description

        Returns:
            The newly created command

        Raises:
            InvalidCommandNameError: If name is invalid
            CommandAlreadyExistsError: If command with name already exists
            StorageError: If storage operation fails
        """
        # Validate name
        is_valid, error_msg = self.validate_command_name(name)
        if not is_valid:
            logger.error(f"Invalid command name: {name} - {error_msg}")
            raise InvalidCommandNameError(error_msg)

        # Check for duplicates
        if self.command_exists(name):
            logger.error(f"Command already exists: {name}")
            raise CommandAlreadyExistsError(f"Command '{name}' already exists")

        # Create command with empty flowchart
        command = Command(
            id="",  # StorageService will generate ID
            name=name,
            description=description,
            flowchart=Flowchart(),
            metadata=CommandMetadata(
                created=datetime.now(),
                modified=datetime.now()
            )
        )

        # Save to storage
        try:
            self.storage_service.save_command(command)
            logger.info(f"Created command: {name}")
            return command
        except Exception as e:
            logger.error(f"Failed to create command '{name}': {e}")
            raise StorageError(f"Failed to create command: {e}") from e

    def load_command(self, name: str) -> Command:
        """
        Load a command by name.

        Args:
            name: Command name

        Returns:
            The loaded command

        Raises:
            StorageError: If command doesn't exist or load fails
        """
        try:
            command = self.storage_service.load_command(name)
            logger.info(f"Loaded command: {name}")
            return command
        except Exception as e:
            logger.error(f"Failed to load command '{name}': {e}")
            raise StorageError(f"Failed to load command: {e}") from e

    def save_command(self, command: Optional[Command] = None) -> None:
        """
        Save a command. Uses current command if none specified.

        Args:
            command: Command to save (defaults to current_command)

        Raises:
            CommandControllerError: If no command to save
            StorageError: If save fails
        """
        cmd_to_save = command if command is not None else self.current_command

        if cmd_to_save is None:
            raise CommandControllerError("No command to save")

        try:
            # Update modified timestamp
            if cmd_to_save.metadata:
                cmd_to_save.metadata.modified = datetime.now()

            self.storage_service.save_command(cmd_to_save)
            logger.info(f"Saved command: {cmd_to_save.name}")

            # Clear dirty flag if saving current command
            if cmd_to_save is self.current_command:
                self._dirty = False

        except Exception as e:
            logger.error(f"Failed to save command '{cmd_to_save.name}': {e}")
            raise StorageError(f"Failed to save command: {e}") from e

    def delete_command(self, name: str) -> None:
        """
        Delete a command by name.

        Args:
            name: Command name

        Raises:
            StorageError: If delete fails
        """
        try:
            self.storage_service.delete_command(name)
            logger.info(f"Deleted command: {name}")

            # Clear current command if it was deleted
            if self.current_command and self.current_command.name == name:
                self.current_command = None
                self._dirty = False

        except Exception as e:
            logger.error(f"Failed to delete command '{name}': {e}")
            raise StorageError(f"Failed to delete command: {e}") from e

    def rename_command(self, old_name: str, new_name: str) -> Command:
        """
        Rename a command and propagate the change to all CommandBlocks.

        This method:
        1. Renames the command itself
        2. Finds all other commands that reference this command via CommandBlocks
        3. Updates those CommandBlocks to use the new name

        Args:
            old_name: Current command name
            new_name: New command name

        Returns:
            The renamed command

        Raises:
            InvalidCommandNameError: If new name is invalid
            CommandAlreadyExistsError: If new name already exists
            StorageError: If rename fails
        """
        # Validate new name
        is_valid, error_msg = self.validate_command_name(new_name)
        if not is_valid:
            logger.error(f"Invalid new command name: {new_name} - {error_msg}")
            raise InvalidCommandNameError(error_msg)

        # Check for duplicates (but allow renaming to same name - no-op)
        if new_name != old_name and self.command_exists(new_name):
            logger.error(f"Command already exists: {new_name}")
            raise CommandAlreadyExistsError(f"Command '{new_name}' already exists")

        # If renaming to same name, just return the command
        if new_name == old_name:
            return self.load_command(old_name)

        try:
            # Load command
            command = self.load_command(old_name)

            # Update name and modified timestamp
            command.name = new_name
            if command.metadata:
                command.metadata.modified = datetime.now()

            # Save with new name
            self.storage_service.save_command(command)

            # Delete old command
            self.storage_service.delete_command(old_name)

            logger.info(f"Renamed command: {old_name} -> {new_name}")

            # Propagate rename to all CommandBlocks in other commands
            self._propagate_command_rename(old_name, new_name)

            # Update current command reference if needed
            if self.current_command and self.current_command.name == old_name:
                self.current_command = command

            return command

        except Exception as e:
            logger.error(f"Failed to rename command '{old_name}' to '{new_name}': {e}")
            raise StorageError(f"Failed to rename command: {e}") from e

    def _propagate_command_rename(self, old_name: str, new_name: str) -> None:
        """
        Propagate command rename to all CommandBlocks that reference it.

        Args:
            old_name: Old command name
            new_name: New command name
        """
        from src.models import CommandBlock

        # Get all commands
        all_commands = self.list_commands()
        commands_updated = 0

        for cmd_meta in all_commands:
            # Skip the renamed command itself
            if cmd_meta['name'] == new_name:
                continue

            try:
                # Load the command
                cmd = self.load_command(cmd_meta['name'])

                # Check if any CommandBlocks reference the old name
                updated = False
                for block in cmd.flowchart.blocks.values():
                    if isinstance(block, CommandBlock) and block.command_name == old_name:
                        block.command_name = new_name
                        updated = True
                        logger.debug(
                            f"Updated CommandBlock in '{cmd.name}' from '{old_name}' to '{new_name}'"
                        )

                # Save the command if it was updated
                if updated:
                    if cmd.metadata:
                        cmd.metadata.modified = datetime.now()
                    self.storage_service.save_command(cmd)
                    commands_updated += 1

            except Exception as e:
                logger.warning(f"Error updating command '{cmd_meta['name']}': {e}")
                # Continue processing other commands even if one fails

        if commands_updated > 0:
            logger.info(
                f"Propagated rename from '{old_name}' to '{new_name}' "
                f"across {commands_updated} command(s)"
            )

    def duplicate_command(self, name: str) -> Command:
        """
        Duplicate an existing command with a new unique name.

        Args:
            name: Name of the command to duplicate

        Returns:
            The newly created duplicate command

        Raises:
            StorageError: If duplication fails
        """
        try:
            # Load the command to duplicate
            original_command = self.load_command(name)

            # Generate a unique name for the duplicate
            base_name = f"copy-of-{name}"
            new_name = base_name
            counter = 1

            # Keep incrementing until we find a unique name
            while self.command_exists(new_name):
                new_name = f"{base_name}-{counter}"
                counter += 1

            # Create a copy of the command
            import copy
            duplicated_command = copy.deepcopy(original_command)

            # Update name and metadata
            duplicated_command.name = new_name
            duplicated_command.id = ""  # Storage service will generate new ID
            if duplicated_command.metadata:
                duplicated_command.metadata.created = datetime.now()
                duplicated_command.metadata.modified = datetime.now()

            # Save the duplicate
            self.storage_service.save_command(duplicated_command)

            logger.info(f"Duplicated command: {name} -> {new_name}")

            return duplicated_command

        except Exception as e:
            logger.error(f"Failed to duplicate command '{name}': {e}")
            raise StorageError(f"Failed to duplicate command: {e}") from e

    # ==================== Validation ====================

    def validate_command_name(self, name: str) -> Tuple[bool, str]:
        """
        Validate a command name.

        Args:
            name: Command name to validate

        Returns:
            Tuple of (is_valid, error_message)
            If valid, error_message is empty string
        """
        # Check empty
        if not name or not name.strip():
            return (False, "Command name cannot be empty")

        # Check length
        if len(name) < self.MIN_NAME_LENGTH:
            return (False, f"Command name must be at least {self.MIN_NAME_LENGTH} character(s)")

        if len(name) > self.MAX_NAME_LENGTH:
            return (False, f"Command name cannot exceed {self.MAX_NAME_LENGTH} characters")

        # Check for spaces
        if ' ' in name:
            return (False, "Command name cannot contain spaces")

        # Check for invalid characters (only allow alphanumeric, hyphens, underscores)
        if not self.VALID_NAME_PATTERN.match(name):
            return (False, "Command name can only contain letters, numbers, hyphens, and underscores")

        return (True, "")

    def command_exists(self, name: str) -> bool:
        """
        Check if a command exists.

        Args:
            name: Command name

        Returns:
            True if command exists, False otherwise
        """
        return self.storage_service.command_exists(name)

    # ==================== Current Command Management ====================

    def set_current_command(self, command: Optional[Command]) -> None:
        """
        Set the current command.

        Args:
            command: Command to set as current (or None to clear)
        """
        # Save current command if dirty and auto-save enabled
        if self._auto_save_enabled and self._dirty and self.current_command:
            try:
                self.auto_save()
            except Exception as e:
                logger.warning(f"Auto-save failed when switching commands: {e}")

        self.current_command = command
        self._dirty = False
        logger.debug(f"Current command set to: {command.name if command else None}")

    def get_current_command(self) -> Optional[Command]:
        """
        Get the current command.

        Returns:
            Current command or None
        """
        return self.current_command

    def mark_dirty(self) -> None:
        """
        Mark current command as modified (has unsaved changes).
        """
        if self.current_command:
            self._dirty = True
            logger.debug(f"Command marked dirty: {self.current_command.name}")

    def is_dirty(self) -> bool:
        """
        Check if current command has unsaved changes.

        Returns:
            True if current command is dirty, False otherwise
        """
        return self._dirty

    # ==================== Auto-Save ====================

    def enable_auto_save(self, enabled: bool) -> None:
        """
        Enable or disable auto-save.

        Args:
            enabled: True to enable, False to disable
        """
        self._auto_save_enabled = enabled
        logger.info(f"Auto-save {'enabled' if enabled else 'disabled'}")

    def auto_save(self) -> None:
        """
        Auto-save current command if dirty.

        Raises:
            CommandControllerError: If no current command
            StorageError: If save fails
        """
        if not self._auto_save_enabled:
            logger.debug("Auto-save disabled, skipping")
            return

        if not self._dirty:
            logger.debug("Current command not dirty, skipping auto-save")
            return

        if not self.current_command:
            raise CommandControllerError("No current command to auto-save")

        logger.info(f"Auto-saving command: {self.current_command.name}")
        self.save_command(self.current_command)

    # ==================== List Operations ====================

    def list_commands(self) -> List[dict]:
        """
        List all commands (metadata only).

        Returns:
            List of command metadata dictionaries
        """
        return self.storage_service.list_commands()

    def get_command_count(self) -> int:
        """
        Get total number of commands.

        Returns:
            Number of commands
        """
        return len(self.list_commands())
