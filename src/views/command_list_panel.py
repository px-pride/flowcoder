"""
Command List Panel for FlowCoder

Displays and manages the list of saved commands in the left panel.
"""

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import logging
from typing import Optional, Callable, List

from src.controllers import CommandController, InvalidCommandNameError
from src.models import Command
from src.services import StorageError, CommandAlreadyExistsError


logger = logging.getLogger(__name__)


class CommandListPanel(ttk.Frame):
    """
    Panel for displaying and managing commands.

    Features:
    - Search/filter entry at top
    - Listbox showing all commands
    - New and Delete buttons at bottom
    - Selection handling with callbacks
    """

    def __init__(
        self,
        parent,
        command_controller: CommandController,
        on_command_selected: Optional[Callable[[Command], None]] = None,
        on_command_created: Optional[Callable[[Command], None]] = None,
        on_command_deleted: Optional[Callable[[str], None]] = None
    ):
        """
        Initialize command list panel.

        Args:
            parent: Parent widget
            command_controller: Command controller for command operations
            on_command_selected: Callback when command is selected (receives Command)
            on_command_created: Callback when new command is created (receives Command)
            on_command_deleted: Callback when command is deleted (receives command name)
        """
        super().__init__(parent)

        self.command_controller = command_controller
        self.on_command_selected = on_command_selected
        self.on_command_created = on_command_created
        self.on_command_deleted = on_command_deleted

        self.command_metadata: List[dict] = []  # List of command metadata dicts
        self.filtered_metadata: List[dict] = []  # Filtered metadata
        self.selected_command: Optional[Command] = None  # Full loaded command

        self._create_widgets()
        self._load_commands()

        logger.info("CommandListPanel initialized")

    def _create_widgets(self):
        """Create all widgets for the panel."""
        # Title label
        title_label = ttk.Label(self, text="Commands", font=('TkDefaultFont', 12, 'bold'))
        title_label.pack(pady=(5, 10), padx=5, anchor=tk.W)

        # Search frame
        search_frame = ttk.Frame(self)
        search_frame.pack(fill=tk.X, padx=5, pady=(0, 5))

        search_label = ttk.Label(search_frame, text="Search:")
        search_label.pack(side=tk.LEFT, padx=(0, 5))

        self.search_var = tk.StringVar()
        self.search_var.trace_add('write', self._on_search_changed)
        self.search_entry = ttk.Entry(search_frame, textvariable=self.search_var)
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Listbox frame (with scrollbar)
        list_frame = ttk.Frame(self)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Scrollbar
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Listbox
        self.listbox = tk.Listbox(
            list_frame,
            yscrollcommand=scrollbar.set,
            selectmode=tk.SINGLE,
            font=('TkDefaultFont', 10)
        )
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.listbox.yview)

        # Bind selection event
        self.listbox.bind('<<ListboxSelect>>', self._on_selection_changed)

        # Button frame
        button_frame = ttk.Frame(self)
        button_frame.pack(fill=tk.X, padx=5, pady=5)

        # New button
        self.new_button = ttk.Button(
            button_frame,
            text="New Command",
            command=self._on_new_command
        )
        self.new_button.pack(side=tk.LEFT, padx=(0, 5), fill=tk.X, expand=True)

        # Duplicate button
        self.duplicate_button = ttk.Button(
            button_frame,
            text="Duplicate",
            command=self._on_duplicate_command,
            state=tk.DISABLED
        )
        self.duplicate_button.pack(side=tk.LEFT, padx=(0, 5), fill=tk.X, expand=True)

        # Rename button
        self.rename_button = ttk.Button(
            button_frame,
            text="Rename",
            command=self._on_rename_command,
            state=tk.DISABLED
        )
        self.rename_button.pack(side=tk.LEFT, padx=(0, 5), fill=tk.X, expand=True)

        # Delete button
        self.delete_button = ttk.Button(
            button_frame,
            text="Delete",
            command=self._on_delete_command,
            state=tk.DISABLED
        )
        self.delete_button.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Command count label
        self.count_label = ttk.Label(self, text="0 commands", font=('TkDefaultFont', 9))
        self.count_label.pack(pady=(5, 5), padx=5, anchor=tk.W)

        logger.debug("Command list panel widgets created")

    def _load_commands(self):
        """Load command metadata from command controller."""
        try:
            self.command_metadata = self.command_controller.list_commands()
            self.filtered_metadata = self.command_metadata.copy()
            self._update_listbox()
            logger.info(f"Loaded {len(self.command_metadata)} commands")
        except Exception as e:
            logger.error(f"Error loading commands: {e}")
            messagebox.showerror("Error", f"Failed to load commands: {e}")

    def _update_listbox(self):
        """Update listbox with filtered commands."""
        # Clear listbox
        self.listbox.delete(0, tk.END)

        # Add filtered commands
        for metadata in self.filtered_metadata:
            display_text = metadata['name']
            if metadata.get('description'):
                # Truncate long descriptions
                desc = metadata['description'][:50]
                if len(metadata['description']) > 50:
                    desc += "..."
                display_text += f" - {desc}"
            self.listbox.insert(tk.END, display_text)

        # Update count label
        total = len(self.command_metadata)
        filtered = len(self.filtered_metadata)
        if filtered == total:
            self.count_label.config(text=f"{total} command{'s' if total != 1 else ''}")
        else:
            self.count_label.config(text=f"{filtered} of {total} commands")

        logger.debug(f"Updated listbox with {filtered} commands")

    def _on_search_changed(self, *args):
        """Handle search text change."""
        search_text = self.search_var.get().lower()

        if not search_text:
            # Show all commands
            self.filtered_metadata = self.command_metadata.copy()
        else:
            # Filter commands by name or description
            self.filtered_metadata = [
                meta for meta in self.command_metadata
                if search_text in meta['name'].lower() or
                   (meta.get('description') and search_text in meta['description'].lower())
            ]

        self._update_listbox()
        logger.debug(f"Search: '{search_text}' -> {len(self.filtered_metadata)} results")

    def _on_selection_changed(self, event):
        """Handle listbox selection change."""
        selection = self.listbox.curselection()

        if selection:
            index = selection[0]
            metadata = self.filtered_metadata[index]

            # Load the full command from controller
            try:
                self.selected_command = self.command_controller.load_command(metadata['name'])
                self.delete_button.config(state=tk.NORMAL)
                self.duplicate_button.config(state=tk.NORMAL)
                self.rename_button.config(state=tk.NORMAL)

                logger.info(f"Selected command: {self.selected_command.name}")

                # Fire callback
                if self.on_command_selected:
                    self.on_command_selected(self.selected_command)
            except Exception as e:
                logger.error(f"Error loading command: {e}")
                messagebox.showerror("Error", f"Failed to load command: {e}")
                self.selected_command = None
                self.delete_button.config(state=tk.DISABLED)
                self.duplicate_button.config(state=tk.DISABLED)
                self.rename_button.config(state=tk.DISABLED)
        else:
            self.selected_command = None
            self.delete_button.config(state=tk.DISABLED)
            self.duplicate_button.config(state=tk.DISABLED)
            self.rename_button.config(state=tk.DISABLED)

    def _on_new_command(self):
        """Handle New Command button click."""
        logger.info("New command requested")

        # Show input dialog for command name
        dialog = tk.Toplevel(self)
        dialog.title("New Command")
        dialog.geometry("400x180")
        dialog.transient(self)
        dialog.grab_set()

        # Center the dialog
        dialog.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() // 2) - (dialog.winfo_width() // 2)
        y = self.winfo_rooty() + (self.winfo_height() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")

        # Name entry
        ttk.Label(dialog, text="Command Name:").pack(pady=(20, 5), padx=20, anchor=tk.W)
        name_var = tk.StringVar()
        name_entry = ttk.Entry(dialog, textvariable=name_var, width=40)
        name_entry.pack(padx=20, fill=tk.X)
        name_entry.focus()

        # Description entry
        ttk.Label(dialog, text="Description (optional):").pack(pady=(10, 5), padx=20, anchor=tk.W)
        desc_var = tk.StringVar()
        desc_entry = ttk.Entry(dialog, textvariable=desc_var, width=40)
        desc_entry.pack(padx=20, fill=tk.X)

        # Buttons
        button_frame = ttk.Frame(dialog)
        button_frame.pack(pady=15)

        def on_create():
            name = name_var.get().strip()

            # Validate command name using controller
            is_valid, error_msg = self.command_controller.validate_command_name(name)
            if not is_valid:
                messagebox.showwarning("Invalid Name", error_msg)
                return

            # Check if command already exists
            if self.command_controller.command_exists(name):
                messagebox.showwarning("Duplicate Name", f"Command '{name}' already exists.")
                return

            dialog.destroy()
            self._create_command(name, desc_var.get().strip())

        def on_cancel():
            dialog.destroy()

        # Bind Enter key to create
        dialog.bind('<Return>', lambda e: on_create())
        dialog.bind('<Escape>', lambda e: on_cancel())

        ttk.Button(button_frame, text="Create", command=on_create).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=on_cancel).pack(side=tk.LEFT, padx=5)

    def _create_command(self, name: str, description: str):
        """
        Create a new command using command controller.

        Args:
            name: Command name
            description: Command description
        """
        try:
            # Create command using controller (validates and saves)
            command = self.command_controller.create_command(name, description)

            logger.info(f"Created command: {name}")

            # Reload commands
            self._load_commands()

            # Select the new command
            for i, meta in enumerate(self.filtered_metadata):
                if meta['name'] == name:
                    self.listbox.selection_clear(0, tk.END)
                    self.listbox.selection_set(i)
                    self.listbox.see(i)
                    # Trigger selection event manually (this will load the full command)
                    self._on_selection_changed(None)
                    break

            # Fire creation callback
            if self.on_command_created:
                self.on_command_created(command)

        except (InvalidCommandNameError, CommandAlreadyExistsError) as e:
            logger.error(f"Error creating command: {e}")
            messagebox.showerror("Error", str(e))
        except Exception as e:
            logger.error(f"Error creating command: {e}")
            messagebox.showerror("Error", f"Failed to create command: {e}")

    def _on_duplicate_command(self):
        """Handle Duplicate button click."""
        if not self.selected_command:
            return

        try:
            original_name = self.selected_command.name

            # Duplicate the command
            duplicated_command = self.command_controller.duplicate_command(original_name)
            logger.info(f"Duplicated command: {original_name} -> {duplicated_command.name}")

            # Reload commands to show the new duplicate
            self._load_commands()

            # Select the newly duplicated command
            self.select_command(duplicated_command.name)

            # Fire callback to notify about new command
            if self.on_command_created:
                self.on_command_created(duplicated_command)

        except StorageError as e:
            logger.error(f"Error duplicating command: {e}")
            messagebox.showerror("Error", str(e))
        except Exception as e:
            logger.error(f"Error duplicating command: {e}")
            messagebox.showerror("Error", f"Failed to duplicate command: {e}")

    def _on_rename_command(self):
        """Handle Rename button click."""
        if not self.selected_command:
            return

        old_name = self.selected_command.name

        # Prompt for new name
        new_name = simpledialog.askstring(
            "Rename Command",
            f"Enter new name for '{old_name}':",
            initialvalue=old_name,
            parent=self
        )

        # User cancelled
        if not new_name:
            return

        # Strip whitespace
        new_name = new_name.strip()

        # Check if name actually changed
        if new_name == old_name:
            return

        # Validate new name
        is_valid, error_msg = self.command_controller.validate_command_name(new_name)
        if not is_valid:
            messagebox.showwarning("Invalid Name", error_msg)
            return

        # Check if command already exists
        if self.command_controller.command_exists(new_name):
            messagebox.showwarning("Duplicate Name", f"Command '{new_name}' already exists.")
            return

        try:
            # Rename the command (this will also propagate to CommandBlocks)
            renamed_command = self.command_controller.rename_command(old_name, new_name)
            logger.info(f"Renamed command: {old_name} -> {new_name}")

            # Reload commands to show the renamed command
            self._load_commands()

            # Select the renamed command
            self.select_command(new_name)

            # Show success message
            messagebox.showinfo(
                "Success",
                f"Command renamed from '{old_name}' to '{new_name}'.\n\n"
                "All CommandBlocks referencing this command have been updated."
            )

        except (InvalidCommandNameError, CommandAlreadyExistsError) as e:
            logger.error(f"Error renaming command: {e}")
            messagebox.showerror("Error", str(e))
        except StorageError as e:
            logger.error(f"Error renaming command: {e}")
            messagebox.showerror("Error", str(e))
        except Exception as e:
            logger.error(f"Error renaming command: {e}")
            messagebox.showerror("Error", f"Failed to rename command: {e}")

    def _on_delete_command(self):
        """Handle Delete button click."""
        if not self.selected_command:
            return

        # Confirm deletion
        result = messagebox.askyesno(
            "Confirm Delete",
            f"Are you sure you want to delete command '{self.selected_command.name}'?\n\n"
            "This action cannot be undone."
        )

        if not result:
            return

        try:
            command_name = self.selected_command.name
            self.command_controller.delete_command(command_name)
            logger.info(f"Deleted command: {command_name}")

            # Clear selection
            self.selected_command = None
            self.delete_button.config(state=tk.DISABLED)
            self.duplicate_button.config(state=tk.DISABLED)

            # Reload commands
            self._load_commands()

            # Fire callback
            if self.on_command_deleted:
                self.on_command_deleted(command_name)

        except StorageError as e:
            logger.error(f"Error deleting command: {e}")
            messagebox.showerror("Error", str(e))
        except Exception as e:
            logger.error(f"Error deleting command: {e}")
            messagebox.showerror("Error", f"Failed to delete command: {e}")

    def refresh(self):
        """Refresh the command list from storage."""
        self._load_commands()
        logger.debug("Command list refreshed")

    def get_selected_command(self) -> Optional[Command]:
        """Get the currently selected command."""
        return self.selected_command

    def select_command(self, name: str):
        """
        Select a command by name.

        Args:
            name: Name of command to select
        """
        for i, meta in enumerate(self.filtered_metadata):
            if meta['name'] == name:
                self.listbox.selection_clear(0, tk.END)
                self.listbox.selection_set(i)
                self.listbox.see(i)
                # Trigger selection event (this will load the full command)
                self._on_selection_changed(None)
                break
