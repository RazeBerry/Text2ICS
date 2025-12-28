"""Dynamic color access based on current theme."""

from eventcalendar.ui.theme.manager import ThemeManager
from eventcalendar.ui.theme.palettes import LIGHT_PALETTE, DARK_PALETTE


def get_color(key: str) -> str:
    """Get color from current theme palette.

    Args:
        key: Color key name (e.g., 'text_primary', 'accent').

    Returns:
        Hex color string, or magenta (#FF00FF) for missing keys.
    """
    palette = LIGHT_PALETTE if ThemeManager.get_theme() == "light" else DARK_PALETTE
    return palette.get(key, "#FF00FF")  # Magenta fallback for missing keys


class _DynamicColors:
    """Dynamic color accessor that reads from current theme.

    This class provides dict-like access to colors that automatically
    returns the correct color for the current theme.
    """

    def __getitem__(self, key: str) -> str:
        """Get color by key using bracket notation.

        Args:
            key: Color key name.

        Returns:
            Hex color string.
        """
        return get_color(key)

    def get(self, key: str, default: str = "") -> str:
        """Get color by key with optional default.

        Args:
            key: Color key name.
            default: Default value if key not found.

        Returns:
            Hex color string or default.
        """
        result = get_color(key)
        return result if result != "#FF00FF" else default


# Singleton instance for backward compatibility
COLORS = _DynamicColors()
