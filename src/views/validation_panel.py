"""
Validation Panel for FlowCoder

Displays validation errors and warnings for the current flowchart.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import logging
from typing import Optional

from src.models import ValidationResult, EndBlock


logger = logging.getLogger(__name__)


class ValidationPanel(ttk.Frame):
    """Panel for displaying flowchart validation results."""

    def __init__(self, parent, command_controller):
        """
        Initialize validation panel.

        Args:
            parent: Parent widget
            command_controller: CommandController instance
        """
        super().__init__(parent)
        self.command_controller = command_controller
        self.current_validation: Optional[ValidationResult] = None
        self.syntax_analyzer = None

        self._create_widgets()
        logger.debug("ValidationPanel initialized")

    def _create_widgets(self):
        """Create panel widgets."""
        # Header with title and validate button
        header_frame = ttk.Frame(self)
        header_frame.pack(fill=tk.X, padx=5, pady=5)

        ttk.Label(
            header_frame,
            text="Validation",
            font=("TkDefaultFont", 10, "bold")
        ).pack(side=tk.LEFT)

        self.validate_btn = ttk.Button(
            header_frame,
            text="Validate Now",
            command=self._on_validate_clicked
        )
        self.validate_btn.pack(side=tk.RIGHT)

        # Status indicator
        self.status_frame = ttk.Frame(self)
        self.status_frame.pack(fill=tk.X, padx=5, pady=2)

        self.status_label = ttk.Label(
            self.status_frame,
            text="No validation run yet",
            foreground="gray"
        )
        self.status_label.pack(side=tk.LEFT)

        # Separator
        ttk.Separator(self, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=5)

        # Scrollable results area
        results_container = ttk.Frame(self)
        results_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Scrollbar
        scrollbar = ttk.Scrollbar(results_container)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Canvas for scrolling
        self.canvas = tk.Canvas(
            results_container,
            yscrollcommand=scrollbar.set,
            highlightthickness=0
        )
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.canvas.yview)

        # Frame inside canvas for content
        self.results_frame = ttk.Frame(self.canvas)
        self.canvas_window = self.canvas.create_window(
            (0, 0),
            window=self.results_frame,
            anchor=tk.NW
        )

        # Configure canvas scrolling
        self.results_frame.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # Placeholder text
        self.placeholder_label = ttk.Label(
            self.results_frame,
            text="Click 'Validate Now' to check for errors",
            foreground="gray"
        )
        self.placeholder_label.pack(pady=20)

    def _on_frame_configure(self, event=None):
        """Update scroll region when frame size changes."""
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        """Update canvas window width when canvas is resized."""
        self.canvas.itemconfig(self.canvas_window, width=event.width)

    def _on_validate_clicked(self):
        """Handle Validate Now button click."""
        command = self.command_controller.get_current_command()
        if not command:
            messagebox.showinfo(
                "No Command",
                "Please create or select a command first"
            )
            return

        # Run validation
        result = command.flowchart.validate()
        syntax_issues = []
        if self.syntax_analyzer:
            syntax_issues = self.syntax_analyzer.analyze(command.flowchart)

        self.display_validation_result(result, syntax_issues)

        # Log result
        if result.valid:
            logger.info("Validation passed")
        else:
            logger.warning(f"Validation failed with {len(result.errors)} errors")

    def display_validation_result(self, result: ValidationResult, syntax_issues=None):
        """
        Display validation result.

        Args:
            result: ValidationResult to display
        """
        self.current_validation = result

        # Clear existing content
        for widget in self.results_frame.winfo_children():
            widget.destroy()

        # Update status
        if result.valid:
            if result.warnings:
                self.status_label.config(
                    text=f"✓ Valid (with {len(result.warnings)} warnings)",
                    foreground="orange"
                )
            else:
                self.status_label.config(
                    text="✓ Valid - No issues found",
                    foreground="green"
                )
        else:
            self.status_label.config(
                text=f"✗ Invalid ({len(result.errors)} errors)",
                foreground="red"
            )

        # Syntax warnings
        if syntax_issues:
            self._create_section(
                "Syntax Warnings",
                [f"{issue.block_name}: {issue.message}" for issue in syntax_issues],
                "orange",
                with_fixes=False
            )

        # Display errors
        if result.errors:
            self._create_section("Errors", result.errors, "red", with_fixes=True)

        # Display warnings
        if result.warnings:
            self._create_section("Warnings", result.warnings, "orange", with_fixes=False)

        # If no errors or warnings
        if not result.errors and not result.warnings:
            success_label = ttk.Label(
                self.results_frame,
                text="✓ No validation issues found!\nYour flowchart is ready to execute.",
                foreground="green",
                justify=tk.CENTER
            )
            success_label.pack(pady=20)

    def set_syntax_analyzer(self, analyzer):
        """Set syntax analyzer instance."""
        self.syntax_analyzer = analyzer

    def _create_section(self, title: str, messages: list, color: str, with_fixes: bool = False):
        """
        Create a section for errors or warnings.

        Args:
            title: Section title
            messages: List of messages
            color: Color for the title
            with_fixes: Whether to show auto-fix buttons
        """
        # Section header
        header_label = ttk.Label(
            self.results_frame,
            text=f"{title} ({len(messages)}):",
            font=("TkDefaultFont", 9, "bold"),
            foreground=color
        )
        header_label.pack(anchor=tk.W, pady=(10, 5))

        # Messages
        for msg in messages:
            msg_frame = ttk.Frame(self.results_frame)
            msg_frame.pack(fill=tk.X, padx=(10, 0), pady=2)

            # Bullet point and message
            msg_label = tk.Label(
                msg_frame,
                text=f"• {msg}",
                foreground=color if color != "orange" else "#FF8C00",  # darker orange for readability
                wraplength=280,
                justify=tk.LEFT,
                anchor=tk.W
            )
            msg_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

            # Auto-fix button for specific errors
            if with_fixes:
                self._add_auto_fix_button(msg_frame, msg)

    def _add_auto_fix_button(self, parent_frame: ttk.Frame, error_msg: str):
        """
        Add auto-fix button if applicable.

        Args:
            parent_frame: Parent frame for the button
            error_msg: Error message to check
        """
        command = self.command_controller.get_current_command()
        if not command:
            return

        # Check for specific fixable errors
        if "should have at least one End block" in error_msg:
            btn = ttk.Button(
                parent_frame,
                text="Add End Block",
                command=lambda: self._auto_fix_add_end_block(),
                width=12
            )
            btn.pack(side=tk.RIGHT, padx=(5, 0))

        elif "completely disconnected" in error_msg:
            # Extract block name from message
            block_name = error_msg.split("'")[1] if "'" in error_msg else None
            if block_name:
                btn = ttk.Button(
                    parent_frame,
                    text="Delete Block",
                    command=lambda: self._auto_fix_delete_block(block_name),
                    width=12
                )
                btn.pack(side=tk.RIGHT, padx=(5, 0))

    def _auto_fix_add_end_block(self):
        """Auto-fix: Add an End block to the flowchart."""
        command = self.command_controller.get_current_command()
        if not command:
            return

        try:
            # Create End block
            end_block = EndBlock()
            command.flowchart.add_block(end_block)

            # Save command
            self.command_controller.save_current_command()

            messagebox.showinfo(
                "Block Added",
                "End block has been added to your flowchart.\n\n"
                "You may need to connect it to your flow."
            )

            # Re-run validation
            self._on_validate_clicked()

            # Notify UI to refresh (if callback exists)
            if hasattr(self, 'on_flowchart_changed'):
                self.on_flowchart_changed()

            logger.info("Auto-fix: Added End block")

        except Exception as e:
            logger.error(f"Failed to add End block: {e}")
            messagebox.showerror("Error", f"Failed to add End block: {e}")

    def _auto_fix_delete_block(self, block_name: str):
        """
        Auto-fix: Delete a disconnected block.

        Args:
            block_name: Name of block to delete
        """
        command = self.command_controller.get_current_command()
        if not command:
            return

        # Find block by name
        block_to_delete = None
        for block in command.flowchart.blocks.values():
            if block.name == block_name:
                block_to_delete = block
                break

        if not block_to_delete:
            messagebox.showerror("Error", f"Block '{block_name}' not found")
            return

        # Confirm deletion
        response = messagebox.askyesno(
            "Confirm Deletion",
            f"Delete block '{block_name}'?\n\nThis action cannot be undone."
        )

        if not response:
            return

        try:
            # Delete block
            command.flowchart.remove_block(block_to_delete.id)

            # Save command
            self.command_controller.save_current_command()

            messagebox.showinfo(
                "Block Deleted",
                f"Block '{block_name}' has been deleted."
            )

            # Re-run validation
            self._on_validate_clicked()

            # Notify UI to refresh (if callback exists)
            if hasattr(self, 'on_flowchart_changed'):
                self.on_flowchart_changed()

            logger.info(f"Auto-fix: Deleted block '{block_name}'")

        except Exception as e:
            logger.error(f"Failed to delete block: {e}")
            messagebox.showerror("Error", f"Failed to delete block: {e}")

    def set_flowchart_changed_callback(self, callback):
        """
        Set callback for when flowchart changes.

        Args:
            callback: Function to call when flowchart is modified
        """
        self.on_flowchart_changed = callback
