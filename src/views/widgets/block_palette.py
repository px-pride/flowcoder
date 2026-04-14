"""
Block Palette Widget

Provides draggable block type buttons for creating new blocks on the canvas.
"""

import tkinter as tk
from tkinter import ttk
from typing import Optional, Callable
import logging


logger = logging.getLogger(__name__)


class BlockPalette(ttk.Frame):
    """
    Palette of draggable block types.

    Users can drag block types from this palette onto the canvas
    to create new blocks.
    """

    # Block type definitions
    BLOCK_TYPES = [
        {
            'type': 'StartBlock',
            'label': 'Start',
            'color': '#4CAF50',
            'description': 'Entry point for flowchart'
        },
        {
            'type': 'PromptBlock',
            'label': 'Prompt',
            'color': '#2196F3',
            'description': 'Send prompt to Claude'
        },
        {
            'type': 'CommandBlock',
            'label': 'Command',
            'color': '#9C27B0',
            'description': 'Invoke another command'
        },
        {
            'type': 'VariableBlock',
            'label': 'Variable',
            'color': '#FBC02D',
            'description': 'Set a variable to a value'
        },
        {
            'type': 'BashBlock',
            'label': 'Bash',
            'color': '#FF5722',
            'description': 'Execute bash command'
        },
        {
            'type': 'BranchBlock',
            'label': 'Branch',
            'color': '#FF9800',
            'description': 'Conditional branching'
        },
        {
            'type': 'RefreshBlock',
            'label': 'Refresh',
            'color': '#00BCD4',
            'description': 'Restart agent session'
        },
        {
            'type': 'EndBlock',
            'label': 'End',
            'color': '#F44336',
            'description': 'Exit point for flowchart'
        },
    ]

    def __init__(
        self,
        parent: tk.Widget,
        on_drag_start: Optional[Callable[[str], None]] = None
    ):
        """
        Initialize block palette.

        Args:
            parent: Parent widget
            on_drag_start: Callback when drag starts (block_type: str)
        """
        super().__init__(parent)

        self.on_drag_start = on_drag_start
        self.dragging_type: Optional[str] = None
        self.canvas = None  # Will be set by set_canvas()

        # Store reference to root window for global event binding
        self.root = self.winfo_toplevel()

        # Create widgets
        self._create_widgets()

        logger.debug("BlockPalette initialized")

    def _create_widgets(self):
        """Create palette widgets."""
        # Title
        title_label = ttk.Label(
            self,
            text="Block Palette",
            font=('TkDefaultFont', 10, 'bold')
        )
        title_label.pack(pady=(5, 5))

        # Separator
        ttk.Separator(self, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=5)

        # Block type buttons
        for block_info in self.BLOCK_TYPES:
            self._create_block_button(block_info)

        logger.debug("Block palette widgets created")

    def _create_block_button(self, block_info: dict):
        """
        Create a draggable button for a block type.

        Args:
            block_info: Block type information dictionary
        """
        # Frame for block button
        frame = ttk.Frame(self, relief=tk.RAISED, borderwidth=1)
        frame.pack(fill=tk.X, padx=10, pady=5)

        # Create canvas for visual representation
        canvas_height = 40
        canvas = tk.Canvas(
            frame,
            width=80,
            height=canvas_height,
            bg=block_info['color'],
            highlightthickness=0
        )
        canvas.pack(side=tk.LEFT, padx=5, pady=5)

        # Draw block type label on canvas
        canvas.create_text(
            40, canvas_height // 2,
            text=block_info['label'],
            fill='white',
            font=('TkDefaultFont', 9, 'bold')
        )

        # Label with description
        label = ttk.Label(
            frame,
            text=f"{block_info['label']}\n{block_info['description']}",
            font=('TkDefaultFont', 8),
            justify=tk.LEFT
        )
        label.pack(side=tk.LEFT, padx=5, pady=5, fill=tk.BOTH, expand=True)

        # Bind drag events to both canvas and frame
        block_type = block_info['type']

        for widget in [canvas, frame, label]:
            widget.bind('<Button-1>', lambda e, bt=block_type: self._on_block_press(e, bt))
            widget.bind('<B1-Motion>', lambda e, bt=block_type: self._on_block_drag(e, bt))
            widget.bind('<ButtonRelease-1>', lambda e, bt=block_type: self._on_block_release(e, bt))
            # Change cursor to indicate draggability
            widget.config(cursor='hand2')

    def _on_block_press(self, event, block_type: str):
        """
        Handle mouse press on block button.

        Args:
            event: Mouse event
            block_type: Type of block being pressed
        """
        self.dragging_type = block_type
        logger.info(f"PALETTE: Started dragging {block_type}, dragging_type={self.dragging_type}")

        # Bind global events to root window for cross-widget dragging
        # This allows us to track the mouse even when it leaves the palette
        self.root.bind('<B1-Motion>', self._on_global_motion, add='+')
        self.root.bind('<ButtonRelease-1>', self._on_global_release, add='+')

        # Callback
        if self.on_drag_start:
            self.on_drag_start(block_type)

    def _on_block_drag(self, event, block_type: str):
        """
        Handle mouse drag on block button.

        Args:
            event: Mouse event
            block_type: Type of block being dragged
        """
        # Visual feedback could be added here
        # For now, the actual drag handling is in FlowchartCanvas
        pass

    def _on_block_release(self, event, block_type: str):
        """
        Handle mouse release after dragging block.

        Args:
            event: Mouse event
            block_type: Type of block being released
        """
        # This handler only fires if release happens on the palette itself
        # For cross-widget drops, _on_global_release handles it
        logger.info(f"PALETTE: Release on palette for {block_type}, dragging_type still={self.dragging_type}")

    def _on_global_motion(self, event):
        """
        Handle global mouse motion during drag.

        Args:
            event: Mouse event
        """
        # Visual feedback could be added here (e.g., ghost block following cursor)
        pass

    def _on_global_release(self, event):
        """
        Handle global mouse release after dragging.

        Args:
            event: Mouse event
        """
        logger.info(f"PALETTE: Global release at root ({event.x_root}, {event.y_root}), dragging_type={self.dragging_type}")

        # Unbind global events
        self.root.unbind('<B1-Motion>')
        self.root.unbind('<ButtonRelease-1>')

        # If we have a canvas reference and are dragging a block type,
        # let the canvas handle the drop (only if a flowchart is loaded)
        if self.canvas and self.dragging_type and self.canvas.flowchart:
            # Convert root coordinates to canvas coordinates
            canvas_x = self.canvas.canvas.winfo_rootx()
            canvas_y = self.canvas.canvas.winfo_rooty()

            # Check if mouse is over the canvas
            if (event.x_root >= canvas_x and
                event.x_root < canvas_x + self.canvas.canvas.winfo_width() and
                event.y_root >= canvas_y and
                event.y_root < canvas_y + self.canvas.canvas.winfo_height()):

                # Calculate position relative to canvas
                rel_x = event.x_root - canvas_x
                rel_y = event.y_root - canvas_y

                # Convert to canvas coordinates (accounting for scroll)
                canvas_coord_x = self.canvas.canvas.canvasx(rel_x)
                canvas_coord_y = self.canvas.canvas.canvasy(rel_y)

                logger.info(f"PALETTE: Drop on canvas at ({canvas_coord_x:.1f}, {canvas_coord_y:.1f})")

                # Create the block on the canvas
                self.canvas._create_block_at_position(self.dragging_type, canvas_coord_x, canvas_coord_y)

        # Clear dragging state
        if self.dragging_type:
            logger.info(f"PALETTE: Clearing dragging_type (was {self.dragging_type})")
            self.dragging_type = None

    def set_canvas(self, canvas):
        """
        Set reference to the flowchart canvas for drag-and-drop.

        Args:
            canvas: FlowchartCanvas instance
        """
        self.canvas = canvas
        logger.debug("BlockPalette: Canvas reference set")

    def get_dragging_type(self) -> Optional[str]:
        """
        Get the block type currently being dragged.

        Returns:
            Block type string or None
        """
        return self.dragging_type

    def clear_dragging_type(self):
        """Clear the dragging type (called by canvas after handling drop)."""
        logger.info(f"PALETTE: Clearing dragging_type (was {self.dragging_type})")
        self.dragging_type = None
