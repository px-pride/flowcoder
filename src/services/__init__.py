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

from .exceptions import (
    ClaudeServiceError,
    ClaudeAPIError,
    SchemaValidationError,
    TimeoutError,
    PromptResult,
)
from .mock_service import MockClaudeService
from .claude_engine_service import ClaudeEngineService

from .service_factory import (
    ServiceFactory,
    ServiceFactoryError
)

# AudioService requires pygame — lazy-load so that headless / embedding
# consumers are not forced to install GUI dependencies.
_AUDIO_LAZY = {
    'AudioService': '.audio_service',
    'AudioServiceError': '.audio_service',
}

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

from .config_service import (
    ConfigService,
    ClaudeConfig,
    ConfigError,
    ConfigNotFoundError as ConfigNotFoundError_,
    ConfigAlreadyExistsError,
    CorruptedConfigError
)



def __getattr__(name: str):
    if name in _AUDIO_LAZY:
        from . import audio_service as _mod
        return getattr(_mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
    'ClaudeEngineService',
    'MockClaudeService',
    'ClaudeServiceError',
    'ClaudeAPIError',
    'SchemaValidationError',
    'TimeoutError',
    'PromptResult',
    # Service Factory
    'ServiceFactory',
    'ServiceFactoryError',
    # Audio (lazy-loaded)
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
    # Config
    'ConfigService',
    'ClaudeConfig',
    'ConfigError',
    'ConfigNotFoundError_',
    'ConfigAlreadyExistsError',
    'CorruptedConfigError',
]
