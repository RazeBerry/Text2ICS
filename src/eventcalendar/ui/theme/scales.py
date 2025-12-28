"""Typography and spacing scales for the design system.

Anthropic-Inspired Design System
================================
Typography uses a refined serif/sans-serif pairing for editorial warmth.
Spacing follows a harmonious scale with generous whitespace.
"""

# =============================================================================
# FONT FAMILIES - Single source of truth for all fonts
# =============================================================================
# Modify these constants to change fonts globally across the application.
# NOTE: Qt stylesheets don't properly handle font-family on macOS.
# Use get_font() to create QFont objects instead.

FONT_FAMILIES = {
    # Apple system fonts (Qt uses .AppleSystemUIFont for system font)
    "sans": ".AppleSystemUIFont",
    "serif": ".AppleSystemUIFont",
    "mono": "SF Mono",
}

# Convenience aliases for direct import
FONT_SANS = FONT_FAMILIES["sans"]
FONT_SERIF = FONT_FAMILIES["serif"]
FONT_MONO = FONT_FAMILIES["mono"]


def get_font(family: str = "sans", size: int = 14, weight: int = 400) -> "QFont":
    """Create a QFont object with the specified family and properties.

    Qt stylesheets don't properly handle font-family on macOS, so use this
    function to create QFont objects and apply them with widget.setFont().

    Args:
        family: Font family key ("sans", "serif", or "mono")
        size: Font size in points
        weight: Font weight (400=normal, 500=medium, 600=semibold, 700=bold)

    Returns:
        QFont object configured with the specified properties.
    """
    from PyQt6.QtGui import QFont

    font_name = FONT_FAMILIES.get(family, FONT_FAMILIES["sans"])
    font = QFont(font_name, size)
    font.setWeight(QFont.Weight(weight))
    return font


def set_app_font(app: "QApplication", family: str = "sans", size: int = 14) -> None:
    """Set the application-wide default font.

    Call this once at app startup to set Geist as the default font.

    Args:
        app: The QApplication instance
        family: Font family key ("sans", "serif", or "mono")
        size: Default font size in points
    """
    font = get_font(family, size)
    app.setFont(font)


# =============================================================================
# TYPOGRAPHY SCALE
# =============================================================================
# Primary: Georgia or system serif for warmth and readability
# Secondary: SF Pro or system sans for UI elements
# The combination evokes thoughtfulness and precision

TYPOGRAPHY_SCALE = {
    "display": {
        "size_px": 36,
        "weight": 400,
        "line_height": 1.15,
        "letter_spacing": "-0.02em",
        "font_family": FONT_SERIF,
    },
    "title": {
        "size_px": 26,
        "weight": 400,
        "line_height": 1.2,
        "letter_spacing": "-0.01em",
        "font_family": FONT_SERIF,
    },
    "headline": {
        "size_px": 18,
        "weight": 500,
        "line_height": 1.35,
        "letter_spacing": "0",
        "font_family": FONT_SANS,
    },
    "body": {
        "size_px": 15,
        "weight": 400,
        "line_height": 1.5,
        "letter_spacing": "0",
        "font_family": FONT_SANS,
    },
    "body_serif": {
        "size_px": 15,
        "weight": 400,
        "line_height": 1.6,
        "letter_spacing": "0.01em",
        "font_family": FONT_SERIF,
    },
    "caption": {
        "size_px": 13,
        "weight": 400,
        "line_height": 1.4,
        "letter_spacing": "0.01em",
        "font_family": FONT_SANS,
    },
    "footnote": {
        "size_px": 11,
        "weight": 400,
        "line_height": 1.3,
        "letter_spacing": "0.02em",
        "font_family": FONT_SANS,
    },
    "label": {
        "size_px": 12,
        "weight": 600,
        "line_height": 1.2,
        "letter_spacing": "0.05em",
        "font_family": FONT_SANS,
    },
    "mono": {
        "size_px": 14,
        "weight": 400,
        "line_height": 1.5,
        "letter_spacing": "0",
        "font_family": FONT_MONO,
    },
}

# Spacing Scale - generous and harmonious
# Based on 8px base unit with refined increments
SPACING_SCALE = {
    "xxs": 4,
    "xs": 8,
    "sm": 16,
    "md": 24,
    "lg": 32,
    "xl": 48,
    "xxl": 64,
    "xxxl": 96,
}

# Border Radius - soft but not overly rounded
BORDER_RADIUS = {
    "xs": 4,
    "sm": 8,
    "md": 12,
    "lg": 16,
    "xl": 24,
    "full": 9999,  # For pills and circles
}

# Shadow Scale - warm-tinted shadows for depth
SHADOW_SCALE = {
    "sm": "0 1px 2px rgba(45, 41, 38, 0.05)",
    "md": "0 4px 12px rgba(45, 41, 38, 0.08)",
    "lg": "0 8px 24px rgba(45, 41, 38, 0.12)",
    "xl": "0 16px 48px rgba(45, 41, 38, 0.16)",
    "inner": "inset 0 1px 2px rgba(45, 41, 38, 0.06)",
    "glow": "0 0 24px rgba(204, 90, 71, 0.2)",  # Terracotta glow
}

# Transition durations
TRANSITIONS = {
    "fast": "120ms",
    "normal": "200ms",
    "slow": "350ms",
    "spring": "400ms cubic-bezier(0.34, 1.56, 0.64, 1)",
}
