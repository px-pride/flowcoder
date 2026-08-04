"""ClaudeEngineService — Claude session backed by flowcoder_engine.

Implements the same BaseService interface as ClaudeAgentService but uses
flowcoder_engine.ClaudeSession to spawn the system claude CLI directly.
This eliminates the claude-agent-sdk dependency and uses the system
claude binary (e.g. 2.1.114) instead of the SDK's bundled binary.

Yields raw dict messages from stream_prompt() — consumers must use
parse_sdk_message which handles both SDK objects and engine dicts.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
from datetime import datetime
from typing import Any, AsyncIterator, Callable, Dict, Optional

from flowcoder_engine.session import ClaudeSession

from .base_service import BaseService
from .exceptions import (
    ClaudeAPIError,
    ClaudeServiceError,
    PromptResult,
    SchemaValidationError,
)

logger = logging.getLogger(__name__)


class ClaudeEngineService(BaseService):
    """Claude session service backed by flowcoder_engine.ClaudeSession."""

    def __init__(
        self,
        cwd: Optional[str] = None,
        system_prompt: Optional[str] = None,
        permission_mode: str = "bypassPermissions",
        max_retries: int = 3,
        timeout_seconds: Optional[int] = 300,
        stderr_callback: Optional[Callable[[str], None]] = None,
        model: Optional[str] = None,
        extra_env: Optional[Dict[str, str]] = None,
    ) -> None:
        self.cwd = cwd or "."
        self.system_prompt = system_prompt
        self.permission_mode = permission_mode
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds
        self.stderr_callback = stderr_callback
        self.model = model
        self.extra_env = extra_env or {}

        self._session: Optional[ClaudeSession] = None
        self._session_active = False

        logger.info(
            f"ClaudeEngineService initialized (cwd={cwd}, "
            f"mode={permission_mode}, model={model})"
        )

    def _build_claude_cmd(self) -> list[str]:
        """Build the inner claude CLI command."""
        binary = shutil.which("claude") or "claude"
        cmd = [
            binary,
            "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--permission-mode", self.permission_mode,
            "--setting-sources", "user,project,local",
        ]
        if self.model:
            cmd.extend(["--model", self.model])
        if self.system_prompt:
            cmd.extend(["--system-prompt", self.system_prompt])
        return cmd

    async def start_session(self) -> None:
        if self._session_active:
            logger.debug("Session already active, skipping start_session()")
            return

        try:
            env = {"CLAUDE_CODE_MAX_OUTPUT_TOKENS": "64000"}
            env.update(self.extra_env)

            self._session = ClaudeSession(
                name=f"gui-{id(self)}",
                claude_cmd=self._build_claude_cmd(),
                env_overrides=env,
                cwd=self.cwd,
            )
            await self._session.start()
            self._session_active = True

            logger.info("Engine session started (system claude binary)")
            if self.stderr_callback:
                try:
                    self.stderr_callback("[System] Claude session initialized successfully")
                except Exception as e:
                    logger.error(f"Stderr callback failed: {e}")

            asyncio.create_task(self._forward_stderr())

        except Exception as e:
            logger.error(f"Failed to start engine session: {e}")
            raise ClaudeServiceError(f"Could not start session: {e}")

    async def _forward_stderr(self) -> None:
        """Forward stderr lines from the inner subprocess to the callback."""
        if not self._session or not self._session._process:
            return
        try:
            while True:
                line = await self._session._process.read_stderr()
                if line is None:
                    return
                if self.stderr_callback:
                    try:
                        self.stderr_callback(line)
                    except Exception:
                        pass
        except Exception:
            pass

    async def ensure_session(self) -> None:
        if not self._session_active:
            await self.start_session()

    async def reset_session(self) -> None:
        logger.info("Resetting engine session...")
        await self.end_session()
        await self.start_session()

    async def end_session(self) -> None:
        if not self._session_active:
            logger.warning("No active session to end")
            return
        try:
            if self._session:
                await asyncio.wait_for(self._session.stop(), timeout=5.0)
                logger.info("Engine session ended")
        except asyncio.TimeoutError:
            logger.warning("Session stop timed out")
        except Exception as e:
            logger.error(f"Error ending session: {e}")
        finally:
            self._session = None
            self._session_active = False

    async def stream_prompt(self, prompt: str) -> AsyncIterator[Dict[str, Any]]:
        """Yield raw engine dict messages as they arrive.

        Format per engine.session.stream_query: type=system|assistant|
        stream_event|result. Consumers should use parse_sdk_message
        (which handles dicts) to extract text.
        """
        if not self._session_active or not self._session:
            raise ClaudeServiceError("No active session. Call start_session() first.")

        try:
            async for chunk in self._session.stream_query(prompt):
                yield chunk
        except Exception as e:
            logger.error(f"Streaming error: {e}", exc_info=True)
            raise ClaudeAPIError(f"Failed to stream prompt: {e}")

    async def execute_prompt(
        self,
        prompt: str,
        output_schema: Optional[Dict[str, Any]] = None,
        retry_on_failure: bool = True,
    ) -> PromptResult:
        if not self._session_active or not self._session:
            raise ClaudeServiceError("No active session. Call start_session() first.")

        start_time = datetime.now()
        attempt = 0
        last_error = None

        while attempt < (self.max_retries if retry_on_failure else 1):
            attempt += 1
            try:
                result = await self._session.query(prompt)
                response_text = result.response_text
                duration_ms = (
                    result.duration_ms
                    or int((datetime.now() - start_time).total_seconds() * 1000)
                )

                structured_output = None
                if output_schema:
                    try:
                        structured_output = self._parse_structured_output(
                            response_text, output_schema
                        )
                    except SchemaValidationError as e:
                        if attempt >= self.max_retries:
                            return PromptResult(
                                raw_response=response_text,
                                structured_output=None,
                                duration_ms=duration_ms,
                                success=False,
                                error=f"Schema validation failed: {e}",
                            )
                        raise

                logger.info(f"Prompt executed successfully in {duration_ms}ms")
                return PromptResult(
                    raw_response=response_text,
                    structured_output=structured_output,
                    duration_ms=duration_ms,
                )

            except SchemaValidationError:
                if attempt < self.max_retries:
                    logger.warning(
                        f"Schema validation failed on attempt {attempt}, retrying..."
                    )
                    last_error = "Schema validation failed"
                    continue
                raise

            except Exception as e:
                last_error = str(e)
                logger.error(
                    f"Prompt execution failed (attempt {attempt}/{self.max_retries}): {e}"
                )
                if attempt >= self.max_retries:
                    raise ClaudeAPIError(
                        f"Failed after {attempt} attempts: {last_error}"
                    )
                await asyncio.sleep(min(2 ** attempt, 10))

        raise ClaudeAPIError(f"Failed after {self.max_retries} attempts: {last_error}")

    # -- structured output parsing (copied from ClaudeAgentService) --

    def _parse_structured_output(
        self, response_text: str, schema: Dict[str, Any]
    ) -> Dict[str, Any]:
        json_text = self._extract_json_from_text(response_text)
        if not json_text:
            raise SchemaValidationError(
                "No JSON found in response. "
                "Claude may not have provided structured output."
            )
        try:
            output = json.loads(json_text)
        except json.JSONDecodeError as e:
            raise SchemaValidationError(f"Invalid JSON in response: {e}")
        self._validate_against_schema(output, schema)
        return output

    def _extract_json_from_text(self, text: str) -> Optional[str]:
        match = re.search(r'```json\s*([\s\S]*?)\s*```', text)
        if match:
            extracted = match.group(1).strip()
            if extracted and (extracted.startswith('{') or extracted.startswith('[')):
                try:
                    json.loads(extracted)
                    return extracted
                except json.JSONDecodeError:
                    pass

        match = re.search(r'```\s*([\s\S]*?)\s*```', text)
        if match:
            content = match.group(1).strip()
            if content.startswith('{') or content.startswith('['):
                try:
                    json.loads(content)
                    return content
                except json.JSONDecodeError:
                    pass

        match = re.search(r'\{[\s\S]*?\}', text)
        if match:
            try:
                json.loads(match.group(0))
                return match.group(0)
            except json.JSONDecodeError:
                pass

        return None

    def _validate_against_schema(
        self, output: Dict[str, Any], schema: Dict[str, Any]
    ) -> None:
        required = schema.get('required', [])
        for field in required:
            if field not in output:
                raise SchemaValidationError(
                    f"Required field '{field}' missing from output"
                )

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

    async def __aenter__(self):
        await self.start_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.end_session()
        return False

    def is_active(self) -> bool:
        return self._session_active
