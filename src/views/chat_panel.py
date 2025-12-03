"""
Chat Panel for FlowCoder

Displays Claude interaction interface in the right panel.
"""

import tkinter as tk
from tkinter import ttk, scrolledtext
import logging
from typing import Optional, Callable
from datetime import datetime


logger = logging.getLogger(__name__)


class ChatPanel(ttk.Frame):
    """
    Panel for Claude Code interaction.

    Features:
    - Scrollable output text area (read-only)
    - Input entry with Send button
    - Clear button for output
    - Slash command detection
    - Auto-scroll to bottom
    """

    def __init__(
        self,
        parent,
        on_message_sent: Optional[Callable[[str], None]] = None,
        on_slash_command: Optional[Callable[[str], None]] = None
    ):
        """
        Initialize chat panel.

        Args:
            parent: Parent widget
            on_message_sent: Callback when message is sent (receives message text)
            on_slash_command: Callback when slash command is detected (receives command)
        """
        super().__init__(parent)

        self.on_message_sent = on_message_sent
        self.on_slash_command = on_slash_command
        self._chat_output_log = None  # Log file for capturing exact chat output

        self._create_widgets()

        logger.info("ChatPanel initialized")

    def _create_widgets(self):
        """Create all widgets for the panel."""
        # Title label
        title_label = ttk.Label(self, text="Chat / Output", font=('TkDefaultFont', 12, 'bold'))
        title_label.pack(pady=(5, 10), padx=5, anchor=tk.W)

        # Main horizontal split: Output (left) | Input (right)
        main_paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))

        # Left pane: Output area
        left_pane = ttk.Frame(main_paned)
        main_paned.add(left_pane, weight=70)  # 70% width for output

        # Output header frame (with Clear button)
        output_header_frame = ttk.Frame(left_pane)
        output_header_frame.pack(fill=tk.X, padx=5, pady=(0, 5))

        output_label = ttk.Label(output_header_frame, text="Output:")
        output_label.pack(side=tk.LEFT)

        self.clear_button = ttk.Button(
            output_header_frame,
            text="Clear All",
            command=self._on_clear,
            width=10
        )
        self.clear_button.pack(side=tk.RIGHT)

        # Create tabbed notebook for Chat and Verbose views
        self.output_notebook = ttk.Notebook(left_pane)
        self.output_notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))

        # Chat tab (clean text only)
        chat_frame = ttk.Frame(self.output_notebook)
        self.output_notebook.add(chat_frame, text="Chat")

        self.output_text = scrolledtext.ScrolledText(
            chat_frame,
            wrap=tk.WORD,
            state=tk.DISABLED,
            font=('TkDefaultFont', 10),
            height=20
        )
        self.output_text.pack(fill=tk.BOTH, expand=True)

        # Configure text tags for Chat tab
        self.output_text.tag_config('user', foreground='#0066cc')
        self.output_text.tag_config('claude', foreground='#6600cc')  # Purple for Claude responses
        self.output_text.tag_config('codex', foreground='#00aa66')  # Green for Codex responses
        self.output_text.tag_config('mock', foreground='#aa6600')  # Orange for Mock responses
        self.output_text.tag_config('system', foreground='#666666', font=('TkDefaultFont', 9, 'italic'))
        self.output_text.tag_config('error', foreground='#cc0000')
        self.output_text.tag_config('command', foreground='#009900', font=('TkDefaultFont', 10, 'bold'))

        # Verbose tab (detailed SDK messages)
        verbose_frame = ttk.Frame(self.output_notebook)
        self.output_notebook.add(verbose_frame, text="Verbose")

        self.verbose_text = scrolledtext.ScrolledText(
            verbose_frame,
            wrap=tk.WORD,
            state=tk.DISABLED,
            font=('Courier', 9),  # Monospace for technical output
            height=20
        )
        self.verbose_text.pack(fill=tk.BOTH, expand=True)

        # Configure text tags for Verbose tab
        self.verbose_text.tag_config('user', foreground='#0066cc')
        self.verbose_text.tag_config('claude', foreground='#6600cc')
        self.verbose_text.tag_config('codex', foreground='#00aa66')
        self.verbose_text.tag_config('mock', foreground='#aa6600')
        self.verbose_text.tag_config('system', foreground='#666666', font=('Courier', 9, 'italic'))
        self.verbose_text.tag_config('error', foreground='#cc0000')
        self.verbose_text.tag_config('metadata', foreground='#999999', font=('Courier', 8))

        # Typing indicator (between output and input)
        self.typing_indicator = ttk.Label(
            left_pane,
            text="AI is typing...",
            font=('TkDefaultFont', 9, 'italic'),
            foreground='#666666'
        )
        self.typing_indicator.pack(anchor=tk.W, padx=5, pady=(5, 0))
        self.typing_indicator.pack_forget()  # Hide initially

        # Right pane: Input area
        right_pane = ttk.Frame(main_paned)
        main_paned.add(right_pane, weight=30)  # 30% width for input

        # Input label
        input_label = ttk.Label(right_pane, text="Input:")
        input_label.pack(anchor=tk.W, padx=5, pady=(0, 2))

        # Multi-line input text widget with scrollbar
        input_text_frame = ttk.Frame(right_pane)
        input_text_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))

        input_scroll = ttk.Scrollbar(input_text_frame, orient=tk.VERTICAL)
        input_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.input_text = tk.Text(
            input_text_frame,
            font=('TkDefaultFont', 10),
            wrap=tk.WORD,
            yscrollcommand=input_scroll.set,
            undo=True,  # Enable undo/redo functionality
            maxundo=-1  # Unlimited undo levels
        )
        self.input_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        input_scroll.config(command=self.input_text.yview)

        # Send button
        send_button_frame = ttk.Frame(right_pane)
        send_button_frame.pack(fill=tk.X, padx=5, pady=(0, 5))

        self.send_button = ttk.Button(
            send_button_frame,
            text="Send",
            command=self._on_send,
            width=10
        )
        self.send_button.pack(side=tk.RIGHT)

        # Bind Enter key to send, Shift+Enter and Ctrl+Enter for line breaks
        self.input_text.bind('<Return>', self._on_enter_key)
        self.input_text.bind('<Shift-Return>', lambda e: None)  # Allow line break
        self.input_text.bind('<Control-Return>', lambda e: None)  # Allow line break

        # Focus on input text
        self.input_text.focus()

        logger.debug("Chat panel widgets created")

    def _on_enter_key(self, event):
        """
        Handle Enter key press in input field.

        - Plain Enter: Send message
        - Shift+Enter or Ctrl+Enter: Insert line break (don't send)
        """
        # Check if Shift or Ctrl is pressed
        if event.state & 0x1 or event.state & 0x4:  # Shift=0x1, Ctrl=0x4
            # Allow the line break to be inserted (default behavior)
            return None

        # Plain Enter: send message
        self._on_send()
        return 'break'  # Prevent default Enter behavior (inserting newline)

    def _on_send(self):
        """Handle Send button click or Enter key press."""
        message = self.input_text.get("1.0", tk.END).strip()

        if not message:
            return

        logger.info(f"Message sent: {message[:50]}...")

        # Check if it's a slash command
        is_slash_command = message.startswith('/')

        # Display user message in BOTH Chat and Verbose tabs
        self.add_message(f"You: {message}", tag='user' if not is_slash_command else 'command')
        self.add_verbose_message(f"You: {message}", tag='user')

        # Clear input
        self.input_text.delete("1.0", tk.END)

        # Fire appropriate callback
        if is_slash_command:
            logger.info(f"Slash command detected: {message}")
            if self.on_slash_command:
                self.on_slash_command(message)
        else:
            if self.on_message_sent:
                self.on_message_sent(message)

    def _on_clear(self):
        """Handle Clear button click - clears both Chat and Verbose tabs."""
        # Clear Chat tab
        self.output_text.config(state=tk.NORMAL)
        self.output_text.delete(1.0, tk.END)
        self.output_text.config(state=tk.DISABLED)

        # Clear Verbose tab
        self.verbose_text.config(state=tk.NORMAL)
        self.verbose_text.delete(1.0, tk.END)
        self.verbose_text.config(state=tk.DISABLED)

        logger.info("Chat and verbose output cleared")

    def add_message(self, message: str, tag: str = 'system'):
        """
        Add a message to the output area.

        Args:
            message: Message text to display
            tag: Text tag for styling ('user', 'system', 'error', 'command')
        """
        self.output_text.config(state=tk.NORMAL)

        # Add timestamp
        timestamp = datetime.now().strftime("%H:%M:%S")

        # Insert message with timestamp
        full_message = f"[{timestamp}] {message}\n"
        self.output_text.insert(tk.END, f"[{timestamp}] ", 'system')
        self.output_text.insert(tk.END, f"{message}\n", tag)

        # Log exact output
        if self._chat_output_log:
            self._chat_output_log.write(full_message)
            self._chat_output_log.flush()

        # Auto-scroll to bottom
        self.output_text.see(tk.END)

        self.output_text.config(state=tk.DISABLED)

        logger.debug(f"Added message: {message[:50]}... (tag={tag})")

    def add_system_message(self, message: str):
        """
        Add a system message to the output area.

        Args:
            message: System message text
        """
        self.add_message(message, tag='system')

    def add_error_message(self, message: str):
        """
        Add an error message to the output area.

        Args:
            message: Error message text
        """
        self.add_message(f"ERROR: {message}", tag='error')

    def set_input_enabled(self, enabled: bool):
        """
        Enable or disable input controls.

        Args:
            enabled: Whether to enable input controls
        """
        state = tk.NORMAL if enabled else tk.DISABLED
        self.input_text.config(state=state)
        self.send_button.config(state=state)

    def get_input_text(self) -> str:
        """
        Get current text in input field.

        Returns:
            Current input text
        """
        return self.input_text.get("1.0", tk.END).strip()

    def set_input_text(self, text: str):
        """
        Set text in input field.

        Args:
            text: Text to set
        """
        self.input_text.delete("1.0", tk.END)
        self.input_text.insert("1.0", text)

    def clear_output(self):
        """Clear all output text."""
        self._on_clear()

    def focus_input(self):
        """Set focus to input field."""
        self.input_text.focus()

    def show_typing_indicator(self):
        """Show 'Claude is typing...' indicator."""
        # Show in pre-packed position (between output notebook and input label)
        self.typing_indicator.pack(anchor=tk.W, padx=5, pady=(5, 0))
        logger.debug("Typing indicator shown")

    def hide_typing_indicator(self):
        """Hide typing indicator."""
        self.typing_indicator.pack_forget()
        logger.debug("Typing indicator hidden")

    def add_streaming_text(self, text: str, tag: str = 'system'):
        """
        Add text to the output area without timestamp (for streaming responses).

        Args:
            text: Text to append
            tag: Text tag for styling
        """
        self.output_text.config(state=tk.NORMAL)
        self.output_text.insert(tk.END, text, tag)

        # Log exact output
        if self._chat_output_log:
            self._chat_output_log.write(text)
            self._chat_output_log.flush()

        self.output_text.see(tk.END)
        self.output_text.config(state=tk.DISABLED)
        self.output_text.update_idletasks()  # Force UI update for streaming

    def start_streaming_message(self, prefix: str, tag: str = 'system'):
        """
        Start a new streaming message with a prefix.

        Args:
            prefix: Prefix text (e.g., "Claude: ")
            tag: Text tag for styling
        """
        self.output_text.config(state=tk.NORMAL)

        # Add blank line if there's already content (for visual separation)
        if self.output_text.get("1.0", tk.END).strip():
            self.output_text.insert(tk.END, "\n")
            # Log the blank line
            if self._chat_output_log:
                self._chat_output_log.write("\n")
                self._chat_output_log.flush()

        # Add timestamp
        timestamp = datetime.now().strftime("%H:%M:%S")
        timestamp_and_prefix = f"[{timestamp}] {prefix}"
        self.output_text.insert(tk.END, f"[{timestamp}] ", 'system')
        self.output_text.insert(tk.END, f"{prefix}", tag)

        # Log exact output
        if self._chat_output_log:
            self._chat_output_log.write(timestamp_and_prefix)
            self._chat_output_log.flush()

        self.output_text.see(tk.END)
        self.output_text.config(state=tk.DISABLED)

    def end_streaming_message(self):
        """End a streaming message by adding a newline."""
        self.output_text.config(state=tk.NORMAL)
        self.output_text.insert(tk.END, "\n")

        # Log exact output
        if self._chat_output_log:
            self._chat_output_log.write("\n")
            self._chat_output_log.flush()

        self.output_text.see(tk.END)
        self.output_text.config(state=tk.DISABLED)

    def add_verbose_message(self, message: str, tag: str = 'metadata'):
        """
        Add a message to the verbose tab.

        Args:
            message: Message text to display in verbose tab
            tag: Text tag for styling
        """
        self.verbose_text.config(state=tk.NORMAL)

        # Add timestamp
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.verbose_text.insert(tk.END, f"[{timestamp}] ", 'system')
        self.verbose_text.insert(tk.END, f"{message}\n", tag)

        # Auto-scroll to bottom
        self.verbose_text.see(tk.END)

        self.verbose_text.config(state=tk.DISABLED)

    def add_verbose_streaming_text(self, text: str, tag: str = 'metadata'):
        """
        Add text to the verbose tab without timestamp (for streaming responses).

        Args:
            text: Text to append
            tag: Text tag for styling
        """
        self.verbose_text.config(state=tk.NORMAL)
        self.verbose_text.insert(tk.END, text, tag)
        self.verbose_text.see(tk.END)
        self.verbose_text.config(state=tk.DISABLED)
        self.verbose_text.update_idletasks()  # Force UI update for streaming

    def start_verbose_streaming_message(self, prefix: str, tag: str = 'metadata'):
        """
        Start a new streaming message in verbose tab with a prefix.

        Args:
            prefix: Prefix text (e.g., "Claude: ")
            tag: Text tag for styling
        """
        self.verbose_text.config(state=tk.NORMAL)

        # Add timestamp
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.verbose_text.insert(tk.END, f"[{timestamp}] ", 'system')
        self.verbose_text.insert(tk.END, f"{prefix}", tag)

        self.verbose_text.see(tk.END)
        self.verbose_text.config(state=tk.DISABLED)

    def end_verbose_streaming_message(self):
        """End a streaming message in verbose tab by adding a newline."""
        self.verbose_text.config(state=tk.NORMAL)
        self.verbose_text.insert(tk.END, "\n")
        self.verbose_text.see(tk.END)
        self.verbose_text.config(state=tk.DISABLED)
