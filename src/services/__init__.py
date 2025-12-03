"""
Services package for FlowCoder

Provides service layer functionality for storage, Claude integration, and audio.
"""

from .storage_service import (
    StorageService,
    StorageError,
    CommandNotFoundError,
    CommandAlreadyExistsError,
    CorruptedCommandError
)

from .base_service import BaseService

from .claude_service import (
    ClaudeAgentService,
    MockClaudeService,
    ClaudeServiceError,
    ClaudeAPIError,
    SchemaValidationError,
    TimeoutError,
    PromptResult
)

from .codex_service import (
    CodexService,
    CodexServiceError
)

from .service_factory import (
    ServiceFactory,
    ServiceFactoryError
)

from .audio_service import (
    AudioService,
    AudioServiceError
)

from .session_manager import (
    SessionManager,
    SessionManagerError,
    SessionNotFoundError,
    SessionAlreadyExistsError,
    MaxSessionsExceededError
)

from .file_system_service import (
    FileSystemService,
    FileNode
)

from .editor_state_service import (
    EditorStateService,
    EditorState
)

from .command_block_executor import (
    CommandBlockExecutor,
    CommandBlockExecutorError,
    CommandNotFoundError as CBECommandNotFoundError,
    MaxRecursionDepthError
)

__all__ = [
    # Storage
    'StorageService',
    'StorageError',
    'CommandNotFoundError',
    'CommandAlreadyExistsError',
    'CorruptedCommandError',
    # Base Service
    'BaseService',
    # Claude
    'ClaudeAgentService',
    'MockClaudeService',
    'ClaudeServiceError',
    'ClaudeAPIError',
    'SchemaValidationError',
    'TimeoutError',
    'PromptResult',
    # Codex
    'CodexService',
    'CodexServiceError',
    # Service Factory
    'ServiceFactory',
    'ServiceFactoryError',
    # Audio
    'AudioService',
    'AudioServiceError',
    # Session Management
    'SessionManager',
    'SessionManagerError',
    'SessionNotFoundError',
    'SessionAlreadyExistsError',
    'MaxSessionsExceededError',
    # File System
    'FileSystemService',
    'FileNode',
    # Editor State
    'EditorStateService',
    'EditorState',
    # Command Block Executor
    'CommandBlockExecutor',
    'CommandBlockExecutorError',
    'CBECommandNotFoundError',
    'MaxRecursionDepthError',
]
