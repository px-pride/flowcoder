"""
Collapsible frame widget for Tkinter.

Provides a frame that can be expanded/collapsed by clicking a header.
"""

import tkinter as tk
from tkinter import ttk


class CollapsibleFrame(ttk.Frame):
    """
    A frame that can be collapsed/expanded by clicking the header.

    The header shows a toggle indicator (▼ expanded, ▶ collapsed) and title.
    Clicking the header or indicator toggles the visibility of the content.
    """

    def __init__(
        self,
        parent,
        title: str = "",
        collapsed: bool = False,
        padding: int = 5,
        **kwargs
    ):
        """
        Initialize the collapsible frame.

        Args:
            parent: Parent widget
            title: Title text shown in the header
            collapsed: Whether to start collapsed (default: False = expanded)
            padding: Padding around the content (default: 5)
            **kwargs: Additional arguments passed to ttk.Frame
        """
        super().__init__(parent, **kwargs)

        self._collapsed = collapsed
        self._title = title
        self._padding = padding

        # Header frame (always visible)
        self._header_frame = ttk.Frame(self)
        self._header_frame.pack(fill=tk.X)

        # Toggle indicator and title
        self._toggle_var = tk.StringVar(value="▶" if collapsed else "▼")
        self._toggle_btn = ttk.Label(
            self._header_frame,
            textvariable=self._toggle_var,
            font=('TkDefaultFont', 9),
            cursor="hand2"
        )
        self._toggle_btn.pack(side=tk.LEFT, padx=(5, 2))

        self._title_label = ttk.Label(
            self._header_frame,
            text=title,
            font=('TkDefaultFont', 9, 'bold'),
            cursor="hand2"
        )
        self._title_label.pack(side=tk.LEFT, padx=(0, 5))

        # Separator line under header
        self._separator = ttk.Separator(self, orient=tk.HORIZONTAL)
        self._separator.pack(fill=tk.X, pady=(2, 0))

        # Content frame (can be hidden)
        self._content_frame = ttk.Frame(self, padding=padding)
        if not collapsed:
            self._content_frame.pack(fill=tk.BOTH, expand=True)

        # Bind click events to toggle
        self._toggle_btn.bind("<Button-1>", self._on_toggle)
        self._title_label.bind("<Button-1>", self._on_toggle)
        self._header_frame.bind("<Button-1>", self._on_toggle)

    @property
    def content_frame(self) -> ttk.Frame:
        """Get the content frame where child widgets should be added."""
        return self._content_frame

    @property
    def is_collapsed(self) -> bool:
        """Check if the frame is currently collapsed."""
        return self._collapsed

    def _on_toggle(self, event=None):
        """Handle toggle click event."""
        if self._collapsed:
            self.expand()
        else:
            self.collapse()

    def collapse(self):
        """Collapse the frame (hide content)."""
        if not self._collapsed:
            self._content_frame.pack_forget()
            self._toggle_var.set("▶")
            self._collapsed = True

    def expand(self):
        """Expand the frame (show content)."""
        if self._collapsed:
            self._content_frame.pack(fill=tk.BOTH, expand=True)
            self._toggle_var.set("▼")
            self._collapsed = False

    def toggle(self):
        """Toggle between collapsed and expanded states."""
        if self._collapsed:
            self.expand()
        else:
            self.collapse()

    def set_title(self, title: str):
        """Update the title text."""
        self._title = title
        self._title_label.configure(text=title)

    def columnconfigure(self, index, **kwargs):
        """Configure column in content frame (for grid layout compatibility)."""
        self._content_frame.columnconfigure(index, **kwargs)

    def rowconfigure(self, index, **kwargs):
        """Configure row in content frame (for grid layout compatibility)."""
        self._content_frame.rowconfigure(index, **kwargs)
