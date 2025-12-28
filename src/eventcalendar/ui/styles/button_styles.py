"""Button style generators for the UI.

Anthropic-Inspired Design System
================================
Buttons feature refined typography, warm shadows, and subtle hover states.
Primary actions use terracotta, secondary actions are understated.
"""

from eventcalendar.ui.theme.colors import get_color
from eventcalendar.ui.theme.scales import (
    TYPOGRAPHY_SCALE, SPACING_SCALE, BORDER_RADIUS
)
from eventcalendar.ui.styles.base import px


class ButtonStyles:
    """Collection of button style generators."""

    @staticmethod
    def accent() -> str:
        """Generate accent (primary) button style.

        Warm terracotta with subtle shadow and refined hover state.

        Returns:
            Stylesheet string for accent buttons.
        """
        return f"""
            QPushButton {{
                background-color: {get_color('accent')};
                color: #FFFFFF;
                border: none;
                border-radius: {px(BORDER_RADIUS["md"])};
                font-family: {TYPOGRAPHY_SCALE["body"]["font_family"]};
                font-size: {px(TYPOGRAPHY_SCALE["body"]["size_px"])};
                font-weight: 600;
                letter-spacing: 0.01em;
                padding: {px(SPACING_SCALE["xs"] + 4)} {px(SPACING_SCALE["md"])};
            }}
            QPushButton:hover {{
                background-color: {get_color('accent_hover')};
            }}
            QPushButton:pressed {{
                background-color: {get_color('accent_pressed')};
            }}
            QPushButton:disabled {{
                background-color: {get_color('accent_disabled')};
                color: {get_color('text_tertiary')};
            }}
        """

    @staticmethod
    def secondary() -> str:
        """Generate secondary button style.

        Subtle, understated with warm border.

        Returns:
            Stylesheet string for secondary buttons.
        """
        return f"""
            QPushButton {{
                background-color: transparent;
                color: {get_color('text_primary')};
                border: 1px solid {get_color('border_medium')};
                border-radius: {px(BORDER_RADIUS["md"])};
                font-family: {TYPOGRAPHY_SCALE["body"]["font_family"]};
                font-size: {px(TYPOGRAPHY_SCALE["body"]["size_px"])};
                font-weight: 500;
                padding: {px(SPACING_SCALE["xs"] + 4)} {px(SPACING_SCALE["md"])};
            }}
            QPushButton:hover {{
                background-color: {get_color('background_secondary')};
                border-color: {get_color('text_tertiary')};
            }}
            QPushButton:pressed {{
                background-color: {get_color('background_tertiary')};
            }}
            QPushButton:disabled {{
                color: {get_color('text_tertiary')};
                border-color: {get_color('border_light')};
            }}
        """

    @staticmethod
    def ghost() -> str:
        """Generate ghost button style.

        Minimal, text-only with subtle hover background.

        Returns:
            Stylesheet string for ghost buttons.
        """
        return f"""
            QPushButton {{
                background-color: transparent;
                color: {get_color('text_secondary')};
                border: none;
                border-radius: {px(BORDER_RADIUS["sm"])};
                font-family: {TYPOGRAPHY_SCALE["body"]["font_family"]};
                font-size: {px(TYPOGRAPHY_SCALE["body"]["size_px"])};
                font-weight: 500;
                padding: {px(SPACING_SCALE["xs"])} {px(SPACING_SCALE["sm"])};
            }}
            QPushButton:hover {{
                background-color: {get_color('background_tertiary')};
                color: {get_color('text_primary')};
            }}
            QPushButton:pressed {{
                background-color: {get_color('border_light')};
            }}
        """

    @staticmethod
    def icon() -> str:
        """Generate icon button style (minimal, square).

        Returns:
            Stylesheet string for icon buttons.
        """
        return f"""
            QPushButton {{
                background-color: transparent;
                color: {get_color('text_secondary')};
                border: none;
                border-radius: {px(BORDER_RADIUS["sm"])};
                padding: {px(SPACING_SCALE["xs"])};
                min-width: 36px;
                min-height: 36px;
            }}
            QPushButton:hover {{
                background-color: {get_color('background_tertiary')};
                color: {get_color('text_primary')};
            }}
            QPushButton:pressed {{
                background-color: {get_color('border_light')};
            }}
        """

    @staticmethod
    def link() -> str:
        """Generate link-style button.

        Looks like a hyperlink with underline on hover.

        Returns:
            Stylesheet string for link buttons.
        """
        return f"""
            QPushButton {{
                background-color: transparent;
                color: {get_color('accent')};
                border: none;
                font-family: {TYPOGRAPHY_SCALE["body"]["font_family"]};
                font-size: {px(TYPOGRAPHY_SCALE["body"]["size_px"])};
                font-weight: 500;
                padding: 0;
                text-decoration: none;
            }}
            QPushButton:hover {{
                color: {get_color('accent_hover')};
                text-decoration: underline;
            }}
            QPushButton:pressed {{
                color: {get_color('accent_pressed')};
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

    @staticmethod
    def danger() -> str:
        """Generate danger/destructive action button.

        Returns:
            Stylesheet string for danger buttons.
        """
        return f"""
            QPushButton {{
                background-color: transparent;
                color: {get_color('error')};
                border: 1px solid {get_color('error')};
                border-radius: {px(BORDER_RADIUS["md"])};
                font-family: {TYPOGRAPHY_SCALE["body"]["font_family"]};
                font-size: {px(TYPOGRAPHY_SCALE["body"]["size_px"])};
                font-weight: 500;
                padding: {px(SPACING_SCALE["xs"] + 4)} {px(SPACING_SCALE["md"])};
            }}
            QPushButton:hover {{
                background-color: {get_color('error')};
                color: white;
            }}
            QPushButton:pressed {{
                background-color: {get_color('accent_pressed')};
                color: white;
            }}
        """

    @staticmethod
    def pill() -> str:
        """Generate pill-shaped button for tags/chips.

        Returns:
            Stylesheet string for pill buttons.
        """
        return f"""
            QPushButton {{
                background-color: {get_color('background_tertiary')};
                color: {get_color('text_secondary')};
                border: none;
                border-radius: {px(BORDER_RADIUS["full"])};
                font-family: {TYPOGRAPHY_SCALE["caption"]["font_family"]};
                font-size: {px(TYPOGRAPHY_SCALE["caption"]["size_px"])};
                font-weight: 500;
                padding: {px(SPACING_SCALE["xxs"])} {px(SPACING_SCALE["sm"])};
            }}
            QPushButton:hover {{
                background-color: {get_color('border_light')};
                color: {get_color('text_primary')};
            }}
            QPushButton:pressed {{
                background-color: {get_color('border_medium')};
            }}
        """
