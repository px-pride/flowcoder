"""
NewSessionDialog - Dialog for creating new Claude Code sessions.

Provides a modal dialog with:
- Session name input with validation
- Working directory selector
- Model selection dropdown
- Optional system prompt text area
- Create/Cancel buttons with keyboard shortcuts
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
import re
from typing import Optional
import logging

from ..services.session_manager import SessionManager
from ..services.service_factory import ServiceFactory
from ..models import Session
from ..utils import validate_git_repo_url, validate_git_branch_name


logger = logging.getLogger(__name__)


class NewSessionDialog(tk.Toplevel):
    """
    Dialog for creating a new Claude Code session.

    Modal dialog with input validation for:
    - Session name (alphanumeric + spaces/hyphens/underscores, no duplicates)
    - Working directory (must exist and be a directory)
    - Optional system prompt
    """

    # Session name validation pattern (alphanumeric, spaces, hyphens, underscores)
    SESSION_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9\s\-_]+$')

    # Max session name length
    MAX_SESSION_NAME_LENGTH = 50

    # Session count warning threshold
    SESSION_WARNING_THRESHOLD = 5

    # Default system prompt (empty = use Claude Code's default)
    DEFAULT_SYSTEM_PROMPT = ""

    def __init__(self, parent, session_manager: Optional[SessionManager] = None):
        """
        Initialize the New Session dialog.

        Args:
            parent: Parent window
            session_manager: Optional SessionManager instance (for testing)
        """
        super().__init__(parent)

        # Configure dialog
        self.title("New Claude Code Session")
        self.geometry("600x500")
        self.resizable(False, True)  # Allow vertical resizing

        # Make modal and force to top
        self.transient(parent)
        self.grab_set()

        # Force window to appear on top
        self.lift()
        self.attributes('-topmost', True)
        self.after(100, lambda: self.attributes('-topmost', False))  # Remove topmost after showing

        # Center on parent
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

        # Ensure window is visible
        self.deiconify()
        self.focus_force()

        # Session manager (use provided or get singleton)
        self.session_manager = session_manager or SessionManager()

        # Git metadata vars
        self.git_repo_var = tk.StringVar()
        self.git_branch_var = tk.StringVar()
        self.git_auto_push_var = tk.BooleanVar(value=False)

        # Result (will be set to created Session if successful)
        self.result: Optional[Session] = None

        # Create UI
        self._create_ui()

        # Bind keyboard shortcuts
        self.bind("<Return>", lambda e: self.on_create())
        self.bind("<Escape>", lambda e: self.on_cancel())

        logger.debug("NewSessionDialog initialized")

    def _create_ui(self):
        """Create dialog UI components."""
        # Create canvas with scrollbar for scrolling
        self.canvas = tk.Canvas(self)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas_window = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        # Bind canvas resize to update scrollable frame width
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # Bind mousewheel scrolling
        self.canvas.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"))  # Linux scroll up
        self.canvas.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"))   # Linux scroll down

        # Pack scrollbar and canvas
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        # Main content frame inside scrollable area
        main_frame = ttk.Frame(self.scrollable_frame, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Session name
        ttk.Label(main_frame, text="Session Name *", font=("TkDefaultFont", 10, "bold")).grid(
            row=0, column=0, sticky=tk.W, pady=(0, 5)
        )

        self.name_var = tk.StringVar()
        self.name_entry = ttk.Entry(main_frame, textvariable=self.name_var, width=50)
        self.name_entry.grid(row=1, column=0, columnspan=2, sticky=tk.EW, pady=(0, 10))
        self.name_entry.focus_set()

        ttk.Label(main_frame, text="Alphanumeric, spaces, hyphens, and underscores only. Max 50 characters.",
                  font=("TkDefaultFont", 8), foreground="gray").grid(
            row=2, column=0, columnspan=2, sticky=tk.W, pady=(0, 15)
        )

        # AI Service Type
        ttk.Label(main_frame, text="AI Service *", font=("TkDefaultFont", 10, "bold")).grid(
            row=3, column=0, sticky=tk.W, pady=(0, 5)
        )

        # Get available services and filter to only show available ones
        available_services = ServiceFactory.get_available_services()
        service_options = []
        service_type_map = {}  # Map display name to service type

        for service_type, (display_name, is_available, reason) in available_services.items():
            if is_available and service_type != "mock":  # Exclude mock from user-facing options
                service_options.append(display_name)
                service_type_map[display_name] = service_type

        self.service_type_var = tk.StringVar(value="Claude Code")  # Default to Claude
        self.service_type_map = service_type_map  # Store for later lookup

        self.service_dropdown = ttk.Combobox(
            main_frame,
            textvariable=self.service_type_var,
            values=service_options,
            state="readonly",
            width=47
        )
        self.service_dropdown.grid(row=4, column=0, columnspan=2, sticky=tk.EW, pady=(0, 5))

        ttk.Label(main_frame, text="Choose which AI service to use for this session.",
                  font=("TkDefaultFont", 8), foreground="gray").grid(
            row=5, column=0, columnspan=2, sticky=tk.W, pady=(0, 15)
        )

        # Working directory
        ttk.Label(main_frame, text="Working Directory *", font=("TkDefaultFont", 10, "bold")).grid(
            row=6, column=0, sticky=tk.W, pady=(0, 5)
        )

        dir_frame = ttk.Frame(main_frame)
        dir_frame.grid(row=7, column=0, columnspan=2, sticky=tk.EW, pady=(0, 10))

        self.directory_var = tk.StringVar()
        self.directory_entry = ttk.Entry(dir_frame, textvariable=self.directory_var, width=42)
        self.directory_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

        self.browse_btn = ttk.Button(dir_frame, text="Browse...", command=self.on_browse)
        self.browse_btn.pack(side=tk.RIGHT)

        ttk.Label(main_frame, text="Directory must exist and be accessible.",
                  font=("TkDefaultFont", 8), foreground="gray").grid(
            row=8, column=0, columnspan=2, sticky=tk.W, pady=(0, 15)
        )

        # System prompt (optional)
        ttk.Label(main_frame, text="System Prompt (Optional)", font=("TkDefaultFont", 10, "bold")).grid(
            row=9, column=0, sticky=tk.W, pady=(0, 5)
        )

        self.system_prompt_text = tk.Text(main_frame, height=6, width=50, wrap=tk.WORD,
                                          undo=True, maxundo=-1)  # Enable undo/redo
        self.system_prompt_text.grid(row=10, column=0, columnspan=2, sticky=tk.EW, pady=(0, 5))
        self.system_prompt_text.insert("1.0", self.DEFAULT_SYSTEM_PROMPT)

        ttk.Label(main_frame, text="Leave blank to use the AI service's default system prompt.",
                  font=("TkDefaultFont", 8), foreground="gray").grid(
            row=11, column=0, columnspan=2, sticky=tk.W, pady=(0, 15)
        )

        # Git metadata section
        git_frame = ttk.LabelFrame(main_frame, text="Git Integration (Optional)", padding=10)
        git_frame.grid(row=12, column=0, columnspan=2, sticky=tk.EW, pady=(0, 15))

        ttk.Label(git_frame, text="Repository URL:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        self.git_repo_entry = ttk.Entry(git_frame, textvariable=self.git_repo_var)
        self.git_repo_entry.grid(row=0, column=1, sticky=tk.EW, padx=5, pady=2)

        ttk.Label(
            git_frame,
            text="Example: https://github.com/org/repo.git or git@github.com:org/repo.git",
            font=("TkDefaultFont", 8),
            foreground="gray"
        ).grid(row=1, column=0, columnspan=2, sticky=tk.W, padx=5, pady=(0, 5))

        ttk.Label(git_frame, text="Branch:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=2)
        self.git_branch_entry = ttk.Entry(git_frame, textvariable=self.git_branch_var)
        self.git_branch_entry.grid(row=2, column=1, sticky=tk.EW, padx=5, pady=2)

        ttk.Label(
            git_frame,
            text="Allowed: letters, numbers, '/', '.', '_', '-'. Leave blank for the default branch.",
            font=("TkDefaultFont", 8),
            foreground="gray"
        ).grid(row=3, column=0, columnspan=2, sticky=tk.W, padx=5, pady=(0, 5))

        self.git_auto_push_check = ttk.Checkbutton(
            git_frame,
            text="Enable auto-push",
            variable=self.git_auto_push_var
        )
        self.git_auto_push_check.grid(row=4, column=0, columnspan=2, sticky=tk.W, padx=5, pady=(5, 0))

        git_frame.columnconfigure(1, weight=1)

        # Buttons
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=13, column=0, columnspan=2, sticky=tk.E, pady=(10, 0))

        ttk.Button(btn_frame, text="Cancel", command=self.on_cancel).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(btn_frame, text="Create Session", command=self.on_create).pack(side=tk.RIGHT)

        # Configure column weights
        main_frame.columnconfigure(0, weight=1)

    def on_browse(self):
        """Handle Browse button click."""
        directory = filedialog.askdirectory(
            parent=self,
            title="Select Working Directory",
            initialdir=self.directory_var.get() or Path.home()
        )

        if directory:
            self.directory_var.set(directory)
            logger.debug(f"Selected directory: {directory}")

    def _on_canvas_configure(self, event):
        """Update scrollable frame width when canvas is resized."""
        self.canvas.itemconfig(self.canvas_window, width=event.width)

    def validate_inputs(self) -> tuple[bool, str]:
        """
        Validate all input fields.

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Session name validation
        name = self.name_var.get().strip()

        if not name:
            return False, "Session name is required."

        if len(name) > self.MAX_SESSION_NAME_LENGTH:
            return False, f"Session name must be {self.MAX_SESSION_NAME_LENGTH} characters or less."

        if not self.SESSION_NAME_PATTERN.match(name):
            return False, "Session name can only contain letters, numbers, spaces, hyphens, and underscores."

        # Check for duplicate session name
        existing_sessions = self.session_manager.list_sessions()
        if any(session.name == name for session in existing_sessions):
            return False, f"A session named '{name}' already exists. Please choose a different name."

        # Working directory validation
        directory = self.directory_var.get().strip()

        if not directory:
            return False, "Working directory is required."

        directory_path = Path(directory)

        if not directory_path.exists():
            return False, f"Directory '{directory}' does not exist."

        if not directory_path.is_dir():
            return False, f"Path '{directory}' is not a directory."

        repo_url = self.git_repo_var.get().strip()
        is_repo_valid, repo_error = validate_git_repo_url(repo_url)
        if not is_repo_valid:
            return False, repo_error

        branch = self.git_branch_var.get().strip()
        is_branch_valid, branch_error = validate_git_branch_name(branch)
        if not is_branch_valid:
            return False, branch_error

        # All validations passed
        return True, ""

    def on_create(self):
        """Handle Create Session button click."""
        # Validate inputs
        is_valid, error_message = self.validate_inputs()

        if not is_valid:
            messagebox.showerror("Validation Error", error_message, parent=self)
            logger.warning(f"Validation failed: {error_message}")
            return

        # Get values
        name = self.name_var.get().strip()
        directory = self.directory_var.get().strip()
        system_prompt = self.system_prompt_text.get("1.0", tk.END).strip()

        # Get selected service type (map from display name to service type)
        service_display_name = self.service_type_var.get()
        service_type = self.service_type_map.get(service_display_name, "claude")

        # Use default if system prompt is empty or unchanged
        if not system_prompt or system_prompt == self.DEFAULT_SYSTEM_PROMPT:
            system_prompt = self.DEFAULT_SYSTEM_PROMPT

        try:
            # Create session via SessionManager
            session = self.session_manager.create_session(
                name=name,
                working_directory=directory,
                system_prompt=system_prompt,
                service_type=service_type
            )

            session.git_repo_url = self.git_repo_var.get().strip()
            session.git_branch = self.git_branch_var.get().strip()
            session.git_auto_push = self.git_auto_push_var.get()

            try:
                remote_status = self.session_manager.configure_git_remote(session)
                if not remote_status.success:
                    messagebox.showwarning(
                        "Git Configuration",
                        remote_status.message,
                        parent=self
                    )
                else:
                    branch_status = self.session_manager.configure_git_branch(session)
                    if not branch_status.success:
                        messagebox.showwarning(
                            "Git Configuration",
                            branch_status.message,
                            parent=self
                        )
            except Exception as e:
                logger.warning(f"Failed to configure git settings: {e}")

            try:
                self.session_manager.save_sessions()
            except Exception as e:
                logger.warning(f"Failed to save sessions after git update: {e}")

            self.result = session
            logger.info(f"Created new session: {session.name}")

            # Close dialog
            self.destroy()

        except Exception as e:
            messagebox.showerror(
                "Error Creating Session",
                f"Failed to create session: {str(e)}",
                parent=self
            )
            logger.error(f"Error creating session: {e}", exc_info=True)

    def on_cancel(self):
        """Handle Cancel button click."""
        logger.debug("New session dialog cancelled")
        self.result = None
        self.destroy()

    def destroy(self):
        """Clean up bindings before destroying dialog."""
        # Unbind mousewheel events to avoid affecting other widgets
        self.canvas.unbind_all("<Button-4>")
        self.canvas.unbind_all("<Button-5>")
        super().destroy()

    @staticmethod
    def show(parent, session_manager: Optional[SessionManager] = None) -> Optional[Session]:
        """
        Show the dialog and return the created session (or None if cancelled).

        Args:
            parent: Parent window
            session_manager: Optional SessionManager instance (for testing)

        Returns:
            Created Session object, or None if cancelled
        """
        logger.info("NewSessionDialog.show() called")
        try:
            dialog = NewSessionDialog(parent, session_manager)
            logger.info("Dialog created, waiting for window close...")
            dialog.wait_window()
            logger.info(f"Dialog closed, result: {dialog.result}")
            return dialog.result
        except Exception as e:
            logger.error(f"Error in NewSessionDialog.show(): {e}", exc_info=True)
            raise
