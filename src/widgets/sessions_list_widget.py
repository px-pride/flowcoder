"""
SessionsListWidget - Display list of all sessions.

Shows session name, state indicator, and working directory for each session.
Allows selection of sessions and refreshes automatically.
"""

import tkinter as tk
from tkinter import ttk
from typing import Optional, Callable
from pathlib import Path

from ..models import SessionState
from ..services import SessionManager


class SessionsListWidget(ttk.Frame):
    """
    Widget displaying list of all sessions.

    Shows session name, state indicator, and working directory.
    Supports session selection and automatic refresh.
    """

    STATE_ICONS = {
        SessionState.IDLE: "🟢",
        SessionState.EXECUTING: "🔵",
        SessionState.HALTED: "🟡",
        SessionState.ERROR: "🔴",
    }

    def __init__(
        self,
        parent,
        on_session_selected: Optional[Callable[[str], None]] = None,
        session_manager: Optional[SessionManager] = None
    ):
        """
        Initialize sessions list widget.

        Args:
            parent: Parent widget
            on_session_selected: Callback fired when session selected (receives session name)
            session_manager: Optional SessionManager instance (for testing)
        """
        super().__init__(parent)

        self.session_manager = session_manager or SessionManager()
        self.on_session_selected = on_session_selected
        self.selected_session_name: Optional[str] = None
        self._session_names = []  # Track session names by index

        self._create_ui()
        self.refresh()

    def _create_ui(self):
        """Create UI components."""
        # Label
        label = ttk.Label(self, text="Sessions", font=("Arial", 12, "bold"))
        label.pack(pady=5, padx=5, anchor=tk.W)

        # Frame for listbox + scrollbar
        list_frame = ttk.Frame(self)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))

        # Scrollbar
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Listbox
        self.listbox = tk.Listbox(
            list_frame,
            yscrollcommand=scrollbar.set,
            font=("Courier New", 10),
            selectmode=tk.SINGLE,
            height=15
        )
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.listbox.yview)

        # Bind selection event
        self.listbox.bind("<<ListboxSelect>>", self._on_selection_changed)

    def refresh(self):
        """
        Refresh sessions list from SessionManager.

        Updates the listbox with current sessions, preserving selection if possible.
        """
        # Save current selection
        current_selection = self.selected_session_name

        # Clear listbox
        self.listbox.delete(0, tk.END)
        self._session_names.clear()

        # Get all sessions
        sessions = self.session_manager.list_sessions()

        if not sessions:
            # Show empty state
            self.listbox.insert(tk.END, "No sessions. Click 'New Session' to create one.")
            self.listbox.config(state=tk.DISABLED)
            return

        self.listbox.config(state=tk.NORMAL)

        # Sort sessions by name for consistent display
        sessions.sort(key=lambda s: s.name)

        # Add each session
        for session in sessions:
            # Format: "🟢 session-name"
            icon = self.STATE_ICONS.get(session.state, "⚪")
            text = f"{icon} {session.name}"
            self.listbox.insert(tk.END, text)
            self._session_names.append(session.name)

        # Restore selection if possible
        if current_selection and current_selection in self._session_names:
            self._select_session_by_name(current_selection)
        elif sessions:
            # Select first session if no previous selection
            self._select_session_by_index(0)

    def _truncate_path(self, path: str, max_len: int) -> str:
        """
        Truncate path for display.

        Args:
            path: Full path
            max_len: Maximum length

        Returns:
            Truncated path with ~ for home directory
        """
        # Replace home directory with ~
        path_obj = Path(path)
        try:
            relative = path_obj.relative_to(Path.home())
            path = f"~/{relative}"
        except ValueError:
            pass

        if len(path) <= max_len:
            return path

        # Truncate with ellipsis
        return "..." + path[-(max_len - 3):]

    def _on_selection_changed(self, event):
        """Handle listbox selection change."""
        selection = self.listbox.curselection()
        if not selection:
            return

        index = selection[0]

        # Check if it's the empty state message
        if not self._session_names:
            return

        # Get session name
        session_name = self._session_names[index]
        self.selected_session_name = session_name

        # Fire callback
        if self.on_session_selected:
            self.on_session_selected(session_name)

    def _select_session_by_name(self, name: str):
        """
        Select session by name.

        Args:
            name: Session name to select
        """
        if name in self._session_names:
            index = self._session_names.index(name)
            self._select_session_by_index(index)

    def _select_session_by_index(self, index: int):
        """
        Select session by index.

        Args:
            index: Listbox index
        """
        if 0 <= index < len(self._session_names):
            self.listbox.selection_clear(0, tk.END)
            self.listbox.selection_set(index)
            self.listbox.see(index)
            self.selected_session_name = self._session_names[index]

    def get_selected_session_name(self) -> Optional[str]:
        """
        Get currently selected session name.

        Returns:
            Selected session name or None
        """
        return self.selected_session_name

    def update_session_state(self, session_name: str, new_state: SessionState):
        """
        Update a session's state indicator.

        Args:
            session_name: Name of session to update
            new_state: New state
        """
        # For now, just refresh the entire list
        # In future, could update individual item for better performance
        self.refresh()
