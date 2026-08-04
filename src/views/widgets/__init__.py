"""
Widgets package for FlowCoder views.
"""

from src.views.widgets.block_widget import BlockWidget
from src.views.widgets.block_palette import BlockPalette
from src.views.widgets.connection_widget import ConnectionWidget
# ExecutionFlowchartView not imported here to avoid circular import
# Import directly from src.views.widgets.execution_flowchart_view

__all__ = ['BlockWidget', 'BlockPalette', 'ConnectionWidget']
