"""Button style generators for the UI.

Warm Editorial Design System
============================
A cohesive button hierarchy using the terracotta + cream palette.
Primary actions use filled terracotta, secondary uses warm outlines,
tertiary actions are ghost-style with hover reveal.
"""

from eventcalendar.ui.theme.colors import get_color
from eventcalendar.ui.theme.scales import BORDER_RADIUS, TYPOGRAPHY_SCALE, SPACING_SCALE
from eventcalendar.ui.styles.base import px


class ButtonStyles:
    """Collection of button style generators."""

    # Consistent typography across all buttons
    _FONT_STACK = '"SF Pro Text", "Helvetica Neue", "Segoe UI", sans-serif'

    @staticmethod
    def accent() -> str:
        """Primary CTA button - terracotta fill.

        Use for: Main actions like "Create Event", "Save", "Submit"
        """
        return f"""
            QPushButton {{
                background-color: {get_color('accent')};
                color: #FFFFFF;
                border: none;
                border-radius: {px(BORDER_RADIUS["md"])};
                font-family: {ButtonStyles._FONT_STACK};
                font-size: 15px;
                font-weight: 600;
                padding: 12px 24px;
            }}
            QPushButton:hover {{
                background-color: {get_color('accent_hover')};
            }}
            QPushButton:pressed {{
                background-color: {get_color('accent_pressed')};
            }}
            QPushButton:disabled {{
                background-color: {get_color('accent_muted')};
                color: rgba(255, 255, 255, 0.6);
            }}
        """

    @staticmethod
    def secondary() -> str:
        """Secondary button - warm outlined style.

        Use for: Secondary actions like "Clear", "Cancel", "Back"
        """
        return f"""
            QPushButton {{
                background-color: transparent;
                color: {get_color('text_primary')};
                border: 1.5px solid {get_color('border_medium')};
                border-radius: {px(BORDER_RADIUS["md"])};
                font-family: {ButtonStyles._FONT_STACK};
                font-size: 15px;
                font-weight: 500;
                padding: 12px 24px;
            }}
            QPushButton:hover {{
                background-color: {get_color('background_secondary')};
                border-color: {get_color('text_tertiary')};
            }}
            QPushButton:pressed {{
                background-color: {get_color('background_tertiary')};
            }}
            QPushButton:disabled {{
                color: {get_color('text_placeholder')};
                border-color: {get_color('border_light')};
            }}
        """

    @staticmethod
    def tertiary() -> str:
        """Tertiary button - ghost style with hover reveal.

        Use for: Utility actions like "Settings", "Dark Mode", navigation
        """
        return f"""
            QPushButton {{
                background-color: transparent;
                color: {get_color('text_tertiary')};
                border: none;
                border-radius: {px(BORDER_RADIUS["md"])};
                font-family: {ButtonStyles._FONT_STACK};
                font-size: 14px;
                font-weight: 500;
                padding: 10px 16px;
            }}
            QPushButton:hover {{
                background-color: {get_color('background_tertiary')};
                color: {get_color('text_primary')};
            }}
            QPushButton:pressed {{
                background-color: {get_color('border_light')};
                color: {get_color('text_primary')};
            }}
        """

    @staticmethod
    def google() -> str:
        """Generate Google-branded button style.

        Returns:
            Stylesheet string for Google-style buttons.
        """
        return f"""
            QPushButton {{
                background-color: #4285F4;
                color: white;
                border: none;
                border-radius: {px(BORDER_RADIUS["md"])};
                font-family: {TYPOGRAPHY_SCALE["body"]["font_family"]};
                font-size: {px(TYPOGRAPHY_SCALE["body"]["size_px"])};
                font-weight: 600;
                padding: {px(SPACING_SCALE["sm"])} {px(SPACING_SCALE["md"])};
            }}
            QPushButton:hover {{
                background-color: #5294FF;
            }}
            QPushButton:pressed {{
                background-color: #3367D6;
            }}
        """
