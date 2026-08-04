"""
Enhanced status bar widget for FlowCoder v2.0.

Displays global status across all tabs with 3 sections:
- Left: Status message
- Middle: Session name + state indicator
- Right: Working directory + connection status
"""

import tkinter as tk
from tkinter import ttk
from typing import Literal

SessionState = Literal["idle", "executing", "halted", "error"]


class StatusBar(ttk.Frame):
    """
    Global status bar displayed at bottom of main window.

    Shows status across all tabs with 3 sections:
    - Left: Status message
    - Middle: Session name + state indicator
    - Right: Working directory + connection status
    """

    # Session state indicators (emoji)
    STATE_INDICATORS = {
        "idle": "🟢",
        "executing": "🔵",
        "halted": "🟡",
        "error": "🔴",
    }

    def __init__(self, parent):
        super().__init__(parent, relief=tk.SUNKEN, borderwidth=1)
        self._create_ui()

    def _create_ui(self):
        """Create the 3-section status bar layout."""
        # Dark mode colors
        dark_bg = '#1e1e1e'
        dark_fg = '#e0e0e0'

        # Left section: Status message
        self.status_label = tk.Label(
            self,
            text="Ready",
            anchor=tk.W,
            relief=tk.SUNKEN,
            borderwidth=1,
            padx=5,
            pady=2,
            bg=dark_bg,
            fg=dark_fg
        )
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Middle section: Session name + state
        self.session_label = tk.Label(
            self,
            text="No active session",
            anchor=tk.CENTER,
            relief=tk.SUNKEN,
            borderwidth=1,
            padx=5,
            pady=2,
            width=30,
            bg=dark_bg,
            fg=dark_fg
        )
        self.session_label.pack(side=tk.LEFT, fill=tk.X, padx=2)

        # Right section: Working directory + connection
        self.info_frame = tk.Frame(self, bg=dark_bg)
        self.info_frame.pack(side=tk.LEFT, fill=tk.X)

        self.dir_label = tk.Label(
            self.info_frame,
            text="Working Dir: ~/",
            anchor=tk.W,
            relief=tk.SUNKEN,
            borderwidth=1,
            padx=5,
            pady=2,
            width=25,
            bg=dark_bg,
            fg=dark_fg
        )
        self.dir_label.pack(side=tk.LEFT, fill=tk.X, padx=2)

        self.connection_label = tk.Label(
            self.info_frame,
            text="Not connected",
            anchor=tk.W,
            relief=tk.SUNKEN,
            borderwidth=1,
            padx=5,
            pady=2,
            width=15,
            bg=dark_bg,
            fg=dark_fg
        )
        self.connection_label.pack(side=tk.LEFT, fill=tk.X)

    def set_status(self, message: str):
        """
        Update the status message (left section).

        Args:
            message: Status text (e.g., "Ready", "Executing...", "File saved")
        """
        self.status_label.configure(text=message)
        self.update_idletasks()

    def set_session(self, session_name: str, state: SessionState = "idle"):
        """
        Update the session info (middle section).

        Args:
            session_name: Name of active session or "No active session"
            state: Session state ("idle", "executing", "halted", "error")
        """
        indicator = self.STATE_INDICATORS.get(state, "⚪")
        text = f"{indicator} {session_name}"
        self.session_label.configure(text=text)
        self.update_idletasks()

    def set_working_dir(self, directory: str):
        """
        Update the working directory display (right section).

        Args:
            directory: Path to working directory
        """
        # Truncate long paths with ellipsis
        max_len = 35
        if len(directory) > max_len:
            display_dir = "..." + directory[-(max_len - 3):]
        else:
            display_dir = directory

        self.dir_label.configure(text=f"Working Dir: {display_dir}")
        self.update_idletasks()

    def set_connection_status(self, status: str):
        """
        Update the Claude connection status (right section).

        Args:
            status: Connection status ("Connected", "Connecting...", "Error", "Not connected")
        """
        # Color-code connection status
        if status == "Connected":
            self.connection_label.configure(text=f"✓ {status}", fg="#4CAF50")  # Green
        elif status == "Connecting...":
            self.connection_label.configure(text=f"⟳ {status}", fg="#2196F3")  # Blue
        elif status == "Error":
            self.connection_label.configure(text=f"✗ {status}", fg="#F44336")  # Red
        else:
            self.connection_label.configure(text=status, fg="#808080")  # Gray

        self.update_idletasks()

    def clear_session(self):
        """Clear session info (show no active session)."""
        self.set_session("No active session", "idle")

    def temporary_status(self, message: str, duration_ms: int = 3000):
        """
        Show temporary status message, then revert to "Ready".

        Args:
            message: Temporary status message
            duration_ms: How long to show message (default 3 seconds)
        """
        self.set_status(message)
        self.after(duration_ms, lambda: self.set_status("Ready"))
