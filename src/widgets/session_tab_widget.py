"""
SessionTabWidget - Widget representing one session's tab content.

Contains:
- Chat panel (top) - for sending messages to Claude
- Execution history (middle) - showing execution log
- Execution flowchart view (bottom) - showing currently executing flowchart
"""

import asyncio
import logging
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from typing import TYPE_CHECKING, List

from ..models import Session, BlockType
from ..models.session_state import SessionState
from ..utils import (
    validate_git_repo_url,
    validate_git_branch_name,
    GitWorkflowOrchestrator,
)

logger = logging.getLogger(__name__)

# Use lazy imports to avoid circular dependency
if TYPE_CHECKING:
    pass


class SessionTabWidget(ttk.Frame):
    """
    Widget representing one session's tab content.

    Each session gets an independent instance with its own:
    - Chat input/output area
    - Execution history panel
    - Execution flowchart view
    """

    def __init__(self, parent, session: Session, storage_service=None, on_close_callback=None, session_manager=None):
        """
        Initialize session tab widget.

        Args:
            parent: Parent widget (notebook)
            session: Session model this tab represents
            storage_service: StorageService for loading commands
            on_close_callback: Optional callback when close button is clicked
        """
        super().__init__(parent)
        self.session = session
        self.storage_service = storage_service
        self.on_close_callback = on_close_callback
        self.session_manager = session_manager
        self.git_workflow = GitWorkflowOrchestrator(self.session.working_directory)
        self._pending_git_retry_block = None

        # Track async tasks for cleanup
        self._async_tasks: List[asyncio.Task] = []

        # Flag to track if widget has been destroyed (for callback guards)
        self._is_destroyed = False

        self._create_ui()

        # Wire up execution controller callbacks for UI updates
        self._setup_execution_callbacks()

    def _track_task(self, coro) -> asyncio.Task:
        """
        Create and track an async task for proper cleanup.

        Args:
            coro: Coroutine to run as a task

        Returns:
            The created task
        """
        task = asyncio.ensure_future(coro)
        self._async_tasks.append(task)

        # Remove from list when done
        def on_done(t):
            if t in self._async_tasks:
                self._async_tasks.remove(t)

        task.add_done_callback(on_done)
        return task

    def _widget_exists(self) -> bool:
        """Check if widget still exists and hasn't been destroyed."""
        if self._is_destroyed:
            return False
        try:
            return self.winfo_exists()
        except tk.TclError:
            return False

    async def cleanup(self):
        """
        Clean up resources when widget is destroyed.

        Cancels all pending async tasks.
        """
        logger.debug(f"SessionTabWidget cleanup started for session: {self.session.name}")

        # Cancel all pending tasks
        for task in self._async_tasks[:]:  # Copy list to avoid modification during iteration
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._async_tasks.clear()
        logger.debug("Cancelled all pending async tasks")

    def _create_ui(self):
        """Create UI components with 3-pane vertical layout."""
        # Top bar with close and restart buttons
        if self.on_close_callback:
            top_bar = ttk.Frame(self)
            top_bar.pack(fill=tk.X, pady=(0, 5))

            close_btn = ttk.Button(
                top_bar,
                text="✕ Close Session",
                command=self._on_close_clicked,
                width=15
            )
            close_btn.pack(side=tk.RIGHT, padx=5)

            restart_btn = ttk.Button(
                top_bar,
                text="🔄 Restart Session",
                command=self._on_restart_clicked,
                width=18
            )
            restart_btn.pack(side=tk.RIGHT, padx=5)

        # Session info panel (working directory, service, and system prompt)
        info_frame = ttk.LabelFrame(self, text="Session Information", padding=5)
        info_frame.pack(fill=tk.X, pady=(0, 5))
        info_frame.columnconfigure(1, weight=1)

        # AI Service
        from ..services.service_factory import ServiceFactory
        service_display = ServiceFactory.get_service_display_name(self.session.service_type)

        svc_label = ttk.Label(info_frame, text="AI Service:", font=('TkDefaultFont', 9, 'bold'))
        svc_label.grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)

        svc_value = ttk.Label(info_frame, text=service_display, font=('TkDefaultFont', 9))
        svc_value.grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)

        # Working directory
        wd_label = ttk.Label(info_frame, text="Working Directory:", font=('TkDefaultFont', 9, 'bold'))
        wd_label.grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)

        wd_value = ttk.Label(info_frame, text=self.session.working_directory, font=('TkDefaultFont', 9))
        wd_value.grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)

        # System prompt
        sp_label = ttk.Label(info_frame, text="System Prompt:", font=('TkDefaultFont', 9, 'bold'))
        sp_label.grid(row=2, column=0, sticky=tk.W, padx=5, pady=2)

        # Truncate system prompt if it's very long
        system_prompt_display = self.session.system_prompt or f"(Using {service_display} default)"
        if len(system_prompt_display) > 100:
            system_prompt_display = system_prompt_display[:97] + "..."

        sp_value = ttk.Label(info_frame, text=system_prompt_display, font=('TkDefaultFont', 9))
        sp_value.grid(row=2, column=1, sticky=tk.W, padx=5, pady=2)

        ttk.Label(info_frame, text="Git Repo URL:", font=('TkDefaultFont', 9, 'bold')).grid(row=3, column=0, sticky=tk.W, padx=5, pady=2)
        self.git_repo_var = tk.StringVar(value=self.session.git_repo_url or "")
        self.git_repo_entry = ttk.Entry(info_frame, textvariable=self.git_repo_var)
        self.git_repo_entry.grid(row=3, column=1, sticky=tk.EW, padx=5, pady=2)

        ttk.Label(
            info_frame,
            text="Example: https://github.com/org/repo.git or git@github.com:org/repo.git",
            font=('TkDefaultFont', 8),
            foreground="gray"
        ).grid(row=4, column=0, columnspan=2, sticky=tk.W, padx=5, pady=(0, 4))

        ttk.Label(info_frame, text="Git Branch:", font=('TkDefaultFont', 9, 'bold')).grid(row=5, column=0, sticky=tk.W, padx=5, pady=2)
        self.git_branch_var = tk.StringVar(value=self.session.git_branch or "")
        self.git_branch_entry = ttk.Entry(info_frame, textvariable=self.git_branch_var)
        self.git_branch_entry.grid(row=5, column=1, sticky=tk.EW, padx=5, pady=2)

        ttk.Label(
            info_frame,
            text="Allowed: letters, numbers, '/', '.', '_', '-'. Leave blank to track default branch.",
            font=('TkDefaultFont', 8),
            foreground="gray"
        ).grid(row=6, column=0, columnspan=2, sticky=tk.W, padx=5, pady=(0, 4))

        self.git_auto_push_var = tk.BooleanVar(value=self.session.git_auto_push)
        self.git_auto_push_check = ttk.Checkbutton(
            info_frame,
            text="Auto-push",
            variable=self.git_auto_push_var
        )
        self.git_auto_push_check.grid(row=7, column=0, columnspan=2, sticky=tk.W, padx=5, pady=(2, 0))

        self.git_save_btn = ttk.Button(info_frame, text="Save Git Settings", command=self._save_git_settings)
        self.git_save_btn.grid(row=8, column=0, columnspan=2, sticky=tk.E, padx=5, pady=(5, 0))

        self.git_retry_btn = ttk.Button(
            info_frame,
            text="Retry Git Sync",
            command=self._retry_git_workflow,
            state=tk.DISABLED
        )
        self.git_retry_btn.grid(row=9, column=0, columnspan=2, sticky=tk.E, padx=5, pady=(2, 0))

        # Horizontal split: Left (chat + history) | Right (flowchart)
        main_paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True)

        # Left pane: Vertical split for chat and history
        left_paned = ttk.PanedWindow(main_paned, orient=tk.VERTICAL)
        main_paned.add(left_paned, weight=60)  # 60% width

        # Left top: Chat panel (40% of left pane height - reduced from 60%)
        chat_container = ttk.Frame(left_paned)
        left_paned.add(chat_container, weight=40)

        chat_frame = ttk.LabelFrame(chat_container, text="Chat", padding=5)
        chat_frame.pack(fill=tk.BOTH, expand=True)

        self._create_chat_panel(chat_frame)

        # Left bottom: Execution history (60% of left pane height - increased from 40%)
        history_container = ttk.Frame(left_paned)
        left_paned.add(history_container, weight=60)

        history_frame = ttk.LabelFrame(history_container, text="Execution History", padding=5)
        history_frame.pack(fill=tk.BOTH, expand=True)

        self._create_execution_history_panel(history_frame)

        # Right pane: Execution flowchart (40% width)
        right_pane = ttk.Frame(main_paned)
        main_paned.add(right_pane, weight=40)  # 40% width

        flowchart_frame = ttk.LabelFrame(right_pane, text="Currently Executing Flowchart", padding=5)
        flowchart_frame.pack(fill=tk.BOTH, expand=True)

        # Lazy import to avoid circular dependency
        from src.views.widgets.execution_flowchart_view import ExecutionFlowchartView
        self.execution_flowchart = ExecutionFlowchartView(flowchart_frame)
        self.execution_flowchart.pack(fill=tk.BOTH, expand=True)

    def _save_git_settings(self):
        repo = self.git_repo_var.get().strip()
        branch = self.git_branch_var.get().strip()

        is_repo_valid, repo_error = validate_git_repo_url(repo)
        if not is_repo_valid:
            messagebox.showerror("Git Settings", repo_error)
            return

        is_branch_valid, branch_error = validate_git_branch_name(branch)
        if not is_branch_valid:
            messagebox.showerror("Git Settings", branch_error)
            return

        self.session.git_repo_url = repo
        self.session.git_branch = branch
        self.session.git_auto_push = self.git_auto_push_var.get()

        if self.session_manager:
            try:
                remote_status = self.session_manager.configure_git_remote(self.session)
                if not remote_status.success:
                    messagebox.showerror("Git Settings", remote_status.message)
                    return

                branch_status = self.session_manager.configure_git_branch(self.session)
                if not branch_status.success:
                    messagebox.showerror("Git Settings", branch_status.message)
                    return
            except Exception as e:
                messagebox.showerror("Git Settings", f"Failed to apply git settings: {e}")
                return

            try:
                self.session_manager.save_sessions()
            except Exception as e:
                messagebox.showerror("Git Settings", f"Failed to save git settings: {e}")
                return

        messagebox.showinfo("Git Settings", "Git settings saved for this session.")

    def _create_chat_panel(self, parent):
        """Create chat panel using existing ChatPanel component."""
        # Lazy import to avoid circular dependency
        from ..views.chat_panel import ChatPanel

        self.chat_panel = ChatPanel(
            parent,
            on_message_sent=self._on_message_sent,
            on_slash_command=self._on_slash_command
        )
        self.chat_panel.pack(fill=tk.BOTH, expand=True)

        # Open session-level chat output log
        import datetime
        import os
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        session_name = self.session.name.replace(' ', '_').replace('/', '_')

        # Ensure logs/sessions directory exists
        os.makedirs("logs/sessions", exist_ok=True)

        log_filename = f"chat_output_{session_name}_{timestamp}.log"
        log_path = os.path.join("logs", "sessions", log_filename)
        self._chat_output_log = open(log_path, "a", encoding="utf-8")
        self.chat_panel._chat_output_log = self._chat_output_log
        logger.info(f"Session chat output log opened: {log_path}")

    def _create_execution_history_panel(self, parent):
        """Create execution history panel using existing ExecutionHistoryPanel component."""
        # Lazy import to avoid circular dependency
        from ..views.execution_history_panel import ExecutionHistoryPanel

        self.execution_history_panel = ExecutionHistoryPanel(parent)
        self.execution_history_panel.pack(fill=tk.BOTH, expand=True)

    def _on_message_sent(self, message: str):
        """
        Handle message sent from chat panel.

        Args:
            message: User message
        """
        # Add user message to session chat history
        from ..models import Message
        self.session.chat_history.append(Message(role="user", content=message))

        # Send to Claude via pass-through (tracked for cleanup)
        self._track_task(self._send_passthrough_message_async(message))

    def _on_slash_command(self, command: str):
        """
        Handle slash command from chat panel (executes named flowchart).

        Args:
            command: The slash command (including /)
        """
        logger.info(f"Slash command: {command}")

        # Check if storage service is available
        if not self.storage_service:
            self.chat_panel.add_error_message("Cannot execute commands: storage service not available")
            logger.error("Storage service not available for session")
            return

        # Parse command: "/command-name arg1 arg2 "quoted arg3" ..."
        # Remove leading '/' and strip
        command_str = command[1:].strip() if len(command) > 1 else ""

        if not command_str:
            self.chat_panel.add_error_message("Invalid slash command")
            return

        # Split into command name and arguments string
        # Command name is first word, rest is arguments
        parts = command_str.split(None, 1)  # Split on first whitespace only
        command_name = parts[0]
        args_string = parts[1] if len(parts) > 1 else ""

        # Try to load the command
        try:
            cmd = self.storage_service.load_command(command_name)
            logger.info(f"Loaded command for execution: {command_name}")

            # Parse arguments using Command.parse_arguments()
            # This handles shlex parsing (quoted strings) and positional mapping
            arguments_dict = {}
            if args_string:
                try:
                    arguments_dict = cmd.parse_arguments(args_string)
                    logger.info(f"Parsed arguments: {arguments_dict}")
                except ValueError as e:
                    self.chat_panel.add_error_message(f"Argument error: {str(e)}")
                    logger.error(f"Failed to parse arguments: {e}")
                    return

            # Create execution copy of flowchart to isolate from original
            # This ensures execution doesn't modify the original command's flowchart
            execution_flowchart = cmd.create_execution_copy()

            # Set as current flowchart in session
            self.session.current_flowchart = execution_flowchart

            # Update execution flowchart view with the same copy
            self.execution_flowchart.load_flowchart(execution_flowchart)
            self.execution_flowchart.reset_all_states()

            # Add message to chat
            if arguments_dict:
                args_display = ' '.join(f"{k}={v}" for k, v in arguments_dict.items() if k.startswith('$'))
                self.chat_panel.add_system_message(f"Executing command: /{command_name} ({args_display})")
            else:
                self.chat_panel.add_system_message(f"Executing command: /{command_name}")

            # Execute the flowchart with arguments (tracked for cleanup)
            if self.session.state != SessionState.EXECUTING:
                self._track_task(self._execute_command_async(cmd, arguments_dict))
            else:
                self.chat_panel.add_error_message("Another command is already executing in this session")

        except Exception as e:
            logger.error(f"Failed to execute slash command '{command_name}': {e}")
            self.chat_panel.add_error_message(
                f"Command '/{command_name}' not found or failed to load: {str(e)}"
            )

    def _parse_sdk_message(self, sdk_message):
        """
        Parse SDK message object and extract text content and metadata.

        Args:
            sdk_message: Message object from Claude Agent SDK or plain text from Codex

        Returns:
            tuple: (text_content, verbose_content, message_type)

        Note:
            message_type can be:
            - "assistant" for Claude SDK structured messages (TextBlocks)
            - "assistant_plain" for Codex plain text chunks
            - "system", "result", "unknown" for other message types
        """

        message_str = str(sdk_message)
        message_type = "unknown"
        text_content = ""
        verbose_content = message_str

        # Check if this is a Claude SDK structured message or plain text (Codex)
        is_structured_message = any(marker in message_str for marker in
                                   ["AssistantMessage", "SystemMessage", "ResultMessage", "StreamEvent", "UserMessage"])

        # Try to parse the message
        try:
            # Check if this is a StreamEvent (new Claude Agent SDK format)
            if "StreamEvent" in message_str and "event=" in message_str:
                # Extract text from content_block_delta events using regex
                # This is more robust than ast.literal_eval which fails on escaped newlines
                # Format: event={'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': '...'}}

                # First check if this is a content_block_delta event
                # Use flexible string matching to handle both escaped and unescaped quotes
                if "content_block_delta" in message_str and "text_delta" in message_str:
                    # Extract the text value using regex
                    # Match various quote combinations to handle Python's repr() escaping
                    import re

                    # Try different patterns (repr() uses different quote combinations)
                    patterns = [
                        r"'text':\s*'((?:[^'\\]|\\.)*)'",      # 'text': '...'
                        r'"text":\s*"((?:[^"\\]|\\.)*)"',      # "text": "..."
                        r"\\'text\\':\s*\"((?:[^\"\\]|\\.)*?)\"",  # \'text\': "..." (escaped key, double value)
                        r"'text':\s*\"((?:[^\"\\]|\\.)*?)\"",  # 'text': "..." (unescaped key, double value)
                    ]

                    text_match = None
                    for pattern in patterns:
                        text_match = re.search(pattern, message_str)
                        if text_match:
                            break

                    if text_match:
                        message_type = "text_delta"  # Changed from "assistant" to distinguish from AssistantMessage
                        # Extract the text and unescape it
                        text_content = text_match.group(1)
                        # Unescape common escape sequences
                        text_content = text_content.replace('\\n', '\n')
                        text_content = text_content.replace('\\t', '\t')
                        text_content = text_content.replace('\\r', '\r')
                        text_content = text_content.replace("\\'", "'")
                        text_content = text_content.replace('\\"', '"')
                        text_content = text_content.replace('\\\\', '\\')

                        verbose_content = f"[StreamEvent] {text_content}"
                        logger.debug(f"Parsed StreamEvent chunk: {len(text_content)} chars")
                        return (text_content, verbose_content, message_type)

                # Check for other event types
                if "content_block_start" in message_str:
                    return ("", "", "content_block_start")

                event_type_checks = [
                    "message_start", "message_stop", "content_block_stop", "message_delta"
                ]
                if any(event_type in message_str for event_type in event_type_checks):
                    logger.debug("Ignoring StreamEvent system message")
                    return ("", "", "system")

            # Determine message type
            elif "AssistantMessage" in message_str:
                message_type = "assistant"
                # Extract text from TextBlock
                # Format: AssistantMessage(content=[TextBlock(text="...")], ...)
                # Try double quotes first
                start = message_str.find('TextBlock(text="')
                if start != -1:
                    start += len('TextBlock(text="')
                    end = message_str.find('")', start)
                    if end != -1:
                        text_content = message_str[start:end]
                        text_content = text_content.replace('\\n', '\n')
                else:
                    # Try single quotes (slash commands use single quotes)
                    start = message_str.find("TextBlock(text='")
                    if start != -1:
                        start += len("TextBlock(text='")
                        end = message_str.find("')", start)
                        if end != -1:
                            text_content = message_str[start:end]
                            text_content = text_content.replace('\\n', '\n')

            elif "SystemMessage" in message_str:
                message_type = "system"
                text_content = "[System initialization]"

            elif "UserMessage" in message_str:
                # Tool results - filter these out, don't display
                message_type = "result"
                text_content = ""  # Don't extract text, just classify as result

            elif "ResultMessage" in message_str:
                message_type = "result"
                # Extract result field
                start = message_str.find("result=\"")
                if start != -1:
                    start += len("result=\"")
                    end = message_str.find('")', start)
                    if end == -1:
                        # Try finding just closing quote
                        end = message_str.rfind('"')
                    if end != -1:
                        text_content = message_str[start:end]
                        text_content = text_content.replace('\\n', '\n')

            # Create pretty verbose output
            try:
                # Try to make it more readable
                verbose_lines = []
                if "AssistantMessage" in message_str:
                    verbose_lines.append("📤 Assistant Message:")
                    if text_content:
                        verbose_lines.append(f"   Content: {text_content[:100]}...")
                elif "SystemMessage" in message_str:
                    verbose_lines.append("⚙️  System Message:")
                    if "session_id" in message_str:
                        # Extract session_id
                        sid_start = message_str.find("'session_id': '") + len("'session_id': '")
                        sid_end = message_str.find("'", sid_start)
                        if sid_end != -1:
                            session_id = message_str[sid_start:sid_end]
                            verbose_lines.append(f"   Session: {session_id}")
                elif "ResultMessage" in message_str:
                    verbose_lines.append("✅ Result Message:")
                    # Extract duration
                    if "duration_ms" in message_str:
                        dur_start = message_str.find("duration_ms=") + len("duration_ms=")
                        dur_end = message_str.find(",", dur_start)
                        if dur_end != -1:
                            duration = message_str[dur_start:dur_end]
                            verbose_lines.append(f"   Duration: {duration}ms")
                    # Extract cost
                    if "total_cost_usd" in message_str:
                        cost_start = message_str.find("total_cost_usd=") + len("total_cost_usd=")
                        cost_end = message_str.find(",", cost_start)
                        if cost_end != -1:
                            cost = message_str[cost_start:cost_end]
                            verbose_lines.append(f"   Cost: ${cost}")

                if verbose_lines:
                    verbose_content = "\n".join(verbose_lines)

            except:
                pass  # Fall back to raw string

        except Exception as e:
            logger.warning(f"Failed to parse SDK message: {e}")
            text_content = message_str

        # Handle plain text messages (e.g., from Codex)
        # If no structured markers found and no text extracted, treat as plain text
        if not is_structured_message and not text_content and message_str.strip():
            message_type = "assistant_plain"
            text_content = message_str
            logger.debug(f"Parsed plain text chunk: {len(text_content)} chars")

        return (text_content, verbose_content, message_type)

    async def _send_passthrough_message_async(self, message: str):
        """
        Send a pass-through message to Claude and stream the response in real-time.

        Args:
            message: User message to send to Claude
        """
        logger.info(f"[ASYNC] Starting pass-through message processing for: {message[:50]}...")

        # Check if agent_service is available
        if not self.session.agent_service:
            self.chat_panel.add_error_message("Claude service not available")
            logger.error("Claude service not available for session")
            return

        try:
            # Get service display name and tag
            from ..services.service_factory import ServiceFactory
            service_name = ServiceFactory.get_service_display_name(self.session.service_type)
            service_tag = self.session.service_type  # "claude", "codex", or "mock"

            # Show typing indicator
            self.chat_panel.show_typing_indicator()

            # Ensure Claude service is active (will start if not already running)
            await self.session.agent_service.ensure_session()
            logger.info("[ASYNC] Claude service ready")

            # Hide typing indicator and start streaming response
            self.chat_panel.hide_typing_indicator()
            self.chat_panel.start_streaming_message(f"{service_name}: ", tag=service_tag)
            self.chat_panel.start_verbose_streaming_message(f"{service_name}: ", tag=service_tag)
            logger.info("[ASYNC] Streaming message display started")

            # Stream response chunks in real-time
            response_text = ""
            chunk_count = 0
            had_previous_text = False  # Track if previous chunk had text content
            async for chunk in self.session.agent_service.stream_prompt(message):
                chunk_count += 1

                # Parse SDK message to extract clean text and verbose info
                text_content, verbose_content, message_type = self._parse_sdk_message(chunk)

                # Display assistant messages (both structured and plain text)
                if message_type in ("assistant", "assistant_plain") and text_content:
                    # Only add paragraph breaks between structured messages (Claude TextBlocks)
                    # NOT between plain text chunks (Codex arbitrary substrings)
                    if message_type == "assistant" and had_previous_text and response_text:
                        response_text += "\n\n"
                        self.chat_panel.add_streaming_text("\n\n", tag=service_tag)
                        self.chat_panel.add_verbose_streaming_text("\n\n", tag=service_tag)

                    response_text += text_content
                    had_previous_text = True

                    # Display clean text content in BOTH Chat and Verbose tabs
                    self.chat_panel.add_streaming_text(text_content, tag=service_tag)
                    self.chat_panel.add_verbose_streaming_text(text_content, tag=service_tag)

                    # Log first chunk to confirm streaming started
                    if chunk_count == 1:
                        logger.info(f"[ASYNC] First chunk received: {text_content[:50]}...")
                elif message_type == "result":
                    # Log result metadata
                    logger.info(f"[ASYNC] {verbose_content}")
                elif message_type == "system":
                    # Log system message
                    logger.debug("[ASYNC] System message received")

            logger.info(f"[ASYNC] Claude response complete: {len(response_text)} chars in {chunk_count} chunks")

            # Close debug log file
            if hasattr(self, '_stream_debug_log') and self._stream_debug_log:
                self._stream_debug_log.write(f"\n{'='*60}\n")
                self._stream_debug_log.write("=== STREAMING SESSION ENDED (Pass-through) ===\n")
                self._stream_debug_log.write(f"Total chunks: {chunk_count}\n")
                self._stream_debug_log.write(f"Total chars: {len(response_text)}\n")
                self._stream_debug_log.close()
                log_path = self._stream_debug_log.name
                self._stream_debug_log = None
                logger.info(f"Stream debug log saved to: {log_path}")
                self.chat_panel.add_message(f"💾 Stream debug log: {log_path}", tag='system')

            # End streaming message in BOTH tabs
            self.chat_panel.end_streaming_message()
            self.chat_panel.end_verbose_streaming_message()

            # Add to session chat history
            from ..models import Message
            self.session.chat_history.append(Message(role="assistant", content=response_text))

        except Exception as e:
            logger.error(f"[ASYNC] Pass-through error: {e}", exc_info=True)
            self.chat_panel.hide_typing_indicator()

            # Close debug log file on error
            if hasattr(self, '_stream_debug_log') and self._stream_debug_log:
                self._stream_debug_log.write(f"\n{'='*60}\n")
                self._stream_debug_log.write("=== ERROR ===\n")
                self._stream_debug_log.write(f"{str(e)}\n")
                self._stream_debug_log.close()
                self._stream_debug_log = None

            self.chat_panel.end_streaming_message()
            self.chat_panel.end_verbose_streaming_message()
            self.chat_panel.add_error_message(f"Error communicating with Claude: {str(e)}")

        finally:
            # Session remains active for future messages
            # Re-enable input
            self.chat_panel.set_input_enabled(True)
            logger.info("[ASYNC] Pass-through processing complete")

    async def _execute_command_async(self, command, arguments_dict=None):
        """
        Execute a command flowchart asynchronously using Claude Agent SDK.

        Args:
            command: Command to execute
            arguments_dict: Optional dict of command arguments ($1, $2, etc.)
        """
        if arguments_dict is None:
            arguments_dict = {}

        logger.info(f"[ASYNC] Starting command execution: {command.name} with args: {arguments_dict}")

        # Check if execution controller is available
        if not self.session.execution_controller:
            self.chat_panel.add_error_message("Execution controller not available for this session")
            logger.error("Execution controller not available for session")
            return

        # Check if Claude service is available
        if not self.session.agent_service:
            self.chat_panel.add_error_message("Claude service not available for this session")
            logger.error("Claude service not available for session")
            return

        # Update session state
        self.session.state = SessionState.EXECUTING

        # Disable chat input during execution
        self.chat_panel.set_input_enabled(False)

        # Clear previous execution states
        self.execution_flowchart.reset_all_states()

        # Display start message
        self.chat_panel.add_system_message(f"Starting execution: {command.name}")

        # Note: start_execution_run is now called automatically via on_execution_start callback

        try:
            # Ensure Claude service session is active (will start if not already running)
            # USES CLAUDE AGENT SDK - NOT ANTHROPIC APIs
            await self.session.agent_service.ensure_session()
            logger.info("[ASYNC] Claude session ready via Claude Agent SDK")

            # Execute the command using the execution controller
            # This uses Claude Agent SDK internally
            # Pass arguments dict for $1, $2, etc. substitution
            context = await self.session.execution_controller.execute(command, arguments_dict)

            # Execution finished successfully
            logger.info(f"[ASYNC] Execution completed with status: {context.status}")
            self.chat_panel.add_system_message(f"✅ Execution completed: {command.name}")

            # Update session state
            self.session.complete_execution(success=True)

        except Exception as e:
            logger.error(f"[ASYNC] Execution error: {e}", exc_info=True)
            self.chat_panel.add_error_message(f"Execution error: {str(e)}")
            self.execution_flowchart.reset_all_states()

            # Update session state
            self.session.complete_execution(success=False, error_message=str(e))

        finally:
            # Re-enable chat input
            self.chat_panel.set_input_enabled(True)
            logger.info("[ASYNC] Command execution complete")

    def _setup_execution_callbacks(self):
        """Wire up execution controller callbacks for UI updates."""
        if not self.session.execution_controller:
            logger.warning("No execution controller to set up callbacks for")
            return

        # Set callbacks on execution controller (from ebd896f)
        self.session.execution_controller.on_execution_start = self._on_execution_start_callback
        self.session.execution_controller.on_block_start = self._on_block_execution_start
        self.session.execution_controller.on_block_complete = self._on_block_execution_complete
        self.session.execution_controller.on_block_complete_async = self._on_block_execution_complete_async
        self.session.execution_controller.on_execution_complete = self._on_execution_complete_callback
        self.session.execution_controller.on_prompt_stream = self._on_prompt_stream

        logger.info(f"Wired up execution callbacks for session '{self.session.name}'")

    def _on_execution_start_callback(self, command_name: str, context):
        """
        Callback when command execution starts.

        Args:
            command_name: Name of command being executed
            context: Execution context with depth information
        """
        if not self._widget_exists():
            return

        logger.info(f"Execution started: {command_name} (depth={context.depth})")

        # Start execution run in history panel with depth for nested commands
        self.execution_history_panel.start_execution_run(command_name, depth=context.depth)

        # Handle flowchart switching for nested commands (Option B)
        if context.depth > 0:
            # This is a nested command - need to switch flowchart
            # Store current flowchart first
            if not hasattr(self, '_flowchart_stack'):
                self._flowchart_stack = []

            # Save current flowchart state before switching
            if self.session.current_flowchart:
                self._flowchart_stack.append(self.session.current_flowchart)
                logger.debug(f"Pushed flowchart to stack, depth now: {len(self._flowchart_stack)}")

            # Load child command's flowchart
            # The child command is already loaded by CommandBlockExecutor
            # We need to get it from the context somehow, or we wait for blocks to execute
            # For now, we'll clear the flowchart view since we don't have the child flowchart here
            # The blocks will update as they execute
            logger.debug("Nested execution starting, flowchart will update as blocks execute")

    def _on_block_execution_start(self, block, context):
        """
        Callback when block execution starts.

        Args:
            block: Block being executed
            context: Current execution context
        """
        if not self._widget_exists():
            return

        logger.info(f"Block execution started: {block.name}")

        # Update block state on execution flowchart
        self.execution_flowchart.update_block_state(block.id, 'executing')

        # Display in chat
        self.chat_panel.add_message(f"[Executing] {block.name}", tag='system')

    def _on_block_execution_complete(self, block, result, context):
        """
        Callback when block execution completes.

        Args:
            block: Block that completed
            result: Execution result
            context: Current execution context
        """
        if not self._widget_exists():
            return

        logger.info(f"Block execution completed: {block.name}, success={result.success}")

        # End streaming message if this was a prompt block
        log_path = None
        if block.type == BlockType.PROMPT:
            self.chat_panel.end_streaming_message()
            self.chat_panel.end_verbose_streaming_message()

            # Close debug log file
            if hasattr(self, '_stream_debug_log') and self._stream_debug_log:
                self._stream_debug_log.write(f"\n{'='*60}\n")
                self._stream_debug_log.write("=== STREAMING SESSION ENDED ===\n")
                self._stream_debug_log.write(f"Block: {block.name}\n")
                self._stream_debug_log.write(f"Success: {result.success}\n")
                self._stream_debug_log.close()
                log_path = self._stream_debug_log.name
                self._stream_debug_log = None

            if log_path:
                logger.info(f"Stream debug log saved to: {log_path}")
                self.chat_panel.add_message(f"💾 Stream debug log: {log_path}", tag='system')

        # Update block state on execution flowchart
        if result.success:
            self.execution_flowchart.update_block_state(block.id, 'completed')

            # For prompt blocks, show structured output if available
            if block.type == BlockType.PROMPT and result.output:
                import json
                output_str = json.dumps(result.output, indent=2) if isinstance(result.output, dict) else str(result.output)
                self.chat_panel.add_message(f"[Output] {output_str[:200]}...", tag='system')
            elif block.type == BlockType.BASH:
                # For bash blocks, show the executed command and result
                self.chat_panel.add_message(f"[Complete] {block.name}", tag='system')
                if result.raw_response:
                    # Show the bash command that was executed (truncate if very long)
                    response_preview = result.raw_response[:500] + "..." if len(result.raw_response) > 500 else result.raw_response
                    self.chat_panel.add_message(response_preview, tag='system')
            elif block.type != BlockType.PROMPT:
                # For other non-prompt blocks, show completion
                self.chat_panel.add_message(f"[Complete] {block.name}", tag='system')

            # Add to execution history (include raw_response for bash blocks)
            self.execution_history_panel.add_block_execution(
                block.name, 'completed',
                output=result.output,
                raw_response=result.raw_response
            )
        else:
            self.execution_flowchart.update_block_state(block.id, 'error')
            # Display error in chat
            self.chat_panel.add_error_message(f"[Error] {block.name}: {result.error}")
            # Add to execution history
            self.execution_history_panel.add_block_execution(block.name, 'error', error=result.error)

    def _should_run_git_workflow(self, block) -> bool:
        return block.type in (BlockType.PROMPT, BlockType.BASH)

    async def _on_block_execution_complete_async(self, block, result, context):
        """
        Async callback after block execution completes.
        Runs git workflow and awaits completion before next block starts.
        """
        if not result.success or not self._should_run_git_workflow(block):
            return

        if not getattr(self, 'git_workflow', None):
            return

        # Run git workflow in thread pool executor to avoid blocking event loop
        import asyncio
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._run_git_workflow, block)

    def _schedule_git_workflow(self, block):
        """Schedule git workflow in background thread (for manual retries)."""
        if not getattr(self, 'git_workflow', None):
            return
        thread = threading.Thread(
            target=self._run_git_workflow,
            args=(block,),
            daemon=True
        )
        thread.start()

    def _retry_git_workflow(self):
        """Manually retry the last failed git workflow."""
        if not self._pending_git_retry_block:
            return

        block = self._pending_git_retry_block
        self._pending_git_retry_block = None
        if hasattr(self, 'git_retry_btn'):
            self.git_retry_btn.configure(state=tk.DISABLED)

        if hasattr(self, 'chat_panel'):
            self.chat_panel.add_message("[Git] Retrying last sync...", tag='system')

        self._schedule_git_workflow(block)

    def _run_git_workflow(self, block):
        try:
            result = self.git_workflow.run(
                block_type=getattr(block.type, 'value', str(block.type)),
                block_name=block.name,
                auto_push=self.session.git_auto_push,
                branch=self.session.git_branch or "",
                remote="origin"
            )
            if not result.changes_detected:
                logger.debug("[Git Workflow] No changes detected; skipping auto commit")
                return

            if result.success:
                details = " and pushed" if result.pushed else ""
                logger.info(f"[Git Workflow] {result.message}{details}")
                self.after(0, self._report_git_workflow_result, result, block)
            else:
                logger.warning(f"[Git Workflow] {result.message}")
                self.after(0, self._report_git_workflow_result, result, block)
        except Exception as e:
            logger.error(f"[Git Workflow] Error running git workflow: {e}", exc_info=True)

    def _report_git_workflow_result(self, result, block):
        if not hasattr(self, 'chat_panel'):
            return
        if result.success:
            message = "[Git] Committed changes"
            if result.commit_hash:
                message += f" ({result.commit_hash})"
            if result.pushed:
                message += " and pushed"
            self.chat_panel.add_message(message, tag='system')

            self._pending_git_retry_block = None
            if hasattr(self, 'git_retry_btn'):
                self.git_retry_btn.configure(state=tk.DISABLED)
        else:
            self._pending_git_retry_block = block
            if hasattr(self, 'git_retry_btn'):
                self.git_retry_btn.configure(state=tk.NORMAL)

            auto_push_state = "enabled" if self.session.git_auto_push else "disabled"
            self.chat_panel.add_error_message(
                f"[Git] {result.message} (auto-push {auto_push_state}). Click 'Retry Git Sync' to try again."
            )
            stdout = result.stdout.strip() if result.stdout else "<empty>"
            stderr = result.stderr.strip() if result.stderr else "<empty>"
            logger.warning(
                "[Git Workflow] Failure details for %s – stdout: %s | stderr: %s",
                getattr(block, 'name', 'unknown'),
                stdout,
                stderr
            )

    def _on_execution_complete_callback(self, context):
        """
        Callback when entire execution completes.

        Args:
            context: Final execution context
        """
        if not self._widget_exists():
            return

        logger.info(f"Execution completed: {context.status}")

        # Display completion message
        duration = (context.end_time - context.start_time).total_seconds() if context.end_time else 0

        # Customize message based on status
        if context.status.value == "halted":
            self.chat_panel.add_system_message(
                f"Execution halted gracefully (Duration: {duration:.2f}s)"
            )
        else:
            self.chat_panel.add_system_message(
                f"Execution completed: {context.status.value} (Duration: {duration:.2f}s)"
            )

        # Finish execution run in history panel
        self.execution_history_panel.end_execution_run(
            status=context.status.value,
            duration=duration
        )

        # Handle flowchart restoration for nested commands (Option B)
        if context.depth > 0 and hasattr(self, '_flowchart_stack') and self._flowchart_stack:
            # Pop flowchart stack to restore parent flowchart
            parent_flowchart = self._flowchart_stack.pop()
            self.session.current_flowchart = parent_flowchart
            self.execution_flowchart.load_flowchart(parent_flowchart)
            logger.debug(f"Restored parent flowchart, stack depth now: {len(self._flowchart_stack)}")

    def _on_prompt_stream(self, prompt_text: str, chunk: str):
        """
        Callback when prompt execution streams data.

        Args:
            prompt_text: The prompt being executed
            chunk: Streaming chunk (empty string = start of prompt)
        """
        if not self._widget_exists():
            return

        if chunk == "":
            # Get service display name and tag
            from ..services.service_factory import ServiceFactory
            service_name = ServiceFactory.get_service_display_name(self.session.service_type)
            self._service_tag = self.session.service_type  # "claude", "codex", or "mock"

            # Start of prompt - show what we're asking the AI service
            self.chat_panel.add_message(f"Prompt: {prompt_text}", tag='user')
            # Show typing indicator
            self.chat_panel.show_typing_indicator()
            # Start streaming response
            self.chat_panel.start_streaming_message(f"{service_name}: ", tag=self._service_tag)
            self.chat_panel.start_verbose_streaming_message(f"{service_name}: ", tag=self._service_tag)
            # Reset streaming state for new prompt
            self._had_previous_text_in_stream = False
            self._current_content_block_index = None
            self._streamed_via_text_delta = False

            # Open debug log file for this streaming session
            import datetime
            from pathlib import Path

            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

            # Ensure logs/debug directory exists
            debug_log_dir = Path("logs/debug")
            debug_log_dir.mkdir(parents=True, exist_ok=True)

            # Create log file
            log_filename = f"stream_debug_{timestamp}.log"
            log_path = debug_log_dir / log_filename
            self._stream_debug_log = open(log_path, "w", encoding="utf-8")
            self._stream_debug_log.write("=== STREAMING SESSION STARTED ===\n")
            self._stream_debug_log.write(f"Service: {self.session.service_type}\n")
            self._stream_debug_log.write(f"Prompt: {prompt_text}\n")
            self._stream_debug_log.write(f"{'='*60}\n\n")
            self._stream_debug_log.flush()

            # Cleanup: Keep only last 50 debug logs
            try:
                debug_logs = sorted(debug_log_dir.glob("stream_debug_*.log"))
                if len(debug_logs) > 50:
                    for old_log in debug_logs[:-50]:
                        try:
                            old_log.unlink()
                        except OSError:
                            pass  # Ignore errors when deleting old logs
            except Exception as e:
                logger.debug(f"Failed to cleanup old debug logs: {e}")

            # Session-level chat_output_log already exists - no need to create it here
        else:
            # Hide typing indicator on first response chunk
            self.chat_panel.hide_typing_indicator()
            # Stream response chunks to both tabs
            # Parse SDK message to extract clean text
            text_content, _, message_type = self._parse_sdk_message(chunk)

            # Log chunk details to debug file
            if hasattr(self, '_stream_debug_log') and self._stream_debug_log:
                self._stream_debug_log.write("--- CHUNK ---\n")
                self._stream_debug_log.write(f"Raw chunk ({len(chunk)} chars): {repr(chunk)}\n")
                self._stream_debug_log.write(f"Message type: {message_type}\n")
                self._stream_debug_log.write(f"Extracted text ({len(text_content)} chars): {repr(text_content)}\n")
                self._stream_debug_log.write("\n")
                self._stream_debug_log.flush()

            # Handle different message types
            if message_type == "content_block_start":
                # Starting a new content block
                chunk_str = str(chunk)
                # Extract block index
                if "'index':" in chunk_str:
                    import re
                    idx_match = re.search(r"'index':\s*(\d+)", chunk_str)
                    if idx_match:
                        block_index = int(idx_match.group(1))
                        # Add paragraph break between text content blocks (not before first block)
                        if self._current_content_block_index is not None and block_index > 0:
                            self.chat_panel.add_streaming_text("\n\n", tag=self._service_tag)
                            self.chat_panel.add_verbose_streaming_text("\n\n", tag=self._service_tag)
                        self._current_content_block_index = block_index

            elif message_type == "text_delta":
                # StreamEvent text chunk - display immediately
                if text_content:
                    # Log exactly what's being displayed
                    if hasattr(self, '_stream_debug_log') and self._stream_debug_log:
                        self._stream_debug_log.write(f">>> DISPLAYED TO USER: {repr(text_content)}\n")
                        self._stream_debug_log.flush()

                    self.chat_panel.add_streaming_text(text_content, tag=self._service_tag)
                    self.chat_panel.add_verbose_streaming_text(text_content, tag=self._service_tag)
                    self._streamed_via_text_delta = True

            elif message_type == "assistant":
                # AssistantMessage with complete text - only display if we DIDN'T stream it via text_delta
                if text_content and not self._streamed_via_text_delta:
                    # Add paragraph break if there was previous content
                    if self._had_previous_text_in_stream:
                        self.chat_panel.add_streaming_text("\n\n", tag=self._service_tag)
                        self.chat_panel.add_verbose_streaming_text("\n\n", tag=self._service_tag)

                    # Log exactly what's being displayed
                    if hasattr(self, '_stream_debug_log') and self._stream_debug_log:
                        self._stream_debug_log.write(f">>> DISPLAYED TO USER: {repr(text_content)}\n")
                        self._stream_debug_log.flush()

                    self.chat_panel.add_streaming_text(text_content, tag=self._service_tag)
                    self.chat_panel.add_verbose_streaming_text(text_content, tag=self._service_tag)
                    self._had_previous_text_in_stream = True

            elif message_type == "assistant_plain":
                # Plain text from services like Codex - display immediately, no paragraph breaks
                if text_content:
                    # Log exactly what's being displayed
                    if hasattr(self, '_stream_debug_log') and self._stream_debug_log:
                        self._stream_debug_log.write(f">>> DISPLAYED TO USER: {repr(text_content)}\n")
                        self._stream_debug_log.flush()

                    self.chat_panel.add_streaming_text(text_content, tag=self._service_tag)
                    self.chat_panel.add_verbose_streaming_text(text_content, tag=self._service_tag)

    def _on_restart_clicked(self):
        """Handle Restart Session button click."""
        from tkinter import messagebox

        # Show confirmation dialog
        result = messagebox.askyesno(
            "⚠️ Restart Session?",
            "This will:\n"
            "• Clear all chat history\n"
            "• Clear all execution history\n"
            "• Restart the agent\n\n"
            "Working directory, system prompt, and service type will be preserved.\n\n"
            "Are you sure?"
        )

        if result:
            # Schedule async restart (tracked for cleanup)
            self._track_task(self._restart_session_async())

    async def _restart_session_async(self):
        """Restart the session (clear state and restart agent)."""
        logger.info(f"Restarting session: {self.session.name}")

        try:
            # 1. Stop agent if running
            if self.session.agent_service and self.session.agent_service._session_active:
                logger.info("Stopping agent...")
                await self.session.agent_service.end_session()

            # 2. Clear session state
            logger.info("Clearing session state...")
            self.session.chat_history.clear()
            self.session.execution_history.clear()
            self.session.clear_halted_state()
            self.session.state = SessionState.IDLE

            # 3. Clear UI panels
            logger.info("Clearing UI panels...")
            # Clear chat panel
            self.after(0, lambda: self.chat_panel.clear_output())
            # Clear execution history panel
            self.after(0, lambda: self.execution_history_panel.clear())
            # Clear execution flowchart
            self.after(0, lambda: self.execution_flowchart.clear())

            # 4. Restart agent
            logger.info("Restarting agent...")
            await self.session.agent_service.ensure_session()

            # 5. Show success message
            logger.info("Session restarted successfully")
            self.after(0, lambda: messagebox.showinfo(
                "Session Restarted",
                "Session has been restarted with a clean state.\n\n"
                "Chat history and execution history have been cleared.\n"
                "Agent is ready for new commands."
            ))

            # 6. Add system message to chat
            self.after(0, lambda: self.chat_panel.add_system_message(
                "🔄 Session restarted - all history cleared"
            ))

        except Exception as e:
            logger.error(f"Error restarting session: {e}", exc_info=True)
            self.after(0, lambda: messagebox.showerror(
                "Restart Failed",
                f"Failed to restart session: {str(e)}"
            ))

    def _on_close_clicked(self):
        """Handle close button click."""
        # Close session-level chat output log
        if hasattr(self, '_chat_output_log') and self._chat_output_log:
            try:
                self._chat_output_log.close()
                logger.info("Session chat output log closed")
            except Exception as e:
                logger.error(f"Error closing chat output log: {e}")
            finally:
                self._chat_output_log = None
                if hasattr(self, 'chat_panel'):
                    self.chat_panel._chat_output_log = None

        if self.on_close_callback:
            self.on_close_callback(self.session)

    def destroy(self):
        """Clean up resources when widget is destroyed."""
        # Mark as destroyed first to stop callbacks from updating UI
        self._is_destroyed = True

        # Close session-level chat output log
        if hasattr(self, '_chat_output_log') and self._chat_output_log:
            try:
                self._chat_output_log.close()
                logger.info("Session chat output log closed on destroy")
            except Exception as e:
                logger.error(f"Error closing chat output log on destroy: {e}")
            finally:
                self._chat_output_log = None
                if hasattr(self, 'chat_panel'):
                    self.chat_panel._chat_output_log = None

        # Schedule cleanup in event loop if running
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self.cleanup())
            else:
                loop.run_until_complete(self.cleanup())
        except RuntimeError:
            # No event loop, tasks will be cleaned up on process exit
            pass

        # Call parent destroy
        super().destroy()
