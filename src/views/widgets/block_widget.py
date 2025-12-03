"""
Block Widget for FlowchartCanvas

Visual representation of flowchart blocks on the canvas.
"""

import tkinter as tk
from typing import Optional, Tuple, Literal
import logging

from src.models import Block, StartBlock, EndBlock, PromptBlock, BranchBlock, CommandBlock, RefreshBlock, VariableBlock, BashBlock


logger = logging.getLogger(__name__)


BlockState = Literal['normal', 'selected', 'executing', 'completed', 'error']


class BlockWidget:
    """
    Visual representation of a flowchart block on canvas.

    Handles rendering, state management, and visual appearance.
    """

    # Block dimensions
    WIDTH = 120
    HEIGHT = 60
    CORNER_RADIUS = 10

    # Colors for different block types (normal state)
    COLORS = {
        'StartBlock': '#4CAF50',      # Green
        'EndBlock': '#F44336',         # Red
        'PromptBlock': '#2196F3',      # Blue
        'CommandBlock': '#9C27B0',     # Purple
        'BranchBlock': '#FF9800',      # Orange
        'RefreshBlock': '#00BCD4',     # Teal
        'VariableBlock': '#FBC02D',    # Gold
        'BashBlock': '#FF5722',        # Deep Orange
    }

    # State colors (overlays)
    STATE_COLORS = {
        'normal': None,                # Use block type color
        'selected': '#FFD700',         # Gold border
        'executing': '#00FF00',        # Bright green
        'completed': '#90EE90',        # Light green
        'error': '#FF0000',            # Red
    }

    def __init__(
        self,
        canvas: tk.Canvas,
        block: Block,
        x: float,
        y: float
    ):
        """
        Initialize block widget.

        Args:
            canvas: Tkinter Canvas to draw on
            block: Block model this widget represents
            x: X position on canvas
            y: Y position on canvas
        """
        self.canvas = canvas
        self.block = block
        self.x = x
        self.y = y
        self.state: BlockState = 'normal'

        # Canvas item IDs
        self.rect_id: Optional[int] = None
        self.text_id: Optional[int] = None
        self.type_text_id: Optional[int] = None
        self.port_ids: dict = {}  # Maps port name to canvas ID

        self._create_visual()
        self._create_ports()

        logger.debug(f"Created BlockWidget for {block.type} at ({x}, {y})")

    def _create_visual(self):
        """Create visual representation on canvas."""
        # Get block color
        block_type = self.block.__class__.__name__
        fill_color = self.COLORS.get(block_type, '#808080')  # Gray default

        # Draw rounded rectangle
        x1, y1 = self.x - self.WIDTH // 2, self.y - self.HEIGHT // 2
        x2, y2 = self.x + self.WIDTH // 2, self.y + self.HEIGHT // 2

        self.rect_id = self._create_rounded_rectangle(
            x1, y1, x2, y2,
            radius=self.CORNER_RADIUS,
            fill=fill_color,
            outline='black',
            width=2,
            tags=('block', f'block_{self.block.id}')
        )

        # Draw block type label at top
        type_label = self._get_type_label()
        self.type_text_id = self.canvas.create_text(
            self.x, self.y - 15,
            text=type_label,
            font=('TkDefaultFont', 8, 'bold'),
            fill='white',
            tags=('block', f'block_{self.block.id}')
        )

        # Draw block name/content at center
        display_name = self._get_display_name()
        self.text_id = self.canvas.create_text(
            self.x, self.y + 5,
            text=display_name,
            font=('TkDefaultFont', 9),
            fill='white',
            width=self.WIDTH - 10,
            tags=('block', f'block_{self.block.id}')
        )

    def _create_rounded_rectangle(
        self,
        x1: float, y1: float,
        x2: float, y2: float,
        radius: float = 10,
        **kwargs
    ) -> int:
        """
        Create a rounded rectangle on canvas.

        Args:
            x1, y1: Top-left corner
            x2, y2: Bottom-right corner
            radius: Corner radius
            **kwargs: Additional canvas.create_polygon arguments

        Returns:
            Canvas item ID
        """
        points = [
            x1 + radius, y1,
            x1 + radius, y1,
            x2 - radius, y1,
            x2 - radius, y1,
            x2, y1,
            x2, y1 + radius,
            x2, y1 + radius,
            x2, y2 - radius,
            x2, y2 - radius,
            x2, y2,
            x2 - radius, y2,
            x2 - radius, y2,
            x1 + radius, y2,
            x1 + radius, y2,
            x1, y2,
            x1, y2 - radius,
            x1, y2 - radius,
            x1, y1 + radius,
            x1, y1 + radius,
            x1, y1,
        ]

        return self.canvas.create_polygon(points, smooth=True, **kwargs)

    def _get_type_label(self) -> str:
        """Get display label for block type."""
        if isinstance(self.block, StartBlock):
            return "START"
        elif isinstance(self.block, EndBlock):
            return "END"
        elif isinstance(self.block, PromptBlock):
            return "PROMPT"
        elif isinstance(self.block, CommandBlock):
            return "COMMAND"
        elif isinstance(self.block, BranchBlock):
            return "BRANCH"
        elif isinstance(self.block, RefreshBlock):
            return "REFRESH"
        elif isinstance(self.block, VariableBlock):
            return "VARIABLE"
        elif isinstance(self.block, BashBlock):
            return "BASH"
        else:
            return "BLOCK"

    def _get_display_name(self) -> str:
        """Get display name for block."""
        # StartBlock, EndBlock, RefreshBlock: empty display
        if isinstance(self.block, (StartBlock, EndBlock, RefreshBlock)):
            return ""

        # VariableBlock: show "{{varName}} = {{value}}"
        if isinstance(self.block, VariableBlock):
            var_name = self.block.variable_name or "var"
            var_value = self.block.variable_value or ""

            # Truncate value if too long
            if len(var_value) > 15:
                var_value = var_value[:15] + "..."

            return f"{{{{{var_name}}}}} = {var_value}"

        # BashBlock: show truncated command
        if isinstance(self.block, BashBlock):
            command = self.block.command or "No command"
            if len(command) > 20:
                return command[:20] + "..."
            return command

        # For PromptBlock, show truncated prompt
        if isinstance(self.block, PromptBlock):
            prompt = self.block.prompt or "Empty"
            if len(prompt) > 20:
                return prompt[:20] + "..."
            return prompt

        # For CommandBlock, show command name and arguments
        if isinstance(self.block, CommandBlock):
            cmd_name = self.block.command_name or "(none)"
            args = self.block.arguments or ""

            # Combine command name and args
            if args:
                display = f"{cmd_name} {args}"
            else:
                display = cmd_name

            # Truncate if too long
            if len(display) > 20:
                return display[:20] + "..."
            return display

        # For BranchBlock, show condition
        if isinstance(self.block, BranchBlock):
            condition = self.block.condition or "No condition"
            if len(condition) > 20:
                condition = condition[:20] + "..."
            return condition

        # For other blocks, use ID or default
        return self.block.id[:8] if self.block.id else "New Block"

    def _create_ports(self):
        """Create visual connector ports on all 4 edges."""
        PORT_RADIUS = 5
        PORT_COLOR = '#FFFFFF'
        PORT_OUTLINE = '#000000'

        # Port positions (middle of each edge)
        port_positions = {
            'top': (self.x, self.y - self.HEIGHT // 2),
            'bottom': (self.x, self.y + self.HEIGHT // 2),
            'left': (self.x - self.WIDTH // 2, self.y),
            'right': (self.x + self.WIDTH // 2, self.y)
        }

        for port_name, (px, py) in port_positions.items():
            port_id = self.canvas.create_oval(
                px - PORT_RADIUS, py - PORT_RADIUS,
                px + PORT_RADIUS, py + PORT_RADIUS,
                fill=PORT_COLOR,
                outline=PORT_OUTLINE,
                width=2,
                tags=('port', f'port_{self.block.id}_{port_name}', f'block_{self.block.id}')
            )
            self.port_ids[port_name] = port_id

    def get_port_position(self, port_name: str) -> Tuple[float, float]:
        """Get the canvas coordinates of a port.

        Args:
            port_name: 'top', 'bottom', 'left', or 'right'

        Returns:
            (x, y) coordinates
        """
        port_positions = {
            'top': (self.x, self.y - self.HEIGHT // 2),
            'bottom': (self.x, self.y + self.HEIGHT // 2),
            'left': (self.x - self.WIDTH // 2, self.y),
            'right': (self.x + self.WIDTH // 2, self.y)
        }
        return port_positions.get(port_name, (self.x, self.y))

    def get_port_at_position(self, x: float, y: float) -> Optional[str]:
        """Check if a position is near a port.

        Args:
            x, y: Canvas coordinates

        Returns:
            Port name if near a port, None otherwise
        """
        PORT_CLICK_RADIUS = 10  # Slightly larger than visual for easier clicking

        for port_name in ['top', 'bottom', 'left', 'right']:
            px, py = self.get_port_position(port_name)
            distance = ((x - px) ** 2 + (y - py) ** 2) ** 0.5
            if distance <= PORT_CLICK_RADIUS:
                return port_name

        return None

    def set_state(self, state: BlockState):
        """
        Set visual state of block.

        Args:
            state: New state (normal, selected, executing, completed, error)
        """
        if self.state == state:
            return

        self.state = state
        self._update_visual()

        logger.debug(f"Block {self.block.id} state -> {state}")

    def _update_visual(self):
        """Update visual appearance based on current state."""
        if self.rect_id is None:
            return

        # Get base color
        block_type = self.block.__class__.__name__
        fill_color = self.COLORS.get(block_type, '#808080')

        # Modify based on state
        if self.state == 'selected':
            # Gold border, thicker
            self.canvas.itemconfig(self.rect_id, outline='#FFD700', width=4)
        elif self.state == 'executing':
            # Bright green fill, pulsing effect
            self.canvas.itemconfig(self.rect_id, fill='#00FF00', outline='black', width=3)
        elif self.state == 'completed':
            # Light green tint
            self.canvas.itemconfig(self.rect_id, fill='#90EE90', outline='black', width=2)
        elif self.state == 'error':
            # Red fill
            self.canvas.itemconfig(self.rect_id, fill='#FF0000', outline='black', width=3)
        else:  # normal
            # Reset to default
            self.canvas.itemconfig(self.rect_id, fill=fill_color, outline='black', width=2)

    def move(self, dx: float, dy: float):
        """
        Move block by delta.

        Args:
            dx: Delta X
            dy: Delta Y
        """
        self.x += dx
        self.y += dy

        # Move all canvas items (block visual + ports)
        for item_id in [self.rect_id, self.text_id, self.type_text_id]:
            if item_id is not None:
                self.canvas.move(item_id, dx, dy)

        # Move ports
        for port_id in self.port_ids.values():
            self.canvas.move(port_id, dx, dy)

    def move_to(self, x: float, y: float):
        """
        Move block to absolute position.

        Args:
            x: New X position
            y: New Y position
        """
        dx = x - self.x
        dy = y - self.y
        self.move(dx, dy)

    def get_position(self) -> Tuple[float, float]:
        """Get current position."""
        return (self.x, self.y)

    def contains_point(self, x: float, y: float) -> bool:
        """
        Check if point is inside block bounds.

        Args:
            x: Point X coordinate
            y: Point Y coordinate

        Returns:
            True if point is inside block
        """
        half_width = self.WIDTH // 2
        half_height = self.HEIGHT // 2

        return (
            self.x - half_width <= x <= self.x + half_width and
            self.y - half_height <= y <= self.y + half_height
        )

    def delete(self):
        """Remove block from canvas."""
        for item_id in [self.rect_id, self.text_id, self.type_text_id]:
            if item_id is not None:
                self.canvas.delete(item_id)

        # Delete ports
        for port_id in self.port_ids.values():
            self.canvas.delete(port_id)

        self.rect_id = None
        self.text_id = None
        self.type_text_id = None
        self.port_ids.clear()

        logger.debug(f"Deleted BlockWidget for {self.block.id}")

    def get_bounds(self) -> Tuple[float, float, float, float]:
        """
        Get bounding box of block.

        Returns:
            Tuple of (x1, y1, x2, y2)
        """
        half_width = self.WIDTH // 2
        half_height = self.HEIGHT // 2

        return (
            self.x - half_width,
            self.y - half_height,
            self.x + half_width,
            self.y + half_height
        )

    def update_display(self):
        """
        Update the visual display of the block.

        Called when block properties have changed (e.g., name or prompt).
        Updates the text labels to reflect current block state.
        """
        if self.text_id is None:
            return

        # Update display name
        display_name = self._get_display_name()
        self.canvas.itemconfig(self.text_id, text=display_name)

        logger.debug(f"Updated display for block {self.block.id}")
