"""Thread-safe theme management."""

import threading


class ThemeManager:
    """Thread-safe theme state management."""

    _theme: str = "light"
    _lock: threading.Lock = threading.Lock()

    @classmethod
    def get_theme(cls) -> str:
        """Get current theme name (thread-safe).

        Returns:
            Current theme name ('light' or 'dark').
        """
        with cls._lock:
            return cls._theme

    @classmethod
    def set_theme(cls, theme: str) -> None:
        """Set the current theme (thread-safe).

        Args:
            theme: Theme name ('light' or 'dark').
        """
        with cls._lock:
            if theme in ("light", "dark"):
                cls._theme = theme

    @classmethod
    def toggle_theme(cls) -> str:
        """Toggle between light and dark theme (thread-safe).

        Returns:
            The new theme name.
        """
        with cls._lock:
            cls._theme = "dark" if cls._theme == "light" else "light"
            return cls._theme

    @classmethod
    def is_dark(cls) -> bool:
        """Check if dark theme is active.

        Returns:
            True if dark theme is active.
        """
        return cls.get_theme() == "dark"


def set_theme(theme: str) -> None:
    """Set the current theme ('light' or 'dark').

    Args:
        theme: Theme name to set.
    """
    ThemeManager.set_theme(theme)


def toggle_theme() -> str:
    """Toggle between light and dark theme.

    Returns:
        The new theme name.
    """
    return ThemeManager.toggle_theme()
