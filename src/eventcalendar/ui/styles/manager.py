"""Style manager for centralized widget styling."""

from typing import Callable, Dict, Tuple
from PyQt6.QtWidgets import QWidget


class StyleManager:
    """Manages widget styles with automatic refresh on theme change.

    This class replaces the pattern of having separate _get_*_style() and
    _apply_*_style() methods for each widget. Instead, widgets are registered
    with their style generator functions and can be refreshed all at once.

    Example:
        style_manager = StyleManager()
        style_manager.register("create_button", button, ButtonStyles.accent)
        style_manager.register("clear_button", clear_btn, ButtonStyles.secondary)

        # On theme change:
        style_manager.refresh_all()
    """

    def __init__(self):
        """Initialize the style manager."""
        self._widgets: Dict[str, Tuple[QWidget, Callable[[], str]]] = {}

    def register(self, name: str, widget: QWidget, style_fn: Callable[[], str]) -> None:
        """Register a widget with its style generator.

        Args:
            name: Unique name for the widget.
            widget: The QWidget to style.
            style_fn: A callable that returns the stylesheet string.
        """
        self._widgets[name] = (widget, style_fn)
        self._apply(name)

    def _apply(self, name: str) -> None:
        """Apply style to a single widget.

        Args:
            name: Name of the registered widget.
        """
        if name in self._widgets:
            widget, style_fn = self._widgets[name]
            widget.setStyleSheet(style_fn())

    def refresh(self, name: str) -> None:
        """Refresh a specific widget's style.

        Args:
            name: Name of the registered widget.
        """
        self._apply(name)

    def refresh_all(self) -> None:
        """Refresh all registered widget styles."""
        for name in self._widgets:
            self._apply(name)

    def unregister(self, name: str) -> None:
        """Remove a widget from management.

        Args:
            name: Name of the widget to unregister.
        """
        self._widgets.pop(name, None)

    def clear(self) -> None:
        """Clear all registered widgets."""
        self._widgets.clear()
