"""Shared exception types and result containers for FlowCoder services."""

from __future__ import annotations

from typing import Any, Dict, Optional


class ClaudeServiceError(Exception):
    """Base exception for Claude service operations."""


class ClaudeAPIError(ClaudeServiceError):
    """Raised when the underlying Claude CLI returns an error."""


class SchemaValidationError(ClaudeServiceError):
    """Raised when a response doesn't match the expected schema."""


class TimeoutError(ClaudeServiceError):
    """Raised when an operation exceeds its timeout."""


class PromptResult:
    """Result of a prompt execution."""

    def __init__(
        self,
        raw_response: str,
        structured_output: Optional[Dict[str, Any]] = None,
        duration_ms: Optional[int] = None,
        success: bool = True,
        error: Optional[str] = None,
    ) -> None:
        self.raw_response = raw_response
        self.structured_output = structured_output
        self.duration_ms = duration_ms
        self.success = success
        self.error = error

    def __repr__(self) -> str:
        status = "success" if self.success else "error"
        return f"PromptResult(status={status}, duration={self.duration_ms}ms)"
