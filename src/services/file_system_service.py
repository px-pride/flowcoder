"""Service for file system operations with security restrictions."""

from pathlib import Path
from typing import List
import logging

logger = logging.getLogger(__name__)


class FileNode:
    """Represents a file or directory in the file tree."""

    def __init__(self, path: Path, is_dir: bool):
        """Initialize file node.

        Args:
            path: Path to file or directory
            is_dir: True if directory, False if file
        """
        self.path = path
        self.name = path.name
        self.is_dir = is_dir
        self.children: List[FileNode] = []

    def __repr__(self):
        return f"FileNode({self.path}, is_dir={self.is_dir})"


class FileSystemService:
    """Service for file system operations with security."""

    # Common binary file extensions to skip
    BINARY_EXTENSIONS = {
        '.pyc', '.pyo', '.so', '.dll', '.exe', '.bin',
        '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico',
        '.mp3', '.mp4', '.avi', '.mov', '.wav',
        '.zip', '.tar', '.gz', '.rar', '.7z',
        '.pdf', '.doc', '.docx', '.xls', '.xlsx'
    }

    # Directories to skip
    SKIP_DIRECTORIES = {
        '__pycache__', '.git', '.svn', '.hg',
        'node_modules', '.venv', 'venv', 'env',
        '.idea', '.vscode', '.DS_Store'
    }

    # Sensitive files that should not be accessible (Phase 6.1: Security)
    SENSITIVE_FILES = {
        '.env', '.env.local', '.env.production',
        'credentials.json', 'credentials.yml', 'credentials.yaml',
        'secrets.json', 'secrets.yml', 'secrets.yaml',
        '.aws/credentials', '.aws/config',
        '.ssh/id_rsa', '.ssh/id_dsa', '.ssh/id_ecdsa', '.ssh/id_ed25519',
        'id_rsa', 'id_dsa', 'id_ecdsa', 'id_ed25519',
        '.netrc', '.npmrc',
        'shadow', 'passwd', 'gshadow', 'group',  # Unix password files
    }

    # Sensitive file patterns (regex-like patterns)
    SENSITIVE_PATTERNS = {
        '*_rsa', '*_dsa', '*_ecdsa', '*_ed25519',  # SSH keys
        '*.pem', '*.key', '*.crt', '*.cer',  # Certificate files
        '*.p12', '*.pfx',  # Certificate bundles
        'password*', '*password*', '*passwd*',  # Password files
        '*secret*', '*credential*', '*token*',  # Credential files
    }

    def __init__(self, working_directory: str):
        """Initialize file system service.

        Args:
            working_directory: Root directory for operations

        Raises:
            ValueError: If working directory doesn't exist or isn't a directory
        """
        self.working_directory = Path(working_directory).resolve()

        if not self.working_directory.exists():
            raise ValueError(f"Working directory does not exist: {working_directory}")

        if not self.working_directory.is_dir():
            raise ValueError(f"Working directory is not a directory: {working_directory}")

        logger.debug(f"FileSystemService initialized for: {self.working_directory}")

    def _validate_path(self, path: str) -> Path:
        """Validate path is within working directory.

        Args:
            path: Path to validate (can be relative or absolute)

        Returns:
            Resolved absolute path

        Raises:
            ValueError: If path is outside working directory
        """
        # Convert to Path and resolve
        full_path = Path(path)

        # If relative, resolve from working directory
        if not full_path.is_absolute():
            full_path = (self.working_directory / full_path).resolve()
        else:
            full_path = full_path.resolve()

        # Check if path is within working directory
        try:
            full_path.relative_to(self.working_directory)
        except ValueError:
            raise ValueError(
                f"Path outside working directory: {path}\n"
                f"Working directory: {self.working_directory}"
            )

        return full_path

    def is_sensitive_file(self, path: str) -> bool:
        """Check if file contains sensitive information (Phase 6.1: Security).

        Args:
            path: Path to check (can be relative or absolute)

        Returns:
            True if file is sensitive and should not be accessed
        """
        # Get the filename and relative path
        path_obj = Path(path)
        filename = path_obj.name.lower()
        path_str = str(path_obj).lower()

        # Check exact filename matches
        if filename in self.SENSITIVE_FILES:
            return True

        # Check path components (e.g., .ssh/id_rsa)
        if any(sensitive in path_str for sensitive in self.SENSITIVE_FILES):
            return True

        # Check patterns using fnmatch
        import fnmatch
        for pattern in self.SENSITIVE_PATTERNS:
            if fnmatch.fnmatch(filename, pattern):
                return True

        return False

    def read_file(self, path: str) -> str:
        """Read file contents.

        Args:
            path: Path to file (relative to working directory)

        Returns:
            File contents as string

        Raises:
            ValueError: If path is invalid or outside working directory
            FileNotFoundError: If file doesn't exist
            PermissionError: If file cannot be read or is sensitive
            UnicodeDecodeError: If file is binary
        """
        # Check for sensitive files first (Phase 6.1: Security)
        if self.is_sensitive_file(path):
            raise PermissionError(
                f"Access denied: File contains sensitive information: {path}"
            )

        full_path = self._validate_path(path)

        if not full_path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        if not full_path.is_file():
            raise ValueError(f"Not a file: {path}")

        # Check if binary file
        if full_path.suffix.lower() in self.BINARY_EXTENSIONS:
            raise UnicodeDecodeError(
                'utf-8', b'', 0, 1,
                f"File appears to be binary: {full_path.suffix}"
            )

        try:
            content = full_path.read_text(encoding='utf-8')
            logger.debug(f"Read file: {path} ({len(content)} chars)")
            return content
        except UnicodeDecodeError:
            # Try to detect encoding
            raise UnicodeDecodeError(
                'utf-8', b'', 0, 1,
                f"File is not UTF-8 encoded or is binary: {path}"
            )

    def write_file(self, path: str, content: str):
        """Write file contents.

        Args:
            path: Path to file (relative to working directory)
            content: Content to write

        Raises:
            ValueError: If path is invalid or outside working directory
            PermissionError: If file cannot be written or is sensitive
        """
        # Check for sensitive files first (Phase 6.1: Security)
        if self.is_sensitive_file(path):
            raise PermissionError(
                f"Access denied: Cannot write to sensitive file: {path}"
            )

        full_path = self._validate_path(path)

        # Create parent directories if they don't exist
        full_path.parent.mkdir(parents=True, exist_ok=True)

        # Write file
        full_path.write_text(content, encoding='utf-8')
        logger.debug(f"Wrote file: {path} ({len(content)} chars)")

    def get_file_tree(self, max_depth: int = 10) -> FileNode:
        """Get file tree for working directory.

        Args:
            max_depth: Maximum depth to traverse (default 10)

        Returns:
            Root FileNode with children populated
        """
        root = FileNode(self.working_directory, is_dir=True)
        self._populate_tree(root, current_depth=0, max_depth=max_depth)
        logger.debug(f"Generated file tree (max_depth={max_depth})")
        return root

    def _populate_tree(self, node: FileNode, current_depth: int, max_depth: int):
        """Recursively populate file tree.

        Args:
            node: Current node to populate
            current_depth: Current recursion depth
            max_depth: Maximum depth to traverse
        """
        if current_depth >= max_depth:
            return

        if not node.is_dir:
            return

        try:
            # Get directory contents
            entries = sorted(node.path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))

            for entry in entries:
                # Skip hidden files and directories
                if entry.name.startswith('.'):
                    continue

                # Skip common directories
                if entry.is_dir() and entry.name in self.SKIP_DIRECTORIES:
                    continue

                # Create child node
                child = FileNode(entry, is_dir=entry.is_dir())
                node.children.append(child)

                # Recurse for directories
                if entry.is_dir():
                    self._populate_tree(child, current_depth + 1, max_depth)

        except PermissionError:
            # Skip directories we can't read
            logger.warning(f"Permission denied reading directory: {node.path}")
            pass

    def get_relative_path(self, path: Path) -> str:
        """Get path relative to working directory.

        Args:
            path: Absolute path

        Returns:
            Relative path string
        """
        try:
            return str(path.relative_to(self.working_directory))
        except ValueError:
            return str(path)

    def is_binary_file(self, path: str) -> bool:
        """Check if file is likely binary.

        Args:
            path: Path to file

        Returns:
            True if file is likely binary
        """
        full_path = self._validate_path(path)

        # Check extension
        if full_path.suffix.lower() in self.BINARY_EXTENSIONS:
            return True

        # Try to read first 8KB and check for null bytes
        try:
            with open(full_path, 'rb') as f:
                chunk = f.read(8192)
                return b'\x00' in chunk
        except:
            return False
