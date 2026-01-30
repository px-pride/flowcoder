"""
Storage Service for FlowCoder

Handles persistence of commands to JSON files.
"""

import json
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

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

    def __init__(self, project_dir: Optional[str] = None):
        """
        Initialize the storage service with three-tier command directories.

        Args:
            project_dir: Project working directory. If provided, commands will be
                         loaded from {project_dir}/.flowcoder/commands/

        Command directories (in priority order):
            1. Project: {project_dir}/.flowcoder/commands/
            2. User: ~/.flowcoder/commands/
            3. Flowcoder: {repo}/commands/
        """
        # Compute flowcoder repo commands directory from this file's location
        # storage_service.py is at src/services/storage_service.py
        # So parent.parent.parent gives us the repo root
        self.flowcoder_commands_dir = Path(__file__).parent.parent.parent / "commands"

        # User commands directory
        self.user_commands_dir = Path.home() / ".flowcoder" / "commands"

        # Project commands directory (optional)
        self.project_commands_dir = (
            Path(project_dir) / ".flowcoder" / "commands"
            if project_dir else None
        )

        # Build search order list (project first if available)
        self._command_dirs: List[Tuple[Path, str]] = []
        if self.project_commands_dir:
            self._command_dirs.append((self.project_commands_dir, "proj"))
        self._command_dirs.append((self.user_commands_dir, "user"))
        self._command_dirs.append((self.flowcoder_commands_dir, "fc"))

        # For backward compatibility, keep commands_dir pointing to project or user
        self.commands_dir = self.project_commands_dir or self.user_commands_dir

        logger.info(f"StorageService initialized with {len(self._command_dirs)} command directories")
        for cmd_dir, source in self._command_dirs:
            exists = cmd_dir.exists()
            logger.debug(f"  {source}: {cmd_dir} (exists={exists})")

    def set_project_dir(self, project_dir: Optional[str]) -> None:
        """
        Update the project directory for command loading.

        Call this when the active session changes to update which project
        commands are visible.

        Args:
            project_dir: New project working directory, or None to disable project tier
        """
        # Update project commands directory
        self.project_commands_dir = (
            Path(project_dir) / ".flowcoder" / "commands"
            if project_dir else None
        )

        # Rebuild search order list
        self._command_dirs = []
        if self.project_commands_dir:
            self._command_dirs.append((self.project_commands_dir, "proj"))
        self._command_dirs.append((self.user_commands_dir, "user"))
        self._command_dirs.append((self.flowcoder_commands_dir, "fc"))

        # Update primary directory for saving new commands
        self.commands_dir = self.project_commands_dir or self.user_commands_dir

        logger.info(f"StorageService project_dir updated to: {project_dir}")
        for cmd_dir, source in self._command_dirs:
            exists = cmd_dir.exists()
            logger.debug(f"  {source}: {cmd_dir} (exists={exists})")

    def _get_command_file_path(self, command_name: str, source: Optional[str] = None) -> Path:
        """
        Get the file path for a command.

        Args:
            command_name: Name of the command
            source: Optional source tier ('proj', 'user', 'fc'). If not provided,
                    searches all directories and returns first match.

        Returns:
            Path to the command file

        Raises:
            CommandNotFoundError: If source specified but not found
        """
        safe_name = command_name.replace(" ", "_")
        filename = f"{safe_name}.json"

        if source:
            # Get specific directory for source
            for cmd_dir, src in self._command_dirs:
                if src == source:
                    return cmd_dir / filename
            raise CommandNotFoundError(f"Unknown source: {source}")

        # Search all directories, return first existing match
        for cmd_dir, src in self._command_dirs:
            path = cmd_dir / filename
            if path.exists():
                return path

        # Not found anywhere, return path in primary directory (for new commands)
        return self.commands_dir / filename

    def _get_source_for_path(self, file_path: Path) -> str:
        """Determine the source tier for a given file path."""
        file_path = file_path.resolve()
        for cmd_dir, source in self._command_dirs:
            if cmd_dir.exists():
                try:
                    file_path.relative_to(cmd_dir.resolve())
                    return source
                except ValueError:
                    continue
        return "fc"  # Default fallback

    def save_command(self, command: Command, overwrite: bool = True) -> None:
        """
        Save a command to disk.

        For existing commands: saves to original location.
        For new commands: saves to project directory (or user if no project).

        Args:
            command: Command to save
            overwrite: If False, raises error if command already exists

        Raises:
            CommandAlreadyExistsError: If command exists and overwrite=False
            StorageError: If save operation fails
        """
        # Determine target directory
        if hasattr(command, '_file_path') and command._file_path:
            # Existing command - save to original location
            file_path = command._file_path
        else:
            # New command - save to primary directory (project or user)
            file_path = self.commands_dir / f"{command.name.replace(' ', '_')}.json"

        # Check if already exists
        if file_path.exists() and not overwrite:
            raise CommandAlreadyExistsError(
                f"Command '{command.name}' already exists"
            )

        # Ensure directory exists (JIT creation)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Update modified timestamp
        command.update_modified()

        try:
            data = command.to_dict()
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            # Update command's file path reference
            command._file_path = file_path
            command._source = self._get_source_for_path(file_path)

            logger.info(f"Saved command '{command.name}' to {file_path}")

        except Exception as e:
            logger.error(f"Failed to save command '{command.name}': {e}")
            raise StorageError(f"Could not save command: {e}")

    def load_command(self, command_name: str, source: Optional[str] = None) -> Command:
        """
        Load a command from disk.

        Args:
            command_name: Name of the command to load
            source: Optional source tier ('proj', 'user', 'fc')

        Returns:
            Loaded Command object

        Raises:
            CommandNotFoundError: If command file doesn't exist
            CorruptedCommandError: If command file is invalid
            StorageError: If load operation fails
        """
        file_path = self._get_command_file_path(command_name, source)

        if not file_path.exists():
            raise CommandNotFoundError(
                f"Command '{command_name}' not found"
            )

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            command = Command.from_dict(data)

            # Store source info on command for save operations
            command._source = self._get_source_for_path(file_path)
            command._file_path = file_path

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

    def delete_command(self, command_name: str, source: Optional[str] = None) -> None:
        """
        Delete a command from disk.

        If source not specified, deletes from highest-priority location.

        Args:
            command_name: Name of the command to delete
            source: Optional source tier to delete from

        Raises:
            CommandNotFoundError: If command doesn't exist
            StorageError: If delete operation fails
        """
        safe_name = command_name.replace(" ", "_")
        filename = f"{safe_name}.json"

        # Find the file to delete
        file_path = None
        if source:
            for cmd_dir, src in self._command_dirs:
                if src == source:
                    file_path = cmd_dir / filename
                    break
        else:
            # Find highest-priority location where command exists
            for cmd_dir, src in self._command_dirs:
                path = cmd_dir / filename
                if path.exists():
                    file_path = path
                    break

        if not file_path or not file_path.exists():
            raise CommandNotFoundError(f"Command '{command_name}' not found")

        try:
            file_path.unlink()
            logger.info(f"Deleted command '{command_name}' from {file_path}")
        except Exception as e:
            logger.error(f"Failed to delete command '{command_name}': {e}")
            raise StorageError(f"Could not delete command: {e}")

    def list_commands(self) -> List[Dict[str, Any]]:
        """
        List all available commands with their metadata from all directories.

        Returns:
            List of command metadata dictionaries with keys:
            - id: Command ID
            - name: Command name
            - description: Command description
            - created: Creation timestamp
            - modified: Last modified timestamp
            - block_count: Number of blocks in flowchart
            - file_path: Path to command file
            - source: Source tier ('proj', 'user', 'fc')

        Raises:
            StorageError: If listing fails
        """
        commands = []

        for cmd_dir, source in self._command_dirs:
            if not cmd_dir.exists():
                continue

            try:
                for file_path in cmd_dir.glob("*.json"):
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)

                        metadata = {
                            'id': data.get('id', ''),
                            'name': data.get('name', ''),
                            'description': data.get('description', ''),
                            'created': data.get('metadata', {}).get('created', ''),
                            'modified': data.get('metadata', {}).get('modified', ''),
                            'block_count': len(data.get('flowchart', {}).get('blocks', {})),
                            'file_path': str(file_path),
                            'source': source,
                        }
                        commands.append(metadata)

                    except json.JSONDecodeError:
                        logger.warning(f"Skipping corrupted file: {file_path}")
                        continue
                    except Exception as e:
                        logger.warning(f"Error reading {file_path}: {e}")
                        continue

            except Exception as e:
                logger.warning(f"Error listing commands from {cmd_dir}: {e}")
                continue

        # Sort by modified date (most recent first)
        commands.sort(key=lambda x: x['modified'], reverse=True)

        logger.info(f"Found {len(commands)} commands across {len(self._command_dirs)} directories")
        return commands

    def command_exists(self, command_name: str, source: Optional[str] = None) -> bool:
        """
        Check if a command exists.

        Args:
            command_name: Name of the command
            source: Optional source tier to check

        Returns:
            True if command exists, False otherwise
        """
        safe_name = command_name.replace(" ", "_")
        filename = f"{safe_name}.json"

        if source:
            for cmd_dir, src in self._command_dirs:
                if src == source:
                    return (cmd_dir / filename).exists()
            return False

        # Check all directories
        for cmd_dir, src in self._command_dirs:
            if (cmd_dir / filename).exists():
                return True
        return False

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
