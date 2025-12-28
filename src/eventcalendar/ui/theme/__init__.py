"""Theme management for EventCalendarGenerator UI."""

from eventcalendar.ui.theme.manager import ThemeManager, set_theme, toggle_theme
from eventcalendar.ui.theme.palettes import LIGHT_PALETTE, DARK_PALETTE
from eventcalendar.ui.theme.colors import get_color, COLORS
from eventcalendar.ui.theme.scales import TYPOGRAPHY_SCALE, SPACING_SCALE, BORDER_RADIUS

__all__ = [
    "ThemeManager",
    "set_theme",
    "toggle_theme",
    "LIGHT_PALETTE",
    "DARK_PALETTE",
    "get_color",
    "COLORS",
    "TYPOGRAPHY_SCALE",
    "SPACING_SCALE",
    "BORDER_RADIUS",
]
