"""
Execution Flowchart View Widget

A read-only flowchart view with execution highlighting enabled.
Used in Agents tab to show execution progress visually.

Phase 1.2 implementation.
"""

import tkinter as tk
from tkinter import ttk
from typing import Optional
import logging

from src.models import Flowchart
from src.views.flowchart_canvas import FlowchartCanvas

logger = logging.getLogger(__name__)


class ExecutionFlowchartView(ttk.Frame):
    """
    Flowchart view with execution highlighting enabled.

    This widget is designed for displaying execution state only,
    not for editing. It shows a flowchart with execution highlighting
    (green for executing, light green for completed, red for error).

    Used in Agents tab to visualize the currently executing flowchart.
    """

    def __init__(self, parent: tk.Widget, flowchart: Optional[Flowchart] = None):
        """
        Initialize execution flowchart view.

        Args:
            parent: Parent widget
            flowchart: Optional flowchart to display initially
        """
        super().__init__(parent)
        self.flowchart = flowchart

        # Create canvas with execution highlighting enabled
        self.canvas = FlowchartCanvas(
            self,
            on_block_selected=None,  # No block selection in execution view
            on_canvas_clicked=None,
            on_flowchart_changed=None,  # Read-only, no changes allowed
            execution_highlighting=True  # Enable execution state highlighting
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Load flowchart if provided
        if flowchart:
            self.load_flowchart(flowchart)

        logger.debug("ExecutionFlowchartView initialized")

    def load_flowchart(self, flowchart: Flowchart):
        """
        Load a flowchart into the view.

        Args:
            flowchart: Flowchart to display
        """
        self.flowchart = flowchart

        # Clear existing content
        self.canvas.clear()

        # Load the flowchart into the canvas
        self.canvas.load_flowchart(flowchart)

        logger.info(f"Loaded flowchart with {len(flowchart.blocks)} blocks")

    def update_block_state(self, block_id: str, state: str):
        """
        Update the execution state of a block.

        Args:
            block_id: ID of block to update
            state: State (executing, completed, error, normal)
        """
        self.canvas.set_block_state(block_id, state)
        logger.debug(f"Updated block {block_id} state to {state}")

    def reset_all_states(self):
        """Reset all blocks to normal state."""
        self.canvas.reset_all_block_states()
        logger.debug("Reset all block states to normal")

    def clear(self):
        """Clear the flowchart view."""
        self.canvas.clear()
        self.flowchart = None
        logger.debug("Cleared execution flowchart view")
