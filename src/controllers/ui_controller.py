"""
UI Controller for FlowCoder

Provides helper methods for UI operations, dialog management,
and thread-safe UI updates for async operations.
"""

import tkinter as tk
from tkinter import messagebox
import logging
import asyncio
from typing import Optional, Callable, Any
from functools import wraps


logger = logging.getLogger(__name__)


class UIController:
    """
    Controller for UI operations and coordination.

    Provides:
    - Dialog management (error, info, warning, question)
    - Progress indicators (busy cursor)
    - Thread-safe UI updates
    - Async operation helpers
    - Status message coordination
    """

    def __init__(self, root: tk.Tk):
        """
        Initialize UI controller.

        Args:
            root: Root Tkinter window
        """
        self.root = root
        self._busy = False
        self._busy_count = 0  # Track nested busy states

        logger.info("UIController initialized")

    # ==================== Dialog Management ====================

    def show_error(self, title: str, message: str) -> None:
        """
        Show error dialog.

        Args:
            title: Dialog title
            message: Error message
        """
        logger.error(f"Error dialog: {title} - {message}")
        messagebox.showerror(title, message, parent=self.root)

    def show_info(self, title: str, message: str) -> None:
        """
        Show info dialog.

        Args:
            title: Dialog title
            message: Info message
        """
        logger.info(f"Info dialog: {title} - {message}")
        messagebox.showinfo(title, message, parent=self.root)

    def show_warning(self, title: str, message: str) -> None:
        """
        Show warning dialog.

        Args:
            title: Dialog title
            message: Warning message
        """
        logger.warning(f"Warning dialog: {title} - {message}")
        messagebox.showwarning(title, message, parent=self.root)

    def ask_yes_no(self, title: str, message: str) -> bool:
        """
        Show yes/no question dialog.

        Args:
            title: Dialog title
            message: Question message

        Returns:
            True if user clicked Yes, False if No
        """
        logger.debug(f"Question dialog: {title} - {message}")
        result = messagebox.askyesno(title, message, parent=self.root)
        logger.debug(f"User answered: {'Yes' if result else 'No'}")
        return result

    def ask_ok_cancel(self, title: str, message: str) -> bool:
        """
        Show OK/Cancel question dialog.

        Args:
            title: Dialog title
            message: Question message

        Returns:
            True if user clicked OK, False if Cancel
        """
        logger.debug(f"OK/Cancel dialog: {title} - {message}")
        result = messagebox.askokcancel(title, message, parent=self.root)
        logger.debug(f"User answered: {'OK' if result else 'Cancel'}")
        return result

    # ==================== Progress Indicators ====================

    def set_busy(self, busy: bool = True) -> None:
        """
        Set busy cursor state.

        Args:
            busy: True to show busy cursor, False to restore normal
        """
        if busy:
            self._busy_count += 1
            if self._busy_count == 1:  # First call to set busy
                self.root.config(cursor="watch")
                self._busy = True
                logger.debug("Busy cursor enabled")
        else:
            self._busy_count = max(0, self._busy_count - 1)
            if self._busy_count == 0:  # All busy operations completed
                self.root.config(cursor="")
                self._busy = False
                logger.debug("Busy cursor disabled")

    def is_busy(self) -> bool:
        """
        Check if UI is in busy state.

        Returns:
            True if busy, False otherwise
        """
        return self._busy

    # ==================== Thread-Safe UI Updates ====================

    def schedule_ui_callback(
        self,
        callback: Callable,
        *args,
        delay: int = 0,
        **kwargs
    ) -> str:
        """
        Schedule a callback to run on the UI thread.

        This is safe to call from any thread. The callback will
        execute on the main Tkinter thread.

        Args:
            callback: Function to call
            *args: Positional arguments for callback
            delay: Delay in milliseconds (default 0)
            **kwargs: Keyword arguments for callback

        Returns:
            Alarm ID that can be used to cancel with root.after_cancel()
        """
        def safe_callback():
            try:
                callback(*args, **kwargs)
            except Exception as e:
                logger.error(f"Error in UI callback: {e}", exc_info=True)

        alarm_id = self.root.after(delay, safe_callback)
        logger.debug(f"Scheduled UI callback: {callback.__name__} (delay={delay}ms)")
        return alarm_id

    def update_ui(self) -> None:
        """
        Force UI to update (process pending events).

        Use sparingly - only when you need immediate visual feedback.
        """
        self.root.update_idletasks()

    # ==================== Async Operation Helpers ====================

    def run_async_task(
        self,
        coro,
        on_complete: Optional[Callable[[Any], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        show_busy: bool = True
    ):
        """
        Run an async task and handle completion/errors safely.

        Args:
            coro: Coroutine to execute
            on_complete: Callback when task completes successfully (receives result)
            on_error: Callback when task fails (receives exception)
            show_busy: Whether to show busy cursor during execution

        Returns:
            asyncio.Task object
        """
        async def wrapped_coro():
            try:
                if show_busy:
                    self.set_busy(True)

                result = await coro

                # Schedule completion callback on UI thread
                if on_complete:
                    self.schedule_ui_callback(on_complete, result)

                return result

            except Exception as e:
                logger.error(f"Async task failed: {e}", exc_info=True)

                # Schedule error callback on UI thread
                if on_error:
                    self.schedule_ui_callback(on_error, e)
                else:
                    # Default error handling
                    self.schedule_ui_callback(
                        self.show_error,
                        "Error",
                        f"An error occurred: {str(e)}"
                    )

            finally:
                if show_busy:
                    self.schedule_ui_callback(self.set_busy, False)

        task = asyncio.ensure_future(wrapped_coro())
        logger.debug(f"Started async task: {coro}")
        return task

    # ==================== Utility Methods ====================

    def safe_call(self, func: Callable, *args, **kwargs) -> Optional[Any]:
        """
        Safely call a function with error handling.

        If the function raises an exception, show an error dialog
        and return None.

        Args:
            func: Function to call
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Function result, or None if error occurred
        """
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in safe_call: {e}", exc_info=True)
            self.show_error("Error", f"An error occurred: {str(e)}")
            return None

    def confirm_action(
        self,
        title: str,
        message: str,
        action: Callable,
        *args,
        **kwargs
    ) -> bool:
        """
        Ask for confirmation before performing an action.

        Args:
            title: Confirmation dialog title
            message: Confirmation message
            action: Function to call if user confirms
            *args: Arguments for action
            **kwargs: Keyword arguments for action

        Returns:
            True if action was performed, False if cancelled
        """
        if self.ask_yes_no(title, message):
            self.safe_call(action, *args, **kwargs)
            return True
        return False


# Decorator for marking methods that update UI (should run on main thread)
def ui_thread(func):
    """
    Decorator to ensure function runs on UI thread.

    If called from another thread, schedules it on the main thread.
    """
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        # If we have a ui_controller attribute, use it
        if hasattr(self, 'ui_controller') and hasattr(self.ui_controller, 'schedule_ui_callback'):
            return self.ui_controller.schedule_ui_callback(func, self, *args, **kwargs)
        else:
            # Fallback: just call directly
            return func(self, *args, **kwargs)
    return wrapper
