"""Service for caching editor state across session switches."""

from typing import Dict, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class EditorState:
    """Represents cached state for a file editor."""

    content: str
    cursor_position: str  # Tkinter index format (e.g., "1.0")
    is_dirty: bool
    last_modified: datetime

    def __repr__(self):
        return f"EditorState(dirty={self.is_dirty}, modified={self.last_modified})"


class EditorStateService:
    """Service for caching editor state when switching sessions."""

    # Maximum number of cached files (to prevent memory bloat)
    MAX_CACHE_SIZE = 100

    def __init__(self):
        """Initialize editor state service."""
        # Cache key: (session_name, file_path) -> EditorState
        self._cache: Dict[Tuple[str, str], EditorState] = {}
        logger.debug("EditorStateService initialized")

    def save_state(
        self,
        session_name: str,
        file_path: str,
        content: str,
        cursor_position: str = "1.0",
        is_dirty: bool = False
    ):
        """Save editor state for a file.

        Args:
            session_name: Name of session
            file_path: Relative path to file
            content: File content in editor
            cursor_position: Cursor position in Tkinter index format
            is_dirty: Whether file has unsaved changes
        """
        key = (session_name, file_path)

        # Check cache size limit
        if key not in self._cache and len(self._cache) >= self.MAX_CACHE_SIZE:
            # Remove oldest entry (LRU eviction)
            oldest_key = min(
                self._cache.keys(),
                key=lambda k: self._cache[k].last_modified
            )
            logger.debug(f"Cache full, removing oldest entry: {oldest_key}")
            del self._cache[oldest_key]

        # Save state
        self._cache[key] = EditorState(
            content=content,
            cursor_position=cursor_position,
            is_dirty=is_dirty,
            last_modified=datetime.now()
        )

        logger.debug(
            f"Saved editor state for {session_name}/{file_path} "
            f"(dirty={is_dirty}, size={len(content)} chars)"
        )

    def restore_state(
        self,
        session_name: str,
        file_path: str
    ) -> Optional[EditorState]:
        """Restore editor state for a file.

        Args:
            session_name: Name of session
            file_path: Relative path to file

        Returns:
            EditorState if cached, None otherwise
        """
        key = (session_name, file_path)
        state = self._cache.get(key)

        if state:
            logger.debug(f"Restored editor state for {session_name}/{file_path}")
        else:
            logger.debug(f"No cached state for {session_name}/{file_path}")

        return state

    def has_cached_state(self, session_name: str, file_path: str) -> bool:
        """Check if editor state is cached.

        Args:
            session_name: Name of session
            file_path: Relative path to file

        Returns:
            True if state is cached
        """
        return (session_name, file_path) in self._cache

    def clear_state(self, session_name: str, file_path: str):
        """Clear cached state for a file (e.g., after saving to disk).

        Args:
            session_name: Name of session
            file_path: Relative path to file
        """
        key = (session_name, file_path)
        if key in self._cache:
            del self._cache[key]
            logger.debug(f"Cleared cached state for {session_name}/{file_path}")

    def clear_session_states(self, session_name: str):
        """Clear all cached states for a session (e.g., when session closes).

        Args:
            session_name: Name of session
        """
        keys_to_remove = [
            key for key in self._cache.keys()
            if key[0] == session_name
        ]

        for key in keys_to_remove:
            del self._cache[key]

        logger.debug(f"Cleared {len(keys_to_remove)} cached states for session {session_name}")

    def get_dirty_files(self, session_name: str) -> list[str]:
        """Get list of dirty (unsaved) files for a session.

        Args:
            session_name: Name of session

        Returns:
            List of file paths with unsaved changes
        """
        dirty_files = [
            file_path
            for (sess_name, file_path), state in self._cache.items()
            if sess_name == session_name and state.is_dirty
        ]

        logger.debug(f"Found {len(dirty_files)} dirty files for session {session_name}")
        return dirty_files

    def get_cache_stats(self) -> dict:
        """Get cache statistics.

        Returns:
            Dict with cache statistics
        """
        total_size = sum(len(state.content) for state in self._cache.values())
        dirty_count = sum(1 for state in self._cache.values() if state.is_dirty)

        return {
            'total_files': len(self._cache),
            'total_size_bytes': total_size,
            'dirty_files': dirty_count,
            'max_cache_size': self.MAX_CACHE_SIZE
        }

    def update_dirty_state(self, session_name: str, file_path: str, is_dirty: bool):
        """Update dirty state for a cached file without changing content.

        Args:
            session_name: Name of session
            file_path: Relative path to file
            is_dirty: New dirty state

        Raises:
            KeyError: If file is not in cache
        """
        key = (session_name, file_path)
        if key not in self._cache:
            raise KeyError(f"No cached state for {session_name}/{file_path}")

        self._cache[key].is_dirty = is_dirty
        self._cache[key].last_modified = datetime.now()

        logger.debug(f"Updated dirty state for {session_name}/{file_path} to {is_dirty}")
