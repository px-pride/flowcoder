"""
Controllers package for FlowCoder

Provides controller layer functionality for execution, command management, and UI coordination.
"""

from .execution_controller import (
    ExecutionController,
    ExecutionControllerError
)

from .command_controller import (
    CommandController,
    CommandControllerError,
    InvalidCommandNameError
)

# UIController requires tkinter — lazy-load so headless / embedding
# consumers don't need GUI libraries.
_UI_LAZY = {
    'UIController': '.ui_controller',
    'ui_thread': '.ui_controller',
}


def __getattr__(name: str):
    if name in _UI_LAZY:
        from . import ui_controller as _mod
        return getattr(_mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    'ExecutionController',
    'ExecutionControllerError',
    'CommandController',
    'CommandControllerError',
    'InvalidCommandNameError',
    # UI (lazy-loaded)
    'UIController',
    'ui_thread',
]
