"""
Views package for FlowCoder

Provides GUI components and windows.
"""

from .main_window import MainWindow
from .command_list_panel import CommandListPanel
from .chat_panel import ChatPanel
from .flowchart_canvas import FlowchartCanvas
from .block_config_panel import BlockConfigPanel
from .execution_history_panel import ExecutionHistoryPanel
from .validation_panel import ValidationPanel
from .widgets.block_palette import BlockPalette

__all__ = [
    'MainWindow',
    'CommandListPanel',
    'ChatPanel',
    'FlowchartCanvas',
    'BlockConfigPanel',
    'ExecutionHistoryPanel',
    'ValidationPanel',
    'BlockPalette',
]
