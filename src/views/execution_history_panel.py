"""
Execution History Panel for FlowCoder

Displays log of executed blocks with timestamps and outputs.
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
import logging
import json
from typing import Optional, Any
from datetime import datetime


logger = logging.getLogger(__name__)


class ExecutionHistoryPanel(ttk.Frame):
    """
    Panel for displaying execution history.

    Features:
    - Tree view showing execution runs and block executions
    - Timestamps for each execution
    - Status indicators (success, error)
    - Expandable JSON output display
    - Clear history button
    - Export history to file
    """

    def __init__(self, parent):
        """
        Initialize execution history panel.

        Args:
            parent: Parent widget
        """
        super().__init__(parent)

        self._run_stack: list[str] = []  # Stack of run IDs for nested command execution
        self.execution_count = 0
        self._block_counter = 0  # Counter for unique block IDs

        self._create_widgets()

        logger.info("ExecutionHistoryPanel initialized")

    @property
    def current_run_id(self) -> Optional[str]:
        """Get current run ID from top of stack."""
        return self._run_stack[-1] if self._run_stack else None

    def _create_widgets(self):
        """Create all widgets for the panel."""
        # Title and controls
        header_frame = ttk.Frame(self)
        header_frame.pack(fill=tk.X, padx=5, pady=5)

        title_label = ttk.Label(
            header_frame,
            text="Execution History",
            font=('TkDefaultFont', 12, 'bold')
        )
        title_label.pack(side=tk.LEFT)

        # Buttons frame
        button_frame = ttk.Frame(header_frame)
        button_frame.pack(side=tk.RIGHT)

        self.export_btn = ttk.Button(
            button_frame,
            text="Export",
            command=self._on_export,
            width=10
        )
        self.export_btn.pack(side=tk.LEFT, padx=2)

        self.clear_btn = ttk.Button(
            button_frame,
            text="Clear",
            command=self._on_clear,
            width=10
        )
        self.clear_btn.pack(side=tk.LEFT, padx=2)

        # Main horizontal split: Tree (left) | Detail view (right)
        main_paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))

        # Left pane: Tree view
        left_pane = ttk.Frame(main_paned)
        main_paned.add(left_pane, weight=60)  # 60% width for tree

        # Scrollbars for tree
        tree_scroll_y = ttk.Scrollbar(left_pane, orient=tk.VERTICAL)
        tree_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)

        tree_scroll_x = ttk.Scrollbar(left_pane, orient=tk.HORIZONTAL)
        tree_scroll_x.pack(side=tk.BOTTOM, fill=tk.X)

        # Treeview
        self.tree = ttk.Treeview(
            left_pane,
            columns=('timestamp', 'status', 'details', 'full_output'),
            show='tree headings',
            yscrollcommand=tree_scroll_y.set,
            xscrollcommand=tree_scroll_x.set
        )
        self.tree.pack(fill=tk.BOTH, expand=True)

        tree_scroll_y.config(command=self.tree.yview)
        tree_scroll_x.config(command=self.tree.xview)

        # Configure columns
        self.tree.heading('#0', text='Execution / Block', anchor=tk.W)
        self.tree.heading('timestamp', text='Timestamp', anchor=tk.W)
        self.tree.heading('status', text='Status', anchor=tk.W)
        self.tree.heading('details', text='Details', anchor=tk.W)

        self.tree.column('#0', width=200, minwidth=150)
        self.tree.column('timestamp', width=150, minwidth=100)
        self.tree.column('status', width=100, minwidth=80)
        self.tree.column('details', width=300, minwidth=200)
        self.tree.column('full_output', width=0, stretch=False)  # Hidden column for storing full output data

        # Tags for styling
        self.tree.tag_configure('run', font=('TkDefaultFont', 10, 'bold'))
        self.tree.tag_configure('block', font=('TkDefaultFont', 9))
        self.tree.tag_configure('success', foreground='#006600')
        self.tree.tag_configure('error', foreground='#cc0000')
        self.tree.tag_configure('executing', foreground='#0066cc')
        self.tree.tag_configure('complete', foreground='#006600')

        # Right pane: Detail view
        right_pane = ttk.Frame(main_paned)
        main_paned.add(right_pane, weight=40)  # 40% width for detail view

        # Detail label
        detail_label = ttk.Label(
            right_pane,
            text="Selected Output:",
            font=('TkDefaultFont', 10, 'bold')
        )
        detail_label.pack(anchor=tk.W, padx=5, pady=(0, 2))

        # Detail text area
        self.detail_text = scrolledtext.ScrolledText(
            right_pane,
            wrap=tk.WORD,
            state=tk.DISABLED,
            font=('Courier', 9)
        )
        self.detail_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))

        # Bind selection event
        self.tree.bind('<<TreeviewSelect>>', self._on_tree_select)

        logger.debug("ExecutionHistoryPanel widgets created")

    def start_execution_run(self, command_name: str, depth: int = 0):
        """
        Start a new execution run.

        Args:
            command_name: Name of the command being executed
            depth: Nesting depth (0 for top-level, >0 for nested commands)
        """
        self.execution_count += 1
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        run_id = f"run_{self.execution_count}_{int(datetime.now().timestamp())}"

        # Determine parent for insertion
        # If depth > 0 and we have a parent run, insert as child of parent run
        # Otherwise, insert at top level
        parent_id = ''
        if depth > 0 and self._run_stack:
            parent_id = self._run_stack[-1]  # Current run becomes parent

        # Create visual nesting indicator
        indent = "  └─ " if depth > 0 else ""
        run_text = f"{indent}Run #{self.execution_count}: {command_name}"

        # Insert run entry
        self.tree.insert(
            parent_id,
            'end' if parent_id else 0,  # Append to parent or insert at top
            run_id,
            text=run_text,
            values=(timestamp, 'Running', '', ''),  # 4th value is full_output (empty for runs)
            tags=('run', 'executing')
        )

        # Push onto stack
        self._run_stack.append(run_id)

        # Expand the new run and its parent
        self.tree.item(run_id, open=True)
        if parent_id:
            self.tree.item(parent_id, open=True)

        # Auto-scroll to show new run
        self.tree.see(run_id)

        logger.info(f"Started execution run: {run_id} (depth={depth}, parent={parent_id or 'none'})")

    def add_block_execution(self, block_name: str, status: str, output: Any = None, error: str = None, raw_response: str = None):
        """
        Add a block execution to the current run.

        Args:
            block_name: Name of the block
            status: Status ('executing', 'completed', 'error')
            output: Block output (will be JSON-formatted if dict/list)
            error: Error message if status is 'error'
            raw_response: Raw response text (e.g., bash command executed)
        """
        if not self.current_run_id:
            logger.warning("No current run to add block execution to")
            return

        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]  # Include milliseconds

        # Use counter instead of timestamp to guarantee uniqueness
        block_id = f"block_{self.current_run_id}_{self._block_counter}"
        self._block_counter += 1

        # Format details
        if error:
            details = f"Error: {error}"
            tags = ('block', 'error')
        elif raw_response:
            # Show raw response (e.g., bash command) in details
            details = raw_response[:100] + "..." if len(raw_response) > 100 else raw_response
            tags = ('block', 'complete' if status == 'completed' else status)
        elif output is not None:
            if isinstance(output, (dict, list)):
                details = json.dumps(output, indent=2)[:100] + "..." if len(str(output)) > 100 else json.dumps(output, indent=2)
            else:
                details = str(output)[:100] + "..." if len(str(output)) > 100 else str(output)
            tags = ('block', 'complete' if status == 'completed' else status)
        else:
            details = ""
            tags = ('block', status)

        # Prepare full output for storage (prefer raw_response, fallback to output)
        full_output = ''
        if raw_response:
            full_output = raw_response
        elif output is not None:
            full_output = json.dumps(output, indent=2) if isinstance(output, (dict, list)) else str(output)

        # Insert block entry under current run
        self.tree.insert(
            self.current_run_id,
            'end',
            block_id,
            text=block_name,
            values=(timestamp, status.capitalize(), details, full_output),
            tags=tags
        )

        # Auto-scroll to show latest
        self.tree.see(block_id)

        logger.debug(f"Added block execution: {block_name} ({status})")

    def end_execution_run(self, status: str, duration: float = 0.0):
        """
        End the current execution run.

        Args:
            status: Final status ('complete', 'error', 'stopped')
            duration: Execution duration in seconds
        """
        if not self.current_run_id:
            logger.warning("No current run to end")
            return

        # Update run status
        status_text = f"{status.capitalize()} ({duration:.2f}s)"
        tags = ['run']
        if status == 'complete':
            tags.append('success')
        elif status == 'error':
            tags.append('error')

        # Store run_id before popping from stack
        run_id = self.current_run_id

        self.tree.item(
            run_id,
            values=(self.tree.item(run_id)['values'][0], status_text, '', ''),  # 4th value is full_output (empty for runs)
            tags=tags
        )

        # Pop from stack
        if self._run_stack and self._run_stack[-1] == run_id:
            self._run_stack.pop()
            logger.info(f"Ended execution run: {run_id} ({status}), stack depth now: {len(self._run_stack)}")
        else:
            logger.warning(f"Run stack mismatch: expected {run_id} at top, but stack is {self._run_stack}")

    def _on_tree_select(self, event):
        """Handle tree item selection."""
        selected = self.tree.selection()
        if not selected:
            return

        item_id = selected[0]

        # Check if item has full output stored
        full_output = self.tree.set(item_id, '#4')

        if full_output:
            # Display full output in detail view
            self.detail_text.config(state=tk.NORMAL)
            self.detail_text.delete('1.0', tk.END)
            self.detail_text.insert('1.0', full_output)
            self.detail_text.config(state=tk.DISABLED)
        else:
            # Clear detail view
            self.detail_text.config(state=tk.NORMAL)
            self.detail_text.delete('1.0', tk.END)
            self.detail_text.insert('1.0', '(No output)')
            self.detail_text.config(state=tk.DISABLED)

    def _on_clear(self):
        """Clear all execution history."""
        if not self.tree.get_children():
            return

        # Confirm with user
        if messagebox.askyesno(
            "Clear History",
            "Are you sure you want to clear all execution history?"
        ):
            # Clear tree
            for item in self.tree.get_children():
                self.tree.delete(item)

            # Clear detail view
            self.detail_text.config(state=tk.NORMAL)
            self.detail_text.delete('1.0', tk.END)
            self.detail_text.config(state=tk.DISABLED)

            # Reset counters
            self.execution_count = 0
            self._run_stack.clear()

            logger.info("Execution history cleared")

    def _on_export(self):
        """Export execution history to JSON file."""
        if not self.tree.get_children():
            messagebox.showinfo("Export History", "No execution history to export.")
            return

        # Ask for file location
        filename = filedialog.asksaveasfilename(
            title="Export Execution History",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialfile=f"execution_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )

        if not filename:
            return

        try:
            # Build history data structure
            history = []

            for run_id in self.tree.get_children():
                run_data = {
                    'run_number': int(run_id.split('_')[1]),
                    'command': self.tree.item(run_id)['text'],
                    'timestamp': self.tree.item(run_id)['values'][0],
                    'status': self.tree.item(run_id)['values'][1],
                    'blocks': []
                }

                # Get all block executions for this run
                for block_id in self.tree.get_children(run_id):
                    block_output = self.tree.set(block_id, '#4')

                    # Try to parse JSON output
                    try:
                        output_data = json.loads(block_output) if block_output else None
                    except (json.JSONDecodeError, ValueError):
                        output_data = block_output

                    block_data = {
                        'name': self.tree.item(block_id)['text'],
                        'timestamp': self.tree.item(block_id)['values'][0],
                        'status': self.tree.item(block_id)['values'][1],
                        'output': output_data
                    }
                    run_data['blocks'].append(block_data)

                history.append(run_data)

            # Write to file
            with open(filename, 'w') as f:
                json.dump(history, f, indent=2)

            messagebox.showinfo(
                "Export Complete",
                f"Execution history exported to:\n{filename}"
            )
            logger.info(f"Exported execution history to: {filename}")

        except Exception as e:
            logger.error(f"Failed to export history: {e}", exc_info=True)
            messagebox.showerror(
                "Export Error",
                f"Failed to export execution history:\n\n{str(e)}"
            )

    def clear(self):
        """Clear the history (without confirmation)."""
        for item in self.tree.get_children():
            self.tree.delete(item)

        self.detail_text.config(state=tk.NORMAL)
        self.detail_text.delete('1.0', tk.END)
        self.detail_text.config(state=tk.DISABLED)

        self.execution_count = 0
        self._run_stack.clear()
