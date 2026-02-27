"""
CLI Agent for FlowCoder

Terminal-based REPL that provides the same agent experience as the GUI's
Sessions tab: chat with Claude via the Agent SDK, and use /slash-commands
to execute flowchart commands.
"""

import asyncio
import logging
import os
import sys
from typing import Optional

from src.models.session import Session, Message
from src.models.session_state import SessionState
from src.models.blocks import BlockType
from src.models.execution import BlockResult, ExecutionContext, ExecutionStatus
from src.services.service_factory import ServiceFactory
from src.services.storage_service import StorageService
from src.controllers.execution_controller import ExecutionController
from src.utils.sdk_message_parser import parse_sdk_message

from . import output as out

logger = logging.getLogger(__name__)

# Default system prompt that teaches Claude about FlowCoder concepts.
# Used when no custom --system-prompt is provided.
DEFAULT_SYSTEM_PROMPT = """\
You are a FlowCoder agent — an AI assistant with knowledge of FlowCoder, a visual \
workflow automation tool built on top of Claude Code.

## What FlowCoder is

FlowCoder lets users build reusable automation workflows as visual flowcharts called \
"commands." Each command is a directed graph of blocks that execute sequentially, with \
branching and looping support. Commands are stored as JSON files and can be run via \
slash commands (e.g., `/deploy`, `/analyze-code utils.py`).

## Block types

Flowcharts are composed of these block types:

- **Start / End** — Entry and exit points of a flowchart.
- **Prompt** — Sends a prompt to you (Claude) and captures the response. Supports \
structured output via JSON schemas, so your response can be parsed into variables \
for downstream blocks.
- **Bash** — Executes a shell command. Can capture stdout into a variable. Supports \
continue-on-error and exit code capture.
- **Variable** — Sets a variable to a literal value or an expression. Supports types: \
string, int, float, boolean.
- **Branch** — Conditional routing. Evaluates an expression against context variables \
and routes to a True or False path.
- **Command** — Invokes another FlowCoder command (sub-flowchart). Supports dynamic \
dispatch via variable substitution in the command name (e.g., `{{tool}}`). Can pass \
arguments and optionally merge child output variables back into the parent scope.
- **Refresh** — Resets the agent session (useful for long-running workflows).

## Variables and arguments

- **Positional arguments**: `$1`, `$2`, etc. Passed when a command is invoked \
(e.g., `/analyze-code utils.py` sets `$1` to `utils.py`).
- **Named variables**: `{{varname}}`. Set by Variable blocks, structured output from \
Prompt blocks, or Bash output capture.  Support nested access: `{{result.status}}`, \
`{{files[0]}}`.
- Variables are substituted in prompt text, bash commands, arguments, and even command \
names (for dynamic dispatch).

## Slash commands

The user can type `/<command-name> [args]` to execute a flowchart command. For example:
- `/deploy` — runs the "deploy" command
- `/analyze-code src/main.py strict` — runs "analyze-code" with $1=src/main.py, $2=strict

You can suggest slash commands to the user when appropriate. If they ask you to create \
a workflow or automate something, you can help them design a flowchart by describing \
the blocks and connections needed.

## Your role

You are a helpful coding assistant that also understands FlowCoder workflows. You can:
- Answer questions about the user's codebase (you have full access via Claude Code)
- Help design, debug, and optimize FlowCoder commands/flowcharts
- Explain how blocks, variables, branching, and command composition work
- Suggest when a task might benefit from a reusable FlowCoder command

When the user runs a slash command, FlowCoder handles execution — you'll receive \
prompts from individual Prompt blocks within the flowchart. Answer those prompts \
directly and concisely, respecting any output schema if one is specified.
"""


class CLIAgent:
    """
    Terminal-based FlowCoder agent with REPL loop.

    Provides:
    - Chat with Claude (messages streamed to stdout)
    - /slash-commands to execute flowchart commands
    - Built-in commands: /help, /commands, /quit
    """

    # Hash commands accepted while executing
    INTERRUPT_COMMANDS = {"#halt", "#stop", "#refresh", "#forcestop"}

    def __init__(
        self,
        cwd: Optional[str] = None,
        service_type: str = "claude",
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        session_name: str = "cli-session",
        debug: bool = False,
        config_name: Optional[str] = None,
        flowchart_cmd: Optional[list] = None,
    ):
        """
        Initialize CLI agent.

        Args:
            cwd: Working directory (default: os.getcwd())
            service_type: AI service type ("claude", "codex", "mock")
            model: Model override (e.g., "claude-sonnet-4-20250514")
            system_prompt: System prompt for the AI
            session_name: Name for this session
            debug: Enable verbose/debug output
            config_name: Name of config file to load (.claudeconfig/.codexconfig)
            flowchart_cmd: Non-interactive mode: [command, arg1, arg2, ...]
        """
        self.cwd = os.path.abspath(cwd or os.getcwd())
        self.service_type = service_type
        self.model = model
        self.system_prompt = system_prompt if system_prompt is not None else DEFAULT_SYSTEM_PROMPT
        self.session_name = session_name
        self.debug = debug
        self.config_name = config_name
        self.flowchart_cmd = flowchart_cmd

        # Initialized in _initialize()
        self.session: Optional[Session] = None
        self.storage_service: Optional[StorageService] = None

        # Streaming state
        self._is_streaming = False
        self._prompt_has_output = False

    async def run(self) -> int:
        """Main entry point. Initialize, run REPL (or -f command), then shutdown.

        Returns:
            Exit code (0 for success, non-zero for errors). Only meaningful in -f mode.
        """
        exit_code = 0
        try:
            await self._initialize()

            if self.flowchart_cmd:
                # Non-interactive -f mode: run one command and exit
                exit_code = await self._run_flowchart_mode()
            else:
                # Interactive REPL mode
                out.print_banner()
                out.print_system(f"Working directory: {self.cwd}")
                out.print_system(f"Service: {ServiceFactory.get_service_display_name(self.service_type)}")
                out.print_system(f"Session: {self.session_name}")
                print()
                await self._repl_loop()
        except KeyboardInterrupt:
            print()
        finally:
            await self._shutdown()
        return exit_code

    async def _run_flowchart_mode(self) -> int:
        """Non-interactive mode: execute a single flowchart command and exit.

        Returns:
            Exit code from the command (0 = success).
        """
        if not self.flowchart_cmd:
            return 1

        command_name = self.flowchart_cmd[0].lstrip("/")
        args_string = " ".join(self.flowchart_cmd[1:])
        command_str = f"/{command_name} {args_string}".strip()

        # Power on the agent
        try:
            await self.session.agent_service.ensure_session()
        except Exception as e:
            out.print_error(f"Failed to start AI session: {e}")
            return 1

        # Execute the command
        await self._handle_slash_command(command_str)

        # Check the execution result
        if self.session.execution_history:
            last_run = self.session.execution_history[-1]
            if last_run.status == "completed":
                return 0
            elif last_run.status == "error":
                return 1
        return 0

    async def _initialize(self) -> None:
        """Set up session, AI service, storage, and execution controller."""
        # Create session (no SessionManager — lightweight, no singleton conflicts)
        self.session = Session(
            name=self.session_name,
            working_directory=self.cwd,
            system_prompt=self.system_prompt or "",
            service_type=self.service_type,
        )

        # Create AI service via factory
        kwargs = {}
        if self.model:
            kwargs["model"] = self.model
        self.session.agent_service = ServiceFactory.create_service(
            service_type=self.service_type,
            cwd=self.cwd,
            system_prompt=self.system_prompt,
            permission_mode="bypassPermissions",
            **kwargs,
        )

        # Storage service for loading flowchart commands
        self.storage_service = StorageService()

        # Execution controller for running flowcharts
        self.session.execution_controller = ExecutionController(
            agent_service=self.session.agent_service,
            storage_service=self.storage_service,
        )
        self._setup_callbacks()

        # Suppress noisy console logs in non-debug mode
        if not self.debug:
            for handler in logging.getLogger().handlers:
                if isinstance(handler, logging.StreamHandler) and handler.stream in (sys.stderr, sys.stdout):
                    handler.setLevel(logging.WARNING)

        logger.info(f"CLI agent initialized: cwd={self.cwd}, service={self.service_type}")

    def _setup_callbacks(self) -> None:
        """Wire execution controller callbacks to terminal output."""
        ec = self.session.execution_controller
        ec.on_execution_start = self._on_execution_start
        ec.on_block_start = self._on_block_start
        ec.on_block_complete = self._on_block_complete
        ec.on_execution_complete = self._on_execution_complete
        ec.on_prompt_stream = self._on_prompt_stream
        ec.on_refresh_requested = self._on_refresh_requested

    # ── REPL ──────────────────────────────────────────────────────────

    async def _repl_loop(self) -> None:
        """Read-eval-print loop. Input is read in an executor to stay async."""
        loop = asyncio.get_event_loop()
        while True:
            try:
                user_input = await loop.run_in_executor(None, self._read_input)
                user_input = user_input.strip()
                if not user_input:
                    continue

                # Hash commands (session functions)
                if user_input.startswith("#"):
                    await self._handle_hash_command(user_input)
                elif user_input.startswith("!"):
                    await self._handle_bang_command(user_input)
                elif user_input.startswith("?"):
                    await self._handle_query_command(user_input)
                elif user_input.startswith("/"):
                    await self._handle_slash_command(user_input)
                else:
                    await self._handle_message(user_input)

            except KeyboardInterrupt:
                # At the prompt: just print newline and continue (like bash)
                print()
                continue
            except EOFError:
                # Ctrl+D — exit cleanly
                break

    def _read_input(self) -> str:
        """Read a line from stdin with a prompt. Runs in executor thread."""
        return input("\033[1m> \033[0m")

    # ── Regular messages (pass-through to Claude) ─────────────────────

    async def _handle_message(self, message: str) -> None:
        """Send a message to Claude and stream the response."""
        self.session.add_message("user", message)

        if not self.session.agent_service:
            out.print_error("AI service not available.")
            return

        # Ensure the SDK session is started
        try:
            out.print_system("Starting session...") if not self.session.agent_service._session_active else None
            await self.session.agent_service.ensure_session()
        except Exception as e:
            out.print_error(f"Failed to start session: {e}")
            return

        response_text = ""
        self._is_streaming = True
        print()  # blank line before response

        try:
            async for chunk in self.session.agent_service.stream_prompt(message):
                text_content, verbose_content, message_type = parse_sdk_message(chunk)

                if message_type == "text_delta" and text_content:
                    out.stream_text(text_content)
                    response_text += text_content
                elif message_type == "assistant_plain" and text_content:
                    out.stream_text(text_content)
                    response_text += text_content
                elif message_type == "content_block_start":
                    # New content block — insert a line break to separate sections
                    if response_text:
                        out.stream_text("\n\n")
                        response_text += "\n\n"
                elif message_type == "result" and self.debug:
                    # Show result metadata in debug mode
                    if verbose_content and "Result Message" in verbose_content:
                        out.print_system(verbose_content)

        except KeyboardInterrupt:
            out.print_error("\n[Interrupted]")
        except Exception as e:
            out.print_error(f"\nError during streaming: {e}")
            logger.exception("Streaming error")
        finally:
            self._is_streaming = False

        out.stream_end()

        if response_text:
            self.session.add_message("assistant", response_text)

    # ── Slash commands (flowchart execution) ──────────────────────────

    async def _handle_slash_command(self, command_str: str) -> None:
        """Parse and execute a slash command."""
        parts = command_str[1:].strip().split(None, 1)
        if not parts:
            return

        command_name = parts[0]
        args_string = parts[1] if len(parts) > 1 else ""

        # Built-in commands
        if command_name in ("help", "h", "?"):
            out.print_help()
            return
        if command_name == "commands":
            self._list_commands()
            return
        if command_name in ("quit", "exit", "q"):
            raise EOFError()

        # Load and execute flowchart command
        try:
            cmd = self.storage_service.load_command(command_name)
        except Exception as e:
            out.print_error(f"Command '/{command_name}' not found: {e}")
            return

        arguments_dict = {}
        if args_string:
            try:
                arguments_dict = cmd.parse_arguments(args_string)
            except Exception as e:
                out.print_error(f"Argument error: {e}")
                return

        execution_flowchart = cmd.create_execution_copy()
        self.session.current_flowchart = execution_flowchart

        out.print_user_echo(f"/{command_name} {args_string}".strip())
        print()

        # Ensure AI service is ready for prompt blocks
        try:
            await self.session.agent_service.ensure_session()
        except Exception as e:
            out.print_error(f"Failed to start AI session: {e}")
            return

        self.session.start_execution(command_name)

        try:
            context = await self.session.execution_controller.execute(
                command=cmd,
                arguments=arguments_dict,
                flowchart=execution_flowchart,
            )

            success = context.status == ExecutionStatus.COMPLETED
            self.session.complete_execution(success=success)

            duration = 0.0
            if context.start_time and context.end_time:
                duration = (context.end_time - context.start_time).total_seconds()

            if success:
                out.print_success(f"Completed ({duration:.1f}s)")
            else:
                out.print_error(f"Finished with status: {context.status.value} ({duration:.1f}s)")

        except KeyboardInterrupt:
            # Halt execution gracefully
            self.session.execution_controller.halt()
            self.session.halt_execution()
            out.print_error("\n[Execution interrupted]")
        except Exception as e:
            self.session.complete_execution(success=False, error_message=str(e))
            out.print_error(f"Execution error: {e}")
            logger.exception("Flowchart execution error")

        print()

    def _list_commands(self) -> None:
        """List available flowchart commands."""
        try:
            commands = self.storage_service.list_commands()
        except Exception as e:
            out.print_error(f"Error listing commands: {e}")
            return

        if not commands:
            out.print_system("No commands found.")
            return

        print(f"\n\033[1mAvailable commands ({len(commands)}):\033[0m")
        for cmd in commands:
            name = cmd.get("name", "?")
            desc = cmd.get("description", "")
            source = cmd.get("source", "")
            source_tag = f" ({source})" if source else ""
            if desc:
                desc_short = desc[:60] + "..." if len(desc) > 60 else desc
                print(f"  /{name}{source_tag} — {desc_short}")
            else:
                print(f"  /{name}{source_tag}")
        print()

    # ── Execution controller callbacks ────────────────────────────────

    def _on_execution_start(self, command_name: str, context: ExecutionContext) -> None:
        """Called when flowchart execution begins."""
        out.print_system(f"Executing: {command_name}")

    def _on_block_start(self, block, context: ExecutionContext) -> None:
        """Called when a block starts executing."""
        out.print_block_status(block.name, block.type.value, "executing")

    def _on_block_complete(self, block, result: BlockResult, context: ExecutionContext) -> None:
        """Called when a block finishes executing."""
        status = "completed" if result.success else "error"
        out.print_block_status(block.name, block.type.value, status)

        # Print error details
        if not result.success and result.error:
            out.print_error(f"    {result.error}")

    def _on_execution_complete(self, context: ExecutionContext) -> None:
        """Called when the entire flowchart execution finishes."""
        logger.debug(f"Execution complete: {context.status.value}")

    def _on_prompt_stream(self, prompt_text: str, chunk: str) -> None:
        """Called with streaming chunks during prompt block execution.

        Args:
            prompt_text: The prompt being executed
            chunk: Raw SDK message (empty string = start of prompt)
        """
        if chunk == "":
            # Start of a new prompt — reset state and show what's being asked
            self._prompt_has_output = False
            preview = prompt_text[:80] + "..." if len(prompt_text) > 80 else prompt_text
            out.print_system(f"    Prompt: {preview}")
            return

        # Parse and stream the chunk
        text_content, _, message_type = parse_sdk_message(chunk)
        if message_type == "text_delta" and text_content:
            out.stream_text(text_content)
            self._prompt_has_output = True
        elif message_type == "assistant_plain" and text_content:
            out.stream_text(text_content)
            self._prompt_has_output = True
        elif message_type == "content_block_start":
            if self._prompt_has_output:
                out.stream_text("\n\n")

    async def _on_refresh_requested(self) -> None:
        """Handle a Refresh block by restarting the SDK session."""
        out.print_system("    Refreshing agent session...")
        try:
            if self.session.agent_service:
                await self.session.agent_service.end_session()

            # Recreate the AI service with a fresh session
            kwargs = {}
            if self.model:
                kwargs["model"] = self.model
            self.session.agent_service = ServiceFactory.create_service(
                service_type=self.service_type,
                cwd=self.cwd,
                system_prompt=self.system_prompt,
                permission_mode="bypassPermissions",
                **kwargs,
            )

            # Re-wire the execution controller to use the new service
            self.session.execution_controller.agent_service = self.session.agent_service

            await self.session.agent_service.ensure_session()
            out.print_system("    Session refreshed.")
        except Exception as e:
            logger.error(f"Refresh failed: {e}", exc_info=True)
            raise

    # ── Hash commands (session functions) ────────────────────────────

    async def _handle_hash_command(self, command_str: str) -> None:
        """Handle #hash session function commands."""
        cmd = command_str.strip().lower()

        if cmd == "#halt":
            if self.session.state == SessionState.EXECUTING:
                self.session.execution_controller.halt()
                out.print_system("Halt requested. Waiting for current block to finish...")
            else:
                out.print_system("Nothing to halt.")

        elif cmd == "#resume":
            if self.session.state == SessionState.HALTED:
                try:
                    self.session.resume_execution()
                    out.print_system("Resuming execution...")
                    # Re-execute from halted context if available
                    if self.session.halted_context and self.session.halted_flowchart:
                        context = await self.session.execution_controller.execute(
                            command=self.session.halted_command,
                            flowchart=self.session.halted_flowchart,
                            context=self.session.halted_context,
                        )
                        success = context.status == ExecutionStatus.COMPLETED
                        self.session.complete_execution(success=success)
                        if success:
                            out.print_success("Execution resumed and completed.")
                        else:
                            out.print_error(f"Execution finished: {context.status.value}")
                except RuntimeError as e:
                    out.print_error(str(e))
            else:
                out.print_system("Nothing to resume. Session is not halted.")

        elif cmd == "#drop":
            if self.session.state == SessionState.HALTED:
                self.session.drop_command_stack()
                out.print_system("Command stack dropped. Session is now idle.")
            else:
                out.print_system("Cannot drop: session is not halted.")

        elif cmd == "#stop":
            if self.session.state == SessionState.EXECUTING:
                self.session.execution_controller.halt()
                out.print_system("Stopping. Waiting for current block to finish...")
            # After halt (or if already idle), turn off the agent
            if self.session.agent_service and self.session.agent_service.is_active():
                await self.session.agent_service.end_session()
                out.print_system("Base agent turned off.")
            else:
                out.print_system("Agent is already off.")

        elif cmd == "#refresh":
            if self.session.state == SessionState.EXECUTING:
                self.session.execution_controller.halt()
                out.print_system("Halting before refresh...")
            # Turn off and back on
            if self.session.agent_service:
                await self.session.agent_service.end_session()
                out.print_system("Agent turned off.")
            await self._on_refresh_requested()

        elif cmd == "#forcestop":
            out.print_error("Force stopping...")
            if self.session.agent_service:
                await self.session.agent_service.end_session()
            self.session.command_stack.clear()
            self.session.clear_halted_state()
            self.session.state = SessionState.IDLE
            out.print_system("Force stopped. Agent off, command stack cleared.")

        else:
            out.print_error(f"Unknown session command: {cmd}")
            out.print_system("Available: #halt, #resume, #drop, #stop, #refresh, #forcestop")

    # ── Bang commands (bash execution) ────────────────────────────

    async def _handle_bang_command(self, command_str: str) -> None:
        """Handle !bash commands — execute in the session's working directory."""
        bash_cmd = command_str[1:].strip()
        if not bash_cmd:
            out.print_system("Usage: !<bash command>")
            return

        import subprocess
        out.print_system(f"$ {bash_cmd}")
        try:
            proc = await asyncio.create_subprocess_shell(
                bash_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=self.cwd,
            )
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                out.stream_text(line.decode(errors="replace"))
            await proc.wait()
            out.stream_end()
            if proc.returncode != 0:
                out.print_error(f"Exit code: {proc.returncode}")
        except Exception as e:
            out.print_error(f"Bash error: {e}")

    # ── Query commands (?settings, ?config) ───────────────────────

    async def _handle_query_command(self, command_str: str) -> None:
        """Handle ?query commands."""
        parts = command_str[1:].strip().split(None, 1)
        if not parts:
            return

        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd == "settings":
            out.print_system("Session settings:")
            out.print_system(f"  Working directory: {self.cwd}")
            out.print_system(f"  Git repo URL: {self.session.git_repo_url or '(not set)'}")
            out.print_system(f"  Git branch: {self.session.git_branch or '(default)'}")
            out.print_system(f"  Auto-push: {self.session.git_auto_push}")
            out.print_system(f"  Config: {self.session.config_name or '(default)'}")
            out.print_system(f"  Sound on prompt: {self.session.sound_on_prompt_complete or 'None'}")
            out.print_system(f"  Sound on block: {self.session.sound_on_block_complete or 'None'}")
            out.print_system(f"  Sound on command pop: {self.session.sound_on_command_pop or 'None'}")

        elif cmd == "config":
            if not arg:
                out.print_system("Usage: ?config <config_name>")
                return
            if self.session.is_agent_on:
                out.print_error("Cannot change config while agent is running. Use #stop first.")
                return
            self.session.config_name = arg
            out.print_success(f"Config set to: {arg}")

        else:
            out.print_error(f"Unknown query: ?{cmd}")
            out.print_system("Available: ?settings, ?config <name>")

    # ── Shutdown ──────────────────────────────────────────────────────

    async def _shutdown(self) -> None:
        """Clean up resources."""
        if self.session and self.session.agent_service:
            try:
                await self.session.agent_service.end_session()
            except Exception as e:
                logger.warning(f"Error ending session: {e}")

        out.print_system("Session ended.")
