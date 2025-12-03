"""
Codex Service for FlowCoder

Wraps OpenAI's Codex TypeScript SDK by spawning Node.js processes.
"""

import asyncio
import json
import logging
import re
import shutil
from typing import Optional, Dict, Any, AsyncIterator
from datetime import datetime
from pathlib import Path
import tempfile

from .base_service import BaseService
from .claude_service import (
    ClaudeServiceError,
    PromptResult,
    SchemaValidationError
)

# Check if Node.js and npm are available
NODE_AVAILABLE = shutil.which("node") is not None
NPM_AVAILABLE = shutil.which("npm") is not None
CODEX_SDK_AVAILABLE = NODE_AVAILABLE and NPM_AVAILABLE

logger = logging.getLogger(__name__)


class CodexServiceError(ClaudeServiceError):
    """Base exception for Codex service operations."""
    pass


class CodexService(BaseService):
    """Service for executing prompts via OpenAI Codex TypeScript SDK."""

    def __init__(
        self,
        cwd: Optional[str] = None,
        system_prompt: Optional[str] = None,
        max_retries: int = 3,
        timeout_seconds: int = 300,
        stderr_callback: Optional[callable] = None
    ):
        """
        Initialize the Codex Service.

        Args:
            cwd: Working directory for Codex operations
            system_prompt: System prompt (prepended to prompts)
            max_retries: Maximum retry attempts
            timeout_seconds: Timeout for operations
            stderr_callback: Optional callback for stderr output
        """
        if not CODEX_SDK_AVAILABLE:
            missing = []
            if not NODE_AVAILABLE:
                missing.append("Node.js")
            if not NPM_AVAILABLE:
                missing.append("npm")
            raise CodexServiceError(
                f"Missing dependencies: {', '.join(missing)}. "
                f"Install Node.js v18+ and Codex SDK: https://developers.openai.com/codex/sdk/"
            )

        self.cwd = Path(cwd or ".").resolve()
        self.system_prompt = system_prompt
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds
        self.stderr_callback = stderr_callback

        self._session_active = False
        self._thread_id: Optional[str] = None
        self._codex_wrapper_script: Optional[Path] = None
        self._node_process: Optional[asyncio.subprocess.Process] = None
        self._command_id = 0  # For tracking async commands
        self._stderr_monitor_task: Optional[asyncio.Task] = None  # Track for cleanup

        logger.info(f"CodexService initialized (cwd={self.cwd})")

    async def start_session(self) -> None:
        """
        Start a Codex session by creating wrapper script.

        Raises:
            CodexServiceError: If session startup fails
        """
        if self._session_active:
            logger.debug("Session already active")
            return

        try:
            # Create/reuse wrapper script for Codex TypeScript SDK
            self._create_wrapper_script()

            # Start persistent Node.js process
            # Wrapper script is in project root, so Node naturally finds node_modules
            self._node_process = await asyncio.create_subprocess_exec(
                "node",
                str(self._codex_wrapper_script),
                cwd=str(self.cwd),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            # Start stderr monitoring task (tracked for cleanup)
            self._stderr_monitor_task = asyncio.create_task(self._monitor_stderr())

            # Wait for "ready" message
            ready_line = await asyncio.wait_for(
                self._node_process.stdout.readline(),
                timeout=30
            )

            if not ready_line:
                # Process died, check stderr
                stderr = await self._node_process.stderr.read()
                raise CodexServiceError(f"Node process failed to start: {stderr.decode()}")

            ready_msg = json.loads(ready_line.decode())
            logger.debug(f"Received startup message: {ready_msg}")

            if ready_msg.get('type') == 'error':
                raise CodexServiceError(f"Node process error: {ready_msg.get('error')}")

            if ready_msg.get('type') != 'ready':
                raise CodexServiceError(f"Unexpected startup message: {ready_msg}")

            self._thread_id = ready_msg.get('threadId')
            self._session_active = True

            logger.info(f"Codex session started (thread_id={self._thread_id})")

            if not self._thread_id:
                logger.error("Warning: thread_id is None - Codex thread may not have started properly")

        except Exception as e:
            logger.error(f"Failed to start Codex session: {e}")
            # Cleanup on failure
            if self._node_process:
                self._node_process.kill()
                await self._node_process.wait()
            raise CodexServiceError(f"Could not start session: {e}")

    async def _monitor_stderr(self) -> None:
        """Monitor stderr from Node.js process and log errors and debug info."""
        if not self._node_process or not self._node_process.stderr:
            return

        try:
            while self._session_active and self._node_process:
                line = await self._node_process.stderr.readline()
                if not line:
                    break

                error_msg = line.decode().strip()
                if error_msg:
                    # Try to parse as JSON to check if it's a debug message
                    try:
                        import json
                        msg_obj = json.loads(error_msg)
                        if msg_obj.get('type') == 'debug':
                            logger.info(f"[Codex Debug] {msg_obj.get('message')}")
                            logger.info(f"  Keys: {msg_obj.get('keys')}")
                            logger.info(f"  Result structure:\n{msg_obj.get('result')}")
                        else:
                            logger.error(f"[Node.js stderr] {error_msg}")
                    except json.JSONDecodeError:
                        # Not JSON, just log as regular error
                        logger.error(f"[Node.js stderr] {error_msg}")

                    # Also send to callback if provided
                    if self.stderr_callback:
                        try:
                            self.stderr_callback(error_msg)
                        except Exception as e:
                            logger.warning(f"Stderr callback failed: {e}")

        except Exception as e:
            logger.debug(f"Stderr monitor ended: {e}")

    def _create_wrapper_script(self) -> None:
        """Create Node.js wrapper script for Codex SDK (once, reused for all sessions)."""
        # Use permanent location in project root
        project_root = Path(__file__).parent.parent.parent
        wrapper_dir = project_root / ".flowcoder"
        wrapper_dir.mkdir(exist_ok=True)
        self._codex_wrapper_script = wrapper_dir / "codex_wrapper.mjs"

        # Only create if doesn't exist (reuse for all sessions)
        if self._codex_wrapper_script.exists():
            logger.debug(f"Reusing existing wrapper script at {self._codex_wrapper_script}")
            return

        # Long-lived process that reads commands from stdin and maintains Codex thread
        wrapper_code = """
import { Codex } from '@openai/codex-sdk';
import * as readline from 'readline';

const codex = new Codex();
let thread = null;

// Initialize thread on startup
async function initThread() {
    try {
        thread = await codex.startThread({
            skipGitRepoCheck: true,
            sandboxMode: 'danger-full-access',
            networkAccessEnabled: true
        });

        console.log(JSON.stringify({
            type: 'ready',
            threadId: 'codex-session-active'  // Thread ID is generated on first run
        }));
    } catch (error) {
        console.error(JSON.stringify({
            type: 'error',
            error: error.message
        }));
        process.exit(1);
    }
}

// Extract text from Codex SDK result
// According to official docs: https://github.com/openai/codex/tree/main/sdk/typescript
// thread.run() returns an object with finalResponse property containing the text output
function extractText(result) {
    // Handle string results directly
    if (typeof result === 'string') {
        return result;
    }

    // According to Codex SDK documentation, the response has:
    // - finalResponse: string containing the agent's text output
    // - items: array of structured completion items
    // - usage: token usage information

    if (result && result.finalResponse !== undefined && result.finalResponse !== null) {
        return String(result.finalResponse);
    }

    // Log error if finalResponse is missing (this shouldn't happen with real SDK)
    console.error(JSON.stringify({
        type: 'error',
        message: 'Codex SDK result missing finalResponse property',
        resultType: typeof result,
        keys: result ? Object.keys(result) : [],
        fullResult: JSON.stringify(result, null, 2)
    }));

    // Fallback: return JSON stringification
    return JSON.stringify(result, null, 2);
}

// Process a command
async function processCommand(cmd) {
    try {
        if (cmd.type === 'run') {
            // Execute prompt on existing thread
            const result = await thread.run(cmd.prompt);

            // Send response
            console.log(JSON.stringify({
                type: 'response',
                commandId: cmd.commandId,
                success: true,
                response: extractText(result),
                threadId: thread.id
            }));

        } else if (cmd.type === 'stream') {
            // For streaming, we'll just run and send the full result
            // (TypeScript SDK may not support true streaming)
            const result = await thread.run(cmd.prompt);
            const output = extractText(result);

            // Send in chunks to simulate streaming
            const chunkSize = 50;
            for (let i = 0; i < output.length; i += chunkSize) {
                const chunk = output.slice(i, i + chunkSize);
                console.log(JSON.stringify({
                    type: 'chunk',
                    commandId: cmd.commandId,
                    chunk: chunk
                }));
            }

            // Send completion marker
            console.log(JSON.stringify({
                type: 'stream_complete',
                commandId: cmd.commandId
            }));

        } else {
            console.error(JSON.stringify({
                type: 'error',
                commandId: cmd.commandId,
                error: 'Unknown command type: ' + cmd.type
            }));
        }
    } catch (error) {
        console.error(JSON.stringify({
            type: 'error',
            commandId: cmd.commandId,
            error: error.message,
            stack: error.stack
        }));
    }
}

// Read commands from stdin
async function main() {
    await initThread();

    const rl = readline.createInterface({
        input: process.stdin,
        output: process.stdout,
        terminal: false
    });

    rl.on('line', async (line) => {
        try {
            const cmd = JSON.parse(line);
            await processCommand(cmd);
        } catch (error) {
            console.error(JSON.stringify({
                type: 'error',
                error: 'Invalid JSON: ' + error.message
            }));
        }
    });
}

main();
"""

        self._codex_wrapper_script.write_text(wrapper_code)
        logger.debug(f"Created wrapper script at {self._codex_wrapper_script}")

    async def ensure_session(self) -> None:
        """Ensure session is active."""
        if not self._session_active:
            await self.start_session()

    async def reset_session(self) -> None:
        """Reset the session."""
        logger.info("Resetting Codex session...")
        await self.end_session()
        await self.start_session()
        logger.info("Codex session reset complete")

    async def end_session(self) -> None:
        """End the Codex session."""
        if not self._session_active:
            logger.warning("No active session to end")
            return

        # Cancel stderr monitor task first (before killing process)
        if self._stderr_monitor_task and not self._stderr_monitor_task.done():
            self._stderr_monitor_task.cancel()
            try:
                await self._stderr_monitor_task
            except asyncio.CancelledError:
                pass  # Expected
            self._stderr_monitor_task = None

        # Kill Node.js process
        if self._node_process:
            try:
                self._node_process.kill()
                await asyncio.wait_for(self._node_process.wait(), timeout=5)
            except asyncio.TimeoutError:
                logger.warning("Node process didn't terminate gracefully")
            except Exception as e:
                logger.warning(f"Error killing Node process: {e}")

            self._node_process = None

        # Note: Wrapper script is permanent and reused, so don't delete it

        self._session_active = False
        self._thread_id = None
        # Don't set _codex_wrapper_script to None - it will be reused
        logger.info("Codex session ended")

    async def stream_prompt(self, prompt: str) -> AsyncIterator[str]:
        """
        Execute a prompt and stream response chunks.

        Args:
            prompt: The prompt text

        Yields:
            Response chunks
        """
        if not self._session_active or not self._node_process:
            raise CodexServiceError("No active session. Call start_session() first.")

        # Prepend system prompt if provided
        full_prompt = f"{self.system_prompt}\n\n{prompt}" if self.system_prompt else prompt

        # Generate command ID
        self._command_id += 1
        command_id = self._command_id

        try:
            # Send stream command to Node process via stdin
            command = {
                "type": "stream",
                "commandId": command_id,
                "prompt": full_prompt
            }

            command_json = json.dumps(command) + "\n"
            self._node_process.stdin.write(command_json.encode())
            await self._node_process.stdin.drain()

            # Read response chunks from stdout
            while True:
                line = await self._node_process.stdout.readline()

                if not line:
                    raise CodexServiceError("Node process closed unexpectedly")

                msg = json.loads(line.decode())

                if msg.get('type') == 'chunk' and msg.get('commandId') == command_id:
                    yield msg['chunk']

                elif msg.get('type') == 'stream_complete' and msg.get('commandId') == command_id:
                    break

                elif msg.get('type') == 'error' and msg.get('commandId') == command_id:
                    raise CodexServiceError(f"Codex error: {msg.get('error')}")
        except Exception as e:
            logger.error(f"Streaming error: {e}", exc_info=True)
            raise CodexServiceError(f"Failed to stream prompt: {e}")

    async def execute_prompt(
        self,
        prompt: str,
        output_schema: Optional[Dict[str, Any]] = None,
        retry_on_failure: bool = True
    ) -> PromptResult:
        """
        Execute a prompt and return complete response.

        Args:
            prompt: The prompt text
            output_schema: Optional JSON schema for structured output
            retry_on_failure: Whether to retry on failure

        Returns:
            PromptResult with response and optional structured output
        """
        if not self._session_active or not self._node_process:
            raise CodexServiceError("No active session. Call start_session() first.")

        start_time = datetime.now()
        attempt = 0
        last_error = None

        # Prepend system prompt if provided
        full_prompt = f"{self.system_prompt}\n\n{prompt}" if self.system_prompt else prompt

        # Add schema instruction if provided
        if output_schema:
            full_prompt += f"\n\nRespond with JSON matching this schema:\n{json.dumps(output_schema, indent=2)}"

        while attempt < (self.max_retries if retry_on_failure else 1):
            attempt += 1

            # Generate command ID
            self._command_id += 1
            command_id = self._command_id

            try:
                # Send run command to Node process via stdin
                command = {
                    "type": "run",
                    "commandId": command_id,
                    "prompt": full_prompt
                }

                command_json = json.dumps(command) + "\n"
                self._node_process.stdin.write(command_json.encode())
                await self._node_process.stdin.drain()

                # Wait for response
                line = await self._node_process.stdout.readline()

                if not line:
                    raise CodexServiceError("Node process closed unexpectedly")

                result_data = json.loads(line.decode())

                # Check for error response
                if result_data.get('type') == 'error':
                    raise CodexServiceError(f"Codex error: {result_data.get('error')}")

                # Verify it's our response
                if result_data.get('commandId') != command_id:
                    raise CodexServiceError("Unexpected command ID in response")

                if not result_data.get('success'):
                    raise CodexServiceError(f"Codex returned error: {result_data.get('error')}")

                response = result_data.get('response', '')
                self._thread_id = result_data.get('threadId')

                # Calculate duration
                duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

                # Parse structured output if schema provided
                structured_output = None
                if output_schema:
                    try:
                        structured_output = self._parse_structured_output(response, output_schema)
                    except SchemaValidationError as e:
                        if attempt >= self.max_retries:
                            logger.warning(f"Schema validation failed after {attempt} attempts: {e}")
                            return PromptResult(
                                raw_response=response,
                                structured_output=None,
                                duration_ms=duration_ms,
                                success=False,
                                error=f"Schema validation failed: {e}"
                            )
                        raise

                logger.info(f"Prompt executed successfully in {duration_ms}ms")
                return PromptResult(
                    raw_response=response,
                    structured_output=structured_output,
                    duration_ms=duration_ms
                )

            except SchemaValidationError:
                if attempt < self.max_retries:
                    logger.warning(f"Schema validation failed on attempt {attempt}, retrying...")
                    last_error = "Schema validation failed"
                    continue
                raise

            except Exception as e:
                last_error = str(e)
                logger.error(f"Execution failed (attempt {attempt}/{self.max_retries}): {e}")

                if attempt >= self.max_retries:
                    duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                    raise CodexServiceError(f"Failed after {attempt} attempts: {last_error}")

                await asyncio.sleep(min(2 ** attempt, 10))

        raise CodexServiceError(f"Failed after {self.max_retries} attempts: {last_error}")

    def _extract_text_from_sdk_message(self, message_str: str) -> str:
        """
        Extract text content from SDK message.

        For Codex, messages are already plain text strings, so return as-is.
        This method exists for compatibility with ExecutionController which
        expects all services to have this method.

        Args:
            message_str: Message string from Codex (already plain text)

        Returns:
            The message text
        """
        return message_str

    def _parse_structured_output(
        self,
        response_text: str,
        schema: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Parse structured output from response."""
        logger.debug(f"Parsing structured output from response (length={len(response_text)}):")
        logger.debug(f"Response text: {response_text[:500]}")

        json_text = self._extract_json_from_text(response_text)

        if not json_text:
            logger.error(f"Could not extract JSON from response: {response_text}")
            raise SchemaValidationError(
                "No JSON found in response. "
                "Codex may not have provided structured output."
            )

        try:
            output = json.loads(json_text)
        except json.JSONDecodeError as e:
            raise SchemaValidationError(f"Invalid JSON in response: {e}")

        self._validate_against_schema(output, schema)
        return output

    def _extract_json_from_text(self, text: str) -> Optional[str]:
        """Extract JSON from response text."""
        # Strip whitespace
        text = text.strip()

        # If the entire response is JSON, use it directly
        if text.startswith('{') or text.startswith('['):
            try:
                json.loads(text)
                logger.debug("Response is pure JSON")
                return text
            except json.JSONDecodeError:
                pass  # Not valid JSON, continue trying other methods

        # Try markdown code block
        match = re.search(r'```json\s*([\s\S]*?)\s*```', text)
        if match:
            logger.debug("Found JSON in ```json block")
            return match.group(1).strip()

        match = re.search(r'```\s*([\s\S]*?)\s*```', text)
        if match:
            content = match.group(1).strip()
            if content.startswith('{') or content.startswith('['):
                logger.debug("Found JSON in ``` block")
                return content

        # Try standalone JSON (non-greedy to get first complete object/array)
        match = re.search(r'\{[\s\S]*?\}', text)
        if match:
            try:
                json.loads(match.group(0))
                logger.debug("Found JSON with non-greedy regex")
                return match.group(0)
            except json.JSONDecodeError:
                pass

        return None

    def _validate_against_schema(
        self,
        output: Dict[str, Any],
        schema: Dict[str, Any]
    ) -> None:
        """Basic schema validation."""
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
