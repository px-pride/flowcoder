"""
Accessibility utilities for FlowCoder (Phase 6.2)

Provides utilities for improving keyboard navigation, focus indicators,
and high contrast mode support.
"""

import tkinter as tk
from tkinter import ttk
from typing import Optional, List, Dict
import logging

logger = logging.getLogger(__name__)


class AccessibilityConfig:
    """Configuration for accessibility features."""

    # High contrast mode enabled
    high_contrast_enabled: bool = False

    # Focus indicator width (pixels)
    focus_indicator_width: int = 2

    # Focus indicator color
    focus_indicator_color: str = "#0078D7"  # Windows blue

    # High contrast colors
    high_contrast_bg: str = "#000000"
    high_contrast_fg: str = "#FFFFFF"
    high_contrast_button_bg: str = "#1A1A1A"
    high_contrast_highlight: str = "#FFFF00"  # Yellow for selected items

    @classmethod
    def toggle_high_contrast(cls) -> bool:
        """Toggle high contrast mode.

        Returns:
            New high contrast state
        """
        cls.high_contrast_enabled = not cls.high_contrast_enabled
        logger.info(f"High contrast mode: {cls.high_contrast_enabled}")
        return cls.high_contrast_enabled


class FocusManager:
    """Manages focus and keyboard navigation for widgets."""

    def __init__(self, root: tk.Tk):
        """Initialize focus manager.

        Args:
            root: Root Tkinter window
        """
        self.root = root
        self.focusable_widgets: List[tk.Widget] = []
        self.focus_indicators: Dict[tk.Widget, Dict] = {}

    def register_widget(
        self,
        widget: tk.Widget,
        tab_index: Optional[int] = None,
        screen_reader_label: Optional[str] = None
    ):
        """Register a widget for focus management.

        Args:
            widget: Widget to register
            tab_index: Optional tab index (lower values focused first)
            screen_reader_label: Optional label for screen readers
        """
        # Store original relief and borderwidth
        if isinstance(widget, (ttk.Button, ttk.Entry, tk.Button, tk.Entry, tk.Text)):
            original_style = self._get_widget_style(widget)
            self.focus_indicators[widget] = original_style

            # Add focus event handlers
            widget.bind("<FocusIn>", lambda e: self._on_focus_in(e.widget))
            widget.bind("<FocusOut>", lambda e: self._on_focus_out(e.widget))

        # Set tab traversal
        if tab_index is not None:
            widget.lift()

        # Add to focusable widgets list
        if widget not in self.focusable_widgets:
            self.focusable_widgets.append(widget)

        # Sort by tab index if specified
        if tab_index is not None:
            # Store tab index as widget property
            widget._tab_index = tab_index
            self.focusable_widgets.sort(key=lambda w: getattr(w, '_tab_index', 999))

        # Set screen reader label (accessibility name)
        if screen_reader_label:
            # Note: Tkinter doesn't have built-in ARIA labels, but we can store it
            widget._screen_reader_label = screen_reader_label

    def _get_widget_style(self, widget: tk.Widget) -> Dict:
        """Get current widget style properties.

        Args:
            widget: Widget to inspect

        Returns:
            Dictionary of style properties
        """
        style = {}
        try:
            if isinstance(widget, (tk.Button, tk.Entry, tk.Text)):
                style['relief'] = widget.cget('relief')
                style['borderwidth'] = widget.cget('borderwidth')
                style['highlightthickness'] = widget.cget('highlightthickness')
                style['highlightbackground'] = widget.cget('highlightbackground')
                style['highlightcolor'] = widget.cget('highlightcolor')
        except tk.TclError:
            pass
        return style

    def _on_focus_in(self, widget: tk.Widget):
        """Handle focus in event.

        Args:
            widget: Widget that received focus
        """
        # Add focus indicator
        try:
            if isinstance(widget, (tk.Button, tk.Entry, tk.Text)):
                widget.config(
                    highlightthickness=AccessibilityConfig.focus_indicator_width,
                    highlightbackground=AccessibilityConfig.focus_indicator_color,
                    highlightcolor=AccessibilityConfig.focus_indicator_color
                )
            elif isinstance(widget, (ttk.Button, ttk.Entry)):
                # ttk widgets don't support highlight*, use state instead
                pass  # ttk automatically handles focus indicator
        except tk.TclError:
            pass

    def _on_focus_out(self, widget: tk.Widget):
        """Handle focus out event.

        Args:
            widget: Widget that lost focus
        """
        # Remove focus indicator
        original_style = self.focus_indicators.get(widget, {})
        try:
            if isinstance(widget, (tk.Button, tk.Entry, tk.Text)):
                if 'highlightthickness' in original_style:
                    widget.config(
                        highlightthickness=original_style.get('highlightthickness', 0),
                        highlightbackground=original_style.get('highlightbackground', ''),
                        highlightcolor=original_style.get('highlightcolor', '')
                    )
                else:
                    widget.config(highlightthickness=0)
        except tk.TclError:
            pass

    def next_widget(self):
        """Move focus to next widget in tab order."""
        current = self.root.focus_get()
        if current in self.focusable_widgets:
            idx = self.focusable_widgets.index(current)
            next_idx = (idx + 1) % len(self.focusable_widgets)
            self.focusable_widgets[next_idx].focus_set()
        elif self.focusable_widgets:
            self.focusable_widgets[0].focus_set()

    def prev_widget(self):
        """Move focus to previous widget in tab order."""
        current = self.root.focus_get()
        if current in self.focusable_widgets:
            idx = self.focusable_widgets.index(current)
            prev_idx = (idx - 1) % len(self.focusable_widgets)
            self.focusable_widgets[prev_idx].focus_set()
        elif self.focusable_widgets:
            self.focusable_widgets[-1].focus_set()


class HighContrastManager:
    """Manages high contrast mode for the application."""

    def __init__(self, root: tk.Tk):
        """Initialize high contrast manager.

        Args:
            root: Root Tkinter window
        """
        self.root = root
        self.original_styles: Dict[tk.Widget, Dict] = {}

    def apply_high_contrast(self, widget: Optional[tk.Widget] = None):
        """Apply high contrast colors to widget and its children.

        Args:
            widget: Widget to apply high contrast to (default: root)
        """
        if widget is None:
            widget = self.root

        # Store original style if not already stored
        if widget not in self.original_styles:
            self.original_styles[widget] = self._get_colors(widget)

        # Apply high contrast colors
        try:
            if isinstance(widget, (tk.Frame, ttk.Frame, tk.Toplevel)):
                widget.config(bg=AccessibilityConfig.high_contrast_bg)
            elif isinstance(widget, (tk.Button, ttk.Button)):
                if isinstance(widget, tk.Button):
                    widget.config(
                        bg=AccessibilityConfig.high_contrast_button_bg,
                        fg=AccessibilityConfig.high_contrast_fg
                    )
            elif isinstance(widget, (tk.Label, ttk.Label)):
                if isinstance(widget, tk.Label):
                    widget.config(
                        bg=AccessibilityConfig.high_contrast_bg,
                        fg=AccessibilityConfig.high_contrast_fg
                    )
            elif isinstance(widget, (tk.Entry, ttk.Entry, tk.Text)):
                if isinstance(widget, (tk.Entry, tk.Text)):
                    widget.config(
                        bg=AccessibilityConfig.high_contrast_button_bg,
                        fg=AccessibilityConfig.high_contrast_fg,
                        insertbackground=AccessibilityConfig.high_contrast_fg
                    )
        except tk.TclError:
            pass

        # Recursively apply to children
        for child in widget.winfo_children():
            self.apply_high_contrast(child)

    def remove_high_contrast(self, widget: Optional[tk.Widget] = None):
        """Remove high contrast colors and restore originals.

        Args:
            widget: Widget to restore (default: root)
        """
        if widget is None:
            widget = self.root

        # Restore original colors
        original = self.original_styles.get(widget, {})
        try:
            if 'bg' in original:
                widget.config(bg=original['bg'])
            if 'fg' in original:
                widget.config(fg=original['fg'])
            if 'insertbackground' in original:
                widget.config(insertbackground=original['insertbackground'])
        except tk.TclError:
            pass

        # Recursively restore children
        for child in widget.winfo_children():
            self.remove_high_contrast(child)

    def _get_colors(self, widget: tk.Widget) -> Dict:
        """Get current widget colors.

        Args:
            widget: Widget to inspect

        Returns:
            Dictionary of color properties
        """
        colors = {}
        try:
            colors['bg'] = widget.cget('bg')
        except (tk.TclError, AttributeError):
            pass
        try:
            colors['fg'] = widget.cget('fg')
        except (tk.TclError, AttributeError):
            pass
        try:
            colors['insertbackground'] = widget.cget('insertbackground')
        except (tk.TclError, AttributeError):
            pass
        return colors


def enable_keyboard_navigation(widget: tk.Widget):
    """Enable keyboard navigation for a widget.

    Args:
        widget: Widget to enable keyboard navigation for
    """
    # Ensure widget is focusable
    try:
        widget.config(takefocus=True)
    except tk.TclError:
        pass


def set_accessible_name(widget: tk.Widget, name: str):
    """Set accessible name for screen readers.

    Note: Tkinter doesn't have native screen reader support, but we can
    store the accessible name as a widget property for future use.

    Args:
        widget: Widget to set name for
        name: Accessible name
    """
    widget._accessible_name = name
