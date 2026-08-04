"""
Commands Tab - Command creation and editing interface.

This tab contains:
- Left panel: Command List + Block Palette
- Right panel: Flowchart Canvas + Block Config Panel

Phase 1.3 implementation - 2-pane layout for editing only.
Chat and execution moved to Agents tab.
"""

import tkinter as tk
from tkinter import ttk
import logging

from src.views.command_list_panel import CommandListPanel
from src.views.flowchart_canvas import FlowchartCanvas
from src.views.block_config_panel import BlockConfigPanel
from src.views.widgets.block_palette import BlockPalette


logger = logging.getLogger(__name__)


class CommandsTab(ttk.Frame):
    """
    Commands tab for creating and editing command flowcharts.

    Contains the complete v1.0 UI migrated into a tab.
    """

    def __init__(self, parent, main_window):
        """
        Initialize the Commands tab.

        Args:
            parent: Parent widget (notebook)
            main_window: Reference to MainWindow instance
        """
        super().__init__(parent)
        self.main_window = main_window

        # Create the UI - migrate all existing MainWindow panels here
        self._create_ui()

        logger.debug("CommandsTab initialized")

    def _create_ui(self):
        """Create two-panel layout (Command editing only)."""
        # Main horizontal paned window
        self.paned_window = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        self.paned_window.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Left panel (Command List + Block Palette)
        self._create_left_panel()

        # Center panel (Flowchart Canvas + Block Config Panel)
        self._create_center_panel()

        logger.debug("CommandsTab two-panel layout created")

    def _create_left_panel(self):
        """Create left panel with Command List and Block Palette."""
        self.left_panel = ttk.Frame(self.paned_window, relief=tk.SUNKEN, borderwidth=1)
        self.paned_window.add(self.left_panel, weight=1)

        # Create CommandListPanel (top half)
        self.command_list_panel = CommandListPanel(
            self.left_panel,
            self.main_window.command_controller,
            on_command_selected=self.main_window._on_command_selected,
            on_command_created=self.main_window._on_command_created,
            on_command_deleted=self.main_window._on_command_deleted
        )
        self.command_list_panel.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # Separator
        ttk.Separator(self.left_panel, orient=tk.HORIZONTAL).pack(side=tk.TOP, fill=tk.X, pady=5)

        # Create BlockPalette
        self.block_palette = BlockPalette(self.left_panel)
        self.block_palette.pack(side=tk.TOP, fill=tk.BOTH, expand=False)

        logger.debug("Left panel created")

    def _create_center_panel(self):
        """Create center panel with Flowchart Canvas and Block Config Panel."""
        self.center_panel = ttk.Frame(self.paned_window, relief=tk.SUNKEN, borderwidth=1)
        self.paned_window.add(self.center_panel, weight=3)

        # Create vertical paned window for canvas and config panel
        self.center_paned = ttk.PanedWindow(self.center_panel, orient=tk.HORIZONTAL)
        self.center_paned.pack(fill=tk.BOTH, expand=True)

        # Flowchart Canvas (left side of center panel)
        canvas_frame = ttk.Frame(self.center_paned)
        self.center_paned.add(canvas_frame, weight=3)

        self.flowchart_canvas = FlowchartCanvas(
            canvas_frame,
            on_block_selected=self.main_window._on_block_selected,
            on_canvas_clicked=self.main_window._on_canvas_clicked,
            on_flowchart_changed=self.main_window._on_flowchart_changed,
            execution_highlighting=False  # Commands tab is for editing, not execution
        )
        self.flowchart_canvas.pack(fill=tk.BOTH, expand=True)

        # Block Config Panel (right side of center panel)
        self.config_panel_frame = ttk.Frame(self.center_paned, width=300)
        self.center_paned.add(self.config_panel_frame, weight=1)

        self.block_config_panel = BlockConfigPanel(
            self.config_panel_frame,
            on_block_updated=self.main_window._on_block_updated,
            command_controller=self.main_window.command_controller
        )
        self.block_config_panel.pack(fill=tk.BOTH, expand=True)

        # Wire up block palette to canvas (bidirectional)
        self.flowchart_canvas.set_block_palette(self.block_palette)
        self.block_palette.set_canvas(self.flowchart_canvas)

        logger.debug("Center panel created")

    # Expose key widgets for MainWindow to access
    def get_command_list_panel(self):
        """Get the command list panel."""
        return self.command_list_panel

    def get_flowchart_canvas(self):
        """Get the flowchart canvas."""
        return self.flowchart_canvas

    def get_block_config_panel(self):
        """Get the block config panel."""
        return self.block_config_panel

    def get_block_palette(self):
        """Get the block palette."""
        return self.block_palette
