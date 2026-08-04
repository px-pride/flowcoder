"""
Storage Service for FlowCoder

Handles persistence of commands to JSON files.
"""

import json
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any

from ..models import Command


logger = logging.getLogger(__name__)


class StorageError(Exception):
    """Base exception for storage operations."""
    pass


class CommandNotFoundError(StorageError):
    """Raised when a command is not found."""
    pass


class CommandAlreadyExistsError(StorageError):
    """Raised when trying to create a command that already exists."""
    pass


class CorruptedCommandError(StorageError):
    """Raised when a command file is corrupted or invalid."""
    pass


class StorageService:
    """Service for saving and loading commands to/from disk."""

    def __init__(self, commands_dir: str = "./commands"):
        """
        Initialize the storage service.

        Args:
            commands_dir: Directory where command files are stored
        """
        self.commands_dir = Path(commands_dir)
        self._ensure_commands_directory()

    def _ensure_commands_directory(self) -> None:
        """Ensure the commands directory exists."""
        try:
            self.commands_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Commands directory ready: {self.commands_dir}")
        except Exception as e:
            logger.error(f"Failed to create commands directory: {e}")
            raise StorageError(f"Could not create commands directory: {e}")

    def _get_command_file_path(self, command_name: str) -> Path:
        """
        Get the file path for a command.

        Args:
            command_name: Name of the command

        Returns:
            Path to the command file
        """
        # Sanitize command name for filename
        safe_name = command_name.replace(" ", "_")
        return self.commands_dir / f"{safe_name}.json"

    def save_command(self, command: Command, overwrite: bool = True) -> None:
        """
        Save a command to disk.

        Args:
            command: Command to save
            overwrite: If False, raises error if command already exists

        Raises:
            CommandAlreadyExistsError: If command exists and overwrite=False
            StorageError: If save operation fails
        """
        file_path = self._get_command_file_path(command.name)

        # Check if already exists
        if file_path.exists() and not overwrite:
            raise CommandAlreadyExistsError(
                f"Command '{command.name}' already exists"
            )

        # Update modified timestamp
        command.update_modified()

        try:
            # Convert to dict
            data = command.to_dict()

            # Write to file with pretty formatting
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            logger.info(f"Saved command '{command.name}' to {file_path}")

        except Exception as e:
            logger.error(f"Failed to save command '{command.name}': {e}")
            raise StorageError(f"Could not save command: {e}")

    def load_command(self, command_name: str) -> Command:
        """
        Load a command from disk.

        Args:
            command_name: Name of the command to load

        Returns:
            Loaded Command object

        Raises:
            CommandNotFoundError: If command file doesn't exist
            CorruptedCommandError: If command file is invalid
            StorageError: If load operation fails
        """
        file_path = self._get_command_file_path(command_name)

        if not file_path.exists():
            raise CommandNotFoundError(
                f"Command '{command_name}' not found"
            )

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            command = Command.from_dict(data)
            logger.info(f"Loaded command '{command_name}' from {file_path}")
            return command

        except json.JSONDecodeError as e:
            logger.error(f"Corrupted command file '{command_name}': {e}")
            raise CorruptedCommandError(
                f"Command file is corrupted: {e}"
            )
        except KeyError as e:
            logger.error(f"Invalid command file '{command_name}': missing {e}")
            raise CorruptedCommandError(
                f"Command file is missing required field: {e}"
            )
        except Exception as e:
            logger.error(f"Failed to load command '{command_name}': {e}")
            raise StorageError(f"Could not load command: {e}")

    def load_command_by_id(self, command_id: str) -> Optional[Command]:
        """
        Load a command by its ID (searches all commands).

        Args:
            command_id: ID of the command to load

        Returns:
            Command if found, None otherwise
        """
        for metadata in self.list_commands():
            if metadata['id'] == command_id:
                return self.load_command(metadata['name'])
        return None

    def delete_command(self, command_name: str) -> None:
        """
        Delete a command from disk.

        Args:
            command_name: Name of the command to delete

        Raises:
            CommandNotFoundError: If command doesn't exist
            StorageError: If delete operation fails
        """
        file_path = self._get_command_file_path(command_name)

        if not file_path.exists():
            raise CommandNotFoundError(
                f"Command '{command_name}' not found"
            )

        try:
            file_path.unlink()
            logger.info(f"Deleted command '{command_name}'")
        except Exception as e:
            logger.error(f"Failed to delete command '{command_name}': {e}")
            raise StorageError(f"Could not delete command: {e}")

    def list_commands(self) -> List[Dict[str, Any]]:
        """
        List all available commands with their metadata.

        Returns:
            List of command metadata dictionaries with keys:
            - id: Command ID
            - name: Command name
            - description: Command description
            - created: Creation timestamp
            - modified: Last modified timestamp
            - block_count: Number of blocks in flowchart
            - file_path: Path to command file

        Raises:
            StorageError: If listing fails
        """
        commands = []

        try:
            # Find all .json files in commands directory
            for file_path in self.commands_dir.glob("*.json"):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)

                    # Extract metadata
                    metadata = {
                        'id': data.get('id', ''),
                        'name': data.get('name', ''),
                        'description': data.get('description', ''),
                        'created': data.get('metadata', {}).get('created', ''),
                        'modified': data.get('metadata', {}).get('modified', ''),
                        'block_count': len(data.get('flowchart', {}).get('blocks', {})),
                        'file_path': str(file_path)
                    }

                    commands.append(metadata)

                except json.JSONDecodeError:
                    logger.warning(f"Skipping corrupted file: {file_path}")
                    continue
                except Exception as e:
                    logger.warning(f"Error reading {file_path}: {e}")
                    continue

            # Sort by modified date (most recent first)
            commands.sort(
                key=lambda x: x['modified'],
                reverse=True
            )

            logger.info(f"Found {len(commands)} commands")
            return commands

        except Exception as e:
            logger.error(f"Failed to list commands: {e}")
            raise StorageError(f"Could not list commands: {e}")

    def command_exists(self, command_name: str) -> bool:
        """
        Check if a command exists.

        Args:
            command_name: Name of the command

        Returns:
            True if command exists, False otherwise
        """
        file_path = self._get_command_file_path(command_name)
        return file_path.exists()

    def get_command_count(self) -> int:
        """
        Get the total number of commands.

        Returns:
            Number of command files
        """
        try:
            return len(list(self.commands_dir.glob("*.json")))
        except Exception:
            return 0

    def export_command(self, command_name: str, export_path: str) -> None:
        """
        Export a command to a specific file path.

        Args:
            command_name: Name of the command to export
            export_path: Path where to export the command

        Raises:
            CommandNotFoundError: If command doesn't exist
            StorageError: If export fails
        """
        command = self.load_command(command_name)

        try:
            export_file = Path(export_path)
            export_file.parent.mkdir(parents=True, exist_ok=True)

            with open(export_file, 'w', encoding='utf-8') as f:
                json.dump(command.to_dict(), f, indent=2, ensure_ascii=False)

            logger.info(f"Exported command '{command_name}' to {export_path}")

        except Exception as e:
            logger.error(f"Failed to export command '{command_name}': {e}")
            raise StorageError(f"Could not export command: {e}")

    def import_command(self, import_path: str, overwrite: bool = False) -> Command:
        """
        Import a command from a file.

        Args:
            import_path: Path to the command file to import
            overwrite: If False, raises error if command already exists

        Returns:
            Imported Command object

        Raises:
            CommandNotFoundError: If import file doesn't exist
            CorruptedCommandError: If import file is invalid
            CommandAlreadyExistsError: If command exists and overwrite=False
            StorageError: If import fails
        """
        import_file = Path(import_path)

        if not import_file.exists():
            raise CommandNotFoundError(
                f"Import file not found: {import_path}"
            )

        try:
            with open(import_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            command = Command.from_dict(data)

            # Check if already exists
            if self.command_exists(command.name) and not overwrite:
                raise CommandAlreadyExistsError(
                    f"Command '{command.name}' already exists"
                )

            # Save to commands directory
            self.save_command(command, overwrite=overwrite)

            logger.info(f"Imported command '{command.name}' from {import_path}")
            return command

        except json.JSONDecodeError as e:
            logger.error(f"Corrupted import file: {e}")
            raise CorruptedCommandError(f"Import file is corrupted: {e}")
        except (CommandAlreadyExistsError, CommandNotFoundError, CorruptedCommandError):
            # Re-raise storage-specific exceptions without wrapping
            raise
        except Exception as e:
            logger.error(f"Failed to import command: {e}")
            raise StorageError(f"Could not import command: {e}")

    def get_storage_stats(self) -> Dict[str, Any]:
        """
        Get statistics about stored commands.

        Returns:
            Dictionary with storage statistics
        """
        try:
            commands = self.list_commands()

            total_size = sum(
                Path(cmd['file_path']).stat().st_size
                for cmd in commands
                if Path(cmd['file_path']).exists()
            )

            total_blocks = sum(cmd['block_count'] for cmd in commands)

            return {
                'total_commands': len(commands),
                'total_blocks': total_blocks,
                'total_size_bytes': total_size,
                'total_size_kb': round(total_size / 1024, 2),
                'commands_dir': str(self.commands_dir),
                'avg_blocks_per_command': round(total_blocks / len(commands), 1) if commands else 0
            }

        except Exception as e:
            logger.error(f"Failed to get storage stats: {e}")
            return {
                'error': str(e),
                'total_commands': 0
            }
