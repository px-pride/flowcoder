"""Text widget with line numbers."""

import tkinter as tk
from tkinter import ttk, font as tkfont
import logging

logger = logging.getLogger(__name__)


class LineNumberedText(ttk.Frame):
    """Text widget with line numbers in the margin."""

    def __init__(self, parent, **kwargs):
        """Initialize line numbered text widget.

        Args:
            parent: Parent widget
            **kwargs: Additional arguments passed to Text widget
        """
        super().__init__(parent)

        self._dirty = False
        self._modified_callback = None
        self._suppress_callback = False

        self._create_ui(**kwargs)

        logger.debug("LineNumberedText widget initialized")

    def _create_ui(self, **text_kwargs):
        """Create UI components."""
        # Container for line numbers and text
        container = ttk.Frame(self)
        container.pack(fill=tk.BOTH, expand=True)

        # Line numbers canvas
        self.line_numbers = tk.Canvas(
            container,
            width=50,
            bg='#f0f0f0',
            highlightthickness=0
        )
        self.line_numbers.pack(side=tk.LEFT, fill=tk.Y)

        # Vertical scrollbar
        self._v_scroll = ttk.Scrollbar(container, orient=tk.VERTICAL)
        self._v_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Enable undo/redo by default unless explicitly disabled
        if 'undo' not in text_kwargs:
            text_kwargs['undo'] = True
        if 'maxundo' not in text_kwargs and text_kwargs.get('undo', True):
            text_kwargs['maxundo'] = -1  # Unlimited undo levels

        # Text widget
        self.text = tk.Text(
            container,
            yscrollcommand=self._on_scroll,
            wrap=tk.NONE,
            **text_kwargs
        )
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._v_scroll.config(command=self.text.yview)

        # Horizontal scrollbar
        h_scroll = ttk.Scrollbar(self, orient=tk.HORIZONTAL, command=self.text.xview)
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.text.config(xscrollcommand=h_scroll.set)

        # Use monospace font
        text_font = tkfont.Font(family='Courier', size=10)
        self.text.config(font=text_font)

        # Bind events
        self.text.bind('<<Modified>>', self._on_text_modified)
        self.text.bind('<KeyRelease>', lambda e: self._update_line_numbers())
        self.text.bind('<ButtonRelease>', lambda e: self._update_line_numbers())

        # Initial line numbers
        self._update_line_numbers()

        logger.debug("LineNumberedText UI created")

    def _on_scroll(self, *args):
        """Handle scrolling."""
        # Update scrollbar
        self._v_scroll.set(*args)

        # Update line numbers
        self._update_line_numbers()

    def _on_text_modified(self, event):
        """Handle text modification."""
        if self.text.edit_modified():
            self._dirty = True
            self._update_line_numbers()

            if self._modified_callback and not self._suppress_callback:
                self._modified_callback()

            # Reset modified flag to detect next modification
            self.text.edit_modified(False)

    def _update_line_numbers(self):
        """Update line numbers display."""
        self.line_numbers.delete('all')

        try:
            # Get visible line range
            first_visible = self.text.index('@0,0')
            last_visible = self.text.index(f'@0,{self.text.winfo_height()}')

            first_line = int(first_visible.split('.')[0])
            last_line = int(last_visible.split('.')[0])

            # Get total number of lines
            total_lines = int(self.text.index('end-1c').split('.')[0])

            # Get font metrics for proper alignment
            text_font = self.text.cget('font')
            if isinstance(text_font, str):
                # Font is a string, need to get actual font object
                actual_font = tkfont.Font(font=text_font)
            else:
                actual_font = text_font

            line_height = actual_font.metrics('linespace')

            # Calculate y offset based on scroll position
            # Get the bbox of the first visible line
            try:
                bbox = self.text.bbox(f"{first_line}.0")
                if bbox:
                    y_offset = bbox[1]
                else:
                    y_offset = 0
            except:
                y_offset = 0

            # Draw line numbers
            for i in range(first_line, min(last_line + 2, total_lines + 1)):
                # Calculate y position
                line_bbox = self.text.bbox(f"{i}.0")
                if line_bbox:
                    y = line_bbox[1] + line_height // 2
                else:
                    # Fallback calculation
                    y = (i - first_line) * line_height + y_offset + line_height // 2

                self.line_numbers.create_text(
                    45, y,
                    text=str(i),
                    anchor=tk.E,
                    fill='#666',
                    font=('Courier', 9)
                )

        except Exception as e:
            # Silently handle errors during line number update
            logger.debug(f"Error updating line numbers: {e}")

    def get_content(self) -> str:
        """Get text content.

        Returns:
            Text content (may include trailing newline)
        """
        return self.text.get('1.0', tk.END)

    def set_content(self, content: str):
        """Set text content.

        Args:
            content: Content to set
        """
        self._suppress_callback = True
        self.text.delete('1.0', tk.END)
        self.text.insert('1.0', content)
        self._dirty = False
        # Reset the modified flag to prevent queued events
        self.text.edit_modified(False)
        self._suppress_callback = False
        self._update_line_numbers()

        logger.debug(f"Content set ({len(content)} chars)")

    def clear_content(self):
        """Clear text content."""
        self._suppress_callback = True
        self.text.delete('1.0', tk.END)
        self._dirty = False
        # Reset the modified flag to prevent queued events
        self.text.edit_modified(False)
        self._suppress_callback = False
        self._update_line_numbers()

        logger.debug("Content cleared")

    def is_dirty(self) -> bool:
        """Check if content has been modified.

        Returns:
            True if modified but not saved
        """
        return self._dirty

    def mark_clean(self):
        """Mark content as saved (not dirty)."""
        self._dirty = False
        logger.debug("Marked as clean")

    def set_readonly(self, readonly: bool):
        """Set read-only mode.

        Args:
            readonly: True to make read-only
        """
        if readonly:
            self.text.config(state=tk.DISABLED, bg='#f5f5f5')
            logger.debug("Set to read-only")
        else:
            self.text.config(state=tk.NORMAL, bg='white')
            logger.debug("Set to writable")

    def set_modified_callback(self, callback):
        """Set callback for when text is modified.

        Args:
            callback: Function to call when text changes
        """
        self._modified_callback = callback
        logger.debug("Modified callback set")

    def focus_text(self):
        """Set focus to text widget."""
        self.text.focus_set()

    def goto_line(self, line_number: int):
        """Scroll to specific line.

        Args:
            line_number: Line number to scroll to (1-indexed)
        """
        self.text.see(f'{line_number}.0')
        self.text.mark_set(tk.INSERT, f'{line_number}.0')
        self._update_line_numbers()

        logger.debug(f"Jumped to line {line_number}")
