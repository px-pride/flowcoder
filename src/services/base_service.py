"""
Base Service Interface for AI Services

Defines the abstract interface that all AI services (Claude, Codex, Mock) must implement.
This ensures compatibility with ExecutionController and other components.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, AsyncIterator


class BaseService(ABC):
    """
    Abstract base class for AI services.

    All AI service implementations (ClaudeAgentService, CodexService, MockClaudeService)
    must inherit from this class and implement all abstract methods.

    This ensures they can be used interchangeably via dependency injection.
    """

    @abstractmethod
    async def start_session(self) -> None:
        """
        Start an AI session.

        Raises:
            Exception: If session startup fails
        """
        pass

    @abstractmethod
    async def end_session(self) -> None:
        """
        End the AI session.

        Raises:
            Exception: If session shutdown fails
        """
        pass

    @abstractmethod
    async def reset_session(self) -> None:
        """
        Reset the AI session by ending and restarting it.

        This clears all conversation history and starts fresh.

        Raises:
            Exception: If reset fails
        """
        pass

    @abstractmethod
    async def ensure_session(self) -> None:
        """
        Ensure an AI session is active, starting one if needed.

        This method is idempotent - safe to call multiple times.
        """
        pass

    @abstractmethod
    async def stream_prompt(self, prompt: str) -> AsyncIterator[str]:
        """
        Execute a prompt with streaming response.

        Args:
            prompt: The prompt text to send

        Yields:
            str: Response chunks as they arrive

        Raises:
            Exception: If streaming fails
        """
        pass

    @abstractmethod
    async def execute_prompt(
        self,
        prompt: str,
        output_schema: Optional[Dict[str, Any]] = None,
        retry_on_failure: bool = True
    ):
        """
        Execute a prompt and return the complete response.

        Args:
            prompt: The prompt text to send
            output_schema: Optional JSON schema for structured output
            retry_on_failure: Whether to retry on failure

        Returns:
            PromptResult with the response and optional structured output

        Raises:
            Exception: If execution fails
        """
        pass

    @abstractmethod
    def is_active(self) -> bool:
        """
        Check if session is active.

        Returns:
            True if session is active, False otherwise
        """
        pass

    @abstractmethod
    async def __aenter__(self):
        """Async context manager entry."""
        pass

    @abstractmethod
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        pass

    # Optional method for services that need to parse structured output
    # Not abstract since some services might handle this differently
    def _parse_structured_output(
        self,
        response_text: str,
        schema: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Parse structured output from response.

        Override this method if the service needs custom parsing logic.

        Args:
            response_text: The raw response text
            schema: JSON schema to validate against

        Returns:
            Parsed structured output as dictionary

        Raises:
            Exception: If parsing fails
        """
        raise NotImplementedError("Subclass must implement _parse_structured_output")
