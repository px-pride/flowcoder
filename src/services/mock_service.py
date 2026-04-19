"""Mock Claude service for testing without spawning the claude CLI."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Dict, Optional

from .base_service import BaseService
from .exceptions import (
    ClaudeServiceError,
    PromptResult,
    SchemaValidationError,
)

logger = logging.getLogger(__name__)


class MockClaudeService(BaseService):
    """Mock Claude service for testing without actual API calls."""

    def __init__(self, cwd: Optional[str] = None) -> None:
        self.cwd = cwd or "."
        self._session_active = False
        self._responses: Dict[str, str] = {}
        self._call_count = 0
        logger.info("MockClaudeService initialized")

    def set_response(self, prompt_substring: str, response: str) -> None:
        """Set a canned response for prompts containing a substring."""
        self._responses[prompt_substring] = response

    async def start_session(self) -> None:
        if self._session_active:
            logger.debug("Mock session already active, skipping start_session()")
            return
        self._session_active = True
        logger.info("Mock session started")

    async def ensure_session(self) -> None:
        if not self._session_active:
            await self.start_session()

    async def reset_session(self) -> None:
        logger.info("Resetting mock session...")
        await self.end_session()
        await self.start_session()
        logger.info("Mock session reset complete")

    async def end_session(self) -> None:
        if not self._session_active:
            return
        self._session_active = False
        logger.info("Mock session ended")

    async def stream_prompt(self, prompt: str):
        if not self._session_active:
            raise ClaudeServiceError("No active session")

        self._call_count += 1

        response_text = None
        for substring, response in self._responses.items():
            if substring.lower() in prompt.lower():
                response_text = response
                break

        if response_text is None:
            response_text = "Mock response for: " + prompt[:50]

        chunk_size = 10
        for i in range(0, len(response_text), chunk_size):
            yield response_text[i:i + chunk_size]
            await asyncio.sleep(0.01)

    async def execute_prompt(
        self,
        prompt: str,
        output_schema: Optional[Dict[str, Any]] = None,
        retry_on_failure: bool = True,
    ) -> PromptResult:
        if not self._session_active:
            raise ClaudeServiceError("No active session")

        self._call_count += 1

        response_text = None
        for substring, response in self._responses.items():
            if substring.lower() in prompt.lower():
                response_text = response
                break

        if response_text is None:
            if output_schema:
                response_text = self._generate_default_response(output_schema)
            else:
                response_text = "Mock response for: " + prompt[:50]

        structured_output = None
        if output_schema:
            try:
                structured_output = self._parse_structured_output(
                    response_text, output_schema
                )
            except SchemaValidationError:
                structured_output = self._generate_minimal_valid_output(output_schema)

        return PromptResult(
            raw_response=response_text,
            structured_output=structured_output,
            duration_ms=100,
            success=True,
        )

    def _generate_default_response(self, schema: Dict[str, Any]) -> str:
        output = self._generate_minimal_valid_output(schema)
        return f"```json\n{json.dumps(output, indent=2)}\n```"

    def _generate_minimal_valid_output(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        output: Dict[str, Any] = {}
        required = schema.get("required", [])
        properties = schema.get("properties", {})

        for field in required:
            if field in properties:
                field_type = properties[field].get("type", "string")
                if field_type == "string":
                    output[field] = "mock_value"
                elif field_type == "number":
                    output[field] = 42
                elif field_type == "boolean":
                    output[field] = True
                elif field_type == "array":
                    output[field] = []
                elif field_type == "object":
                    output[field] = {}

        return output

    def _parse_structured_output(
        self, response_text: str, schema: Dict[str, Any]
    ) -> Dict[str, Any]:
        json_text = self._extract_json_from_text(response_text)
        if not json_text:
            raise SchemaValidationError(
                "No JSON found in response. Mock service may not have provided structured output."
            )
        try:
            output = json.loads(json_text)
        except json.JSONDecodeError as e:
            raise SchemaValidationError(f"Invalid JSON in response: {e}")
        self._validate_against_schema(output, schema)
        return output

    def _extract_json_from_text(self, text: str) -> Optional[str]:
        match = re.search(r"```json\s*([\s\S]*?)\s*```", text)
        if match:
            return match.group(1).strip()

        match = re.search(r"```\s*([\s\S]*?)\s*```", text)
        if match:
            content = match.group(1).strip()
            if content.startswith("{") or content.startswith("["):
                return content

        match = re.search(r"\{[\s\S]*?\}", text)
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
        required = schema.get("required", [])
        for field in required:
            if field not in output:
                raise SchemaValidationError(
                    f"Required field '{field}' missing from output"
                )

    async def __aenter__(self):
        await self.start_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.end_session()
        return False

    def is_active(self) -> bool:
        return self._session_active
