"""
Embedding facade for FlowCoder.

Provides a single entry point for external systems (like Axi) to use
FlowCoder's slash command / flowchart capabilities on top of an existing
ClaudeSDKClient.

Usage:
    from src.embedding import FlowCoderSession

    # Wrap an existing, already-running ClaudeSDKClient
    fc = FlowCoderSession.create(client=my_client, cwd="/path/to/project")

    # Regular message — yields raw SDK objects
    async for chunk in fc.stream_message("explain this code"):
        process(chunk)

    # Slash command — streaming via on_prompt_stream callback
    context = await fc.execute_command("/deploy staging")
    print(context.status)

    # List available commands
    commands = fc.list_commands()
"""

import logging
from typing import Any, AsyncIterator, Optional, Callable

from src.services.claude_service import ClaudeAgentService
from src.services.storage_service import StorageService
from src.controllers.execution_controller import ExecutionController
from src.models.execution import ExecutionContext, ExecutionStatus

logger = logging.getLogger(__name__)

# Re-export the default system prompt so embedders can append it
from src.cli.agent import DEFAULT_SYSTEM_PROMPT as FLOWCODER_SYSTEM_PROMPT  # noqa: F401


class FlowCoderSession:
    """
    Embeddable FlowCoder session that wraps an external ClaudeSDKClient.

    NOT safe for concurrent use — one operation at a time per instance.
    External systems should serialize calls (e.g., Axi's per-agent query_lock).
    """

    def __init__(
        self,
        agent_service: ClaudeAgentService,
        storage_service: StorageService,
        execution_controller: ExecutionController,
    ):
        self.agent_service = agent_service
        self.storage_service = storage_service
        self.execution_controller = execution_controller

    @classmethod
    def create(
        cls,
        client: Any,
        cwd: str = ".",
        commands_dir: Optional[str] = None,
        on_execution_start: Optional[Callable] = None,
        on_block_start: Optional[Callable] = None,
        on_block_complete: Optional[Callable] = None,
        on_block_complete_async: Optional[Callable] = None,
        on_execution_complete: Optional[Callable] = None,
        on_prompt_stream: Optional[Callable] = None,
        on_refresh_requested: Optional[Callable] = None,
    ) -> "FlowCoderSession":
        """Create a FlowCoder session wrapping an external SDK client.

        Args:
            client: A running ClaudeSDKClient instance.
            cwd: Working directory for the agent.
            commands_dir: Directory containing flowchart command JSON files.
                          Defaults to ``./commands`` relative to cwd.
            on_execution_start: (command_name, context) -> None
            on_block_start: (block, context) -> None
            on_block_complete: (block, result, context) -> None
            on_block_complete_async: async (block, result, context) -> None
            on_execution_complete: (context) -> None
            on_prompt_stream: (prompt_text, chunk_str) -> None.
                Receives string-ified SDK chunks during prompt block execution.
            on_refresh_requested: async () -> None.
                Called when a Refresh block fires. The embedder is responsible
                for resetting the session (e.g., sleep + wake in Axi).

        Returns:
            A ready-to-use FlowCoderSession.
        """
        import os

        agent_service = ClaudeAgentService.from_client(client, cwd=cwd)

        resolved_commands_dir = commands_dir or os.path.join(cwd, "commands")
        storage_service = StorageService(commands_dir=resolved_commands_dir)

        ec = ExecutionController(
            agent_service=agent_service,
            storage_service=storage_service,
            on_execution_start=on_execution_start,
            on_block_start=on_block_start,
            on_block_complete=on_block_complete,
            on_block_complete_async=on_block_complete_async,
            on_execution_complete=on_execution_complete,
            on_prompt_stream=on_prompt_stream,
        )
        if on_refresh_requested:
            ec.on_refresh_requested = on_refresh_requested

        session = cls(agent_service, storage_service, ec)
        logger.info(f"FlowCoderSession created (cwd={cwd}, commands={resolved_commands_dir})")
        return session

    async def stream_message(self, text: str) -> AsyncIterator[Any]:
        """Send a regular message to Claude. Yields raw SDK objects.

        Args:
            text: The user's message text.

        Yields:
            Raw SDK message objects (StreamEvent, AssistantMessage, etc.)
        """
        async for chunk in self.agent_service.stream_prompt(text):
            yield chunk

    async def execute_command(self, command_str: str) -> ExecutionContext:
        """Execute a slash command (flowchart).

        Streaming during prompt blocks is delivered via the ``on_prompt_stream``
        callback passed to ``create()``.

        Args:
            command_str: Full command string, e.g. "/deploy staging" or
                         "deploy staging" (leading slash is optional).

        Returns:
            ExecutionContext with the full execution log and final status.

        Raises:
            CommandNotFoundError: If the command doesn't exist.
            ExecutionControllerError: If execution fails.
        """
        # Strip leading slash if present
        stripped = command_str.lstrip("/").strip()
        parts = stripped.split(None, 1)
        if not parts:
            raise ValueError("Empty command string")

        command_name = parts[0]
        args_string = parts[1] if len(parts) > 1 else ""

        cmd = self.storage_service.load_command(command_name)

        arguments_dict = {}
        if args_string:
            arguments_dict = cmd.parse_arguments(args_string)

        execution_flowchart = cmd.create_execution_copy()

        context = await self.execution_controller.execute(
            command=cmd,
            arguments=arguments_dict,
            flowchart=execution_flowchart,
        )

        return context

    def list_commands(self) -> list[dict]:
        """List available flowchart commands.

        Returns:
            List of command metadata dicts (name, description, block_count, etc.)
        """
        return self.storage_service.list_commands()

    def halt(self) -> None:
        """Request that the current flowchart execution stop after the current block."""
        self.execution_controller.halt()

    @property
    def last_context(self) -> Optional[ExecutionContext]:
        """The most recent execution context, or None."""
        return self.execution_controller.current_context
