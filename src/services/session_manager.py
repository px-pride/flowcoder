"""
SessionManager - Manages multiple Claude Code sessions.

Provides lifecycle management for sessions including creation, deletion,
persistence, and active session tracking.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from ..models import Session, SessionState
from ..utils import (
    GitRepoInitializer,
    GitRemoteManager,
    GitRemoteError,
)
from .service_factory import ServiceFactory

logger = logging.getLogger(__name__)


class SessionManagerError(Exception):
    """Base exception for session manager operations."""
    pass


class SessionNotFoundError(SessionManagerError):
    """Raised when a session is not found."""
    pass


class SessionAlreadyExistsError(SessionManagerError):
    """Raised when trying to create a session that already exists."""
    pass


class MaxSessionsExceededError(SessionManagerError):
    """Raised when maximum number of concurrent sessions is exceeded."""
    pass


@dataclass
class GitOperationStatus:
    success: bool
    message: str
    auth_error: bool = False


class SessionManager:
    """
    Manages multiple Claude Code sessions.

    Singleton pattern - only one instance exists.
    Handles session lifecycle, persistence, and active session tracking.
    """

    _instance: Optional['SessionManager'] = None

    MAX_CONCURRENT_SESSIONS = 1  # Multiple sessions disabled until cancel scope issue is fixed
    SESSION_WARNING_THRESHOLD = 5  # Warning threshold
    GIT_MAX_RETRIES = 3
    GIT_RETRY_BASE_DELAY = 0.5

    def __new__(cls, *args, **kwargs):
        """Singleton pattern - return existing instance if it exists."""
        if cls._instance is None:
            cls._instance = super(SessionManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """
        Initialize the session manager.

        Note: Each session gets its own refresh callback via _create_session_refresh_callback()
        """
        # Only initialize once (singleton pattern)
        if self._initialized:
            return

        self.sessions: Dict[str, Session] = {}
        self.active_session_name: Optional[str] = None

        # Observer callbacks for session changes
        self._session_change_callbacks: List = []

        # Default sessions file location
        self.sessions_file = Path.home() / ".flowcoder" / "sessions.json"

        # Ensure sessions directory exists
        self._ensure_sessions_directory()

        # Try to load existing sessions
        try:
            self.load_sessions()
        except Exception as e:
            logger.warning(f"Could not load sessions on init: {e}")

        self._initialized = True
        logger.info("SessionManager initialized")

    def add_session_change_callback(self, callback):
        """
        Register a callback to be notified when sessions change.

        Args:
            callback: Callable that takes no arguments

        Returns:
            Callable that unregisters the callback when called
        """
        if callback not in self._session_change_callbacks:
            self._session_change_callbacks.append(callback)
            logger.debug(f"Registered session change callback: {callback}")

        # Return unregister function for cleanup
        def unregister():
            self.remove_session_change_callback(callback)

        return unregister

    def remove_session_change_callback(self, callback):
        """
        Unregister a session change callback.

        Args:
            callback: Callback to remove
        """
        if callback in self._session_change_callbacks:
            self._session_change_callbacks.remove(callback)
            logger.debug(f"Removed session change callback: {callback}")

    def _notify_session_change(self):
        """Notify all registered callbacks that sessions have changed."""
        for callback in self._session_change_callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"Error in session change callback: {e}", exc_info=True)

    def _ensure_sessions_directory(self) -> None:
        """Ensure the sessions directory exists."""
        try:
            self.sessions_file.parent.mkdir(parents=True, exist_ok=True)
            logger.info(f"Sessions directory ready: {self.sessions_file.parent}")
        except Exception as e:
            logger.error(f"Failed to create sessions directory: {e}")
            raise SessionManagerError(f"Could not create sessions directory: {e}")

    def _run_async_sync(self, coro) -> None:
        """
        Run an async coroutine from a synchronous context (e.g., background thread).

        Only use this from threads that don't have an event loop running.
        For async contexts, call the async method directly.

        Args:
            coro: Coroutine to run
        """
        asyncio.run(coro)

    def _create_session_refresh_callback(self, session_name: str) -> Callable:
        """
        Create a refresh callback for a specific session.

        This creates a closure that refreshes only the specified session's AI service,
        not the main window's service.

        Args:
            session_name: Name of the session to create refresh callback for

        Returns:
            Async callable that refreshes the session's AI service
        """
        async def refresh_session():
            """Refresh this specific session's AI service."""
            session = self.sessions.get(session_name)
            if not session:
                logger.warning(f"Cannot refresh session '{session_name}' - session not found")
                return

            logger.info(f"Refreshing AI service for session '{session_name}'...")

            # Properly close old client to prevent memory leaks
            if hasattr(session.agent_service, '_session_active') and session.agent_service._session_active:
                try:
                    logger.info(f"Closing existing session for '{session_name}'...")
                    await session.agent_service.end_session()
                    logger.info(f"Successfully closed existing client for session '{session_name}'")
                except Exception as e:
                    logger.warning(f"Error closing client for session '{session_name}': {e}")

            # Create new AI service instance for this session
            try:
                session.agent_service = ServiceFactory.create_service(
                    service_type=session.service_type,
                    cwd=session.working_directory,
                    system_prompt=session.system_prompt,
                    permission_mode="bypassPermissions"
                )
                logger.info(f"Created new {session.service_type} service for session '{session_name}'")
            except Exception as e:
                logger.error(f"Failed to create new service for session '{session_name}': {e}")
                return

            # Update execution controller with new service
            if session.execution_controller:
                session.execution_controller.agent_service = session.agent_service
                logger.info(f"Updated execution controller for session '{session_name}'")

            # Session will initialize lazily via ensure_session() on next execution
            logger.info(f"Session '{session_name}' refresh complete")

        return refresh_session

    def create_session(
        self,
        name: str,
        working_directory: str,
        system_prompt: str = "",
        service_type: str = "claude"
    ) -> Session:
        """
        Create a new session.

        Args:
            name: Unique name for the session
            working_directory: Working directory for the session
            system_prompt: System prompt for AI (optional)
            service_type: AI service type ("claude", "codex", or "mock")

        Returns:
            Created Session object

        Raises:
            SessionAlreadyExistsError: If session with this name already exists
            MaxSessionsExceededError: If max concurrent sessions exceeded
            ValueError: If name is empty or working directory invalid
        """
        # Validate name
        if not name or not name.strip():
            raise ValueError("Session name cannot be empty")

        name = name.strip()

        # Check if session already exists
        if name in self.sessions:
            raise SessionAlreadyExistsError(f"Session '{name}' already exists")

        # Check max sessions limit
        if len(self.sessions) >= self.MAX_CONCURRENT_SESSIONS:
            raise MaxSessionsExceededError(
                f"Maximum concurrent sessions ({self.MAX_CONCURRENT_SESSIONS}) exceeded. "
                f"Please close a session before creating a new one."
            )

        # Warning threshold
        if len(self.sessions) >= self.SESSION_WARNING_THRESHOLD:
            logger.warning(
                f"High number of concurrent sessions ({len(self.sessions)}). "
                f"Consider closing unused sessions for better performance."
            )

        # Create session (Session.__post_init__ will validate working directory)
        try:
            session = Session(
                name=name,
                working_directory=working_directory,
                system_prompt=system_prompt,
                service_type=service_type
            )
        except ValueError as e:
            # Re-raise validation errors from Session
            raise ValueError(f"Invalid session parameters: {e}")

        # Ensure working directory is a git repo (Phase 6.1)
        try:
            git_initializer = GitRepoInitializer(session.working_directory)
            git_result = git_initializer.ensure_repository()
            if git_result.initialized:
                logger.info(
                    f"Initialized git repository for session '{name}'"
                )
            else:
                logger.debug(
                    f"Git repository already present for session '{name}'"
                )
        except Exception as e:
            logger.error(
                f"Failed to initialize git repository for '{name}': {e}"
            )

        # Configure remote/branch if metadata present (Phase 6.2.x)
        remote_status = self.configure_git_remote(session)
        if not remote_status.success:
            logger.warning(remote_status.message)

        branch_status = self.configure_git_branch(session)
        if not branch_status.success:
            logger.warning(branch_status.message)

        # Initialize AI service for this session using ServiceFactory
        try:
            session.agent_service = ServiceFactory.create_service(
                service_type=session.service_type,
                cwd=session.working_directory,
                system_prompt=session.system_prompt,
                permission_mode="bypassPermissions"  # Skip permission prompts for automation
            )
            logger.info(f"Initialized {session.service_type} service for session '{name}'")
        except Exception as e:
            logger.error(f"Failed to initialize {session.service_type} service: {e}")
            # Continue without service - service will be None
            session.agent_service = None

        # Initialize ExecutionController for this session
        try:
            if session.agent_service:
                # Lazy import to avoid circular dependency
                from ..controllers.execution_controller import ExecutionController
                from ..services import StorageService

                # Get storage service instance (shared across sessions)
                storage_service = StorageService()

                session.execution_controller = ExecutionController(
                    agent_service=session.agent_service,
                    storage_service=storage_service
                )

                # Set per-session refresh callback
                # Each session gets its own refresh callback that only refreshes that session
                session.execution_controller.on_refresh_requested = self._create_session_refresh_callback(name)
                logger.info(f"Set per-session refresh callback for session '{name}'")

                logger.info(f"Initialized ExecutionController for session '{name}' with storage_service")
            else:
                logger.warning(f"Skipping ExecutionController init (no agent_service) for session '{name}'")
                session.execution_controller = None
        except Exception as e:
            logger.error(f"Failed to initialize ExecutionController: {e}")
            session.execution_controller = None

        # Add to sessions
        self.sessions[name] = session

        # If this is the first session, make it active
        if len(self.sessions) == 1:
            self.active_session_name = name
            logger.info(f"Set '{name}' as active session (first session)")

        logger.info(f"Created session '{name}' in {working_directory}")

        # Auto-save sessions
        try:
            self.save_sessions()
        except Exception as e:
            logger.warning(f"Could not auto-save sessions: {e}")

        # Notify observers that sessions changed
        self._notify_session_change()

        return session

    def get_session(self, name: str) -> Session:
        """
        Get a session by name.

        Args:
            name: Name of the session

        Returns:
            Session object

        Raises:
            SessionNotFoundError: If session not found
        """
        if name not in self.sessions:
            raise SessionNotFoundError(f"Session '{name}' not found")

        return self.sessions[name]

    def list_sessions(self) -> List[Session]:
        """
        List all sessions.

        Returns:
            List of Session objects
        """
        return list(self.sessions.values())

    async def close_session_async(self, name: str) -> None:
        """
        Close and remove a session (async version).

        Use this when calling from an async context.

        Args:
            name: Name of the session to close

        Raises:
            SessionNotFoundError: If session not found
        """
        if name not in self.sessions:
            raise SessionNotFoundError(f"Session '{name}' not found")

        # Get session before removing
        session = self.sessions[name]

        # Cleanup execution controller first (clean up running processes)
        if session.execution_controller:
            try:
                await session.execution_controller.cleanup_processes()
                logger.info(f"Cleaned up execution controller processes for '{name}'")
            except Exception as e:
                logger.warning(f"Error cleaning up execution controller for '{name}': {e}")

            # Clear callback references to prevent memory leaks
            session.execution_controller.on_block_start = None
            session.execution_controller.on_block_complete = None
            session.execution_controller.on_execution_complete = None
            session.execution_controller.on_prompt_stream = None
            session.execution_controller.on_execution_start = None
            session.execution_controller.on_refresh_requested = None

        # Cleanup Claude service (end SDK session)
        if session.agent_service:
            try:
                await session.agent_service.end_session()
                logger.info(f"Ended Claude SDK session for '{name}'")
            except asyncio.CancelledError:
                # SDK can raise CancelledError from its internal cancel scopes
                # This is expected during force-kill scenarios
                logger.info(f"Claude SDK session for '{name}' was force-killed")
            except Exception as e:
                logger.warning(f"Error ending Claude SDK session for '{name}': {e}")
            finally:
                # Force the session state to inactive even if end_session() failed
                # This prevents "command already in progress" errors
                session.agent_service._session_active = False
                session.agent_service._client = None

        # Remove from sessions
        del self.sessions[name]

        # If this was the active session, clear active session
        # (or set to first available session)
        if self.active_session_name == name:
            if self.sessions:
                # Set first available session as active
                self.active_session_name = next(iter(self.sessions.keys()))
                logger.info(f"Active session changed to '{self.active_session_name}'")
            else:
                self.active_session_name = None
                logger.info("No active session (all sessions closed)")

        logger.info(f"Closed session '{name}'")

        # Auto-save sessions
        try:
            self.save_sessions()
        except Exception as e:
            logger.warning(f"Could not auto-save sessions: {e}")

        # Notify observers that sessions changed
        self._notify_session_change()

    def close_session(self, name: str) -> None:
        """
        Close and remove a session (sync version).

        Use this when calling from a synchronous context (e.g., background thread).
        For async contexts, use close_session_async() instead.

        Args:
            name: Name of the session to close

        Raises:
            SessionNotFoundError: If session not found
        """
        self._run_async_sync(self.close_session_async(name))

    async def cleanup_all_sessions_async(self) -> None:
        """
        Clean up all session processes without deleting sessions.

        Used during application shutdown to terminate running processes
        while preserving session data for next startup.
        """
        logger.info(f"Cleaning up processes for {len(self.sessions)} sessions...")

        for name, session in self.sessions.items():
            try:
                # Clean up execution controller processes
                if session.execution_controller:
                    await session.execution_controller.cleanup_processes()
                    logger.info(f"Cleaned up processes for session '{name}'")

                # End Claude agent session
                if session.agent_service:
                    try:
                        await session.agent_service.end_session()
                        logger.info(f"Ended agent session for '{name}'")
                    except asyncio.CancelledError:
                        logger.info(f"Agent session for '{name}' was force-killed")
                    except Exception as e:
                        logger.warning(f"Error ending agent session for '{name}': {e}")

            except Exception as e:
                logger.error(f"Error cleaning up session '{name}': {e}")

        logger.info("All session processes cleaned up")

    async def close_all_sessions_async(self) -> None:
        """
        Close and DELETE all sessions asynchronously.

        This removes sessions from memory and disk. Only use when you want
        to permanently remove all sessions, not for app shutdown.
        """
        logger.info(f"Closing all {len(self.sessions)} sessions...")

        # Get list of session names (copy since we're modifying during iteration)
        session_names = list(self.sessions.keys())

        for name in session_names:
            try:
                await self.close_session_async(name)
            except Exception as e:
                logger.error(f"Error closing session '{name}' during shutdown: {e}")

        logger.info("All sessions closed")

    def close_all_sessions(self) -> None:
        """
        Close all sessions synchronously. Used during application shutdown.

        For async contexts, use close_all_sessions_async() instead.
        """
        self._run_async_sync(self.close_all_sessions_async())

    def get_active_session(self) -> Optional[Session]:
        """
        Get the currently active session.

        Returns:
            Active Session object, or None if no active session
        """
        if self.active_session_name is None:
            return None

        return self.sessions.get(self.active_session_name)

    def set_active_session(self, name: str) -> None:
        """
        Set the active session.

        Args:
            name: Name of the session to make active

        Raises:
            SessionNotFoundError: If session not found
        """
        if name not in self.sessions:
            raise SessionNotFoundError(f"Session '{name}' not found")

        self.active_session_name = name
        logger.info(f"Set '{name}' as active session")

        # Auto-save sessions
        try:
            self.save_sessions()
        except Exception as e:
            logger.warning(f"Could not auto-save sessions: {e}")

    def save_sessions(self) -> None:
        """
        Save all sessions to disk.

        Raises:
            SessionManagerError: If save operation fails
        """
        try:
            # Serialize all sessions
            data = {
                "active_session": self.active_session_name,
                "sessions": {
                    name: session.to_dict()
                    for name, session in self.sessions.items()
                }
            }

            # Write to file with pretty formatting
            with open(self.sessions_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            logger.info(f"Saved {len(self.sessions)} sessions to {self.sessions_file}")

        except Exception as e:
            logger.error(f"Failed to save sessions: {e}")
            raise SessionManagerError(f"Could not save sessions: {e}")

    def load_sessions(self) -> None:
        """
        Load sessions from disk.

        Raises:
            SessionManagerError: If load operation fails
        """
        # If sessions file doesn't exist, that's OK (first run)
        if not self.sessions_file.exists():
            logger.info("No sessions file found (first run)")
            return

        try:
            with open(self.sessions_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Load sessions
            self.sessions = {}
            for name, session_data in data.get("sessions", {}).items():
                try:
                    session = Session.from_dict(session_data)

                    # Reset state to IDLE if it was EXECUTING (no execution can be running after restart)
                    if session.state == SessionState.EXECUTING:
                        session.state = SessionState.IDLE
                        logger.info(f"Reset session '{name}' state from EXECUTING to IDLE (program restart)")

                    # Ensure git repo + remote exist for loaded sessions
                    try:
                        git_initializer = GitRepoInitializer(session.working_directory)
                        git_initializer.ensure_repository()
                    except Exception as e:
                        logger.error(
                            f"Failed to initialize git repository for loaded session '{name}': {e}"
                        )

                    remote_status = self.configure_git_remote(session)
                    if not remote_status.success:
                        logger.warning(remote_status.message)

                    branch_status = self.configure_git_branch(session)
                    if not branch_status.success:
                        logger.warning(branch_status.message)

                    # Initialize AI service for this session using ServiceFactory
                    try:
                        session.agent_service = ServiceFactory.create_service(
                            service_type=session.service_type,
                            cwd=session.working_directory,
                            system_prompt=session.system_prompt,
                            permission_mode="bypassPermissions"
                        )
                        logger.info(f"Initialized {session.service_type} service for loaded session '{name}'")
                    except Exception as e:
                        logger.error(f"Failed to initialize {session.service_type} service for loaded session '{name}': {e}")
                        session.agent_service = None

                    # Initialize ExecutionController for this session
                    try:
                        if session.agent_service:
                            from ..controllers.execution_controller import ExecutionController
                            from ..services import StorageService

                            storage_service = StorageService()

                            session.execution_controller = ExecutionController(
                                agent_service=session.agent_service,
                                storage_service=storage_service
                            )

                            # Set per-session refresh callback
                            session.execution_controller.on_refresh_requested = self._create_session_refresh_callback(name)
                            logger.info(f"Set per-session refresh callback for loaded session '{name}'")

                            logger.info(f"Initialized ExecutionController for loaded session '{name}'")
                        else:
                            logger.warning(f"Skipping ExecutionController init (no agent_service) for loaded session '{name}'")
                            session.execution_controller = None
                    except Exception as e:
                        logger.error(f"Failed to initialize ExecutionController for loaded session '{name}': {e}")
                        session.execution_controller = None

                    self.sessions[name] = session
                except Exception as e:
                    logger.warning(f"Could not load session '{name}': {e}")
                    continue

            # Load active session
            active_session = data.get("active_session")
            if active_session and active_session in self.sessions:
                self.active_session_name = active_session
            else:
                # If active session not found, set to first session
                if self.sessions:
                    self.active_session_name = next(iter(self.sessions.keys()))
                else:
                    self.active_session_name = None

            logger.info(f"Loaded {len(self.sessions)} sessions from {self.sessions_file}")

        except json.JSONDecodeError as e:
            logger.error(f"Corrupted sessions file: {e}")
            raise SessionManagerError(f"Sessions file is corrupted: {e}")
        except Exception as e:
            logger.error(f"Failed to load sessions: {e}")
            raise SessionManagerError(f"Could not load sessions: {e}")

    def session_exists(self, name: str) -> bool:
        """
        Check if a session exists.

        Args:
            name: Name of the session

        Returns:
            True if session exists, False otherwise
        """
        return name in self.sessions

    def get_session_count(self) -> int:
        """
        Get the total number of sessions.

        Returns:
            Number of sessions
        """
        return len(self.sessions)

    def is_at_warning_threshold(self) -> bool:
        """
        Check if session count is at warning threshold.

        Returns:
            True if at or above warning threshold
        """
        return len(self.sessions) >= self.SESSION_WARNING_THRESHOLD

    def is_at_max_sessions(self) -> bool:
        """
        Check if session count is at maximum.

        Returns:
            True if at maximum sessions
        """
        return len(self.sessions) >= self.MAX_CONCURRENT_SESSIONS

    def __repr__(self) -> str:
        """String representation of session manager."""
        return (
            f"SessionManager("
            f"sessions={len(self.sessions)}, "
            f"active='{self.active_session_name or 'None'}'"
            f")"
        )


    def configure_git_remote(self, session: Session) -> GitOperationStatus:
        """Ensure the session's `origin` remote matches the stored repo URL."""
        if not session.git_repo_url:
            return GitOperationStatus(True, "No remote configured for this session.")

        def operation() -> GitOperationStatus:
            try:
                manager = GitRemoteManager(session.working_directory)
                manager.ensure_remote("origin", session.git_repo_url)
                message = f"Configured git remote for session '{session.name}'"
                logger.info(message)
                return GitOperationStatus(True, message)
            except GitRemoteError as e:
                message = self._format_git_error("remote configuration", e)
                logger.error(message)
                return GitOperationStatus(False, message, auth_error=e.is_auth_error())

        return self._execute_with_retry("remote configuration", operation)

    def configure_git_branch(self, session: Session) -> GitOperationStatus:
        branch = (session.git_branch or "").strip()
        if not branch:
            return GitOperationStatus(True, "No branch requested for this session.")

        def operation() -> GitOperationStatus:
            try:
                remote = "origin" if session.git_repo_url else None
                manager = GitRemoteManager(session.working_directory)
                manager.checkout_branch(branch, remote=remote)
                message = f"Checked out branch '{branch}' for session '{session.name}'"
                logger.info(message)
                return GitOperationStatus(True, message)
            except GitRemoteError as e:
                message = self._format_git_error("branch checkout", e)
                logger.error(message)
                return GitOperationStatus(False, message, auth_error=e.is_auth_error())

        return self._execute_with_retry("branch checkout", operation)

    @staticmethod
    def _format_git_error(action: str, error: GitRemoteError) -> str:
        base = f"Git {action} failed: {error}"
        if error.is_auth_error():
            hint = (
                "Authentication appears to have failed. Ensure your SSH agent"
                " has the correct key (e.g., run `ssh-add ~/.ssh/id_rsa`) or"
                " configure an HTTPS credential helper/Personal Access Token."
            )
            return f"{base}\n{hint}"
        return base

    def _execute_with_retry(
        self,
        description: str,
        operation: Callable[[], GitOperationStatus]
    ) -> GitOperationStatus:
        delay = self.GIT_RETRY_BASE_DELAY
        last_status = GitOperationStatus(True, "")
        for attempt in range(1, self.GIT_MAX_RETRIES + 1):
            last_status = operation()
            if last_status.success or last_status.auth_error:
                return last_status
            if attempt < self.GIT_MAX_RETRIES:
                logger.info(
                    f"Retrying git {description} (attempt {attempt + 1}/{self.GIT_MAX_RETRIES})"
                )
                self._sleep(delay)
                delay *= 2
        return last_status

    def _sleep(self, seconds: float) -> None:
        """Wrapper for time.sleep to simplify testing."""
        time.sleep(seconds)
