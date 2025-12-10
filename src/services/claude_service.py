"""
Claude Agent Service for FlowCoder

Wraps the Claude Agent SDK for executing prompts with structured output support.
"""

import asyncio
import json
import logging
import os
import re
import signal
from typing import Optional, Dict, Any
from datetime import datetime

from .base_service import BaseService

try:
    from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
    CLAUDE_SDK_AVAILABLE = True
except ImportError:
    CLAUDE_SDK_AVAILABLE = False
    ClaudeSDKClient = None
    ClaudeAgentOptions = None


logger = logging.getLogger(__name__)


class ClaudeServiceError(Exception):
    """Base exception for Claude service operations."""
    pass


class ClaudeAPIError(ClaudeServiceError):
    """Raised when Claude API returns an error."""
    pass


class SchemaValidationError(ClaudeServiceError):
    """Raised when response doesn't match expected schema."""
    pass


class TimeoutError(ClaudeServiceError):
    """Raised when operation times out."""
    pass


class PromptResult:
    """Result of a prompt execution."""

    def __init__(
        self,
        raw_response: str,
        structured_output: Optional[Dict[str, Any]] = None,
        duration_ms: Optional[int] = None,
        success: bool = True,
        error: Optional[str] = None
    ):
        self.raw_response = raw_response
        self.structured_output = structured_output
        self.duration_ms = duration_ms
        self.success = success
        self.error = error

    def __repr__(self) -> str:
        status = "success" if self.success else "error"
        return f"PromptResult(status={status}, duration={self.duration_ms}ms)"


class ClaudeAgentService(BaseService):
    """Service for executing prompts via Claude Agent SDK."""

    def __init__(
        self,
        cwd: Optional[str] = None,
        system_prompt: Optional[str] = None,
        permission_mode: str = "plan",
        max_retries: int = 3,
        timeout_seconds: int = 300,
        stderr_callback: Optional[callable] = None,
        model: Optional[str] = "claude-opus-4-5"
    ):
        """
        Initialize the Claude Agent Service.

        Args:
            cwd: Working directory for Claude operations
            system_prompt: System prompt to use
            permission_mode: Permission mode (plan, acceptEdits, bypassPermissions, default)
            max_retries: Maximum number of retry attempts on failure
            timeout_seconds: Timeout for operations in seconds
            stderr_callback: Optional callback for Claude Code's verbose output (tool calls, thinking, etc.)
            model: Optional model identifier (e.g., "claude-haiku-4", "claude-sonnet-4-5-20250929")
        """
        if not CLAUDE_SDK_AVAILABLE:
            raise ClaudeServiceError(
                "Claude Agent SDK not installed. "
                "Run: pip install claude-agent-sdk"
            )

        self.cwd = cwd or "."
        self.system_prompt = system_prompt
        self.permission_mode = permission_mode
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds
        self.stderr_callback = stderr_callback
        self.model = model

        self._client: Optional[Any] = None
        self._session_active = False

        logger.info(f"ClaudeAgentService initialized (cwd={cwd}, mode={permission_mode}, model={model})")

    async def start_session(self) -> None:
        """
        Start a Claude session.

        Raises:
            ClaudeServiceError: If session already active or startup fails
        """
        if self._session_active:
            logger.debug("Session already active, skipping start_session()")
            return  # Allow multiple calls - session already running

        try:
            # Build options dict, only including system_prompt if provided
            # When system_prompt is None/empty, we don't pass it at all so
            # Claude Code uses its built-in default (passing None would cause
            # the SDK to pass --system-prompt "" which overrides the default)
            options_kwargs = {
                "permission_mode": self.permission_mode,
                "cwd": self.cwd,
                "model": self.model,
                "env": {
                    "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "64000"
                },
                "include_partial_messages": True,  # Show intermediate reasoning as it happens
                "stderr": self.stderr_callback  # Capture tool calls, thinking, file operations
            }

            # Only add system_prompt if it's a non-empty string
            if self.system_prompt:
                options_kwargs["system_prompt"] = self.system_prompt

            options = ClaudeAgentOptions(**options_kwargs)

            self._client = ClaudeSDKClient(options=options)
            await self._client.__aenter__()
            self._session_active = True

            logger.info("Claude session started with max_output_tokens=64000, streaming enabled")

            # Notify via callback that session is ready
            if self.stderr_callback:
                try:
                    self.stderr_callback("[System] Claude session initialized successfully")
                except Exception as e:
                    logger.error(f"Stderr callback failed: {e}")

        except Exception as e:
            logger.error(f"Failed to start Claude session: {e}")
            raise ClaudeServiceError(f"Could not start session: {e}")

    async def ensure_session(self) -> None:
        """
        Ensure a Claude session is active, starting one if needed.

        This method is idempotent - safe to call multiple times.
        """
        if not self._session_active:
            await self.start_session()

    async def reset_session(self) -> None:
        """
        Reset the Claude session by ending and restarting it.

        This clears all conversation history and starts fresh.

        Raises:
            ClaudeServiceError: If reset fails
        """
        logger.info("Resetting Claude session...")
        await self.end_session()
        await self.start_session()
        logger.info("Claude session reset complete")

    async def end_session(self) -> None:
        """
        End the Claude session.

        Attempts graceful shutdown first, then force-kills if necessary.
        """
        if not self._session_active:
            logger.warning("No active session to end")
            return

        # Get the process PID before attempting shutdown (for force-kill fallback)
        # The SDK stores the process in _transport._process._process (asyncio.subprocess.Process)
        client_pid = None
        try:
            if self._client and hasattr(self._client, '_transport'):
                transport = self._client._transport
                if hasattr(transport, '_process') and transport._process:
                    # transport._process is a wrapper, the actual Process is in _process
                    inner_process = getattr(transport._process, '_process', None)
                    if inner_process and hasattr(inner_process, 'pid'):
                        client_pid = inner_process.pid
                        logger.debug(f"Claude client process PID: {client_pid}")
        except Exception as e:
            logger.debug(f"Could not get client PID: {e}")

        try:
            if self._client:
                # Try graceful shutdown with timeout
                try:
                    await asyncio.wait_for(
                        self._client.__aexit__(None, None, None),
                        timeout=5.0
                    )
                    logger.info("Claude session ended gracefully")
                except asyncio.TimeoutError:
                    logger.warning("Graceful shutdown timed out, forcing termination")
                    self._force_kill_client_sync(client_pid)
                except asyncio.CancelledError:
                    # SDK sometimes raises CancelledError from its internal cancel scopes
                    logger.warning("Shutdown cancelled by SDK, forcing termination")
                    self._force_kill_client_sync(client_pid)

                self._client = None

        except Exception as e:
            logger.error(f"Error ending Claude session: {e}")
            # Try force kill as last resort
            self._force_kill_client_sync(client_pid)
        finally:
            # Always mark session as inactive
            self._session_active = False
            self._client = None

    def _force_kill_client_sync(self, pid: Optional[int]) -> None:
        """
        Force kill the Claude client process (synchronous version).

        Uses synchronous time.sleep instead of async to avoid cancel scope issues.

        Args:
            pid: Process ID to kill, or None to skip
        """
        import time

        if pid is None:
            logger.warning("No PID available for force kill")
            return

        try:
            # First try SIGTERM
            logger.info(f"Sending SIGTERM to Claude process {pid}")
            os.kill(pid, signal.SIGTERM)

            # Wait briefly for graceful termination (sync)
            time.sleep(1.0)

            # Check if still running and send SIGKILL if needed
            try:
                os.kill(pid, 0)  # Check if process exists
                logger.warning(f"Process {pid} still running, sending SIGKILL")
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                logger.info(f"Process {pid} terminated after SIGTERM")

        except ProcessLookupError:
            logger.debug(f"Process {pid} already terminated")
        except Exception as e:
            logger.error(f"Error force-killing process {pid}: {e}")

    async def stream_prompt(self, prompt: str):
        """
        Execute a prompt with Claude and yield response chunks in real-time.

        Args:
            prompt: The prompt text to send to Claude

        Yields:
            str: Response chunks as they arrive from Claude

        Raises:
            ClaudeServiceError: If no active session
            ClaudeAPIError: If Claude API fails
        """
        if not self._session_active or not self._client:
            raise ClaudeServiceError("No active session. Call start_session() first.")

        try:
            # Send prompt to Claude
            await self._client.query(prompt)

            # Yield response chunks as they arrive
            async for chunk in self._client.receive_response():
                yield str(chunk)

        except Exception as e:
            logger.error(f"Streaming error: {e}", exc_info=True)
            raise ClaudeAPIError(f"Failed to stream prompt: {e}")

    async def execute_prompt(
        self,
        prompt: str,
        output_schema: Optional[Dict[str, Any]] = None,
        retry_on_failure: bool = True
    ) -> PromptResult:
        """
        Execute a prompt with Claude.

        Args:
            prompt: The prompt text to send to Claude
            output_schema: Optional JSON schema for structured output
            retry_on_failure: Whether to retry on failure

        Returns:
            PromptResult with the response and optional structured output

        Raises:
            ClaudeServiceError: If no active session
            ClaudeAPIError: If Claude API fails after retries
            SchemaValidationError: If response doesn't match schema
        """
        if not self._session_active or not self._client:
            raise ClaudeServiceError("No active session. Call start_session() first.")

        start_time = datetime.now()
        attempt = 0
        last_error = None

        while attempt < (self.max_retries if retry_on_failure else 1):
            attempt += 1

            try:
                # Send prompt to Claude
                await self._client.query(prompt)

                # Collect response
                response_text = ""
                async for message in self._client.receive_response():
                    response_text += str(message)

                # Calculate duration
                duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

                # Parse structured output if schema provided
                structured_output = None
                if output_schema:
                    try:
                        structured_output = self._parse_structured_output(
                            response_text,
                            output_schema
                        )
                    except SchemaValidationError as e:
                        if attempt >= self.max_retries:
                            # On final attempt, return error result instead of raising
                            logger.warning(f"Schema validation failed after {attempt} attempts: {e}")
                            return PromptResult(
                                raw_response=response_text,
                                structured_output=None,
                                duration_ms=duration_ms,
                                success=False,
                                error=f"Schema validation failed: {e}"
                            )
                        raise

                logger.info(f"Prompt executed successfully in {duration_ms}ms")
                return PromptResult(
                    raw_response=response_text,
                    structured_output=structured_output,
                    duration_ms=duration_ms
                )

            except SchemaValidationError:
                # Re-raise schema errors to retry
                if attempt < self.max_retries:
                    logger.warning(f"Schema validation failed on attempt {attempt}, retrying...")
                    last_error = "Schema validation failed"
                    continue
                raise

            except Exception as e:
                last_error = str(e)
                logger.error(f"Prompt execution failed (attempt {attempt}/{self.max_retries}): {e}")

                if attempt >= self.max_retries:
                    duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                    raise ClaudeAPIError(f"Failed after {attempt} attempts: {last_error}")

                # Wait before retry (exponential backoff)
                import asyncio
                await asyncio.sleep(min(2 ** attempt, 10))

        # Should not reach here, but just in case
        raise ClaudeAPIError(f"Failed after {self.max_retries} attempts: {last_error}")

    def _parse_structured_output(
        self,
        response_text: str,
        schema: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Parse structured output from Claude's response.

        Args:
            response_text: The raw response text from Claude
            schema: JSON schema to validate against

        Returns:
            Parsed structured output as dictionary

        Raises:
            SchemaValidationError: If parsing or validation fails
        """
        # Try to extract JSON from response
        json_text = self._extract_json_from_text(response_text)

        if not json_text:
            raise SchemaValidationError(
                "No JSON found in response. "
                "Claude may not have provided structured output."
            )

        # Parse JSON
        try:
            output = json.loads(json_text)
        except json.JSONDecodeError as e:
            raise SchemaValidationError(f"Invalid JSON in response: {e}")

        # Validate against schema (basic validation)
        self._validate_against_schema(output, schema)

        return output

    def _extract_json_from_text(self, text: str) -> Optional[str]:
        """
        Extract JSON from Claude's response text.

        Looks for JSON in markdown code blocks or standalone JSON objects.

        Args:
            text: Response text to search

        Returns:
            Extracted JSON string or None
        """
        # Try markdown code block with json language
        match = re.search(r'```json\s*([\s\S]*?)\s*```', text)
        if match:
            extracted = match.group(1).strip()

            # Validate it's not empty and starts with { or [
            if extracted and (extracted.startswith('{') or extracted.startswith('[')):
                # Verify it's valid JSON before returning
                try:
                    json.loads(extracted)
                    return extracted
                except json.JSONDecodeError:
                    # Not valid JSON, try next pattern
                    pass
            else:
                # Empty or doesn't look like JSON, try next pattern
                pass

        # Try markdown code block without language
        match = re.search(r'```\s*([\s\S]*?)\s*```', text)
        if match:
            content = match.group(1).strip()
            # Check if it looks like JSON
            if content.startswith('{') or content.startswith('['):
                # Verify it's valid JSON before returning
                try:
                    json.loads(content)
                    return content
                except json.JSONDecodeError:
                    # Not valid JSON, try next pattern
                    pass

        # Try to find standalone JSON object
        # Use NON-GREEDY match to avoid capturing multiple objects
        match = re.search(r'\{[\s\S]*?\}', text)
        if match:
            try:
                # Validate it's actual JSON
                json.loads(match.group(0))
                return match.group(0)
            except json.JSONDecodeError:
                pass

        return None

    def _validate_against_schema(
        self,
        output: Dict[str, Any],
        schema: Dict[str, Any]
    ) -> None:
        """
        Basic validation of output against schema.

        Args:
            output: The parsed output
            schema: JSON schema to validate against

        Raises:
            SchemaValidationError: If validation fails
        """
        # Check required fields if specified
        required = schema.get('required', [])
        for field in required:
            if field not in output:
                raise SchemaValidationError(
                    f"Required field '{field}' missing from output"
                )

        # Check property types if specified
        properties = schema.get('properties', {})
        for field, field_schema in properties.items():
            if field in output:
                expected_type = field_schema.get('type')
                actual_value = output[field]

                if expected_type == 'string' and not isinstance(actual_value, str):
                    raise SchemaValidationError(
                        f"Field '{field}' should be string, got {type(actual_value).__name__}"
                    )
                elif expected_type == 'number' and not isinstance(actual_value, (int, float)):
                    raise SchemaValidationError(
                        f"Field '{field}' should be number, got {type(actual_value).__name__}"
                    )
                elif expected_type == 'boolean' and not isinstance(actual_value, bool):
                    raise SchemaValidationError(
                        f"Field '{field}' should be boolean, got {type(actual_value).__name__}"
                    )
                elif expected_type == 'array' and not isinstance(actual_value, list):
                    raise SchemaValidationError(
                        f"Field '{field}' should be array, got {type(actual_value).__name__}"
                    )
                elif expected_type == 'object' and not isinstance(actual_value, dict):
                    raise SchemaValidationError(
                        f"Field '{field}' should be object, got {type(actual_value).__name__}"
                    )

        logger.debug("Schema validation passed")

    async def __aenter__(self):
        """Async context manager entry."""
        await self.start_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.end_session()
        return False

    def is_active(self) -> bool:
        """Check if session is active."""
        return self._session_active


class MockClaudeService(BaseService):
    """Mock Claude service for testing without actual API calls."""

    def __init__(self, cwd: Optional[str] = None):
        """Initialize mock service."""
        self.cwd = cwd or "."
        self._session_active = False
        self._responses: Dict[str, str] = {}
        self._call_count = 0

        logger.info("MockClaudeService initialized")

    def set_response(self, prompt_substring: str, response: str) -> None:
        """
        Set a canned response for prompts containing a substring.

        Args:
            prompt_substring: Substring to match in prompts
            response: Response to return
        """
        self._responses[prompt_substring] = response

    async def start_session(self) -> None:
        """Start mock session."""
        if self._session_active:
            logger.debug("Mock session already active, skipping start_session()")
            return  # Allow multiple calls - session already running
        self._session_active = True
        logger.info("Mock session started")

    async def ensure_session(self) -> None:
        """
        Ensure a mock session is active, starting one if needed.

        This method is idempotent - safe to call multiple times.
        """
        if not self._session_active:
            await self.start_session()

    async def reset_session(self) -> None:
        """
        Reset the mock session by ending and restarting it.

        This clears all conversation history and starts fresh.
        """
        logger.info("Resetting mock session...")
        await self.end_session()
        await self.start_session()
        logger.info("Mock session reset complete")

    async def end_session(self) -> None:
        """End mock session."""
        if not self._session_active:
            return
        self._session_active = False
        logger.info("Mock session ended")

    async def stream_prompt(self, prompt: str):
        """
        Stream mock prompt response in chunks (simulates real streaming).

        Args:
            prompt: The prompt text

        Yields:
            str: Response chunks
        """
        if not self._session_active:
            raise ClaudeServiceError("No active session")

        self._call_count += 1

        # Find matching response
        response_text = None
        for substring, response in self._responses.items():
            if substring.lower() in prompt.lower():
                response_text = response
                break

        if response_text is None:
            response_text = "Mock response for: " + prompt[:50]

        # Yield response in chunks to simulate streaming
        chunk_size = 10  # Characters per chunk
        for i in range(0, len(response_text), chunk_size):
            chunk = response_text[i:i + chunk_size]
            yield chunk
            # Small delay to simulate real streaming (optional)
            await asyncio.sleep(0.01)

    async def execute_prompt(
        self,
        prompt: str,
        output_schema: Optional[Dict[str, Any]] = None,
        retry_on_failure: bool = True
    ) -> PromptResult:
        """
        Execute mock prompt.

        Returns pre-configured response based on prompt content.
        """
        if not self._session_active:
            raise ClaudeServiceError("No active session")

        self._call_count += 1

        # Find matching response
        response_text = None
        for substring, response in self._responses.items():
            if substring.lower() in prompt.lower():
                response_text = response
                break

        if response_text is None:
            # Default response
            if output_schema:
                # Generate simple JSON response matching schema
                response_text = self._generate_default_response(output_schema)
            else:
                response_text = "Mock response for: " + prompt[:50]

        # Parse structured output if needed
        structured_output = None
        if output_schema:
            try:
                service = ClaudeAgentService(cwd=self.cwd)
                structured_output = service._parse_structured_output(
                    response_text,
                    output_schema
                )
            except SchemaValidationError:
                # If default response doesn't match schema, create minimal valid response
                structured_output = self._generate_minimal_valid_output(output_schema)

        return PromptResult(
            raw_response=response_text,
            structured_output=structured_output,
            duration_ms=100,  # Mock duration
            success=True
        )

    def _generate_default_response(self, schema: Dict[str, Any]) -> str:
        """Generate a default JSON response matching schema."""
        output = self._generate_minimal_valid_output(schema)
        return f"```json\n{json.dumps(output, indent=2)}\n```"

    def _generate_minimal_valid_output(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """Generate minimal valid output for a schema."""
        output = {}

        required = schema.get('required', [])
        properties = schema.get('properties', {})

        for field in required:
            if field in properties:
                field_type = properties[field].get('type', 'string')

                if field_type == 'string':
                    output[field] = "mock_value"
                elif field_type == 'number':
                    output[field] = 42
                elif field_type == 'boolean':
                    output[field] = True
                elif field_type == 'array':
                    output[field] = []
                elif field_type == 'object':
                    output[field] = {}

        return output

    def _parse_structured_output(
        self,
        response_text: str,
        schema: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Parse structured output from response.

        Args:
            response_text: The raw response text
            schema: JSON schema to validate against

        Returns:
            Parsed structured output as dictionary

        Raises:
            SchemaValidationError: If parsing or validation fails
        """
        # Try to extract JSON from response
        json_text = self._extract_json_from_text(response_text)

        if not json_text:
            raise SchemaValidationError(
                "No JSON found in response. "
                "Claude may not have provided structured output."
            )

        # Parse JSON
        try:
            output = json.loads(json_text)
        except json.JSONDecodeError as e:
            raise SchemaValidationError(f"Invalid JSON in response: {e}")

        # Validate against schema (basic validation)
        self._validate_against_schema(output, schema)

        return output

    def _extract_json_from_text(self, text: str) -> Optional[str]:
        """
        Extract JSON from response text.

        Args:
            text: Response text to search

        Returns:
            Extracted JSON string or None
        """
        # Try markdown code block with json language
        match = re.search(r'```json\s*([\s\S]*?)\s*```', text)
        if match:
            return match.group(1).strip()

        # Try markdown code block without language
        match = re.search(r'```\s*([\s\S]*?)\s*```', text)
        if match:
            content = match.group(1).strip()
            # Check if it looks like JSON
            if content.startswith('{') or content.startswith('['):
                return content

        # Try to find standalone JSON object
        # Use NON-GREEDY match to avoid capturing multiple objects
        match = re.search(r'\{[\s\S]*?\}', text)
        if match:
            try:
                # Validate it's actual JSON
                json.loads(match.group(0))
                return match.group(0)
            except json.JSONDecodeError:
                pass

        return None

    def _validate_against_schema(
        self,
        output: Dict[str, Any],
        schema: Dict[str, Any]
    ) -> None:
        """
        Basic validation of output against schema.

        Args:
            output: The parsed output
            schema: JSON schema to validate against

        Raises:
            SchemaValidationError: If validation fails
        """
        # Check required fields if specified
        required = schema.get('required', [])
        for field in required:
            if field not in output:
                raise SchemaValidationError(
                    f"Required field '{field}' missing from output"
                )

    async def __aenter__(self):
        """Async context manager entry."""
        await self.start_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.end_session()
        return False

    def is_active(self) -> bool:
        """Check if session is active."""
        return self._session_active

    def get_call_count(self) -> int:
        """Get number of execute_prompt calls."""
        return self._call_count
