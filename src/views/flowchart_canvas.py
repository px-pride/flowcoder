"""
Flowchart Canvas for FlowCoder

Canvas widget for displaying and interacting with flowcharts.
Supports zoom, pan, block selection, and rendering.
"""

import tkinter as tk
from tkinter import ttk
from typing import Optional, Dict, List
import logging
import uuid

from src.models import (
    Flowchart,
    Block,
    StartBlock,
    EndBlock,
    PromptBlock,
    BranchBlock,
    VariableBlock,
    BashBlock,
    CommandBlock,
    Connection,
    RefreshBlock
)
from src.views.widgets.block_widget import BlockWidget
from src.views.widgets.connection_widget import ConnectionWidget


logger = logging.getLogger(__name__)


# Undo/Redo Action classes
class Action:
    """Base class for undoable actions."""
    def do(self):
        """Perform the action."""
        raise NotImplementedError

    def undo(self):
        """Undo the action."""
        raise NotImplementedError


class CreateBlockAction(Action):
    """Action for creating a block."""
    def __init__(self, canvas, block: Block, x: float, y: float):
        self.canvas = canvas
        self.block = block
        self.x = x
        self.y = y

    def do(self):
        self.canvas._add_block_to_canvas(self.block, self.x, self.y)

    def undo(self):
        self.canvas._remove_block_from_canvas(self.block.id)


class MoveBlockAction(Action):
    """Action for moving a block."""
    def __init__(self, canvas, block_id: str, old_x: float, old_y: float, new_x: float, new_y: float):
        self.canvas = canvas
        self.block_id = block_id
        self.old_x = old_x
        self.old_y = old_y
        self.new_x = new_x
        self.new_y = new_y

    def do(self):
        if self.block_id in self.canvas.block_widgets:
            self.canvas.block_widgets[self.block_id].move_to(self.new_x, self.new_y)
            # Also update the block model's position for autosave
            if self.canvas.flowchart and self.block_id in self.canvas.flowchart.blocks:
                block = self.canvas.flowchart.blocks[self.block_id]
                block.position.x = self.new_x
                block.position.y = self.new_y

    def undo(self):
        if self.block_id in self.canvas.block_widgets:
            self.canvas.block_widgets[self.block_id].move_to(self.old_x, self.old_y)
            # Also update the block model's position for autosave
            if self.canvas.flowchart and self.block_id in self.canvas.flowchart.blocks:
                block = self.canvas.flowchart.blocks[self.block_id]
                block.position.x = self.old_x
                block.position.y = self.old_y


class DeleteBlockAction(Action):
    """Action for deleting a block."""
    def __init__(self, canvas, block: Block, x: float, y: float):
        self.canvas = canvas
        self.block = block
        self.x = x
        self.y = y

    def do(self):
        self.canvas._remove_block_from_canvas(self.block.id)

    def undo(self):
        self.canvas._add_block_to_canvas(self.block, self.x, self.y)


class CreateConnectionAction(Action):
    """Action for creating a connection."""
    def __init__(self, canvas, connection: Connection):
        self.canvas = canvas
        self.connection = connection

    def do(self):
        self.canvas._add_connection_to_canvas(self.connection)

    def undo(self):
        self.canvas._remove_connection_from_canvas(self.connection.id)


class DeleteConnectionAction(Action):
    """Action for deleting a connection."""
    def __init__(self, canvas, connection: Connection):
        self.canvas = canvas
        self.connection = connection

    def do(self):
        self.canvas._remove_connection_from_canvas(self.connection.id)

    def undo(self):
        self.canvas._add_connection_to_canvas(self.connection)


class FlowchartCanvas(ttk.Frame):
    """
    Canvas for displaying and editing flowcharts.

    Features:
    - Render blocks with BlockWidget
    - Block selection with mouse clicks
    - Zoom in/out (mouse wheel or buttons)
    - Pan by dragging canvas (middle mouse or Ctrl+drag)
    - Visual state management
    """

    # Canvas settings
    DEFAULT_WIDTH = 800
    DEFAULT_HEIGHT = 600
    BACKGROUND_COLOR = '#f8f8f8'
    GRID_COLOR = '#e0e0e0'
    GRID_SIZE = 50

    # Zoom settings
    MIN_ZOOM = 0.25
    MAX_ZOOM = 4.0
    ZOOM_FACTOR = 1.1

    def __init__(
        self,
        parent: tk.Widget,
        on_block_selected: Optional[callable] = None,
        on_canvas_clicked: Optional[callable] = None,
        on_flowchart_changed: Optional[callable] = None,
        execution_highlighting: bool = True
    ):
        """
        Initialize flowchart canvas.

        Args:
            parent: Parent widget
            on_block_selected: Callback when block is selected (block: Block)
            on_canvas_clicked: Callback when empty canvas is clicked
            on_flowchart_changed: Callback when flowchart is modified (for autosave)
            execution_highlighting: If True, allow execution state highlighting (executing, completed, error).
                                   If False, only normal/selected states are allowed (for editing-only canvases).
        """
        super().__init__(parent)

        self.on_block_selected = on_block_selected
        self.on_canvas_clicked = on_canvas_clicked
        self.on_flowchart_changed = on_flowchart_changed
        self.execution_highlighting = execution_highlighting

        # Current flowchart and blocks
        self.flowchart: Optional[Flowchart] = None
        self.block_widgets: Dict[str, BlockWidget] = {}  # block_id -> BlockWidget
        self.connection_widgets: Dict[str, ConnectionWidget] = {}  # connection_id -> ConnectionWidget
        self.selected_block_id: Optional[str] = None
        self.selected_connection_id: Optional[str] = None

        # View state
        self.zoom_level = 1.0
        self.previous_zoom_level = 1.0  # Track previous zoom for delta calculation
        self.pan_offset_x = 0.0
        self.pan_offset_y = 0.0

        # Panning state
        self._pan_start_x = 0
        self._pan_start_y = 0
        self._is_panning = False

        # Dragging state for moving blocks
        self._dragging_block_id: Optional[str] = None
        self._drag_start_x = 0
        self._drag_start_y = 0
        self._drag_original_x = 0
        self._drag_original_y = 0

        # Connection creation state (port-based dragging)
        self._dragging_connection = False
        self._drag_source_block_id: Optional[str] = None
        self._drag_source_port: Optional[str] = None
        self._drag_is_true_path = True  # True unless Ctrl held
        self._connection_preview_line: Optional[int] = None

        # Undo/Redo stacks
        self.undo_stack: List[Action] = []
        self.redo_stack: List[Action] = []

        # Block palette reference (set by parent)
        self.block_palette = None

        # Snap to grid setting
        self.snap_to_grid_enabled = True

        # Create UI
        self._create_widgets()
        self._bind_events()

        logger.debug("FlowchartCanvas initialized")

    def _create_widgets(self):
        """Create canvas and toolbar widgets."""
        # Toolbar container frame at top
        toolbar_container = ttk.Frame(self)
        toolbar_container.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)

        # First row: Zoom, Reset, Undo, Redo
        toolbar_row1 = ttk.Frame(toolbar_container)
        toolbar_row1.pack(side=tk.TOP, fill=tk.X)

        # Zoom controls
        ttk.Label(toolbar_row1, text="Zoom:").pack(side=tk.LEFT, padx=5)

        self.zoom_out_btn = ttk.Button(
            toolbar_row1,
            text="-",
            width=3,
            command=self.zoom_out
        )
        self.zoom_out_btn.pack(side=tk.LEFT, padx=2)

        self.zoom_label = ttk.Label(toolbar_row1, text="100%", width=8)
        self.zoom_label.pack(side=tk.LEFT, padx=2)

        self.zoom_in_btn = ttk.Button(
            toolbar_row1,
            text="+",
            width=3,
            command=self.zoom_in
        )
        self.zoom_in_btn.pack(side=tk.LEFT, padx=2)

        self.zoom_reset_btn = ttk.Button(
            toolbar_row1,
            text="Reset",
            command=self.reset_view
        )
        self.zoom_reset_btn.pack(side=tk.LEFT, padx=10)

        # Undo/Redo disabled - functionality was broken and removed
        # Keeping stub attributes for compatibility
        self.undo_btn = None
        self.redo_btn = None

        # Canvas info label (right side of row 1)
        self.info_label = ttk.Label(toolbar_row1, text="No flowchart loaded")
        self.info_label.pack(side=tk.RIGHT, padx=5)

        # Second row: Info/Help text
        toolbar_row2 = ttk.Frame(toolbar_container)
        toolbar_row2.pack(side=tk.TOP, fill=tk.X, pady=(5, 0))

        # Help text for connections
        help_label = ttk.Label(
            toolbar_row2,
            text="Drag from port to port to connect  •  Ctrl+Drag for False path (blue)",
            foreground='gray',
            font=('Arial', 9)
        )
        help_label.pack(side=tk.LEFT, padx=5)

        # Canvas with scrollbars
        canvas_frame = ttk.Frame(self)
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        # Scrollbars
        v_scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        h_scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL)
        h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)

        # Canvas
        self.canvas = tk.Canvas(
            canvas_frame,
            bg=self.BACKGROUND_COLOR,
            scrollregion=(0, 0, 2000, 2000),
            xscrollcommand=h_scrollbar.set,
            yscrollcommand=v_scrollbar.set
        )
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        v_scrollbar.config(command=self.canvas.yview)
        h_scrollbar.config(command=self.canvas.xview)

        # Overlay frame (shown when no command is selected)
        self.overlay_frame = ttk.Frame(canvas_frame)
        self.overlay_label = ttk.Label(
            self.overlay_frame,
            text="Select a command to edit its flowchart",
            font=('TkDefaultFont', 14),
            foreground='gray'
        )
        self.overlay_label.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        # Show overlay by default (no command selected initially)
        self._show_overlay()

        # Draw grid
        self._draw_grid()

        logger.debug("Canvas widgets created")

    def _draw_grid(self):
        """Draw background grid on canvas."""
        # Get visible area
        width = self.canvas.winfo_width() or self.DEFAULT_WIDTH
        height = self.canvas.winfo_height() or self.DEFAULT_HEIGHT

        # Expand to scrollregion
        scroll = self.canvas.cget('scrollregion').split()
        if scroll and len(scroll) == 4:
            max_x = int(scroll[2])
            max_y = int(scroll[3])
        else:
            max_x = 2000
            max_y = 2000

        # Draw vertical lines
        for x in range(0, max_x, self.GRID_SIZE):
            self.canvas.create_line(
                x, 0, x, max_y,
                fill=self.GRID_COLOR,
                tags='grid'
            )

        # Draw horizontal lines
        for y in range(0, max_y, self.GRID_SIZE):
            self.canvas.create_line(
                0, y, max_x, y,
                fill=self.GRID_COLOR,
                tags='grid'
            )

        # Move grid to back
        self.canvas.tag_lower('grid')

    def _show_overlay(self):
        """Show the overlay indicating no command is selected."""
        self.overlay_frame.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.overlay_frame.lift()

    def _hide_overlay(self):
        """Hide the overlay when a command is selected."""
        self.overlay_frame.place_forget()

    def _bind_events(self):
        """Bind mouse and keyboard events."""
        # Mouse events for selection and dragging
        self.canvas.bind('<Button-1>', self._on_canvas_click)
        self.canvas.bind('<B1-Motion>', self._on_canvas_drag)
        self.canvas.bind('<ButtonRelease-1>', self._on_canvas_release)

        # Mouse events for panning (middle button only)
        self.canvas.bind('<Button-2>', self._on_pan_start)
        self.canvas.bind('<B2-Motion>', self._on_pan_move)
        self.canvas.bind('<ButtonRelease-2>', self._on_pan_end)

        # Mouse wheel for zoom
        self.canvas.bind('<MouseWheel>', self._on_mousewheel)  # Windows/Mac
        self.canvas.bind('<Button-4>', lambda e: self.zoom_in())  # Linux scroll up
        self.canvas.bind('<Button-5>', lambda e: self.zoom_out())  # Linux scroll down

        # Keyboard shortcuts - bind to canvas only, not globally
        # This allows text widgets to handle their own keyboard events
        self.canvas.bind('<Control-z>', self._on_undo_key)
        self.canvas.bind('<Control-y>', self._on_redo_key)

        # Only bind Delete key if this is an editable canvas
        # Read-only canvases (execution view) don't need Delete functionality
        if self.on_flowchart_changed is not None:
            self.canvas.bind('<Delete>', self._on_delete_key)
            logger.debug("Delete key bound (editable canvas)")
        else:
            logger.debug("Delete key NOT bound (read-only canvas)")

        logger.debug("Canvas events bound")

    def _is_canvas_focused(self) -> bool:
        """Check if the canvas or any of its child widgets has focus.

        Returns:
            True if canvas or its children have focus, False otherwise
        """
        focused = self.focus_get()
        if focused is None:
            return False

        # Check if focused widget is the canvas itself
        if focused == self.canvas:
            return True

        # Check if focused widget is a child of the canvas
        # This includes BlockWidget frames and their children
        parent = focused
        while parent:
            if parent == self.canvas:
                return True
            try:
                parent = parent.master
            except AttributeError:
                break

        return False

    def _on_undo_key(self, event) -> Optional[str]:
        """Handle Ctrl+Z key press. DISABLED - undo functionality removed.

        Args:
            event: Keyboard event

        Returns:
            None to let event propagate to text widgets
        """
        # Undo disabled - let event propagate for text widget handling
        return None

    def _on_redo_key(self, event) -> Optional[str]:
        """Handle Ctrl+Y key press. DISABLED - redo functionality removed.

        Args:
            event: Keyboard event

        Returns:
            None to let event propagate to text widgets
        """
        # Redo disabled - let event propagate for text widget handling
        return None

    def _on_delete_key(self, event) -> Optional[str]:
        """Handle Delete key press - only delete if canvas has focus.

        Args:
            event: Keyboard event

        Returns:
            'break' if handled, None otherwise
        """
        if self._is_canvas_focused():
            self.delete_selected()
            return 'break'  # Stop event propagation
        return None  # Allow event to propagate to text widgets

    def load_flowchart(self, flowchart: Flowchart):
        """
        Load and render a flowchart on the canvas.

        Args:
            flowchart: Flowchart to display
        """
        # Clear existing (but don't show overlay yet)
        self.clear()

        self.flowchart = flowchart

        # Hide overlay since a command is now selected
        self._hide_overlay()

        if not flowchart or not flowchart.blocks:
            self.info_label.config(text="Empty flowchart")
            logger.info("Loaded empty flowchart")
            return

        # Create BlockWidgets for each block
        for block in flowchart.blocks.values():
            # Use position from block data
            x = block.position.x
            y = block.position.y

            # Create widget
            widget = BlockWidget(self.canvas, block, x, y)
            self.block_widgets[block.id] = widget

        # Create ConnectionWidgets for each connection
        for connection in flowchart.connections:
            self._add_connection_to_canvas(connection)

        # Update info
        connection_count = len(flowchart.connections)
        if connection_count > 0:
            self.info_label.config(text=f"{len(flowchart.blocks)} blocks, {connection_count} connections")
        else:
            self.info_label.config(text=f"{len(flowchart.blocks)} blocks")

        logger.info(f"Loaded flowchart with {len(flowchart.blocks)} blocks and {connection_count} connections")

    def clear(self):
        """Clear the canvas."""
        # Delete all block widgets
        for widget in self.block_widgets.values():
            widget.delete()

        # Delete all connection widgets
        for widget in self.connection_widgets.values():
            widget.destroy()

        self.block_widgets.clear()
        self.connection_widgets.clear()
        self.flowchart = None
        self.selected_block_id = None
        self.selected_connection_id = None

        # Cancel connection dragging if active
        if self._dragging_connection:
            self._cancel_connection_drag()

        # Clear canvas (except grid)
        for item in self.canvas.find_all():
            if 'grid' not in self.canvas.gettags(item):
                self.canvas.delete(item)

        self.info_label.config(text="No flowchart loaded")

        # Show overlay since no command is selected
        self._show_overlay()

        logger.debug("Canvas cleared")

    def _on_canvas_click(self, event):
        """Handle canvas click for block selection and drag start."""
        # Get canvas coordinates
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)

        # Check if clicked on a port (for connection dragging)
        clicked_port_info = None  # (block_id, port_name)
        for block_id, widget in self.block_widgets.items():
            port_name = widget.get_port_at_position(canvas_x, canvas_y)
            if port_name:
                clicked_port_info = (block_id, port_name)
                break

        if clicked_port_info:
            # Start dragging a connection from this port
            block_id, port_name = clicked_port_info
            self._start_port_drag(block_id, port_name, event.state, canvas_x, canvas_y)
            return

        # Check if clicked on a block (but not a port)
        clicked_block_id = None
        for block_id, widget in self.block_widgets.items():
            if widget.contains_point(canvas_x, canvas_y):
                clicked_block_id = block_id
                break

        # Check if clicked on a connection
        clicked_connection_id = None
        if not clicked_block_id:
            for connection_id, widget in self.connection_widgets.items():
                if widget.contains_point(canvas_x, canvas_y):
                    clicked_connection_id = connection_id
                    break

        if clicked_block_id:
            # Select block
            self.select_block(clicked_block_id)

            # Prepare for potential drag
            self._dragging_block_id = clicked_block_id
            self._drag_start_x = canvas_x
            self._drag_start_y = canvas_y
            widget = self.block_widgets[clicked_block_id]
            self._drag_original_x, self._drag_original_y = widget.get_position()

            # Callback
            if self.on_block_selected and self.flowchart:
                block = self.flowchart.blocks.get(clicked_block_id)
                if block:
                    self.on_block_selected(block)

        elif clicked_connection_id:
            # Select connection
            self.select_connection(clicked_connection_id)

        else:
            # Clicked empty canvas - check if dropping from palette
            if self.block_palette and self.block_palette.get_dragging_type():
                block_type = self.block_palette.get_dragging_type()
                self._create_block_at_position(block_type, canvas_x, canvas_y)
            else:
                self.deselect_all()

                # Restore canvas focus so keyboard shortcuts work
                self.canvas.focus_set()

                if self.on_canvas_clicked:
                    self.on_canvas_clicked()

        logger.debug(f"Canvas click at ({canvas_x:.1f}, {canvas_y:.1f}), block: {clicked_block_id}, connection: {clicked_connection_id}")

    def _on_canvas_drag(self, event):
        """Handle mouse drag for moving blocks or drawing connection preview."""
        # Get canvas coordinates
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)

        # Handle connection preview dragging
        if self._dragging_connection:
            self._update_port_drag_preview(canvas_x, canvas_y)
            return

        # Handle block dragging
        if not self._dragging_block_id:
            return

        # Calculate delta
        dx = canvas_x - self._drag_start_x
        dy = canvas_y - self._drag_start_y

        # Move block
        if self._dragging_block_id in self.block_widgets:
            new_x = self._drag_original_x + dx
            new_y = self._drag_original_y + dy

            # Apply snap to grid
            if self.snap_to_grid_enabled:
                new_x = self._snap_to_grid(new_x)
                new_y = self._snap_to_grid(new_y)

            # Check for overlap
            if not self._would_overlap(self._dragging_block_id, new_x, new_y):
                self.block_widgets[self._dragging_block_id].move_to(new_x, new_y)

                # Update connections connected to this block
                self._update_block_connections(self._dragging_block_id)

    def _on_canvas_release(self, event):
        """Handle mouse release after dragging."""
        # Get canvas coordinates
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)

        # Handle connection drag completion
        if self._dragging_connection:
            self._complete_port_drag(canvas_x, canvas_y)
            return

        # Debug logging
        palette_type = self.block_palette.get_dragging_type() if self.block_palette else None
        logger.debug(f"Canvas release at ({canvas_x:.1f}, {canvas_y:.1f}), palette_type={palette_type}, dragging_block_id={self._dragging_block_id}")

        # Check if dropping a block from palette
        if self.block_palette and palette_type:
            # Create block at drop position
            self._create_block_at_position(palette_type, canvas_x, canvas_y)

            # Clear palette state
            self.block_palette.clear_dragging_type()

            logger.info(f"Dropped {palette_type} from palette at ({canvas_x:.1f}, {canvas_y:.1f})")

        elif self._dragging_block_id:
            # Moving an existing block
            widget = self.block_widgets[self._dragging_block_id]
            final_x, final_y = widget.get_position()

            # Create undo action if position changed
            if (final_x != self._drag_original_x or final_y != self._drag_original_y):
                action = MoveBlockAction(
                    self,
                    self._dragging_block_id,
                    self._drag_original_x,
                    self._drag_original_y,
                    final_x,
                    final_y
                )
                self._execute_action(action)

            # Reset drag state
            self._dragging_block_id = None

        logger.debug("Canvas release")

    def select_block(self, block_id: str):
        """
        Select a block by ID.

        Args:
            block_id: ID of block to select
        """
        # Deselect previous
        if self.selected_block_id and self.selected_block_id in self.block_widgets:
            self.block_widgets[self.selected_block_id].set_state('normal')

        # Select new
        self.selected_block_id = block_id
        if block_id in self.block_widgets:
            self.block_widgets[block_id].set_state('selected')
            logger.info(f"Selected block: {block_id}")

        # Restore canvas focus so keyboard shortcuts (Del, Ctrl+Z, Ctrl+Y) work
        self.canvas.focus_set()

    def deselect_all(self):
        """Deselect all blocks and connections."""
        if self.selected_block_id and self.selected_block_id in self.block_widgets:
            self.block_widgets[self.selected_block_id].set_state('normal')

        if self.selected_connection_id and self.selected_connection_id in self.connection_widgets:
            self.connection_widgets[self.selected_connection_id].set_selected(False)

        self.selected_block_id = None
        self.selected_connection_id = None
        logger.debug("Deselected all")

    def set_block_state(self, block_id: str, state: str):
        """
        Set visual state of a block.

        Args:
            block_id: Block ID
            state: State (normal, selected, executing, completed, error)
        """
        # If execution highlighting is disabled, ignore execution states
        if not self.execution_highlighting and state in ('executing', 'completed', 'error'):
            logger.debug(f"Ignoring execution state '{state}' for block {block_id} (execution_highlighting=False)")
            return

        if block_id in self.block_widgets:
            self.block_widgets[block_id].set_state(state)

    def reset_all_block_states(self):
        """Reset all blocks to normal state."""
        for block_id in self.block_widgets:
            self.set_block_state(block_id, 'normal')
        logger.debug("Reset all block states to normal")

    # Zoom and Pan

    def zoom_in(self):
        """Zoom in on canvas."""
        if self.zoom_level < self.MAX_ZOOM:
            self.zoom_level *= self.ZOOM_FACTOR
            self._apply_zoom()
            logger.debug(f"Zoomed in to {self.zoom_level:.2f}")

    def zoom_out(self):
        """Zoom out on canvas."""
        if self.zoom_level > self.MIN_ZOOM:
            self.zoom_level /= self.ZOOM_FACTOR
            self._apply_zoom()
            logger.debug(f"Zoomed out to {self.zoom_level:.2f}")

    def reset_view(self):
        """Reset zoom and pan to defaults."""
        # Don't update previous_zoom_level before calling _apply_zoom()
        # so that _apply_zoom() can calculate the correct scale factor
        self.zoom_level = 1.0
        self.pan_offset_x = 0.0
        self.pan_offset_y = 0.0
        self._apply_zoom()
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)
        logger.debug("View reset")

    def _apply_zoom(self):
        """Apply current zoom level to canvas."""
        # Update zoom label
        zoom_percent = int(self.zoom_level * 100)
        self.zoom_label.config(text=f"{zoom_percent}%")

        # Calculate the scale factor as delta between current and previous zoom
        if self.previous_zoom_level != 0:
            scale_factor = self.zoom_level / self.previous_zoom_level
        else:
            scale_factor = self.zoom_level

        # Apply scale transformation to all canvas items
        # Scale relative to the origin (0, 0)
        self.canvas.scale('all', 0, 0, scale_factor, scale_factor)

        # Update previous zoom level for next time
        self.previous_zoom_level = self.zoom_level

        logger.debug(f"Applied zoom: scale_factor={scale_factor:.3f}, new_zoom={self.zoom_level:.3f}")

    def _on_mousewheel(self, event):
        """Handle mouse wheel for zoom."""
        if event.delta > 0:
            self.zoom_in()
        else:
            self.zoom_out()

    def _on_pan_start(self, event):
        """Start panning."""
        self._is_panning = True
        self._pan_start_x = event.x
        self._pan_start_y = event.y
        self.canvas.config(cursor='fleur')  # Hand cursor
        logger.debug("Pan started")

    def _on_pan_move(self, event):
        """Handle panning movement."""
        if not self._is_panning:
            return

        # Calculate delta
        dx = event.x - self._pan_start_x
        dy = event.y - self._pan_start_y

        # Scroll canvas
        self.canvas.xview_scroll(-dx, 'units')
        self.canvas.yview_scroll(-dy, 'units')

        # Update start position
        self._pan_start_x = event.x
        self._pan_start_y = event.y

    def _on_pan_end(self, event):
        """End panning."""
        self._is_panning = False
        self.canvas.config(cursor='')
        logger.debug("Pan ended")

    # Block creation and management

    def _create_block_at_position(self, block_type: str, x: float, y: float):
        """
        Create a new block at specified position.

        Args:
            block_type: Type of block to create (StartBlock, EndBlock, etc.)
            x: X position
            y: Y position
        """
        from tkinter import messagebox

        # Apply snap to grid
        if self.snap_to_grid_enabled:
            x = self._snap_to_grid(x)
            y = self._snap_to_grid(y)

        # Create block instance
        block_id = str(uuid.uuid4())
        if block_type == 'StartBlock':
            block = StartBlock(id=block_id)
        elif block_type == 'EndBlock':
            block = EndBlock(id=block_id)
        elif block_type == 'PromptBlock':
            block = PromptBlock(id=block_id, prompt="New prompt")
        elif block_type == 'CommandBlock':
            block = CommandBlock(id=block_id, command_name="", arguments="")
        elif block_type == 'VariableBlock':
            block = VariableBlock(id=block_id, variable_name="", variable_value="")
        elif block_type == 'BashBlock':
            block = BashBlock(id=block_id, command="", capture_output=True, output_variable="", working_directory="")
        elif block_type == 'BranchBlock':
            block = BranchBlock(id=block_id)  # No condition parameter - uses branches list
        elif block_type == 'RefreshBlock':
            block = RefreshBlock(id=block_id)
        else:
            logger.error(f"Unknown block type: {block_type}")
            return

        # Check for overlap
        if self._would_overlap(block_id, x, y):
            logger.warning(f"Cannot create block at ({x}, {y}) - would overlap")
            messagebox.showwarning(
                "Cannot Add Block",
                "Cannot place block here - it would overlap with an existing block.\n\n"
                "Try placing it in a different location."
            )
            return

        # Add to flowchart model
        if not self.flowchart:
            # Create empty flowchart if none exists
            self.flowchart = Flowchart()

        try:
            self.flowchart.add_block(block)
        except ValueError as e:
            # Handle validation errors (e.g., duplicate start/end blocks)
            error_msg = str(e)
            logger.warning(f"Cannot create {block_type}: {error_msg}")
            messagebox.showwarning(
                "Cannot Add Block",
                error_msg
            )
            return

        # Create undo action
        action = CreateBlockAction(self, block, x, y)
        self._execute_action(action)

        logger.info(f"Created {block_type} at ({x}, {y})")

    def _add_block_to_canvas(self, block: Block, x: float, y: float):
        """
        Add block widget to canvas (called by undo/redo).

        Args:
            block: Block model
            x: X position
            y: Y position
        """
        # Ensure block exists in flowchart model (redo after deletion)
        if self.flowchart and block.id not in self.flowchart.blocks:
            try:
                self.flowchart.add_block(block)
            except ValueError:
                # Block may have been re-added already; force insert to keep model/canvas in sync
                self.flowchart.blocks[block.id] = block

        if block.id not in self.block_widgets:
            widget = BlockWidget(self.canvas, block, x, y)
            self.block_widgets[block.id] = widget

            # Update info
            if self.flowchart:
                self.info_label.config(text=f"{len(self.flowchart.blocks)} blocks")

    def _remove_block_from_canvas(self, block_id: str):
        """
        Remove block widget from canvas (called by undo/redo).

        Args:
            block_id: ID of block to remove
        """
        if block_id in self.block_widgets:
            self.block_widgets[block_id].delete()
            del self.block_widgets[block_id]

            # Remove from flowchart model
            if self.flowchart and block_id in self.flowchart.blocks:
                del self.flowchart.blocks[block_id]

                # Update info
                if self.flowchart.blocks:
                    self.info_label.config(text=f"{len(self.flowchart.blocks)} blocks")
                else:
                    self.info_label.config(text="Empty flowchart")

            # Deselect if this was selected
            if self.selected_block_id == block_id:
                self.selected_block_id = None

    def delete_selected(self):
        """Delete the currently selected block or connection."""
        if self.selected_block_id:
            self.delete_selected_block()
        elif self.selected_connection_id:
            self.delete_selected_connection()

    def delete_selected_block(self):
        """Delete the currently selected block."""
        if not self.selected_block_id:
            return

        # Get block and position
        if self.selected_block_id in self.block_widgets:
            widget = self.block_widgets[self.selected_block_id]
            x, y = widget.get_position()

            # Find block model
            if self.flowchart:
                block = self.flowchart.blocks.get(self.selected_block_id)
                if block:
                    # Also delete all connections to/from this block
                    self._delete_block_connections(self.selected_block_id)

                    action = DeleteBlockAction(self, block, x, y)
                    self._execute_action(action)

                    logger.info(f"Deleted block: {self.selected_block_id}")

    def delete_selected_connection(self):
        """Delete the currently selected connection."""
        if not self.selected_connection_id:
            return

        if self.flowchart:
            # Find connection in flowchart
            connection = None
            for conn in self.flowchart.connections:
                if conn.id == self.selected_connection_id:
                    connection = conn
                    break

            if connection:
                action = DeleteConnectionAction(self, connection)
                self._execute_action(action)

                logger.info(f"Deleted connection: {self.selected_connection_id}")

    # Undo/Redo system

    def _execute_action(self, action: Action):
        """
        Execute an action and add to undo stack.

        Args:
            action: Action to execute
        """
        action.do()
        self.undo_stack.append(action)
        self.redo_stack.clear()  # Clear redo stack when new action is performed
        self._update_undo_redo_buttons()

        # Trigger autosave callback
        if self.on_flowchart_changed:
            self.on_flowchart_changed()

    def undo(self):
        """Undo the last action. DISABLED - functionality was broken."""
        # Undo functionality disabled due to bugs
        logger.debug("Undo called but disabled")
        pass

    def redo(self):
        """Redo the last undone action. DISABLED - functionality was broken."""
        # Redo functionality disabled due to bugs
        logger.debug("Redo called but disabled")
        pass

    def _update_undo_redo_buttons(self):
        """Update undo/redo button states. DISABLED - buttons removed."""
        # Buttons no longer exist, nothing to update
        pass

    # Helper methods

    def _snap_to_grid(self, value: float) -> float:
        """
        Snap value to grid.

        Args:
            value: Value to snap

        Returns:
            Snapped value
        """
        return round(value / self.GRID_SIZE) * self.GRID_SIZE

    def _would_overlap(self, block_id: str, x: float, y: float) -> bool:
        """
        Check if block at position would overlap with another block.

        Args:
            block_id: ID of block being positioned (exclude from check)
            x: X position
            y: Y position

        Returns:
            True if would overlap, False otherwise
        """
        # Simple bounding box check
        half_width = BlockWidget.WIDTH // 2
        half_height = BlockWidget.HEIGHT // 2

        new_bounds = (
            x - half_width,
            y - half_height,
            x + half_width,
            y + half_height
        )

        for other_id, other_widget in self.block_widgets.items():
            if other_id == block_id:
                continue

            other_bounds = other_widget.get_bounds()

            # Check if rectangles overlap
            if not (new_bounds[2] < other_bounds[0] or  # new right < other left
                    new_bounds[0] > other_bounds[2] or  # new left > other right
                    new_bounds[3] < other_bounds[1] or  # new bottom < other top
                    new_bounds[1] > other_bounds[3]):   # new top > other bottom
                return True

        return False

    def set_block_palette(self, palette):
        """
        Set reference to block palette.

        Args:
            palette: BlockPalette instance
        """
        self.block_palette = palette

    def get_selected_block(self) -> Optional[Block]:
        """
        Get currently selected block.

        Returns:
            Selected Block or None
        """
        if self.selected_block_id and self.flowchart:
            return self.flowchart.blocks.get(self.selected_block_id)
        return None

    # Port-based connection management methods

    def _start_port_drag(self, block_id: str, port_name: str, event_state: int, start_x: float, start_y: float):
        """
        Start dragging a connection from a port.

        Args:
            block_id: Source block ID
            port_name: Source port name
            event_state: Event state (to check for Ctrl key)
            start_x: Starting X coordinate
            start_y: Starting Y coordinate
        """
        # Check if Ctrl key is held (for False path)
        # event.state & 0x4 checks for Ctrl key
        self._drag_is_true_path = not (event_state & 0x4)

        self._dragging_connection = True
        self._drag_source_block_id = block_id
        self._drag_source_port = port_name
        self._drag_connection_start_x = start_x
        self._drag_connection_start_y = start_y

        logger.debug(f"Started connection drag from {block_id}:{port_name}, is_true_path={self._drag_is_true_path}")

    def _update_port_drag_preview(self, x: float, y: float):
        """
        Update the connection preview line while dragging from a port.

        Args:
            x, y: Current mouse position
        """
        if not self._drag_source_block_id or not self._drag_source_port:
            return

        # Get source port position
        if self._drag_source_block_id in self.block_widgets:
            source_widget = self.block_widgets[self._drag_source_block_id]
            source_x, source_y = source_widget.get_port_position(self._drag_source_port)

            # Remove old preview
            if self._connection_preview_line:
                self.canvas.delete(self._connection_preview_line)

            # Choose color based on True/False path
            color = 'black' if self._drag_is_true_path else 'blue'

            # Draw new preview
            self._connection_preview_line = self.canvas.create_line(
                source_x, source_y, x, y,
                fill=color,
                width=2,
                dash=(5, 5),
                arrow=tk.LAST
            )

    def _complete_port_drag(self, x: float, y: float):
        """
        Complete connection drag by checking if released on a target port.

        Args:
            x, y: Release position
        """
        from tkinter import messagebox

        # Calculate drag distance
        drag_distance = ((x - self._drag_connection_start_x) ** 2 +
                        (y - self._drag_connection_start_y) ** 2) ** 0.5

        # Minimum drag distance threshold (5 pixels)
        # If user barely moved, treat as accidental click and cancel silently
        MIN_DRAG_DISTANCE = 5
        if drag_distance < MIN_DRAG_DISTANCE:
            self._cancel_connection_drag()
            return

        # Check if released on a port
        target_block_id = None
        target_port = None
        for block_id, widget in self.block_widgets.items():
            port_name = widget.get_port_at_position(x, y)
            if port_name:
                target_block_id = block_id
                target_port = port_name
                break

        # Clean up preview line
        if self._connection_preview_line:
            self.canvas.delete(self._connection_preview_line)
            self._connection_preview_line = None

        # If not released on a port, cancel
        if not target_block_id or not target_port:
            self._cancel_connection_drag()
            return

        # Validate connection
        if self._drag_source_block_id == target_block_id:
            messagebox.showwarning(
                "Invalid Connection",
                "Cannot connect a block to itself."
            )
            self._cancel_connection_drag()
            return

        # Check connection limits
        error_msg = self._check_connection_limits(
            self._drag_source_block_id,
            self._drag_source_port,
            self._drag_is_true_path
        )
        if error_msg:
            messagebox.showwarning("Connection Limit", error_msg)
            self._cancel_connection_drag()
            return

        # Check if identical connection already exists (same ports and path type)
        if self.flowchart:
            for conn in self.flowchart.connections:
                if (conn.source_block_id == self._drag_source_block_id and
                    conn.target_block_id == target_block_id and
                    conn.source_port == self._drag_source_port and
                    conn.target_port == target_port and
                    conn.is_true_path == self._drag_is_true_path):
                    messagebox.showwarning(
                        "Duplicate Connection",
                        "This exact connection already exists."
                    )
                    self._cancel_connection_drag()
                    return

        # Create connection with port information
        connection = Connection(
            id=str(uuid.uuid4()),
            source_block_id=self._drag_source_block_id,
            target_block_id=target_block_id,
            source_port=self._drag_source_port,
            target_port=target_port,
            is_true_path=self._drag_is_true_path
        )

        # Add to flowchart
        if not self.flowchart:
            self.flowchart = Flowchart()

        action = CreateConnectionAction(self, connection)
        self._execute_action(action)

        path_type = "True (black)" if self._drag_is_true_path else "False (blue)"
        logger.info(f"Created {path_type} connection: {self._drag_source_block_id}:{self._drag_source_port} -> {target_block_id}:{target_port}")

        # Reset drag state
        self._cancel_connection_drag()

    def _cancel_connection_drag(self):
        """Cancel connection dragging."""
        self._dragging_connection = False
        self._drag_source_block_id = None
        self._drag_source_port = None
        self._drag_is_true_path = True

        if self._connection_preview_line:
            self.canvas.delete(self._connection_preview_line)
            self._connection_preview_line = None

        logger.debug("Connection drag cancelled")

    def _check_connection_limits(self, source_block_id: str, source_port: str, is_true_path: bool) -> Optional[str]:
        """
        Check if creating a connection would violate connection limits.

        Args:
            source_block_id: Source block ID
            source_port: Source port name
            is_true_path: True for black arrow, False for blue arrow

        Returns:
            Error message if limit would be violated, None otherwise
        """
        if not self.flowchart:
            return None

        # Get source block
        source_block = self.flowchart.blocks.get(source_block_id)
        if not source_block:
            return None

        # Count existing outgoing connections from this source port
        existing_true_from_port = 0
        existing_false_from_port = 0

        for conn in self.flowchart.connections:
            if conn.source_block_id == source_block_id and conn.source_port == source_port:
                if conn.is_true_path:
                    existing_true_from_port += 1
                else:
                    existing_false_from_port += 1

        # For BranchBlock: allow max 1 True and max 1 False
        if isinstance(source_block, BranchBlock):
            if is_true_path and existing_true_from_port >= 1:
                return "Branch blocks can only have ONE True path (black arrow).\nDelete the existing True connection first."
            if not is_true_path and existing_false_from_port >= 1:
                return "Branch blocks can only have ONE False path (blue arrow).\nDelete the existing False connection first."

        # For other blocks: allow max 1 outgoing connection total from this port
        else:
            if existing_true_from_port + existing_false_from_port >= 1:
                return "Normal blocks can only have ONE outgoing connection per port.\nDelete the existing connection first."

        return None

    def select_connection(self, connection_id: str):
        """
        Select a connection by ID.

        Args:
            connection_id: ID of connection to select
        """
        # Deselect previous block
        if self.selected_block_id and self.selected_block_id in self.block_widgets:
            self.block_widgets[self.selected_block_id].set_state('normal')
            self.selected_block_id = None

        # Deselect previous connection
        if self.selected_connection_id and self.selected_connection_id in self.connection_widgets:
            self.connection_widgets[self.selected_connection_id].set_selected(False)

        # Select new connection
        self.selected_connection_id = connection_id
        if connection_id in self.connection_widgets:
            self.connection_widgets[connection_id].set_selected(True)
            logger.info(f"Selected connection: {connection_id}")

        # Restore canvas focus so keyboard shortcuts (Del, Ctrl+Z, Ctrl+Y) work
        self.canvas.focus_set()

    def _add_connection_to_canvas(self, connection: Connection):
        """
        Add connection widget to canvas (called by undo/redo).

        Args:
            connection: Connection model
        """
        if connection.id not in self.connection_widgets:
            # Get source and target block widgets
            if (connection.source_block_id in self.block_widgets and
                connection.target_block_id in self.block_widgets):

                source_widget = self.block_widgets[connection.source_block_id]
                target_widget = self.block_widgets[connection.target_block_id]

                # Get port positions instead of block centers
                source_x, source_y = source_widget.get_port_position(connection.source_port)
                target_x, target_y = target_widget.get_port_position(connection.target_port)

                # Create connection widget
                widget = ConnectionWidget(
                    self.canvas,
                    connection,
                    source_x, source_y,
                    target_x, target_y
                )
                self.connection_widgets[connection.id] = widget

                # Add to flowchart model
                if self.flowchart:
                    if connection not in self.flowchart.connections:
                        self.flowchart.connections.append(connection)

                    # Update info
                    connection_count = len(self.flowchart.connections)
                    if connection_count > 0:
                        self.info_label.config(text=f"{len(self.flowchart.blocks)} blocks, {connection_count} connections")

    def _remove_connection_from_canvas(self, connection_id: str):
        """
        Remove connection widget from canvas (called by undo/redo).

        Args:
            connection_id: ID of connection to remove
        """
        if connection_id in self.connection_widgets:
            self.connection_widgets[connection_id].destroy()
            del self.connection_widgets[connection_id]

            # Remove from flowchart model
            if self.flowchart:
                self.flowchart.connections = [
                    conn for conn in self.flowchart.connections
                    if conn.id != connection_id
                ]

                # Update info
                connection_count = len(self.flowchart.connections)
                if connection_count > 0:
                    self.info_label.config(text=f"{len(self.flowchart.blocks)} blocks, {connection_count} connections")
                else:
                    self.info_label.config(text=f"{len(self.flowchart.blocks)} blocks")

            # Deselect if this was selected
            if self.selected_connection_id == connection_id:
                self.selected_connection_id = None

    def _update_block_connections(self, block_id: str):
        """
        Update all connections connected to a block when it moves.

        Args:
            block_id: ID of block that moved
        """
        if block_id not in self.block_widgets:
            return

        block_widget = self.block_widgets[block_id]

        # Update all connections involving this block
        for connection_id, connection_widget in self.connection_widgets.items():
            connection = connection_widget.connection

            if connection.source_block_id == block_id:
                # Update source port position
                source_x, source_y = block_widget.get_port_position(connection.source_port)
                target_widget = self.block_widgets.get(connection.target_block_id)
                if target_widget:
                    target_x, target_y = target_widget.get_port_position(connection.target_port)
                    connection_widget.update_positions(source_x, source_y, target_x, target_y)

            elif connection.target_block_id == block_id:
                # Update target port position
                target_x, target_y = block_widget.get_port_position(connection.target_port)
                source_widget = self.block_widgets.get(connection.source_block_id)
                if source_widget:
                    source_x, source_y = source_widget.get_port_position(connection.source_port)
                    connection_widget.update_positions(source_x, source_y, target_x, target_y)

    def _delete_block_connections(self, block_id: str):
        """
        Delete all connections to/from a block.

        Args:
            block_id: ID of block
        """
        if not self.flowchart:
            return

        # Find all connections involving this block
        connections_to_delete = []
        for conn in self.flowchart.connections:
            if conn.source_block_id == block_id or conn.target_block_id == block_id:
                connections_to_delete.append(conn)

        # Delete them
        for conn in connections_to_delete:
            self._remove_connection_from_canvas(conn.id)

        logger.debug(f"Deleted {len(connections_to_delete)} connections for block {block_id}")
