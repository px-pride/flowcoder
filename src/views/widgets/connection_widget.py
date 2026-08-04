"""
ConnectionWidget for FlowCoder

Visual representation of connections (arrows) between blocks in the flowchart.
"""

import tkinter as tk
from typing import Optional, Tuple
import math
import logging

from src.models import Connection

logger = logging.getLogger(__name__)


class ConnectionWidget:
    """
    Visual representation of a connection between blocks.

    Renders as an arrow from source block to target block.
    Supports selection, labels, and different visual states.
    """

    # Visual settings
    LINE_WIDTH_NORMAL = 2
    LINE_WIDTH_SELECTED = 3
    LINE_WIDTH_HOVER = 3
    COLOR_TRUE_PATH = '#e0e0e0'  # Light gray for dark mode (True path)
    COLOR_FALSE_PATH = '#64B5F6'  # Light blue for dark mode (False path)
    COLOR_SELECTED = '#FFD700'  # Gold
    COLOR_HOVER = '#FFA726'  # Orange
    ARROW_SHAPE = (12, 15, 5)  # Arrow head dimensions (length, width, base_width) - increased for better visibility
    LABEL_FONT = ('Arial', 9)
    LABEL_BG = '#3c3c3c'  # Dark mode
    LABEL_BORDER = '#555555'  # Dark mode

    # Hit detection
    HIT_TOLERANCE = 8  # Pixels from line to detect click

    def __init__(
        self,
        canvas: tk.Canvas,
        connection: Connection,
        source_x: float,
        source_y: float,
        target_x: float,
        target_y: float
    ):
        """
        Initialize connection widget.

        Args:
            canvas: Tkinter canvas to draw on
            connection: Connection model
            source_x, source_y: Source block center position
            target_x, target_y: Target block center position
        """
        self.canvas = canvas
        self.connection = connection

        # Position
        self.source_x = source_x
        self.source_y = source_y
        self.target_x = target_x
        self.target_y = target_y

        # Visual state
        self.is_selected = False
        self.is_hover = False

        # Canvas item IDs
        self.line_id: Optional[int] = None
        self.label_bg_id: Optional[int] = None
        self.label_text_id: Optional[int] = None

        # Path waypoints (calculated during draw)
        self.waypoints: list = []

        # Draw the connection
        self.draw()

        logger.debug(f"ConnectionWidget created: {connection.id}")

    def draw(self):
        """Draw the connection arrow on the canvas."""
        # Choose color and width based on state
        if self.is_selected:
            color = self.COLOR_SELECTED
            width = self.LINE_WIDTH_SELECTED
        elif self.is_hover:
            color = self.COLOR_HOVER
            width = self.LINE_WIDTH_HOVER
        else:
            # Use color based on True/False path
            color = self.COLOR_TRUE_PATH if self.connection.is_true_path else self.COLOR_FALSE_PATH
            width = self.LINE_WIDTH_NORMAL

        # Calculate path with waypoints (source/target are already port positions)
        self.waypoints = self._calculate_waypoints(
            self.source_x, self.source_y,
            self.target_x, self.target_y
        )

        # Draw line with arrow using waypoints
        # Flatten the list of (x, y) tuples into a flat list of coordinates
        coords = []
        for x, y in self.waypoints:
            coords.extend([x, y])

        self.line_id = self.canvas.create_line(
            *coords,
            fill=color,
            width=width,
            arrow=tk.LAST,
            arrowshape=self.ARROW_SHAPE,
            smooth=False,
            tags=('connection', f'connection_{self.connection.id}')
        )

        # Draw label if exists
        if self.connection.label:
            # Use midpoint of the entire path for label
            mid_idx = len(self.waypoints) // 2
            label_x, label_y = self.waypoints[mid_idx]
            self._draw_label_at(label_x, label_y)

        # Lower connections below blocks
        self.canvas.tag_lower('connection')

    def _get_start_point(self) -> Tuple[float, float]:
        """
        Get the starting point of the arrow (edge of source block).

        Calculates the intersection point on the edge of the source block.
        """
        # For multi-segment paths, use the direction to the first waypoint
        # For simple paths, use direction to target
        return self._calculate_edge_point(
            self.source_x, self.source_y,
            self.target_x, self.target_y,
            is_source=True
        )

    def _get_end_point(self) -> Tuple[float, float]:
        """
        Get the ending point of the arrow (edge of target block).

        Calculates the intersection point on the edge of the target block.
        """
        # For multi-segment paths, use the direction from the last waypoint
        # For simple paths, use direction from source
        return self._calculate_edge_point(
            self.target_x, self.target_y,
            self.source_x, self.source_y,
            is_source=False
        )

    def _calculate_edge_point(self, center_x: float, center_y: float, other_x: float, other_y: float, is_source: bool) -> Tuple[float, float]:
        """
        Calculate the point where a line intersects the edge of a block.

        Args:
            center_x, center_y: Center of the block
            other_x, other_y: Point the line is coming from/going to
            is_source: Whether this is the source block (affects direction)

        Returns:
            (x, y) point on the block's edge
        """
        # Block dimensions (from BlockWidget)
        BLOCK_WIDTH = 120
        BLOCK_HEIGHT = 60
        half_width = BLOCK_WIDTH / 2
        half_height = BLOCK_HEIGHT / 2

        # Calculate direction vector
        dx = other_x - center_x
        dy = other_y - center_y

        # Avoid division by zero
        if abs(dx) < 0.1 and abs(dy) < 0.1:
            return center_x, center_y

        # Calculate intersection with block edges
        # Check which edge the line intersects based on slope
        if abs(dx) > abs(dy):
            # Line is more horizontal - intersects left or right edge
            if dx > 0:
                # Going right
                edge_x = center_x + half_width
                edge_y = center_y
            else:
                # Going left
                edge_x = center_x - half_width
                edge_y = center_y
        else:
            # Line is more vertical - intersects top or bottom edge
            if dy > 0:
                # Going down
                edge_x = center_x
                edge_y = center_y + half_height
            else:
                # Going up
                edge_x = center_x
                edge_y = center_y - half_height

        return edge_x, edge_y

    def _calculate_waypoints(self, start_x: float, start_y: float, end_x: float, end_y: float) -> list:
        """
        Calculate waypoints for routing the connection.

        Uses orthogonal (Manhattan-style) routing to avoid overlapping connections.
        Detects backward connections (loops) and routes them around the side.

        Args:
            start_x, start_y: Starting point
            end_x, end_y: Ending point

        Returns:
            List of (x, y) tuples representing the path
        """
        # Minimum offset for routing around blocks
        SIDE_OFFSET = 80

        # Check if this is a backward connection (going upward)
        is_backward = end_y < start_y

        # Check if blocks are vertically aligned (same or very close x position)
        is_vertical = abs(end_x - start_x) < 20

        if is_backward and is_vertical:
            # Route around the side for backward vertical connections (loops)
            # This prevents overlapping with the forward connection

            # Determine which side to route based on connection label or ID
            # Use a simple hash to consistently pick a side
            route_right = hash(self.connection.id) % 2 == 0

            if route_right:
                # Route to the right
                waypoints = [
                    (start_x, start_y),                    # Start point
                    (start_x + SIDE_OFFSET, start_y),      # Go right
                    (start_x + SIDE_OFFSET, end_y),        # Go up
                    (end_x, end_y)                         # End point
                ]
            else:
                # Route to the left
                waypoints = [
                    (start_x, start_y),                    # Start point
                    (start_x - SIDE_OFFSET, start_y),      # Go left
                    (start_x - SIDE_OFFSET, end_y),        # Go up
                    (end_x, end_y)                         # End point
                ]
        elif not is_vertical and abs(end_y - start_y) > 20:
            # For non-vertical connections, use orthogonal routing
            # Go horizontal first, then vertical
            mid_y = (start_y + end_y) / 2
            waypoints = [
                (start_x, start_y),
                (start_x, mid_y),
                (end_x, mid_y),
                (end_x, end_y)
            ]
        else:
            # Direct connection for simple cases
            waypoints = [
                (start_x, start_y),
                (end_x, end_y)
            ]

        return waypoints

    def _draw_label_at(self, x: float, y: float):
        """Draw label text at specific position."""
        # Create text
        self.label_text_id = self.canvas.create_text(
            x, y,
            text=self.connection.label,
            font=self.LABEL_FONT,
            tags=('connection', 'connection_label', f'connection_{self.connection.id}')
        )

        # Get text bounding box for background
        bbox = self.canvas.bbox(self.label_text_id)
        if bbox:
            # Add padding
            padding = 3
            x1, y1, x2, y2 = bbox
            self.label_bg_id = self.canvas.create_rectangle(
                x1 - padding, y1 - padding,
                x2 + padding, y2 + padding,
                fill=self.LABEL_BG,
                outline=self.LABEL_BORDER,
                tags=('connection', 'connection_label_bg', f'connection_{self.connection.id}')
            )

            # Raise text above background
            self.canvas.tag_raise(self.label_text_id)

    def update_positions(self, source_x: float, source_y: float, target_x: float, target_y: float):
        """
        Update connection positions when blocks move.

        Args:
            source_x, source_y: New source block position
            target_x, target_y: New target block position
        """
        self.source_x = source_x
        self.source_y = source_y
        self.target_x = target_x
        self.target_y = target_y

        # Redraw
        self.clear()
        self.draw()

    def set_selected(self, selected: bool):
        """Set selection state and update visual."""
        self.is_selected = selected
        self.redraw()

    def set_hover(self, hover: bool):
        """Set hover state and update visual."""
        self.is_hover = hover
        self.redraw()

    def redraw(self):
        """Redraw the connection with current state."""
        self.clear()
        self.draw()

    def clear(self):
        """Remove connection from canvas."""
        if self.line_id:
            self.canvas.delete(self.line_id)
            self.line_id = None
        if self.label_bg_id:
            self.canvas.delete(self.label_bg_id)
            self.label_bg_id = None
        if self.label_text_id:
            self.canvas.delete(self.label_text_id)
            self.label_text_id = None

    def destroy(self):
        """Clean up and remove from canvas."""
        self.clear()
        logger.debug(f"ConnectionWidget destroyed: {self.connection.id}")

    def contains_point(self, x: float, y: float) -> bool:
        """
        Check if point is near the connection line.

        Args:
            x, y: Point coordinates

        Returns:
            True if point is within HIT_TOLERANCE of the line
        """
        # Check distance to all segments in the multi-segment path
        if not self.waypoints or len(self.waypoints) < 2:
            return False

        # Check each segment
        for i in range(len(self.waypoints) - 1):
            x1, y1 = self.waypoints[i]
            x2, y2 = self.waypoints[i + 1]
            distance = self._point_to_segment_distance(x, y, x1, y1, x2, y2)
            if distance <= self.HIT_TOLERANCE:
                return True

        return False

    def _point_to_segment_distance(self, px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
        """
        Calculate perpendicular distance from point to a line segment.

        Args:
            px, py: Point coordinates
            x1, y1: Segment start
            x2, y2: Segment end

        Returns:
            Distance in pixels
        """
        # Calculate line length squared
        line_length_sq = (x2 - x1) ** 2 + (y2 - y1) ** 2

        # Handle degenerate case (segment endpoints at same point)
        if line_length_sq == 0:
            return math.sqrt((px - x1) ** 2 + (py - y1) ** 2)

        # Calculate projection of point onto line (clamped to segment)
        t = max(0, min(1, ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / line_length_sq))

        # Find closest point on line segment
        closest_x = x1 + t * (x2 - x1)
        closest_y = y1 + t * (y2 - y1)

        # Calculate distance
        distance = math.sqrt((px - closest_x) ** 2 + (py - closest_y) ** 2)
        return distance

    def get_midpoint(self) -> Tuple[float, float]:
        """Get the midpoint of the connection for label positioning."""
        return (
            (self.source_x + self.target_x) / 2,
            (self.source_y + self.target_y) / 2
        )

    def __repr__(self) -> str:
        """String representation."""
        return f"ConnectionWidget({self.connection.source_block_id} -> {self.connection.target_block_id})"
