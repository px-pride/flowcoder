"""File explorer widget for browsing session directories."""

import tkinter as tk
from tkinter import ttk
from typing import Optional, Callable
import logging

from ..services.file_system_service import FileSystemService, FileNode

logger = logging.getLogger(__name__)


class FileExplorerWidget(ttk.Frame):
    """Widget for browsing files in a tree view."""

    def __init__(
        self,
        parent,
        file_system_service: FileSystemService,
        on_file_select: Optional[Callable[[str], None]] = None
    ):
        """Initialize file explorer.

        Args:
            parent: Parent widget
            file_system_service: FileSystemService instance
            on_file_select: Callback when file is double-clicked (receives relative path)
        """
        super().__init__(parent)

        self.file_system_service = file_system_service
        self.on_file_select = on_file_select

        self._create_ui()
        self.refresh()

        logger.debug("FileExplorerWidget initialized")

    def _create_ui(self):
        """Create UI components."""
        # Toolbar
        toolbar = ttk.Frame(self)
        toolbar.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)

        ttk.Label(toolbar, text="Files", font=('TkDefaultFont', 10, 'bold')).pack(side=tk.LEFT)

        refresh_btn = ttk.Button(toolbar, text="🔄 Refresh", command=self.refresh, width=10)
        refresh_btn.pack(side=tk.RIGHT)

        # Tree view frame
        tree_frame = ttk.Frame(self)
        tree_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Scrollbars
        v_scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL)
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        h_scroll = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL)
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)

        # Tree widget
        self.tree = ttk.Treeview(
            tree_frame,
            yscrollcommand=v_scroll.set,
            xscrollcommand=h_scroll.set,
            selectmode='browse'
        )
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        v_scroll.config(command=self.tree.yview)
        h_scroll.config(command=self.tree.xview)

        # Configure tree columns
        self.tree['columns'] = ()
        self.tree.heading('#0', text='Name')

        # Bind events
        self.tree.bind('<<TreeviewSelect>>', self._on_tree_select)
        self.tree.bind('<Double-1>', self._on_tree_double_click)

        logger.debug("FileExplorerWidget UI created")

    def refresh(self):
        """Refresh file tree from file system."""
        logger.debug("Refreshing file tree")

        # Clear existing tree
        self.tree.delete(*self.tree.get_children())

        try:
            # Get file tree from service
            root_node = self.file_system_service.get_file_tree()

            # Populate tree (children of root, not root itself)
            for child in root_node.children:
                self._populate_tree_item('', child)

            logger.debug(f"File tree refreshed ({len(root_node.children)} items)")

        except Exception as e:
            logger.error(f"Error refreshing file tree: {e}")

    def _populate_tree_item(self, parent_id: str, node: FileNode):
        """Recursively populate tree items.

        Args:
            parent_id: Parent tree item ID (empty string for root)
            node: FileNode to add
        """
        # Get relative path for this node
        rel_path = self.file_system_service.get_relative_path(node.path)

        # Choose icon based on type
        if node.is_dir:
            icon = "📁"
            display_name = node.name
        else:
            icon = "📄"
            display_name = node.name

        # Insert tree item
        item_id = self.tree.insert(
            parent_id,
            tk.END,
            text=f"{icon} {display_name}",
            tags=('directory' if node.is_dir else 'file',),
            open=False  # Collapsed by default
        )

        # Store relative path as item value (for retrieval later)
        # We use iid (item id) to store the path mapping
        self._item_paths = getattr(self, '_item_paths', {})
        self._item_paths[item_id] = rel_path

        # Add children for directories
        if node.is_dir:
            for child in node.children:
                self._populate_tree_item(item_id, child)

    def _on_tree_select(self, event):
        """Handle tree selection (single click)."""
        selection = self.tree.selection()
        if not selection:
            return

        item_id = selection[0]
        tags = self.tree.item(item_id, 'tags')

        # Could show file info in status bar here
        # For now, just log selection
        if hasattr(self, '_item_paths') and item_id in self._item_paths:
            path = self._item_paths[item_id]
            logger.debug(f"Selected: {path}")

    def _on_tree_double_click(self, event):
        """Handle tree double-click to open file."""
        selection = self.tree.selection()
        if not selection:
            return

        item_id = selection[0]
        tags = self.tree.item(item_id, 'tags')

        # Only open files, not directories
        if 'file' in tags:
            # Get relative path from stored mapping
            if hasattr(self, '_item_paths') and item_id in self._item_paths:
                rel_path = self._item_paths[item_id]

                logger.info(f"Opening file: {rel_path}")

                if rel_path and self.on_file_select:
                    self.on_file_select(rel_path)

    def _get_item_path(self, item_id: str) -> str:
        """Get full relative path for tree item.

        Args:
            item_id: Tree item ID

        Returns:
            Relative path from working directory
        """
        # Use stored path mapping if available
        if hasattr(self, '_item_paths') and item_id in self._item_paths:
            return self._item_paths[item_id]

        # Fallback: Build path by traversing up the tree
        parts = []
        current = item_id

        while current:
            text = self.tree.item(current, 'text')
            # Remove icon from text (icon is first character + space)
            if ' ' in text:
                name = text.split(' ', 1)[1]
            else:
                name = text

            # Skip root (working directory itself)
            parent = self.tree.parent(current)
            if parent:  # Not root
                parts.insert(0, name)

            current = parent

        return '/'.join(parts) if parts else ''

    def expand_all(self):
        """Expand all tree items."""
        def expand_recursive(item_id):
            self.tree.item(item_id, open=True)
            for child in self.tree.get_children(item_id):
                expand_recursive(child)

        for item in self.tree.get_children():
            expand_recursive(item)

        logger.debug("Expanded all tree items")

    def collapse_all(self):
        """Collapse all tree items."""
        def collapse_recursive(item_id):
            self.tree.item(item_id, open=False)
            for child in self.tree.get_children(item_id):
                collapse_recursive(child)

        for item in self.tree.get_children():
            collapse_recursive(item)

        logger.debug("Collapsed all tree items")
