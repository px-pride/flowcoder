"""Files tab for browsing and editing session files."""

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional
import logging

from ..services.session_manager import SessionManager
from ..services.file_system_service import FileSystemService
from ..services.editor_state_service import EditorStateService
from ..widgets.sessions_list_widget import SessionsListWidget
from ..widgets.file_explorer_widget import FileExplorerWidget
from ..widgets.line_numbered_text import LineNumberedText

logger = logging.getLogger(__name__)


class FilesTab(ttk.Frame):
    """Files tab for browsing and editing files in session working directories."""

    def __init__(self, parent, main_window, session_manager=None):
        """Initialize Files tab.

        Args:
            parent: Parent widget (notebook)
            main_window: Reference to MainWindow instance
            session_manager: Shared SessionManager instance (optional, creates new if None)
        """
        super().__init__(parent)
        self.main_window = main_window

        self.session_manager = session_manager if session_manager else SessionManager()
        self.editor_state_service = EditorStateService()

        self.current_session_name: Optional[str] = None
        self.current_file_path: Optional[str] = None
        self.file_system_service: Optional[FileSystemService] = None

        # Cache FileExplorerWidget instances per session (avoid recreation lag)
        self._file_explorer_cache: dict = {}  # session_name -> FileExplorerWidget

        self._create_ui()
        self._refresh_sessions()

        # Register callback to refresh when sessions change
        self.session_manager.add_session_change_callback(self._on_sessions_changed)

    def _on_sessions_changed(self):
        """Called when sessions are created or closed in any tab."""
        logger.debug("Sessions changed notification received in FilesTab")

        # Clean up cache for deleted sessions
        current_session_names = {s.name for s in self.session_manager.list_sessions()}
        cached_session_names = set(self._file_explorer_cache.keys())
        deleted_sessions = cached_session_names - current_session_names

        for session_name in deleted_sessions:
            logger.debug(f"Cleaning up cached FileExplorerWidget for deleted session: {session_name}")
            explorer = self._file_explorer_cache.pop(session_name)
            explorer.destroy()

        # Refresh the sessions list
        self._refresh_sessions()

    def _create_ui(self):
        """Create UI components."""
        # Main container with 3 panes
        main_paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True)

        # Left pane: Sessions list
        left_frame = ttk.Frame(main_paned, width=200)
        main_paned.add(left_frame, weight=0)

        ttk.Label(left_frame, text="Sessions", font=('TkDefaultFont', 10, 'bold')).pack(
            side=tk.TOP, padx=5, pady=5
        )

        self.sessions_list = SessionsListWidget(
            left_frame,
            on_session_selected=self._on_session_select
        )
        self.sessions_list.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Center pane: File explorer
        center_frame = ttk.Frame(main_paned, width=250)
        main_paned.add(center_frame, weight=0)

        self.file_explorer_container = ttk.Frame(center_frame)
        self.file_explorer_container.pack(fill=tk.BOTH, expand=True)

        self.file_explorer: Optional[FileExplorerWidget] = None

        # Show placeholder when no session selected
        self.explorer_placeholder = ttk.Label(
            self.file_explorer_container,
            text="Select a session to browse files",
            foreground='gray'
        )
        self.explorer_placeholder.pack(expand=True)

        # Right pane: Text editor
        right_frame = ttk.Frame(main_paned)
        main_paned.add(right_frame, weight=1)

        # Toolbar
        toolbar = ttk.Frame(right_frame)
        toolbar.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)

        self.file_label = ttk.Label(toolbar, text="No file open", font=('TkDefaultFont', 10))
        self.file_label.pack(side=tk.LEFT)

        self.save_btn = ttk.Button(
            toolbar,
            text="💾 Save to Disk",
            command=self._on_save_to_disk,
            state=tk.DISABLED
        )
        self.save_btn.pack(side=tk.RIGHT, padx=5)

        self.reload_btn = ttk.Button(
            toolbar,
            text="🔄 Reload from Disk",
            command=self._on_reload_from_disk,
            state=tk.DISABLED
        )
        self.reload_btn.pack(side=tk.RIGHT, padx=5)

        # Editor
        self.editor = LineNumberedText(right_frame)
        self.editor.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.editor.set_readonly(True)  # Read-only until file loaded

        # Set modified callback
        self.editor.set_modified_callback(self._on_editor_modified)

        # Show placeholder
        self.editor.set_content("Open a file to edit...")
        self.editor.set_readonly(True)

    def _refresh_sessions(self):
        """Refresh sessions list."""
        self.sessions_list.refresh()

    def _on_session_select(self, session_name: str):
        """Handle session selection.

        Args:
            session_name: Name of selected session
        """
        # Save current editor state if needed
        if self.current_session_name and self.current_file_path:
            self._save_current_editor_state()

        # Update current session
        self.current_session_name = session_name
        self.current_file_path = None

        # Get session
        session = self.session_manager.get_session(session_name)
        if not session:
            logger.warning(f"Session not found: {session_name}")
            return

        # Create FileSystemService for session
        self.file_system_service = FileSystemService(session.working_directory)

        # Update file explorer
        self._update_file_explorer()

        # Clear editor
        self.editor.clear_content()
        self.editor.set_readonly(True)
        self.file_label.config(text="No file open")
        self.save_btn.config(state=tk.DISABLED)
        self.reload_btn.config(state=tk.DISABLED)

    def _update_file_explorer(self):
        """Update file explorer for current session (using cache to avoid lag)."""
        if not self.file_system_service or not self.current_session_name:
            return

        # Hide current file explorer if any
        if self.file_explorer:
            self.file_explorer.pack_forget()

        # Hide placeholder
        self.explorer_placeholder.pack_forget()

        # Check if we have cached explorer for this session
        if self.current_session_name in self._file_explorer_cache:
            # Reuse cached explorer (no recreation = no lag)
            logger.debug(f"Reusing cached FileExplorerWidget for session: {self.current_session_name}")
            self.file_explorer = self._file_explorer_cache[self.current_session_name]
            self.file_explorer.pack(fill=tk.BOTH, expand=True)
        else:
            # Create new file explorer and cache it
            logger.debug(f"Creating new FileExplorerWidget for session: {self.current_session_name}")
            self.file_explorer = FileExplorerWidget(
                self.file_explorer_container,
                self.file_system_service,
                on_file_select=self._on_file_select
            )
            self.file_explorer.pack(fill=tk.BOTH, expand=True)
            self._file_explorer_cache[self.current_session_name] = self.file_explorer

    def _on_file_select(self, file_path: str):
        """Handle file selection from explorer.

        Args:
            file_path: Relative path to selected file
        """
        if not self.current_session_name or not self.file_system_service:
            return

        # Detect if same file is being re-opened (force reload from disk)
        is_same_file = (self.current_file_path == file_path)
        if is_same_file:
            # Check if file has unsaved changes
            if self.editor.is_dirty():
                # Warn user before discarding changes
                response = messagebox.askyesno(
                    "Unsaved Changes",
                    f"File '{file_path}' has unsaved changes.\n\n"
                    "Reload from disk and discard changes?",
                    icon='warning',
                    parent=self
                )
                if not response:
                    # User cancelled, don't reload
                    logger.debug(f"User cancelled reload of {file_path}")
                    return

            logger.debug(f"Re-opening current file, forcing reload from disk: {file_path}")
            # Clear cache to force fresh read from disk
            self.editor_state_service.clear_state(
                self.current_session_name,
                file_path
            )

        # Save current editor state if different file
        if self.current_file_path and self.current_file_path != file_path:
            self._save_current_editor_state()

        # Update current file
        self.current_file_path = file_path

        # Check if we have cached state
        cached_state = self.editor_state_service.restore_state(
            self.current_session_name,
            file_path
        )

        # Enable editor before setting content (DISABLED widgets can't be modified)
        self.editor.set_readonly(False)

        if cached_state and cached_state.is_dirty:
            # Load from cache (preserve unsaved edits)
            logger.debug(f"Loading {file_path} from cache (has unsaved edits)")
            self.editor.set_content(cached_state.content)
            self.editor.text.mark_set(tk.INSERT, cached_state.cursor_position)
            self.editor._dirty = True
        else:
            # Load from disk (get latest version)
            try:
                logger.debug(f"Loading {file_path} from disk")
                content = self.file_system_service.read_file(file_path)
                self.editor.set_content(content)
            except UnicodeDecodeError as e:
                messagebox.showerror(
                    "Binary File",
                    f"Cannot open binary file: {file_path}\n\n{e.reason}",
                    parent=self
                )
                # Re-disable editor on error
                self.editor.set_readonly(True)
                return
            except Exception as e:
                messagebox.showerror(
                    "Error Loading File",
                    f"Failed to load file: {file_path}\n\n{str(e)}",
                    parent=self
                )
                # Re-disable editor on error
                self.editor.set_readonly(True)
                return

        # Update UI
        self._update_file_label()
        self.save_btn.config(state=tk.NORMAL)
        self.reload_btn.config(state=tk.NORMAL)
        self.editor.focus_text()

    def _save_current_editor_state(self):
        """Save current editor state to cache."""
        if not self.current_session_name or not self.current_file_path:
            return

        content = self.editor.get_content()
        cursor_position = self.editor.text.index(tk.INSERT)
        is_dirty = self.editor.is_dirty()

        logger.debug(
            f"Saving editor state for {self.current_session_name}/{self.current_file_path} "
            f"(dirty={is_dirty})"
        )

        self.editor_state_service.save_state(
            session_name=self.current_session_name,
            file_path=self.current_file_path,
            content=content,
            cursor_position=cursor_position,
            is_dirty=is_dirty
        )

    def _on_save_to_disk(self):
        """Handle Save to Disk button click."""
        if not self.current_session_name or not self.current_file_path:
            return

        if not self.file_system_service:
            return

        try:
            # Get content from editor
            content = self.editor.get_content()

            # Write to disk
            logger.info(f"Saving {self.current_file_path} to disk")
            self.file_system_service.write_file(self.current_file_path, content)

            # Mark editor as clean
            self.editor.mark_clean()

            # Clear cached state (file is saved)
            self.editor_state_service.clear_state(
                self.current_session_name,
                self.current_file_path
            )

            # Update UI
            self._update_file_label()

            # Show confirmation
            messagebox.showinfo(
                "File Saved",
                f"File saved to disk:\n{self.current_file_path}",
                parent=self
            )

        except Exception as e:
            logger.error(f"Error saving file {self.current_file_path}: {e}")
            messagebox.showerror(
                "Error Saving File",
                f"Failed to save file: {self.current_file_path}\n\n{str(e)}",
                parent=self
            )

    def _on_reload_from_disk(self):
        """Handle Reload from Disk button click."""
        if not self.current_session_name or not self.current_file_path:
            return

        if not self.file_system_service:
            return

        # Check if file has unsaved changes
        if self.editor.is_dirty():
            # Warn user before discarding changes
            response = messagebox.askyesno(
                "Unsaved Changes",
                f"File '{self.current_file_path}' has unsaved changes.\n\n"
                "Reload from disk and discard changes?",
                icon='warning',
                parent=self
            )
            if not response:
                # User cancelled
                logger.debug(f"User cancelled reload of {self.current_file_path}")
                return

        try:
            # Clear cache to force fresh read from disk
            logger.info(f"Reloading {self.current_file_path} from disk")
            self.editor_state_service.clear_state(
                self.current_session_name,
                self.current_file_path
            )

            # Read fresh content from disk
            content = self.file_system_service.read_file(self.current_file_path)

            # Update editor
            self.editor.set_content(content)
            self.editor.mark_clean()

            # Update UI
            self._update_file_label()

            # Show confirmation
            messagebox.showinfo(
                "File Reloaded",
                f"File reloaded from disk:\n{self.current_file_path}",
                parent=self
            )

        except UnicodeDecodeError as e:
            logger.error(f"Error reloading file {self.current_file_path}: {e}")
            messagebox.showerror(
                "Binary File",
                f"Cannot reload binary file: {self.current_file_path}\n\n{e.reason}",
                parent=self
            )
        except Exception as e:
            logger.error(f"Error reloading file {self.current_file_path}: {e}")
            messagebox.showerror(
                "Error Reloading File",
                f"Failed to reload file: {self.current_file_path}\n\n{str(e)}",
                parent=self
            )

    def _on_editor_modified(self):
        """Handle editor modification."""
        self._update_file_label()

    def _update_file_label(self):
        """Update file label with dirty indicator."""
        if not self.current_file_path:
            self.file_label.config(text="No file open")
            return

        # Add asterisk if dirty
        dirty_indicator = " *" if self.editor.is_dirty() else ""
        self.file_label.config(text=f"{self.current_file_path}{dirty_indicator}")
