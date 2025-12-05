"""
Block Configuration Panel for FlowCoder

Panel for editing block properties based on block type.
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from typing import Optional, Callable
import json
import logging

from src.models import Block, StartBlock, EndBlock, PromptBlock, BranchBlock, VariableBlock, BashBlock, CommandBlock, RefreshBlock

logger = logging.getLogger(__name__)


class BlockConfigPanel(ttk.Frame):
    """
    Panel for configuring block properties.

    Shows different fields based on block type:
    - All blocks: name
    - PromptBlock: prompt text, output schema (JSON), sound effect
    - CommandBlock: command name, arguments, merge output
    - VariableBlock: variable name, variable value (with substitution support)
    - BashBlock: bash command, capture output, output variable, working directory
    - BranchBlock: source block, branches, default target
    - Start/EndBlock: minimal configuration
    """

    # Sound effect options
    SOUND_EFFECTS = [
        "",  # None
        "success.wav",
        "error.wav",
        "alert.wav",
        "transition.wav",
        "done.wav"
    ]

    def __init__(
        self,
        parent: tk.Widget,
        on_block_updated: Optional[Callable[[Block], None]] = None,
        command_controller = None
    ):
        """
        Initialize block configuration panel.

        Args:
            parent: Parent widget
            on_block_updated: Callback when block is updated (block: Block)
            command_controller: Optional CommandController for listing commands
        """
        super().__init__(parent)

        self.on_block_updated = on_block_updated
        self.current_block: Optional[Block] = None
        self.command_controller = command_controller

        # Autosave state
        self._autosave_timer = None
        self._autosave_delay_ms = 500  # Wait 500ms after last change before saving

        # Create UI
        self._create_widgets()

        logger.debug("BlockConfigPanel initialized")

    def _create_widgets(self):
        """Create panel widgets."""
        # Title label
        self.title_label = ttk.Label(
            self,
            text="Block Configuration",
            font=('Arial', 12, 'bold')
        )
        self.title_label.pack(side=tk.TOP, fill=tk.X, padx=10, pady=10)

        # Scrollable content frame (dark mode)
        dark_bg = '#2b2b2b'
        canvas = tk.Canvas(self, highlightthickness=0, bg=dark_bg)
        scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=canvas.yview)
        self.content_frame = ttk.Frame(canvas)

        self.content_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=self.content_frame, anchor=tk.NW)
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Placeholder message (shown when no block selected)
        self.placeholder_label = ttk.Label(
            self.content_frame,
            text="Select a block to configure",
            foreground='gray'
        )
        self.placeholder_label.pack(pady=50)

        logger.debug("BlockConfigPanel widgets created")

    def _schedule_autosave(self, *args):
        """
        Schedule an autosave after a delay.
        Cancels any pending autosave and starts a new timer.
        This implements debouncing - only saves after user stops typing for the delay period.
        """
        # Cancel any existing timer
        if self._autosave_timer:
            self.after_cancel(self._autosave_timer)

        # Schedule new autosave
        self._autosave_timer = self.after(
            self._autosave_delay_ms,
            lambda: self._save_changes(show_message=False)
        )
        logger.debug("Autosave scheduled")

    def load_block(self, block: Optional[Block]):
        """
        Load a block for configuration.

        Args:
            block: Block to configure, or None to clear
        """
        self.current_block = block

        # Clear existing widgets in content frame
        for widget in self.content_frame.winfo_children():
            widget.destroy()

        if block is None:
            # Show placeholder
            self.placeholder_label = ttk.Label(
                self.content_frame,
                text="Select a block to configure",
                foreground='gray'
            )
            self.placeholder_label.pack(pady=50)
            return

        # Update title
        block_type = block.type.value.capitalize()
        self.title_label.config(text=f"Configure {block_type} Block")

        # Create fields based on block type
        if isinstance(block, PromptBlock):
            self._create_prompt_block_fields(block)
        elif isinstance(block, CommandBlock):
            self._create_command_block_fields(block)
        elif isinstance(block, VariableBlock):
            self._create_variable_block_fields(block)
        elif isinstance(block, BashBlock):
            self._create_bash_block_fields(block)
        elif isinstance(block, BranchBlock):
            self._create_branch_block_fields(block)
        elif isinstance(block, (StartBlock, EndBlock, RefreshBlock)):
            self._create_simple_block_fields(block)

        logger.info(f"Loaded block for configuration: {block.id} ({block.type.value})")

    def _create_simple_block_fields(self, block: Block):
        """Create fields for Start/End blocks."""
        # Name field (read-only for Start/End)
        ttk.Label(self.content_frame, text="Block Type:").pack(anchor=tk.W, padx=10, pady=(10, 0))
        type_label = ttk.Label(
            self.content_frame,
            text=block.type.value.capitalize(),
            foreground='blue'
        )
        type_label.pack(anchor=tk.W, padx=10, pady=(0, 10))

        ttk.Label(self.content_frame, text="Block Name:").pack(anchor=tk.W, padx=10, pady=(10, 0))
        self.name_entry = ttk.Entry(self.content_frame)
        self.name_entry.insert(0, block.name)
        self.name_entry.pack(fill=tk.X, padx=10, pady=(0, 10))

        # Bind autosave on name change
        self.name_entry.bind('<KeyRelease>', self._schedule_autosave)

        # Info message
        info_label = ttk.Label(
            self.content_frame,
            text=f"{block.type.value.capitalize()} blocks have minimal configuration.",
            foreground='gray',
            wraplength=250
        )
        info_label.pack(anchor=tk.W, padx=10, pady=10)

        # Save button
        self._create_save_button()

    def _create_variable_block_fields(self, block: VariableBlock):
        """Create fields for VariableBlock."""
        # Block name
        ttk.Label(self.content_frame, text="Block Name:").pack(anchor=tk.W, padx=10, pady=(10, 0))
        self.name_entry = ttk.Entry(self.content_frame)
        self.name_entry.insert(0, block.name)
        self.name_entry.pack(fill=tk.X, padx=10, pady=(0, 10))
        self.name_entry.bind('<KeyRelease>', self._schedule_autosave)

        # Variable name
        ttk.Label(self.content_frame, text="Variable Name:").pack(anchor=tk.W, padx=10, pady=(10, 0))
        self.variable_name_entry = ttk.Entry(self.content_frame)
        self.variable_name_entry.insert(0, block.variable_name)
        self.variable_name_entry.pack(fill=tk.X, padx=10, pady=(0, 5))
        self.variable_name_entry.bind('<KeyRelease>', self._schedule_autosave)

        # Help text for variable name
        help_label = ttk.Label(
            self.content_frame,
            text="Alphanumeric characters and underscores only",
            foreground='gray',
            font=('TkDefaultFont', 8)
        )
        help_label.pack(anchor=tk.W, padx=10, pady=(0, 10))

        # Variable type dropdown (NEW - Issue #2)
        ttk.Label(self.content_frame, text="Variable Type:").pack(anchor=tk.W, padx=10, pady=(10, 0))

        self.variable_type_var = tk.StringVar(value=block.variable_type or "string")
        type_dropdown = ttk.Combobox(
            self.content_frame,
            textvariable=self.variable_type_var,
            values=["string", "int", "float", "boolean"],
            state='readonly',
            width=37
        )
        type_dropdown.pack(fill=tk.X, padx=10, pady=(0, 5))
        self.variable_type_var.trace('w', self._schedule_autosave)

        # Help text for variable type
        help_label_type = ttk.Label(
            self.content_frame,
            text="Type determines how the value is interpreted in conditions",
            foreground='gray',
            font=('TkDefaultFont', 8),
            wraplength=250
        )
        help_label_type.pack(anchor=tk.W, padx=10, pady=(0, 10))

        # Variable value (dark mode)
        ttk.Label(self.content_frame, text="Variable Value:").pack(anchor=tk.W, padx=10, pady=(10, 0))
        self.variable_value_text = scrolledtext.ScrolledText(
            self.content_frame,
            height=5,
            width=40,
            wrap=tk.WORD,
            bg='#1e1e1e',
            fg='#e0e0e0',
            insertbackground='#e0e0e0'
        )
        self.variable_value_text.insert('1.0', block.variable_value)
        self.variable_value_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 5))
        self.variable_value_text.bind('<KeyRelease>', self._schedule_autosave)

        # Help text for variable value
        help_label2 = ttk.Label(
            self.content_frame,
            text="Supports variable substitution: $1, $2, {{varname}}",
            foreground='gray',
            font=('TkDefaultFont', 8),
            wraplength=250
        )
        help_label2.pack(anchor=tk.W, padx=10, pady=(0, 10))

        # Info box
        info_frame = ttk.Frame(self.content_frame, relief=tk.RIDGE, borderwidth=1)
        info_frame.pack(fill=tk.X, padx=10, pady=10)

        info_text = ttk.Label(
            info_frame,
            text="Variable blocks set variables that can be used in later blocks.\n\n"
                 "Examples:\n"
                 "• Variable Name: 'count', Value: '5'\n"
                 "• Variable Name: 'file', Value: '$1'\n"
                 "• Variable Name: 'message', Value: 'Hello {{name}}'",
            foreground='#333',
            font=('TkDefaultFont', 8),
            wraplength=250,
            justify=tk.LEFT
        )
        info_text.pack(padx=10, pady=10)

        # Save button
        self._create_save_button()

    def _create_bash_block_fields(self, block: BashBlock):
        """Create fields for BashBlock."""
        # Block name
        ttk.Label(self.content_frame, text="Block Name:").pack(anchor=tk.W, padx=10, pady=(10, 0))
        self.name_entry = ttk.Entry(self.content_frame)
        self.name_entry.insert(0, block.name)
        self.name_entry.pack(fill=tk.X, padx=10, pady=(0, 10))
        self.name_entry.bind('<KeyRelease>', self._schedule_autosave)

        # Bash command (dark mode)
        ttk.Label(self.content_frame, text="Bash Command:").pack(anchor=tk.W, padx=10, pady=(10, 0))
        self.bash_command_text = scrolledtext.ScrolledText(
            self.content_frame,
            height=8,
            width=40,
            wrap=tk.WORD,
            bg='#1e1e1e',
            fg='#e0e0e0',
            insertbackground='#e0e0e0'
        )
        self.bash_command_text.insert('1.0', block.command)
        self.bash_command_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 5))
        self.bash_command_text.bind('<KeyRelease>', self._schedule_autosave)

        # Help text for command
        help_label = ttk.Label(
            self.content_frame,
            text="Supports variable substitution: $1, $2, {{varname}}",
            foreground='gray',
            font=('TkDefaultFont', 8),
            wraplength=250
        )
        help_label.pack(anchor=tk.W, padx=10, pady=(0, 10))

        # Always capture output (variable name is optional anyway)
        self.capture_output_var = tk.BooleanVar(value=True)

        # Output variable name
        ttk.Label(self.content_frame, text="Output Variable Name (optional):").pack(anchor=tk.W, padx=10, pady=(10, 0))
        self.output_variable_entry = ttk.Entry(self.content_frame)
        self.output_variable_entry.insert(0, block.output_variable)
        self.output_variable_entry.pack(fill=tk.X, padx=10, pady=(0, 5))
        self.output_variable_entry.bind('<KeyRelease>', self._schedule_autosave)

        # Help text for output variable
        help_label2 = ttk.Label(
            self.content_frame,
            text="If specified, stdout will be stored in this variable",
            foreground='gray',
            font=('TkDefaultFont', 8),
            wraplength=250
        )
        help_label2.pack(anchor=tk.W, padx=10, pady=(0, 10))

        # Output type dropdown
        ttk.Label(self.content_frame, text="Output Type:").pack(anchor=tk.W, padx=10, pady=(10, 0))
        self.output_type_var = tk.StringVar(value=block.output_type or "string")
        output_type_dropdown = ttk.Combobox(
            self.content_frame,
            textvariable=self.output_type_var,
            values=["string", "int", "float", "boolean"],
            state='readonly',
            width=37
        )
        output_type_dropdown.pack(fill=tk.X, padx=10, pady=(0, 5))
        self.output_type_var.trace('w', self._schedule_autosave)

        # Help text for output type
        help_label_type = ttk.Label(
            self.content_frame,
            text="Type to convert output to (default: string)",
            foreground='gray',
            font=('TkDefaultFont', 8),
            wraplength=250
        )
        help_label_type.pack(anchor=tk.W, padx=10, pady=(0, 10))

        # Working directory
        ttk.Label(self.content_frame, text="Working Directory (optional):").pack(anchor=tk.W, padx=10, pady=(10, 0))
        self.working_directory_entry = ttk.Entry(self.content_frame)
        self.working_directory_entry.insert(0, block.working_directory)
        self.working_directory_entry.pack(fill=tk.X, padx=10, pady=(0, 5))
        self.working_directory_entry.bind('<KeyRelease>', self._schedule_autosave)

        # Help text for working directory
        help_label3 = ttk.Label(
            self.content_frame,
            text="Defaults to session working directory if not specified",
            foreground='gray',
            font=('TkDefaultFont', 8),
            wraplength=250
        )
        help_label3.pack(anchor=tk.W, padx=10, pady=(0, 10))

        # Continue on error checkbox
        self.continue_on_error_var = tk.BooleanVar(value=block.continue_on_error)
        continue_checkbox = ttk.Checkbutton(
            self.content_frame,
            text="Continue workflow even if command fails",
            variable=self.continue_on_error_var,
            command=self._schedule_autosave
        )
        continue_checkbox.pack(anchor=tk.W, padx=10, pady=(5, 5))

        # Exit code variable name
        ttk.Label(self.content_frame, text="Exit Code Variable Name (optional):").pack(anchor=tk.W, padx=10, pady=(10, 0))
        self.exit_code_variable_entry = ttk.Entry(self.content_frame)
        self.exit_code_variable_entry.insert(0, block.exit_code_variable)
        self.exit_code_variable_entry.pack(fill=tk.X, padx=10, pady=(0, 5))
        self.exit_code_variable_entry.bind('<KeyRelease>', self._schedule_autosave)

        # Help text for exit code variable
        help_label4 = ttk.Label(
            self.content_frame,
            text="If specified, command exit code will be stored in this variable",
            foreground='gray',
            font=('TkDefaultFont', 8),
            wraplength=250
        )
        help_label4.pack(anchor=tk.W, padx=10, pady=(0, 10))

        # Security warning box
        warning_frame = ttk.Frame(self.content_frame, relief=tk.RIDGE, borderwidth=1)
        warning_frame.pack(fill=tk.X, padx=10, pady=10)

        warning_text = ttk.Label(
            warning_frame,
            text="⚠️ Security Warning\n\n"
                 "Bash commands run with your user permissions.\n"
                 "Dangerous commands will be validated and may require confirmation.\n\n"
                 "Commands are logged for security audit.",
            foreground='#D32F2F',
            font=('TkDefaultFont', 8),
            wraplength=250,
            justify=tk.LEFT
        )
        warning_text.pack(padx=10, pady=10)

        # Save button
        self._create_save_button()

    def _create_prompt_block_fields(self, block: PromptBlock):
        """Create fields for PromptBlock."""
        # Block name
        ttk.Label(self.content_frame, text="Block Name:").pack(anchor=tk.W, padx=10, pady=(10, 0))
        self.name_entry = ttk.Entry(self.content_frame)
        self.name_entry.insert(0, block.name)
        self.name_entry.pack(fill=tk.X, padx=10, pady=(0, 10))

        # Bind autosave on name change
        self.name_entry.bind('<KeyRelease>', self._schedule_autosave)

        # Prompt text (multi-line, dark mode)
        ttk.Label(self.content_frame, text="Prompt Text:").pack(anchor=tk.W, padx=10, pady=(10, 0))
        self.prompt_text = scrolledtext.ScrolledText(
            self.content_frame,
            height=8,
            wrap=tk.WORD,
            font=('Courier', 10),
            undo=True,  # Enable undo/redo functionality
            maxundo=-1,  # Unlimited undo levels
            bg='#1e1e1e',
            fg='#e0e0e0',
            insertbackground='#e0e0e0'
        )
        self.prompt_text.insert('1.0', block.prompt)
        self.prompt_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        # Bind autosave on prompt text change
        self.prompt_text.bind('<KeyRelease>', self._schedule_autosave)

        # Output schema (JSON)
        ttk.Label(self.content_frame, text="Output Schema (JSON):").pack(anchor=tk.W, padx=10, pady=(10, 0))

        # Add help text
        help_text = ttk.Label(
            self.content_frame,
            text="Optional: JSON Schema for structured output",
            foreground='gray',
            font=('Arial', 8)
        )
        help_text.pack(anchor=tk.W, padx=10)

        self.schema_text = scrolledtext.ScrolledText(
            self.content_frame,
            height=6,
            wrap=tk.WORD,
            font=('Courier', 9),
            undo=True,  # Enable undo/redo functionality
            maxundo=-1,  # Unlimited undo levels
            bg='#1e1e1e',
            fg='#e0e0e0',
            insertbackground='#e0e0e0'
        )
        if block.output_schema:
            self.schema_text.insert('1.0', json.dumps(block.output_schema, indent=2))
        self.schema_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        # Bind autosave on schema text change
        self.schema_text.bind('<KeyRelease>', self._schedule_autosave)

        # Validate JSON button
        validate_btn = ttk.Button(
            self.content_frame,
            text="Validate JSON",
            command=self._validate_json_schema
        )
        validate_btn.pack(anchor=tk.W, padx=10, pady=(0, 10))

        # Sound effect selector
        ttk.Label(self.content_frame, text="Sound Effect:").pack(anchor=tk.W, padx=10, pady=(10, 0))
        self.sound_effect_var = tk.StringVar(value=block.sound_effect or "")
        sound_dropdown = ttk.Combobox(
            self.content_frame,
            textvariable=self.sound_effect_var,
            values=self.SOUND_EFFECTS,
            state='readonly'
        )
        sound_dropdown.pack(fill=tk.X, padx=10, pady=(0, 10))

        # Bind autosave on sound effect change
        self.sound_effect_var.trace('w', self._schedule_autosave)

        # Save button
        self._create_save_button()

    def _create_command_block_fields(self, block: CommandBlock):
        """Create fields for CommandBlock."""
        # Block name
        ttk.Label(self.content_frame, text="Block Name:").pack(anchor=tk.W, padx=10, pady=(10, 0))
        self.name_entry = ttk.Entry(self.content_frame)
        self.name_entry.insert(0, block.name)
        self.name_entry.pack(fill=tk.X, padx=10, pady=(0, 10))

        # Bind autosave on name change
        self.name_entry.bind('<KeyRelease>', self._schedule_autosave)

        # Command name dropdown
        ttk.Label(self.content_frame, text="Command to Invoke:").pack(anchor=tk.W, padx=10, pady=(10, 0))

        # Get list of available commands
        command_names = []
        if self.command_controller:
            try:
                command_metadata = self.command_controller.list_commands()
                command_names = [cmd['name'] for cmd in command_metadata]
            except Exception as e:
                logger.error(f"Error loading command list: {e}")

        # Command dropdown
        self.command_name_var = tk.StringVar(value=block.command_name or "")
        command_dropdown = ttk.Combobox(
            self.content_frame,
            textvariable=self.command_name_var,
            values=command_names,
            state='readonly' if command_names else 'normal'
        )
        command_dropdown.pack(fill=tk.X, padx=10, pady=(0, 10))

        # Bind autosave on command change
        self.command_name_var.trace('w', self._schedule_autosave)

        # Arguments field
        ttk.Label(self.content_frame, text="Arguments:").pack(anchor=tk.W, padx=10, pady=(10, 0))

        # Help text
        help_text = ttk.Label(
            self.content_frame,
            text="Optional: Arguments to pass (can use $1, {{varname}}, etc.)",
            foreground='gray',
            font=('Arial', 8)
        )
        help_text.pack(anchor=tk.W, padx=10)

        self.arguments_entry = ttk.Entry(self.content_frame)
        self.arguments_entry.insert(0, block.arguments)
        self.arguments_entry.pack(fill=tk.X, padx=10, pady=(0, 10))

        # Bind autosave on arguments change
        self.arguments_entry.bind('<KeyRelease>', self._schedule_autosave)

        # Merge output checkbox
        ttk.Label(self.content_frame, text="Output Handling:").pack(anchor=tk.W, padx=10, pady=(10, 0))

        self.merge_output_var = tk.BooleanVar(value=block.merge_output)
        merge_check = ttk.Checkbutton(
            self.content_frame,
            text="Merge child output into parent scope",
            variable=self.merge_output_var
        )
        merge_check.pack(anchor=tk.W, padx=10, pady=(0, 10))

        # Bind autosave on checkbox change
        self.merge_output_var.trace('w', self._schedule_autosave)

        # Info panel
        info_frame = ttk.LabelFrame(self.content_frame, text="How Command Blocks Work", padding=10)
        info_frame.pack(fill=tk.X, padx=10, pady=10)

        info_text = (
            "Command blocks allow you to invoke other commands\n"
            "from within a flowchart, enabling composition and\n"
            "reusability.\n"
            "\n"
            "• Select which command to invoke\n"
            "• Pass arguments (can reference parent variables)\n"
            "• Choose whether to merge child output back\n"
            "\n"
            "Example: Invoke 'analyze-code' with arguments:\n"
            "  $1 {{mode}}"
        )
        info_label = ttk.Label(
            info_frame,
            text=info_text,
            foreground='#333',
            wraplength=250,
            justify=tk.LEFT
        )
        info_label.pack(anchor=tk.W)

        # Save button
        self._create_save_button()

    def _create_branch_block_fields(self, block: BranchBlock):
        """Create fields for BranchBlock."""
        # Block name
        ttk.Label(self.content_frame, text="Block Name:").pack(anchor=tk.W, padx=10, pady=(10, 0))
        self.name_entry = ttk.Entry(self.content_frame)
        self.name_entry.insert(0, block.name)
        self.name_entry.pack(fill=tk.X, padx=10, pady=(0, 10))

        # Bind autosave on name change
        self.name_entry.bind('<KeyRelease>', self._schedule_autosave)

        # Condition field
        ttk.Label(self.content_frame, text="Condition:").pack(anchor=tk.W, padx=10, pady=(10, 0))

        # Help text
        help_text = ttk.Label(
            self.content_frame,
            text="Expression that evaluates to True or False",
            foreground='gray',
            font=('Arial', 8)
        )
        help_text.pack(anchor=tk.W, padx=10)

        self.condition_entry = ttk.Entry(self.content_frame)
        self.condition_entry.insert(0, block.condition)
        self.condition_entry.pack(fill=tk.X, padx=10, pady=(0, 10))

        # Bind autosave on condition change
        self.condition_entry.bind('<KeyRelease>', self._schedule_autosave)

        # Connection info
        info_frame = ttk.LabelFrame(self.content_frame, text="How Branch Blocks Work", padding=10)
        info_frame.pack(fill=tk.X, padx=10, pady=10)

        info_text = (
            "1. Connect a block TO this branch block (input)\n"
            "2. Create two connections FROM this branch block:\n"
            "   • True path: Drag from any port (black arrow)\n"
            "   • False path: Ctrl+Drag from any port (blue arrow)\n"
            "\n"
            "Condition Examples:\n"
            "• count > 5\n"
            "• status == 'success'\n"
            "• hasErrors == true"
        )
        info_label = ttk.Label(
            info_frame,
            text=info_text,
            foreground='#333',
            wraplength=250,
            justify=tk.LEFT
        )
        info_label.pack(anchor=tk.W)

        # Save button
        self._create_save_button()

    def _create_save_button(self):
        """Create save/apply button."""
        button_frame = ttk.Frame(self.content_frame)
        button_frame.pack(fill=tk.X, padx=10, pady=20)

        save_btn = ttk.Button(
            button_frame,
            text="Apply Changes",
            command=self._save_changes
        )
        save_btn.pack(side=tk.LEFT, padx=5)

        cancel_btn = ttk.Button(
            button_frame,
            text="Revert",
            command=lambda: self.load_block(self.current_block)
        )
        cancel_btn.pack(side=tk.LEFT, padx=5)

    def _validate_json_schema(self):
        """Validate the JSON schema field."""
        if not hasattr(self, 'schema_text'):
            return

        schema_str = self.schema_text.get('1.0', tk.END).strip()

        if not schema_str:
            messagebox.showinfo(
                "JSON Validation",
                "Schema is empty (optional field)"
            )
            return

        try:
            json.loads(schema_str)
            messagebox.showinfo(
                "JSON Validation",
                "✓ Valid JSON schema"
            )
        except json.JSONDecodeError as e:
            messagebox.showerror(
                "JSON Validation Error",
                f"Invalid JSON:\n\n{str(e)}"
            )

    def _save_changes(self, show_message=True):
        """
        Save changes to the current block.

        Args:
            show_message: If True, shows success/error messages. If False, saves silently (for autosave).
        """
        if not self.current_block:
            return

        try:
            # Update name (all blocks)
            if hasattr(self, 'name_entry'):
                new_name = self.name_entry.get().strip()
                if not new_name:
                    if show_message:
                        messagebox.showwarning(
                            "Validation Error",
                            "Block name cannot be empty"
                        )
                    return
                self.current_block.name = new_name

            # Update PromptBlock-specific fields
            if isinstance(self.current_block, PromptBlock):
                # Update prompt
                if hasattr(self, 'prompt_text'):
                    new_prompt = self.prompt_text.get('1.0', tk.END).strip()
                    if not new_prompt:
                        if show_message:
                            messagebox.showwarning(
                                "Validation Error",
                                "Prompt text cannot be empty"
                            )
                        return
                    self.current_block.prompt = new_prompt

                # Update schema
                if hasattr(self, 'schema_text'):
                    schema_str = self.schema_text.get('1.0', tk.END).strip()
                    if schema_str:
                        try:
                            self.current_block.output_schema = json.loads(schema_str)
                        except json.JSONDecodeError as e:
                            if show_message:
                                messagebox.showerror(
                                    "JSON Error",
                                    f"Invalid JSON schema:\n\n{str(e)}\n\nPlease fix the JSON before saving."
                                )
                            return
                    else:
                        self.current_block.output_schema = None

                # Update sound effect
                if hasattr(self, 'sound_effect_var'):
                    sound_effect = self.sound_effect_var.get()
                    self.current_block.sound_effect = sound_effect if sound_effect else None

            # Update CommandBlock-specific fields
            if isinstance(self.current_block, CommandBlock):
                # Update command name
                if hasattr(self, 'command_name_var'):
                    new_command_name = self.command_name_var.get().strip()
                    if not new_command_name:
                        if show_message:
                            messagebox.showwarning(
                                "Validation Error",
                                "Command name cannot be empty"
                            )
                        return
                    self.current_block.command_name = new_command_name

                # Update arguments
                if hasattr(self, 'arguments_entry'):
                    self.current_block.arguments = self.arguments_entry.get().strip()

                # Update inherit_variables
                if hasattr(self, 'inherit_variables_var'):
                    self.current_block.inherit_variables = self.inherit_variables_var.get()

                # Update merge_output
                if hasattr(self, 'merge_output_var'):
                    self.current_block.merge_output = self.merge_output_var.get()

            # Update VariableBlock-specific fields
            if isinstance(self.current_block, VariableBlock):
                # Update variable name
                if hasattr(self, 'variable_name_entry'):
                    new_variable_name = self.variable_name_entry.get().strip()
                    if not new_variable_name:
                        if show_message:
                            messagebox.showwarning(
                                "Validation Error",
                                "Variable name cannot be empty"
                            )
                        return
                    # Validate variable name format
                    if not new_variable_name.replace("_", "").isalnum():
                        if show_message:
                            messagebox.showwarning(
                                "Validation Error",
                                "Variable name must be alphanumeric (underscores allowed)"
                            )
                        return
                    self.current_block.variable_name = new_variable_name

                # Update variable value
                if hasattr(self, 'variable_value_text'):
                    new_variable_value = self.variable_value_text.get('1.0', tk.END).strip()
                    self.current_block.variable_value = new_variable_value

                # Update variable type (NEW - Issue #2)
                if hasattr(self, 'variable_type_var'):
                    self.current_block.variable_type = self.variable_type_var.get()

            # Update BashBlock-specific fields
            if isinstance(self.current_block, BashBlock):
                # Update bash command
                if hasattr(self, 'bash_command_text'):
                    new_command = self.bash_command_text.get('1.0', tk.END).strip()
                    if not new_command:
                        if show_message:
                            messagebox.showwarning(
                                "Validation Error",
                                "Bash command cannot be empty"
                            )
                        return
                    self.current_block.command = new_command

                # Update capture output
                if hasattr(self, 'capture_output_var'):
                    self.current_block.capture_output = self.capture_output_var.get()

                # Update output variable
                if hasattr(self, 'output_variable_entry'):
                    new_output_var = self.output_variable_entry.get().strip()
                    if new_output_var and not new_output_var.replace("_", "").isalnum():
                        if show_message:
                            messagebox.showwarning(
                                "Validation Error",
                                "Output variable name must be alphanumeric (underscores allowed)"
                            )
                        return
                    self.current_block.output_variable = new_output_var

                # Update working directory
                if hasattr(self, 'working_directory_entry'):
                    self.current_block.working_directory = self.working_directory_entry.get().strip()

                # Update continue on error
                if hasattr(self, 'continue_on_error_var'):
                    self.current_block.continue_on_error = self.continue_on_error_var.get()

                # Update exit code variable
                if hasattr(self, 'exit_code_variable_entry'):
                    new_exit_code_var = self.exit_code_variable_entry.get().strip()
                    if new_exit_code_var and not new_exit_code_var.replace("_", "").isalnum():
                        if show_message:
                            messagebox.showwarning(
                                "Validation Error",
                                "Exit code variable name must be alphanumeric (underscores allowed)"
                            )
                        return
                    self.current_block.exit_code_variable = new_exit_code_var

                # Update output type
                if hasattr(self, 'output_type_var'):
                    self.current_block.output_type = self.output_type_var.get()

            # Update BranchBlock-specific fields
            if isinstance(self.current_block, BranchBlock):
                # Update condition
                if hasattr(self, 'condition_entry'):
                    new_condition = self.condition_entry.get().strip()
                    if not new_condition:
                        if show_message:
                            messagebox.showwarning(
                                "Validation Error",
                                "Branch condition cannot be empty"
                            )
                        return
                    self.current_block.condition = new_condition

            # Call callback to notify of update
            if self.on_block_updated:
                self.on_block_updated(self.current_block)

            if show_message:
                messagebox.showinfo(
                    "Success",
                    "Block configuration updated successfully"
                )

            logger.info(f"Block configuration saved: {self.current_block.id}")

        except Exception as e:
            if show_message:
                messagebox.showerror(
                    "Error",
                    f"Failed to save changes:\n\n{str(e)}"
                )
            logger.error(f"Error saving block configuration: {e}", exc_info=True)

    def clear(self):
        """Clear the panel."""
        self.load_block(None)
