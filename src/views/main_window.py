"""
Main Window for FlowCoder v2.0

Provides the main application window with tabbed interface:
- Commands tab: Command creation and editing
- Agents tab: Multi-session Claude Code execution (placeholder)
- Files tab: File browser and editor (placeholder)
"""

import tkinter as tk
from tkinter import ttk, messagebox
import logging
import asyncio
from typing import Optional, List

from src.services import StorageService, ClaudeAgentService, MockClaudeService, AudioService
from src.controllers import ExecutionController, CommandController, UIController
from src.views.commands_tab import CommandsTab
from src.views.agents_tab import AgentsTab
from src.views.files_tab import FilesTab
from src.views.widgets.status_bar import StatusBar
from src.models import Command, Block, BlockType
from src.models.execution import ExecutionContext, BlockResult
from src.utils.accessibility import FocusManager, HighContrastManager, AccessibilityConfig


logger = logging.getLogger(__name__)


class MainWindow:
    """
    Main application window for FlowCoder v2.0.

    Layout:
    - Menu bar at top
    - Tabbed interface (Commands, Agents, Files)
    - Enhanced status bar at bottom
    """

    def __init__(self, title: str = "FlowCoder", width: int = 1200, height: int = 800):
        """
        Initialize main window.

        Args:
            title: Window title
            width: Initial window width
            height: Initial window height
        """
        self.root = tk.Tk()
        self.root.title(title)
        self.root.geometry(f"{width}x{height}")

        # Configure window behavior
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Initialize UI controller (first, as other components may use it)
        self.ui_controller = UIController(self.root)

        # Initialize storage service
        self.storage_service = StorageService()

        # Initialize session manager (shared by Agents and Files tabs)
        from src.services.session_manager import SessionManager
        self.session_manager = SessionManager()

        # Initialize command controller
        self.command_controller = CommandController(self.storage_service)

        # Current command being edited
        self.current_command: Optional[Command] = None

        # Track if previous streaming chunk had text content (for paragraph breaks)
        self._had_previous_text_in_stream = False

        # Initialize audio service
        self.audio_service = AudioService()

        # Working directory for Claude operations
        import os
        self.working_directory = os.getcwd()

        # Initialize Claude service and execution controller
        # Use real Claude Agent SDK by default, MockClaudeService for testing
        use_mock = os.getenv('USE_MOCK_CLAUDE', 'false').lower() == 'true'

        if use_mock:
            logger.info("Using MockClaudeService (USE_MOCK_CLAUDE=true)")
            self.agent_service = MockClaudeService()
        else:
            logger.info(f"Using real ClaudeAgentService with cwd={self.working_directory}")
            self.agent_service = ClaudeAgentService(
                cwd=self.working_directory,
                system_prompt="You are a helpful assistant that helps users create automated workflows.",
                permission_mode="bypassPermissions",
                stderr_callback=self._on_claude_stderr,
                model="claude-opus-4-5"
            )

        self.execution_controller = ExecutionController(
            self.agent_service,
            on_block_start=self._on_block_execution_start,
            on_block_complete=self._on_block_execution_complete,
            on_execution_complete=self._on_execution_complete,
            on_prompt_stream=self._on_prompt_stream
        )
        self.execution_controller.on_refresh_requested = self.refresh_claude_session

        # Execution state
        self.is_executing = False
        self.execution_task: Optional[asyncio.Task] = None

        # Track async tasks for cleanup
        self._async_tasks: List[asyncio.Task] = []

        # Create and configure asyncio event loop for Tkinter integration
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        logger.info("AsyncIO event loop created and configured")

        # Create menu bar
        self._create_menu_bar()

        # Create tabbed interface
        self._create_tabs()

        # Create enhanced status bar
        self._create_status_bar()

        # Apply styling
        self._apply_styling()

        # Initialize accessibility features (Phase 6.2)
        self._initialize_accessibility()

        # Start asyncio task runner
        self._schedule_async_tasks()

        # Don't auto-start Claude session - user must explicitly start it
        # Session will auto-start when user sends a message or runs a command

        logger.info(f"MainWindow v2.0 initialized ({width}x{height})")

    def _create_menu_bar(self):
        """Create menu bar with File, Edit, and Help menus."""
        self.menu_bar = tk.Menu(self.root)
        self.root.config(menu=self.menu_bar)

        # File menu
        self.file_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_bar.add_cascade(label="File", menu=self.file_menu)
        self.file_menu.add_command(label="New Command", command=self.on_new_command, accelerator="Ctrl+N")
        self.file_menu.add_command(label="Open Command", command=self.on_open_command, accelerator="Ctrl+O")
        self.file_menu.add_command(label="Save Command", command=self.on_save_command, accelerator="Ctrl+S")
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Import...", command=self.on_import)
        self.file_menu.add_command(label="Export...", command=self.on_export)
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Exit", command=self.on_closing, accelerator="Ctrl+Q")

        # Edit menu
        self.edit_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_bar.add_cascade(label="Edit", menu=self.edit_menu)
        self.edit_menu.add_command(label="Undo", command=self.on_undo, accelerator="Ctrl+Z")
        self.edit_menu.add_command(label="Redo", command=self.on_redo, accelerator="Ctrl+Y")
        self.edit_menu.add_separator()
        self.edit_menu.add_command(label="Cut", command=self.on_cut, accelerator="Ctrl+X")
        self.edit_menu.add_command(label="Copy", command=self.on_copy, accelerator="Ctrl+C")
        self.edit_menu.add_command(label="Paste", command=self.on_paste, accelerator="Ctrl+V")
        self.edit_menu.add_separator()
        self.edit_menu.add_command(label="Select All", command=self.on_select_all, accelerator="Ctrl+A")

        # Settings menu
        self.settings_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_bar.add_cascade(label="Settings", menu=self.settings_menu)
        self.settings_menu.add_command(label="Set Working Directory...", command=self.on_set_working_directory)
        self.settings_menu.add_command(label="Refresh Claude Connection", command=self.on_refresh_claude)
        self.settings_menu.add_separator()
        self.settings_menu.add_command(label="Preferences", command=self.on_preferences)

        # Help menu
        self.help_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_bar.add_cascade(label="Help", menu=self.help_menu)
        self.help_menu.add_command(label="Documentation", command=self.on_documentation)
        self.help_menu.add_command(label="Keyboard Shortcuts", command=self.on_shortcuts)
        self.help_menu.add_separator()
        self.help_menu.add_command(label="About", command=self.on_about)

        # Bind keyboard shortcuts with focus guards
        # Application shortcuts - only trigger when text widgets don't have focus
        self.root.bind("<Control-n>", self._handle_new_command_key)
        self.root.bind("<Control-o>", self._handle_open_command_key)
        self.root.bind("<Control-s>", self._handle_save_command_key)
        self.root.bind("<Control-q>", self._handle_quit_key)
        self.root.bind("<Control-r>", self._handle_switch_agents_key)

        # Text editing shortcuts - always work for text widgets
        self.root.bind("<Control-a>", self._handle_select_all_key)
        self.root.bind("<Control-x>", self._handle_cut_key)
        self.root.bind("<Control-c>", self._handle_copy_key)
        self.root.bind("<Control-v>", self._handle_paste_key)
        self.root.bind("<Control-z>", self._handle_undo_key)
        self.root.bind("<Control-y>", self._handle_redo_key)

        # Accessibility keyboard shortcuts (Phase 6.2)
        self.root.bind("<Control-h>", self._handle_high_contrast_key)

        logger.debug("Menu bar created")

    def _create_tabs(self):
        """Create tabbed interface with Commands, Agents, and Files tabs."""
        # Create main tab container (notebook)
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, side=tk.TOP)

        # Create tabs (passing shared session_manager to Agents and Files)
        self.commands_tab = CommandsTab(self.notebook, self)
        self.agents_tab = AgentsTab(self.notebook, self, session_manager=self.session_manager)
        self.files_tab = FilesTab(self.notebook, self, session_manager=self.session_manager)

        # Add tabs to notebook
        self.notebook.add(self.commands_tab, text="Commands")
        self.notebook.add(self.agents_tab, text="Agents")
        self.notebook.add(self.files_tab, text="Files")

        # Set default tab
        self.notebook.select(0)  # Commands tab

        # Create property accessors for backward compatibility
        # MainWindow code references these widgets, so we proxy them from tabs
        # Commands tab widgets (editing only)
        self.command_list_panel = self.commands_tab.get_command_list_panel()
        self.flowchart_canvas = self.commands_tab.get_flowchart_canvas()
        self.block_config_panel = self.commands_tab.get_block_config_panel()
        self.block_palette = self.commands_tab.get_block_palette()

        # Agents tab widgets (execution and chat)
        self.chat_panel = self.agents_tab.get_chat_panel()
        self.history_panel = self.agents_tab.get_history_panel()
        self.execution_view = self.agents_tab.get_execution_view()
        self.run_btn = self.agents_tab.get_run_btn()
        self.halt_btn = self.agents_tab.get_halt_btn()

        logger.debug("Tabbed interface created (Commands, Agents, Files)")

    def _create_status_bar(self):
        """Create enhanced status bar at bottom of window."""
        self.status_bar = StatusBar(self.root)
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM)

        # Initialize status bar
        self.status_bar.set_status("Ready")
        self.status_bar.set_session("No active session", "idle")
        self.status_bar.set_working_dir(self.working_directory)
        self.status_bar.set_connection_status("Not connected")

        logger.debug("Enhanced status bar created")

    def _apply_styling(self):
        """Apply basic styling and theme."""
        # Configure ttk style
        style = ttk.Style()

        # Try to use a modern theme
        available_themes = style.theme_names()
        if 'clam' in available_themes:
            style.theme_use('clam')
        elif 'alt' in available_themes:
            style.theme_use('alt')

        # Configure colors for frames
        style.configure('TFrame', background='#f0f0f0')
        style.configure('TLabel', background='#f0f0f0')

        logger.debug(f"Applied theme: {style.theme_use()}")

    def _initialize_accessibility(self):
        """Initialize accessibility features (Phase 6.2)."""
        # Initialize focus manager
        self.focus_manager = FocusManager(self.root)

        # Initialize high contrast manager
        self.high_contrast_manager = HighContrastManager(self.root)

        logger.info("Accessibility features initialized")

    def toggle_high_contrast(self):
        """Toggle high contrast mode (Ctrl+H keyboard shortcut)."""
        enabled = AccessibilityConfig.toggle_high_contrast()

        if enabled:
            self.high_contrast_manager.apply_high_contrast()
            self.set_status("High contrast mode enabled")
            logger.info("High contrast mode enabled")
        else:
            self.high_contrast_manager.remove_high_contrast()
            self.set_status("High contrast mode disabled")
            logger.info("High contrast mode disabled")

    # Menu callbacks

    def on_new_command(self):
        """Handle File > New Command."""
        logger.info("New Command requested")
        # Placeholder - will be implemented in later subphase
        self.set_status("New Command - To be implemented")

    def on_open_command(self):
        """Handle File > Open Command."""
        logger.info("Open Command requested")
        self.set_status("Open Command - To be implemented")

    def on_save_command(self):
        """Handle File > Save Command."""
        logger.info("Save Command requested")

        if not self.current_command:
            self.set_status("No command to save")
            self.ui_controller.show_info("No Command", "No command is currently loaded.")
            return

        try:
            self.ui_controller.set_busy(True)
            self.command_controller.save_command(self.current_command)
            self.set_status(f"Saved: {self.current_command.name}")
            self.ui_controller.show_info("Success", f"Command '{self.current_command.name}' saved successfully.")
        except Exception as e:
            logger.error(f"Error saving command: {e}")
            self.ui_controller.show_error("Error", f"Failed to save command: {e}")
        finally:
            self.ui_controller.set_busy(False)

    def on_import(self):
        """Handle File > Import."""
        logger.info("Import requested")
        self.set_status("Import - To be implemented")

    def on_export(self):
        """Handle File > Export."""
        logger.info("Export requested")
        self.set_status("Export - To be implemented")

    def on_undo(self):
        """Handle Edit > Undo - delegates to focused text widget."""
        logger.info("Undo requested")
        focused = self.root.focus_get()

        if isinstance(focused, tk.Text):
            try:
                # Tkinter Text widgets support undo/redo natively if configured
                focused.edit_undo()
                self.set_status("Undo")
                return
            except tk.TclError as e:
                logger.debug(f"Undo not available for Text widget: {e}")

        self.set_status("Undo - No compatible widget focused")

    def on_redo(self):
        """Handle Edit > Redo - delegates to focused text widget."""
        logger.info("Redo requested")
        focused = self.root.focus_get()

        if isinstance(focused, tk.Text):
            try:
                # Tkinter Text widgets support undo/redo natively if configured
                focused.edit_redo()
                self.set_status("Redo")
                return
            except tk.TclError as e:
                logger.debug(f"Redo not available for Text widget: {e}")

        self.set_status("Redo - No compatible widget focused")

    def on_cut(self):
        """Handle Edit > Cut - delegates to focused text widget."""
        logger.info("Cut requested")
        focused = self.root.focus_get()

        if isinstance(focused, tk.Text):
            try:
                focused.event_generate("<<Cut>>")
                self.set_status("Cut")
                return
            except tk.TclError as e:
                logger.error(f"Cut failed for Text widget: {e}")
        elif isinstance(focused, (tk.Entry, ttk.Entry)):
            try:
                focused.event_generate("<<Cut>>")
                self.set_status("Cut")
                return
            except tk.TclError as e:
                logger.error(f"Cut failed for Entry widget: {e}")

        self.set_status("Cut - No compatible widget focused")

    def on_copy(self):
        """Handle Edit > Copy - delegates to focused text widget."""
        logger.info("Copy requested")
        focused = self.root.focus_get()

        if isinstance(focused, tk.Text):
            try:
                focused.event_generate("<<Copy>>")
                self.set_status("Copy")
                return
            except tk.TclError as e:
                logger.error(f"Copy failed for Text widget: {e}")
        elif isinstance(focused, (tk.Entry, ttk.Entry)):
            try:
                focused.event_generate("<<Copy>>")
                self.set_status("Copy")
                return
            except tk.TclError as e:
                logger.error(f"Copy failed for Entry widget: {e}")

        self.set_status("Copy - No compatible widget focused")

    def on_paste(self):
        """Handle Edit > Paste - delegates to focused text widget."""
        logger.info("Paste requested")
        focused = self.root.focus_get()

        if isinstance(focused, tk.Text):
            try:
                focused.event_generate("<<Paste>>")
                self.set_status("Paste")
                return
            except tk.TclError as e:
                logger.error(f"Paste failed for Text widget: {e}")
        elif isinstance(focused, (tk.Entry, ttk.Entry)):
            try:
                focused.event_generate("<<Paste>>")
                self.set_status("Paste")
                return
            except tk.TclError as e:
                logger.error(f"Paste failed for Entry widget: {e}")

        self.set_status("Paste - No compatible widget focused")

    def on_select_all(self):
        """Handle Edit > Select All - delegates to focused text widget."""
        logger.info("Select All requested")
        focused = self.root.focus_get()

        if isinstance(focused, tk.Text):
            try:
                # Select all text in Text widget
                focused.tag_add(tk.SEL, "1.0", tk.END)
                focused.mark_set(tk.INSERT, "1.0")
                focused.see(tk.INSERT)
                self.set_status("Select All")
                return
            except tk.TclError as e:
                logger.error(f"Select All failed for Text widget: {e}")
        elif isinstance(focused, (tk.Entry, ttk.Entry)):
            try:
                # Select all text in Entry widget
                focused.select_range(0, tk.END)
                focused.icursor(tk.END)
                self.set_status("Select All")
                return
            except tk.TclError as e:
                logger.error(f"Select All failed for Entry widget: {e}")

        self.set_status("Select All - No compatible widget focused")

    def on_set_working_directory(self):
        """Handle Settings > Set Working Directory."""
        from tkinter import filedialog

        # Show directory selection dialog
        new_directory = filedialog.askdirectory(
            title="Select Working Directory for Claude",
            initialdir=self.working_directory
        )

        if new_directory:
            self.working_directory = new_directory
            logger.info(f"Working directory changed to: {self.working_directory}")
            self.set_status(f"Working directory: {self.working_directory}")

            # Show confirmation message
            messagebox.showinfo(
                "Working Directory Set",
                f"Working directory set to:\n{self.working_directory}\n\n"
                "Click 'Refresh Claude Connection' or press Ctrl+R to apply changes."
            )

    def on_refresh_claude(self):
        """Handle Settings > Refresh Claude Connection."""
        logger.info(f"Refreshing Claude connection with cwd={self.working_directory}")

        # Show confirmation dialog
        response = messagebox.askyesno(
            "Refresh Claude Connection",
            f"This will restart Claude with working directory:\n{self.working_directory}\n\n"
            "Any ongoing operations will be interrupted. Continue?"
        )

        if not response:
            return

        # Schedule async refresh in event loop (tracked for cleanup)
        self._track_task(self._async_refresh_claude())

    async def _async_refresh_claude(self):
        """Asynchronously refresh the Claude connection with proper cleanup."""
        try:
            # Properly close existing session if active
            if hasattr(self.agent_service, '_session_active') and self.agent_service._session_active:
                try:
                    logger.info("Closing existing Claude session...")
                    await self.agent_service.end_session()
                    logger.info("Claude session closed successfully")
                except Exception as e:
                    logger.warning(f"Error closing Claude session: {e}")

            # Re-initialize Claude service with new working directory
            import os
            use_mock = os.getenv('USE_MOCK_CLAUDE', 'false').lower() == 'true'

            if use_mock:
                logger.info("Reinitializing MockClaudeService")
                self.agent_service = MockClaudeService()
            else:
                logger.info(f"Reinitializing ClaudeAgentService with cwd={self.working_directory}")
                self.agent_service = ClaudeAgentService(
                    cwd=self.working_directory,
                    system_prompt="You are a helpful assistant that helps users create automated workflows.",
                    permission_mode="bypassPermissions",
                    stderr_callback=self._on_claude_stderr,
                    model="claude-opus-4-5"
                )

            # Update execution controller with new service
            self.execution_controller.agent_service = self.agent_service

            # Session will initialize lazily via ensure_session() on next execution
            self.set_status(f"Claude connection refreshed (cwd: {self.working_directory})")
            messagebox.showinfo(
                "Connection Refreshed",
                f"Claude connection has been refreshed.\n\nWorking directory: {self.working_directory}"
            )
        except Exception as e:
            logger.error(f"Error during Claude refresh: {e}", exc_info=True)
            messagebox.showerror(
                "Refresh Failed",
                f"Failed to refresh Claude connection: {e}"
            )

    def switch_to_agents_tab(self):
        """Switch to Agents tab (Ctrl+R shortcut)."""
        self.notebook.select(1)  # Agents tab is at index 1
        logger.debug("Switched to Agents tab")

    def on_preferences(self):
        """Handle Edit > Preferences."""
        logger.info("Preferences requested")

        # Create preferences dialog
        dialog = tk.Toplevel(self.root)
        dialog.title("Preferences")
        dialog.geometry("400x250")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        # Center the dialog
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - (dialog.winfo_width() // 2)
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")

        # Audio Settings Section
        audio_frame = ttk.LabelFrame(dialog, text="Audio Settings", padding=10)
        audio_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Enable/Disable Audio
        enable_var = tk.BooleanVar(value=self.audio_service.is_enabled())
        enable_check = ttk.Checkbutton(
            audio_frame,
            text="Enable Sound Effects",
            variable=enable_var,
            command=lambda: self.audio_service.set_enabled(enable_var.get())
        )
        enable_check.pack(anchor=tk.W, pady=(0, 10))

        # Volume Control
        volume_frame = ttk.Frame(audio_frame)
        volume_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(volume_frame, text="Volume:").pack(side=tk.LEFT)

        volume_var = tk.IntVar(value=int(self.audio_service.get_volume() * 100))
        volume_label = ttk.Label(volume_frame, text=f"{volume_var.get()}%", width=5)
        volume_label.pack(side=tk.RIGHT, padx=(5, 0))

        def on_volume_change(val):
            volume = int(float(val))
            volume_var.set(volume)
            volume_label.config(text=f"{volume}%")
            self.audio_service.set_volume(volume / 100.0)

        volume_slider = ttk.Scale(
            volume_frame,
            from_=0,
            to=100,
            orient=tk.HORIZONTAL,
            command=on_volume_change,
            variable=volume_var
        )
        volume_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 5))

        # Mute Toggle
        mute_var = tk.BooleanVar(value=self.audio_service.is_muted())
        mute_check = ttk.Checkbutton(
            audio_frame,
            text="Mute All Sounds",
            variable=mute_var,
            command=lambda: (
                self.audio_service.mute() if mute_var.get()
                else self.audio_service.unmute()
            )
        )
        mute_check.pack(anchor=tk.W, pady=(0, 10))

        # Test Sound Button
        def test_sound():
            # Try to find a test sound file
            available_sounds = self.audio_service.get_available_sounds()
            if available_sounds:
                test_file = available_sounds[0]
                success = self.audio_service.play_sound(test_file)
                if success:
                    self.set_status(f"Playing test sound: {test_file}")
                else:
                    messagebox.showwarning("Test Sound", "Failed to play test sound.")
            else:
                messagebox.showinfo(
                    "No Sounds Available",
                    "No sound files found in the sounds directory.\n\n"
                    "Please add sound files to the 'sounds' directory.\n"
                    "See sounds/README.md for instructions."
                )

        test_btn = ttk.Button(audio_frame, text="Test Sound", command=test_sound)
        test_btn.pack(anchor=tk.W)

        # Close Button
        close_frame = ttk.Frame(dialog)
        close_frame.pack(fill=tk.X, padx=10, pady=10)

        close_btn = ttk.Button(
            close_frame,
            text="Close",
            command=dialog.destroy
        )
        close_btn.pack(side=tk.RIGHT)

        self.set_status("Preferences dialog opened")

    def on_documentation(self):
        """Handle Help > Documentation."""
        logger.info("Documentation requested")
        messagebox.showinfo("Documentation", "Documentation will be available online.")

    def on_shortcuts(self):
        """Handle Help > Keyboard Shortcuts."""
        shortcuts_text = """
Keyboard Shortcuts:

File:
  Ctrl+N - New Command
  Ctrl+O - Open Command
  Ctrl+S - Save Command
  Ctrl+Q - Exit

Edit (in text fields):
  Ctrl+A - Select All
  Ctrl+Z - Undo
  Ctrl+Y - Redo
  Ctrl+X - Cut
  Ctrl+C - Copy
  Ctrl+V - Paste
        """
        messagebox.showinfo("Keyboard Shortcuts", shortcuts_text)

    def on_about(self):
        """Handle Help > About."""
        about_text = """FlowCoder
Version 1.0

A GUI drag-and-drop meta-agent builder for Claude Code.

Created with Claude Agent SDK
        """
        messagebox.showinfo("About FlowCoder", about_text)

    def on_closing(self):
        """Handle window close event."""
        logger.info("Window closing")
        if self.ui_controller.ask_ok_cancel("Quit", "Do you want to quit?"):
            # Save sessions synchronously FIRST before any async cleanup
            # This ensures sessions persist even if async cleanup doesn't complete
            try:
                logger.info("Saving sessions before shutdown...")
                self.session_manager.save_sessions()
                logger.info("Sessions saved")
            except Exception as e:
                logger.error(f"Failed to save sessions on shutdown: {e}")

            # Clean up Claude session if active (tracked for cleanup)
            self._track_task(self._cleanup_and_close())

    async def _cleanup_and_close(self):
        """Clean up resources and close the application."""
        try:
            # Clean up all session processes (but preserve session data for next startup)
            logger.info("Cleaning up session processes...")
            await self.session_manager.cleanup_all_sessions_async()
            logger.info("Session processes cleaned up")

            # Clean up main window's own execution controller (if used independently)
            logger.info("Cleaning up main window bash processes...")
            await self.execution_controller.cleanup_processes()
            logger.info("Main window bash processes cleaned up")

            # Clean up main window's own Claude session (if used independently)
            logger.info("Cleaning up main window Claude session...")
            await self.agent_service.end_session()
            logger.info("Main window Claude session ended")

            # Shutdown audio service
            logger.info("Shutting down audio service...")
            self.audio_service.shutdown()
            logger.info("Audio service shutdown")

            # Clean up agents tab (unregister callbacks, cancel tasks)
            logger.info("Cleaning up agents tab...")
            await self.agents_tab.cleanup()
            logger.info("Agents tab cleanup complete")

            # Unbind tkinter keyboard shortcuts
            logger.info("Unbinding keyboard shortcuts...")
            self._unbind_keyboard_shortcuts()
            logger.info("Keyboard shortcuts unbound")

        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
        finally:
            self.root.destroy()

    def _unbind_keyboard_shortcuts(self):
        """Unbind all keyboard shortcuts to prevent memory leaks."""
        try:
            self.root.unbind("<Control-n>")
            self.root.unbind("<Control-o>")
            self.root.unbind("<Control-s>")
            self.root.unbind("<Control-q>")
            self.root.unbind("<Control-r>")
            self.root.unbind("<Control-a>")
            self.root.unbind("<Control-x>")
            self.root.unbind("<Control-c>")
            self.root.unbind("<Control-v>")
            self.root.unbind("<Control-z>")
            self.root.unbind("<Control-y>")
            self.root.unbind("<Control-h>")
        except Exception as e:
            logger.warning(f"Error unbinding shortcuts: {e}")

    # Command List Panel callbacks

    def _on_command_selected(self, command: Command):
        """
        Handle command selection from command list panel.

        Args:
            command: The selected command
        """
        self.current_command = command
        logger.info(f"Command selected: {command.name}")
        self.set_status(f"Selected: {command.name}")

        # Enable Run button if not already executing
        # Note: run_btn is None in Phase 3.2+ (moved to session tabs)
        if not self.is_executing and self.run_btn:
            self.run_btn.config(state=tk.NORMAL)

        # Load flowchart into canvas
        if command.flowchart:
            self.flowchart_canvas.load_flowchart(command.flowchart)
        else:
            self.flowchart_canvas.clear()

    def _on_command_created(self, command: Command):
        """
        Handle new command creation.

        Args:
            command: The newly created command
        """
        self.current_command = command
        logger.info(f"Command created: {command.name}")
        self.set_status(f"Created: {command.name}")

        # Load flowchart into canvas (will be empty for new command)
        if command.flowchart:
            self.flowchart_canvas.load_flowchart(command.flowchart)
        else:
            self.flowchart_canvas.clear()

    def _on_command_deleted(self, command_name: str):
        """
        Handle command deletion.

        Args:
            command_name: Name of the deleted command
        """
        if self.current_command and self.current_command.name == command_name:
            self.current_command = None
            self.flowchart_canvas.clear()
        logger.info(f"Command deleted: {command_name}")
        self.set_status(f"Deleted: {command_name}")

    def _save_current_command(self):
        """Save the current command to storage (autosave)."""
        if not self.current_command:
            logger.warning("No current command to save")
            return

        try:
            # Update flowchart in command model
            if self.flowchart_canvas.flowchart:
                self.current_command.flowchart = self.flowchart_canvas.flowchart

            # Save to storage
            self.storage_service.save_command(self.current_command, overwrite=True)
            logger.info(f"Auto-saved command: {self.current_command.name}")

            # Update status bar briefly
            self.set_status(f"Auto-saved: {self.current_command.name}")

        except Exception as e:
            logger.error(f"Failed to auto-save command: {e}", exc_info=True)
            messagebox.showerror(
                "Autosave Error",
                f"Failed to auto-save command:\n\n{str(e)}"
            )

    # Flowchart Canvas callbacks

    def _on_block_selected(self, block: Block):
        """
        Handle block selection on canvas.

        Args:
            block: The selected block
        """
        logger.info(f"Block selected: {block.type} ({block.id[:8]})")
        self.set_status(f"Selected block: {block.type}")

        # Load block into configuration panel
        self.block_config_panel.load_block(block)

    def _on_canvas_clicked(self):
        """Handle click on empty canvas area."""
        logger.debug("Canvas clicked (empty area)")
        self.set_status("Ready")

        # Clear configuration panel
        self.block_config_panel.clear()

    def _on_block_updated(self, block: Block):
        """
        Handle block update from configuration panel.

        Args:
            block: The updated block
        """
        logger.info(f"Block updated: {block.type} ({block.id[:8]})")
        self.set_status(f"Updated block: {block.name}")

        # Trigger canvas redraw to update block widget
        if block.id in self.flowchart_canvas.block_widgets:
            widget = self.flowchart_canvas.block_widgets[block.id]
            widget.update_display()

        # Save command if one is loaded
        if self.current_command:
            self._save_current_command()
            logger.info("Auto-saved command after block update")

    def _on_flowchart_changed(self):
        """
        Handle flowchart changes (blocks added/deleted/moved, connections changed).
        Triggers autosave.
        """
        if self.current_command:
            self._save_current_command()
            logger.debug("Auto-saved after flowchart change")

    # Chat Panel callbacks

    def _on_message_sent(self, message: str):
        """
        Handle regular message sent from chat panel (pass-through mode).

        Args:
            message: The message text
        """
        logger.info(f"Pass-through message: {message[:50]}...")
        self.set_status("Sending to Claude...")

        # Disable input while processing
        self.chat_panel.set_input_enabled(False)

        # Send message to Claude asynchronously (tracked for cleanup)
        self._track_task(self._send_passthrough_message_async(message))

    def _on_slash_command(self, command: str):
        """
        Handle slash command from chat panel (executes named flowchart).

        Args:
            command: The slash command (including /)
        """
        logger.info(f"Slash command: {command}")

        # Parse command name (remove /)
        command_name = command[1:].strip().split()[0] if len(command) > 1 else ""

        if not command_name:
            self.chat_panel.add_error_message("Invalid slash command")
            return

        # Try to load the command
        try:
            cmd = self.storage_service.load_command(command_name)
            logger.info(f"Loaded command for execution: {command_name}")

            # Set as current command
            self.current_command = cmd

            # Update canvas
            self.flowchart_canvas.load_flowchart(cmd.flowchart)
            self.flowchart_canvas.reset_all_block_states()

            # Add message to chat
            self.chat_panel.add_system_message(f"Executing command: /{command_name}")

            # Execute the flowchart
            if not self.is_executing:
                self._start_async_execution()
            else:
                self.chat_panel.add_error_message("Another command is already executing")

        except Exception as e:
            logger.error(f"Failed to execute slash command '{command_name}': {e}")
            self.chat_panel.add_error_message(
                f"Command '/{command_name}' not found or failed to load: {str(e)}"
            )

    def _parse_sdk_message(self, sdk_message):
        """
        Parse SDK message object and extract text content and metadata.

        Args:
            sdk_message: Message object from Claude Agent SDK

        Returns:
            tuple: (text_content, verbose_content, message_type)
        """

        message_str = str(sdk_message)
        message_type = "unknown"
        text_content = ""
        verbose_content = message_str

        # Try to parse the message
        try:
            # Determine message type
            if "AssistantMessage" in message_str:
                message_type = "assistant"
                # Extract text from TextBlock
                # Format: AssistantMessage(content=[TextBlock(text="...")], ...)
                # Try double quotes first
                start = message_str.find('TextBlock(text="')
                if start != -1:
                    start += len('TextBlock(text="')
                    end = message_str.find('")', start)
                    if end != -1:
                        text_content = message_str[start:end]
                        text_content = text_content.replace('\\n', '\n')
                else:
                    # Try single quotes (slash commands use single quotes)
                    start = message_str.find("TextBlock(text='")
                    if start != -1:
                        start += len("TextBlock(text='")
                        end = message_str.find("')", start)
                        if end != -1:
                            text_content = message_str[start:end]
                            text_content = text_content.replace('\\n', '\n')

            elif "SystemMessage" in message_str:
                message_type = "system"
                text_content = "[System initialization]"

            elif "ResultMessage" in message_str:
                message_type = "result"
                # Extract result field
                start = message_str.find("result=\"")
                if start != -1:
                    start += len("result=\"")
                    end = message_str.find('")', start)
                    if end == -1:
                        # Try finding just closing quote
                        end = message_str.rfind('"')
                    if end != -1:
                        text_content = message_str[start:end]
                        text_content = text_content.replace('\\n', '\n')

            # Create pretty verbose output
            try:
                # Try to make it more readable
                verbose_lines = []
                if "AssistantMessage" in message_str:
                    verbose_lines.append("📤 Assistant Message:")
                    if text_content:
                        verbose_lines.append(f"   Content: {text_content[:100]}...")
                elif "SystemMessage" in message_str:
                    verbose_lines.append("⚙️  System Message:")
                    if "session_id" in message_str:
                        # Extract session_id
                        sid_start = message_str.find("'session_id': '") + len("'session_id': '")
                        sid_end = message_str.find("'", sid_start)
                        if sid_end != -1:
                            session_id = message_str[sid_start:sid_end]
                            verbose_lines.append(f"   Session: {session_id}")
                elif "ResultMessage" in message_str:
                    verbose_lines.append("✅ Result Message:")
                    # Extract duration
                    if "duration_ms" in message_str:
                        dur_start = message_str.find("duration_ms=") + len("duration_ms=")
                        dur_end = message_str.find(",", dur_start)
                        if dur_end != -1:
                            duration = message_str[dur_start:dur_end]
                            verbose_lines.append(f"   Duration: {duration}ms")
                    # Extract cost
                    if "total_cost_usd" in message_str:
                        cost_start = message_str.find("total_cost_usd=") + len("total_cost_usd=")
                        cost_end = message_str.find(",", cost_start)
                        if cost_end != -1:
                            cost = message_str[cost_start:cost_end]
                            verbose_lines.append(f"   Cost: ${cost}")

                if verbose_lines:
                    verbose_content = "\n".join(verbose_lines)

            except:
                pass  # Fall back to raw string

        except Exception as e:
            logger.warning(f"Failed to parse SDK message: {e}")
            text_content = message_str

        return (text_content, verbose_content, message_type)

    async def _send_passthrough_message_async(self, message: str):
        """
        Send a pass-through message to Claude and stream the response in real-time.

        Args:
            message: User message to send to Claude
        """
        logger.info(f"[ASYNC] Starting pass-through message processing for: {message[:50]}...")

        try:
            # Ensure Claude session is active (will start if not already running)
            await self.agent_service.ensure_session()
            logger.info("[ASYNC] Claude session ready")

            # Start streaming response in BOTH Chat and Verbose tabs
            self.chat_panel.start_streaming_message("Claude: ", tag='claude')
            self.chat_panel.start_verbose_streaming_message("Claude: ", tag='claude')
            logger.info("[ASYNC] Streaming message display started")

            # Stream response chunks in real-time
            response_text = ""
            chunk_count = 0
            had_previous_text = False  # Track if previous chunk had text content
            async for chunk in self.agent_service.stream_prompt(message):
                chunk_count += 1

                # Parse SDK message to extract clean text and verbose info
                text_content, verbose_content, message_type = self._parse_sdk_message(chunk)

                # Only display assistant messages in both tabs (clean text only)
                if message_type == "assistant" and text_content:
                    # Add paragraph break between separate TextBlocks
                    if had_previous_text and response_text:
                        response_text += "\n\n"
                        self.chat_panel.add_streaming_text("\n\n", tag='claude')
                        self.chat_panel.add_verbose_streaming_text("\n\n", tag='claude')

                    response_text += text_content
                    had_previous_text = True

                    # Display clean text content in BOTH Chat and Verbose tabs
                    self.chat_panel.add_streaming_text(text_content, tag='claude')
                    self.chat_panel.add_verbose_streaming_text(text_content, tag='claude')

                    # Log first chunk to confirm streaming started
                    if chunk_count == 1:
                        logger.info(f"[ASYNC] First chunk received: {text_content[:50]}...")
                elif message_type == "result":
                    # Log result metadata
                    logger.info(f"[ASYNC] {verbose_content}")
                elif message_type == "system":
                    # Log system message
                    logger.debug("[ASYNC] System message received")

            logger.info(f"[ASYNC] Claude response complete: {len(response_text)} chars in {chunk_count} chunks")

            # End streaming message in BOTH tabs
            self.chat_panel.end_streaming_message()
            self.chat_panel.end_verbose_streaming_message()

        except Exception as e:
            logger.error(f"[ASYNC] Pass-through error: {e}", exc_info=True)
            self.chat_panel.end_streaming_message()
            self.chat_panel.end_verbose_streaming_message()
            self.chat_panel.add_error_message(f"Error communicating with Claude: {str(e)}")

        finally:
            # Session remains active for future messages
            # Re-enable input
            self.chat_panel.set_input_enabled(True)
            self.set_status("Ready")
            logger.info("[ASYNC] Pass-through processing complete")

    # Execution methods

    def run_execution(self):
        """Start executing the current flowchart."""
        if not self.current_command:
            messagebox.showwarning(
                "No Command",
                "Please load a command first."
            )
            return

        if self.is_executing:
            return

        # Start async execution
        self._start_async_execution()

    def halt_execution(self):
        """Halt the current execution gracefully (finish current block, then stop)."""
        if not self.is_executing:
            return

        # Request halt from execution controller
        self.execution_controller.halt()

        # Clean up any running bash processes (tracked for cleanup)
        self._track_task(self.execution_controller.cleanup_processes())

        # Update UI to show waiting state
        if self.halt_btn:
            self.halt_btn.config(state=tk.DISABLED)
        self.set_status("Halting - waiting for current block to finish...")
        self.status_bar.set_connection_status("Connecting...")  # Orange "Connecting..." indicator
        self.chat_panel.add_system_message("Halt requested - waiting for current block to finish...")

        logger.info("Halt requested")

    def refresh_claude_session(self):
        """
        Refresh the agent session (called by Refresh Block).

        This performs the same logic as on_refresh_claude (Refresh Button)
        but without showing confirmation/success dialogs.
        """
        if self.is_executing:
            return

        logger.info(f"Refreshing agent session with cwd={self.working_directory}")

        # Display message in both chat tabs
        self.chat_panel.add_system_message("Refreshing agent session...")
        self.chat_panel.add_verbose_message("Refreshing agent session...", tag='system')
        self.status_bar.set_connection_status("Connecting...")

        # Schedule async refresh in event loop (tracked for cleanup)
        self._track_task(self._async_refresh_session())

    async def _async_refresh_session(self):
        """Asynchronously refresh the session with proper cleanup."""
        try:
            # Properly close existing session if active
            if hasattr(self.agent_service, '_session_active') and self.agent_service._session_active:
                try:
                    logger.info("Closing existing agent session...")
                    await self.agent_service.end_session()
                    logger.info("Agent session closed successfully")
                except Exception as e:
                    logger.warning(f"Error closing agent session: {e}")

            # Re-initialize agent service with current working directory
            import os
            use_mock = os.getenv('USE_MOCK_CLAUDE', 'false').lower() == 'true'

            if use_mock:
                logger.info("Reinitializing MockClaudeService")
                self.agent_service = MockClaudeService()
            else:
                logger.info(f"Reinitializing ClaudeAgentService with cwd={self.working_directory}")
                self.agent_service = ClaudeAgentService(
                    cwd=self.working_directory,
                    system_prompt="You are a helpful assistant that helps users create automated workflows.",
                    permission_mode="bypassPermissions",
                    stderr_callback=self._on_claude_stderr,
                    model="claude-opus-4-5"
                )

            # Update execution controller with new service
            self.execution_controller.agent_service = self.agent_service

            # Session will initialize lazily via ensure_session() on next execution

            # Display success message (no dialog - unlike Refresh Button)
            self.chat_panel.add_system_message("Agent session refreshed successfully")
            self.chat_panel.add_verbose_message("Agent session refreshed successfully", tag='system')
            self.set_status(f"Agent connection refreshed (cwd: {self.working_directory})")
            logger.info("Agent session refresh complete")
        except Exception as e:
            logger.error(f"Error refreshing agent session: {e}", exc_info=True)
            self.chat_panel.add_system_message(f"Failed to refresh agent session: {e}")
            self.chat_panel.add_verbose_message(f"Failed to refresh agent session: {e}", tag='error')

    def _start_async_execution(self):
        """Start execution in async context."""
        self.is_executing = True
        if self.run_btn:
            self.run_btn.config(state=tk.DISABLED)
        if self.halt_btn:
            self.halt_btn.config(state=tk.NORMAL)
        self.commands_tab.refresh_claude_btn.config(state=tk.DISABLED)
        self.set_status("Executing...")
        self.status_bar.set_connection_status("Connecting...")  # Blue indicator for executing

        # Disable chat input during execution
        self.chat_panel.set_input_enabled(False)

        # Clear previous execution states
        self.flowchart_canvas.reset_all_block_states()

        # Display start message
        self.chat_panel.add_system_message(
            f"Starting execution: {self.current_command.name}"
        )

        # Start execution run in history panel
        self.history_panel.start_execution_run(self.current_command.name)

        # Switch to history tab to show execution progress
        self.right_notebook.select(1)  # Select "Execution History" tab

        # Schedule async execution (tracked for cleanup)
        self.execution_task = self._track_task(self._execute_async())

    async def _execute_async(self):
        """Execute the flowchart asynchronously."""
        try:
            # Ensure Claude service session is active (will start if not already running)
            await self.agent_service.ensure_session()

            # Execute the command
            context = await self.execution_controller.execute(self.current_command)

            # Execution finished successfully
            logger.info(f"Execution completed with status: {context.status}")

        except Exception as e:
            logger.error(f"Execution error: {e}", exc_info=True)
            self.chat_panel.add_error_message(f"Execution error: {str(e)}")
            self.flowchart_canvas.reset_all_block_states()

        finally:
            # Session remains active for future operations
            # Update UI
            self.is_executing = False
            if self.run_btn:
                self.run_btn.config(state=tk.NORMAL)
            if self.halt_btn:
                self.halt_btn.config(state=tk.DISABLED)
            self.commands_tab.refresh_claude_btn.config(state=tk.NORMAL)
            self.status_bar.set_connection_status("Connected")

            # Re-enable chat input
            self.chat_panel.set_input_enabled(True)

    def _on_claude_stderr(self, message: str):
        """
        Callback for Claude Code's verbose output (stderr).
        Shows tool calls, thinking, file operations, etc.

        Args:
            message: The stderr message from Claude Code

        Note: The Claude SDK may not call this callback consistently.
              Currently used for system messages and diagnostics.
        """
        # Send to verbose chat panel
        # Note: chat_panel may be None during initialization
        if self.chat_panel:
            self.chat_panel.add_verbose_message(message, tag='system')

    def _on_prompt_stream(self, prompt_text: str, chunk: str):
        """
        Callback when prompt execution streams data.

        Args:
            prompt_text: The prompt being executed
            chunk: Streaming chunk (empty string = start of prompt)
        """
        if chunk == "":
            # Start of prompt - show what we're asking Claude
            self.chat_panel.add_message(f"Prompt: {prompt_text}", tag='user')
            # Start streaming response
            self.chat_panel.start_streaming_message("Claude: ", tag='claude')
            self.chat_panel.start_verbose_streaming_message("Claude: ", tag='claude')
            # Reset paragraph tracking for new prompt
            self._had_previous_text_in_stream = False
        else:
            # Stream response chunks to both tabs
            # Parse SDK message to extract clean text
            text_content, _, message_type = self._parse_sdk_message(chunk)
            if message_type == "assistant" and text_content:
                # Add paragraph break between separate TextBlocks
                if self._had_previous_text_in_stream:
                    self.chat_panel.add_streaming_text("\n\n", tag='claude')
                    self.chat_panel.add_verbose_streaming_text("\n\n", tag='claude')

                self.chat_panel.add_streaming_text(text_content, tag='claude')
                self.chat_panel.add_verbose_streaming_text(text_content, tag='claude')
                self._had_previous_text_in_stream = True

    def _on_block_execution_start(self, block: Block, context: ExecutionContext):
        """
        Callback when block execution starts.

        Args:
            block: Block being executed
            context: Current execution context
        """
        logger.info(f"Block execution started: {block.name}")

        # Update block state on canvas
        self.flowchart_canvas.set_block_state(block.id, 'executing')

        # Display in chat
        self.chat_panel.add_message(f"[Executing] {block.name}")

        # Add to execution history
        self.history_panel.add_block_execution(block.name, 'executing')

        # Update status
        self.set_status(f"Executing: {block.name}")

        # Force UI update
        self.root.update_idletasks()

    def _on_block_execution_complete(self, block: Block, result: BlockResult, context: ExecutionContext):
        """
        Callback when block execution completes.

        Args:
            block: Block that completed
            result: Execution result
            context: Current execution context
        """
        logger.info(f"Block execution completed: {block.name}, success={result.success}")

        # End streaming message if this was a prompt block
        if block.type == BlockType.PROMPT:
            self.chat_panel.end_streaming_message()
            self.chat_panel.end_verbose_streaming_message()

        # Update block state on canvas
        if result.success:
            self.flowchart_canvas.set_block_state(block.id, 'completed')

            # For prompt blocks, show structured output if available
            if block.type == BlockType.PROMPT and result.output:
                import json
                output_str = json.dumps(result.output, indent=2) if isinstance(result.output, dict) else str(result.output)
                self.chat_panel.add_message(f"[Output] {output_str[:200]}...", tag='system')
            elif block.type != BlockType.PROMPT:
                # For non-prompt blocks, show completion
                self.chat_panel.add_message(f"[Complete] {block.name}", tag='system')

            # Add to execution history
            self.history_panel.add_block_execution(block.name, 'completed', output=result.output)

            # Play sound effect if configured
            self._play_block_sound(block)
        else:
            self.flowchart_canvas.set_block_state(block.id, 'error')
            # Display error in chat
            self.chat_panel.add_error_message(f"[Error] {block.name}: {result.error}")
            # Add to execution history
            self.history_panel.add_block_execution(block.name, 'error', error=result.error)

        # Force UI update
        self.root.update_idletasks()

    def _on_execution_complete(self, context: ExecutionContext):
        """
        Callback when entire execution completes.

        Args:
            context: Final execution context
        """
        logger.info(f"Execution completed: {context.status}")

        # Display completion message
        duration = (context.end_time - context.start_time).total_seconds() if context.end_time else 0

        # Customize message based on status
        if context.status.value == "halted":
            self.chat_panel.add_system_message(
                f"Execution halted gracefully (Duration: {duration:.2f}s)"
            )
            self.set_status("Execution halted")
        else:
            self.chat_panel.add_system_message(
                f"Execution completed: {context.status.value} (Duration: {duration:.2f}s)"
            )
            self.set_status(f"Execution {context.status.value}")

        # End execution run in history panel
        self.history_panel.end_execution_run(context.status.value, duration)

    def _play_block_sound(self, block: Block) -> None:
        """
        Play sound effect for a block if configured.

        Args:
            block: Block that completed execution
        """
        # Only PromptBlocks have sound effects
        if not hasattr(block, 'sound_effect'):
            return

        if block.sound_effect:
            success = self.audio_service.play_sound(block.sound_effect)
            if success:
                logger.debug(f"Played sound: {block.sound_effect}")

    # Utility methods

    def _track_task(self, coro) -> asyncio.Task:
        """
        Create and track an async task for proper cleanup.

        Args:
            coro: Coroutine to run as a task

        Returns:
            The created task
        """
        task = asyncio.ensure_future(coro)
        self._async_tasks.append(task)

        # Remove from list when done
        def on_done(t):
            if t in self._async_tasks:
                self._async_tasks.remove(t)

        task.add_done_callback(on_done)
        return task

    def _is_text_widget_focused(self) -> bool:
        """Check if a text entry widget currently has focus.

        Returns:
            True if a text widget (Entry, Text, etc.) has focus
        """
        focused = self.root.focus_get()
        if focused is None:
            return False

        # Check if the focused widget is a text entry widget
        return isinstance(focused, (tk.Text, tk.Entry, ttk.Entry))

    def _handle_new_command_key(self, event) -> Optional[str]:
        """Handle Ctrl+N key press - only if text widget doesn't have focus.

        Args:
            event: Keyboard event

        Returns:
            'break' if handled, None otherwise
        """
        if not self._is_text_widget_focused():
            self.on_new_command()
            return 'break'
        return None

    def _handle_open_command_key(self, event) -> Optional[str]:
        """Handle Ctrl+O key press - only if text widget doesn't have focus.

        Args:
            event: Keyboard event

        Returns:
            'break' if handled, None otherwise
        """
        if not self._is_text_widget_focused():
            self.on_open_command()
            return 'break'
        return None

    def _handle_save_command_key(self, event) -> Optional[str]:
        """Handle Ctrl+S key press - only if text widget doesn't have focus.

        Args:
            event: Keyboard event

        Returns:
            'break' if handled, None otherwise
        """
        if not self._is_text_widget_focused():
            self.on_save_command()
            return 'break'
        return None

    def _handle_quit_key(self, event) -> Optional[str]:
        """Handle Ctrl+Q key press - only if text widget doesn't have focus.

        Args:
            event: Keyboard event

        Returns:
            'break' if handled, None otherwise
        """
        if not self._is_text_widget_focused():
            self.on_closing()
            return 'break'
        return None

    def _handle_switch_agents_key(self, event) -> Optional[str]:
        """Handle Ctrl+R key press - only if text widget doesn't have focus.

        Args:
            event: Keyboard event

        Returns:
            'break' if handled, None otherwise
        """
        if not self._is_text_widget_focused():
            self.switch_to_agents_tab()
            return 'break'
        return None

    def _handle_high_contrast_key(self, event) -> Optional[str]:
        """Handle Ctrl+H key press - toggle high contrast.

        Args:
            event: Keyboard event

        Returns:
            'break' if handled, None otherwise
        """
        # High contrast toggle works regardless of focus
        self.toggle_high_contrast()
        return 'break'

    def _handle_select_all_key(self, event) -> Optional[str]:
        """Handle Ctrl+A key press - select all in text widget.

        Args:
            event: Keyboard event

        Returns:
            'break' if handled, None otherwise
        """
        if self._is_text_widget_focused():
            self.on_select_all()
            return 'break'
        return None

    def _handle_cut_key(self, event) -> Optional[str]:
        """Handle Ctrl+X key press - cut from text widget.

        For text widgets, we return None to let Tkinter's native class binding
        handle it. The class binding fires BEFORE this toplevel binding, so
        the cut already happened - we just need to not interfere.

        Args:
            event: Keyboard event

        Returns:
            None to let native handling work
        """
        # Text widgets have native Ctrl+X handling via <<Cut>> class binding
        # which fires before this toplevel binding. Just let it through.
        return None

    def _handle_copy_key(self, event) -> Optional[str]:
        """Handle Ctrl+C key press - copy from text widget.

        For text widgets, we return None to let Tkinter's native class binding
        handle it. The class binding fires BEFORE this toplevel binding, so
        the copy already happened - we just need to not interfere.

        Args:
            event: Keyboard event

        Returns:
            None to let native handling work
        """
        # Text widgets have native Ctrl+C handling via <<Copy>> class binding
        # which fires before this toplevel binding. Just let it through.
        return None

    def _handle_paste_key(self, event) -> Optional[str]:
        """Handle Ctrl+V key press - paste into text widget.

        For text widgets, we return None to let Tkinter's native class binding
        handle it. The class binding fires BEFORE this toplevel binding, so
        the paste already happened - we just need to not interfere.

        Previously this called on_paste() which generated another <<Paste>>
        event, causing double-paste. The fix is to do nothing here.

        Args:
            event: Keyboard event

        Returns:
            None to let native handling work
        """
        # Text widgets have native Ctrl+V handling via <<Paste>> class binding
        # which fires before this toplevel binding. Just let it through.
        return None

    def _handle_undo_key(self, event) -> Optional[str]:
        """Handle Ctrl+Z key press - undo in text widget.

        Args:
            event: Keyboard event

        Returns:
            'break' if handled, None otherwise
        """
        if self._is_text_widget_focused():
            self.on_undo()
            return 'break'
        return None

    def _handle_redo_key(self, event) -> Optional[str]:
        """Handle Ctrl+Y key press - redo in text widget.

        Args:
            event: Keyboard event

        Returns:
            'break' if handled, None otherwise
        """
        if self._is_text_widget_focused():
            self.on_redo()
            return 'break'
        return None

    def set_status(self, message: str):
        """
        Update status bar message.

        Args:
            message: Status message to display
        """
        self.status_bar.set_status(message)
        logger.debug(f"Status: {message}")

    def set_connection_status(self, connected: bool):
        """
        Update connection status in status bar.

        Args:
            connected: Whether Claude is connected
        """
        if connected:
            self.status_bar.set_connection_status("Connected")
        else:
            self.status_bar.set_connection_status("Not connected")

    def _schedule_async_tasks(self):
        """
        Schedule asyncio task processing to run periodically with Tkinter.
        This enables async/await code to work alongside Tkinter's event loop.
        """
        # Process all pending asyncio tasks
        self.loop.stop()
        self.loop.run_forever()

        # Reschedule for next iteration (every 10ms for responsiveness)
        self.root.after(10, self._schedule_async_tasks)

    def run(self):
        """Start the GUI event loop."""
        logger.info("Starting main event loop with asyncio integration")
        self.root.mainloop()

        # Clean up asyncio event loop
        logger.info("Cleaning up asyncio event loop")

        # Cancel all pending tasks
        pending = asyncio.all_tasks(self.loop)
        for task in pending:
            task.cancel()

        # Run loop one final time to process cancellations
        if pending:
            self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))

        # Close the loop
        self.loop.close()
        logger.info("Main event loop ended")
