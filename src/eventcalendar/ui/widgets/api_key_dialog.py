"""API key setup dialog for first-run configuration.

Anthropic-Inspired Design System
================================
A warm, welcoming onboarding experience with editorial typography,
clear visual hierarchy, and terracotta accents. The design feels
helpful rather than bureaucratic.
"""

import logging
import re

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QFrame
)

from eventcalendar.storage.key_manager import save_api_key
from eventcalendar.ui.theme.colors import get_color
from eventcalendar.ui.theme.scales import TYPOGRAPHY_SCALE, SPACING_SCALE, BORDER_RADIUS
from eventcalendar.ui.styles.base import px
from eventcalendar.ui.styles.button_styles import ButtonStyles

logger = logging.getLogger(__name__)


class APIKeySetupDialog(QDialog):
    """Dialog to help users set up their Gemini API key.

    Features an Anthropic-inspired design with warm colors, editorial
    typography, and a welcoming onboarding flow.
    """

    GOOGLE_AI_STUDIO_URL = "https://aistudio.google.com/apikey"

    def __init__(self, parent=None):
        """Initialize the API key setup dialog.

        Args:
            parent: Parent widget.
        """
        super().__init__(parent)
        self.setWindowTitle("Welcome")
        self.setMinimumWidth(480)
        self.setMaximumWidth(560)
        self.setModal(True)

        self._setup_ui()
        self._apply_theme()

    def _setup_ui(self) -> None:
        """Set up the dialog UI components."""
        layout = QVBoxLayout(self)
        layout.setSpacing(SPACING_SCALE["md"])
        layout.setContentsMargins(
            SPACING_SCALE["xl"], SPACING_SCALE["xl"],
            SPACING_SCALE["xl"], SPACING_SCALE["xl"]
        )

        # Welcome header - serif for warmth
        self.welcome_label = QLabel("Welcome to Calendar\nEvent Creator")
        layout.addWidget(self.welcome_label)

        # Explanation - inviting tone
        self.explanation_label = QLabel(
            "This app uses AI to intelligently extract event details "
            "from your text and images. To get started, you'll need "
            "a free API key from Google."
        )
        self.explanation_label.setWordWrap(True)
        layout.addWidget(self.explanation_label)

        layout.addSpacing(SPACING_SCALE["sm"])

        # Step 1 card
        step1_card = self._create_step_card(
            step_number="1",
            title="Get your free API key",
            description="Visit Google AI Studio to create your key. It takes about 30 seconds."
        )
        layout.addWidget(step1_card)

        # Get API Key button
        self.get_key_btn = QPushButton("Open Google AI Studio")
        self.get_key_btn.setMinimumHeight(48)
        self.get_key_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.get_key_btn.clicked.connect(self._open_google_ai_studio)
        layout.addWidget(self.get_key_btn)

        layout.addSpacing(SPACING_SCALE["sm"])

        # Step 2 card
        step2_card = self._create_step_card(
            step_number="2",
            title="Paste your API key",
            description="Copy the key from Google and paste it below."
        )
        layout.addWidget(step2_card)

        # API Key input with refined styling
        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("Paste your API key here...")
        self.api_key_input.setMinimumHeight(52)
        self.api_key_input.textChanged.connect(self._validate_input)
        layout.addWidget(self.api_key_input)

        # Validation message
        self.validation_label = QLabel("")
        self.validation_label.hide()
        layout.addWidget(self.validation_label)

        layout.addSpacing(SPACING_SCALE["xs"])

        # Security note with subtle styling
        self.security_note = QLabel(
            "Your API key is stored securely on your device "
            "(system keychain when available) and used only to authenticate "
            "requests to Google Gemini."
        )
        self.security_note.setWordWrap(True)
        layout.addWidget(self.security_note)

        layout.addSpacing(SPACING_SCALE["md"])

        # Buttons with clear hierarchy
        button_layout = QHBoxLayout()
        button_layout.setSpacing(SPACING_SCALE["sm"])

        self.cancel_btn = QPushButton("Quit")
        self.cancel_btn.setMinimumHeight(44)
        self.cancel_btn.setMinimumWidth(100)
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.reject)

        self.save_btn = QPushButton("Continue")
        self.save_btn.setMinimumHeight(44)
        self.save_btn.setMinimumWidth(140)
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._save_and_continue)

        button_layout.addStretch()
        button_layout.addWidget(self.cancel_btn)
        button_layout.addWidget(self.save_btn)

        layout.addLayout(button_layout)

    def _create_step_card(self, step_number: str, title: str, description: str) -> QFrame:
        """Create a styled step indicator card.

        Args:
            step_number: The step number to display.
            title: The step title.
            description: The step description.

        Returns:
            Styled QFrame widget.
        """
        card = QFrame()
        card.setObjectName(f"stepCard{step_number}")

        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(SPACING_SCALE["sm"])

        # Step number badge
        badge = QLabel(step_number)
        badge.setObjectName(f"stepBadge{step_number}")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedSize(32, 32)
        card_layout.addWidget(badge)

        # Text container
        text_container = QVBoxLayout()
        text_container.setSpacing(SPACING_SCALE["xxs"])
        text_container.setContentsMargins(0, 0, 0, 0)

        title_label = QLabel(title)
        title_label.setObjectName(f"stepTitle{step_number}")
        text_container.addWidget(title_label)

        desc_label = QLabel(description)
        desc_label.setObjectName(f"stepDesc{step_number}")
        desc_label.setWordWrap(True)
        text_container.addWidget(desc_label)

        card_layout.addLayout(text_container, 1)

        return card

    def _apply_theme(self) -> None:
        """Apply current theme colors to all widgets."""
        title_style = TYPOGRAPHY_SCALE["title"]
        body_style = TYPOGRAPHY_SCALE["body"]
        body_serif = TYPOGRAPHY_SCALE["body_serif"]
        headline_style = TYPOGRAPHY_SCALE["headline"]
        caption_style = TYPOGRAPHY_SCALE["caption"]

        # Dialog background
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {get_color('background_primary')};
            }}
        """)

        # Welcome header - serif for editorial warmth
        self.welcome_label.setStyleSheet(f"""
            QLabel {{
                font-family: {title_style["font_family"]};
                font-size: {px(title_style["size_px"])};
                font-weight: {title_style["weight"]};
                letter-spacing: {title_style["letter_spacing"]};
                color: {get_color('text_primary')};
                line-height: 1.2;
            }}
        """)

        # Explanation text - serif for warmth
        self.explanation_label.setStyleSheet(f"""
            QLabel {{
                font-family: {body_serif["font_family"]};
                font-size: {px(body_serif["size_px"])};
                letter-spacing: {body_serif["letter_spacing"]};
                color: {get_color('text_secondary')};
                line-height: {body_serif["line_height"]};
            }}
        """)

        # Style step badges and text
        for step_num in ["1", "2"]:
            badge = self.findChild(QLabel, f"stepBadge{step_num}")
            if badge:
                badge.setStyleSheet(f"""
                    QLabel {{
                        background-color: {get_color('accent')};
                        color: white;
                        font-family: {body_style["font_family"]};
                        font-size: {px(caption_style["size_px"])};
                        font-weight: 600;
                        border-radius: {px(BORDER_RADIUS["full"])};
                    }}
                """)

            title = self.findChild(QLabel, f"stepTitle{step_num}")
            if title:
                title.setStyleSheet(f"""
                    QLabel {{
                        font-family: {headline_style["font_family"]};
                        font-size: {px(headline_style["size_px"])};
                        font-weight: {headline_style["weight"]};
                        color: {get_color('text_primary')};
                    }}
                """)

            desc = self.findChild(QLabel, f"stepDesc{step_num}")
            if desc:
                desc.setStyleSheet(f"""
                    QLabel {{
                        font-family: {body_style["font_family"]};
                        font-size: {px(caption_style["size_px"])};
                        color: {get_color('text_secondary')};
                    }}
                """)

        # Google button - blue with white text
        self.get_key_btn.setStyleSheet(ButtonStyles.google())

        # API Key input field - refined with warm border
        mono_style = TYPOGRAPHY_SCALE["mono"]
        self.api_key_input.setStyleSheet(f"""
            QLineEdit {{
                border: 2px solid {get_color('border_medium')};
                border-radius: {px(BORDER_RADIUS["md"])};
                padding: {px(SPACING_SCALE["sm"])};
                font-family: {mono_style["font_family"]};
                font-size: {px(mono_style["size_px"])};
                background-color: {get_color('background_secondary')};
                color: {get_color('text_primary')};
            }}
            QLineEdit:focus {{
                border-color: {get_color('accent')};
                background-color: {get_color('surface_elevated')};
            }}
            QLineEdit::placeholder {{
                color: {get_color('text_placeholder')};
            }}
        """)

        # Security note - subtle and reassuring
        self.security_note.setStyleSheet(f"""
            QLabel {{
                font-family: {caption_style["font_family"]};
                font-size: {px(caption_style["size_px"])};
                color: {get_color('text_tertiary')};
                font-style: italic;
            }}
        """)

        # Buttons
        self.cancel_btn.setStyleSheet(ButtonStyles.secondary())
        self.save_btn.setStyleSheet(ButtonStyles.accent())

    def _open_google_ai_studio(self) -> None:
        """Open Google AI Studio in the default browser."""
        QDesktopServices.openUrl(QUrl(self.GOOGLE_AI_STUDIO_URL))

    def _validate_input(self) -> None:
        """Validate the API key input."""
        text = self.api_key_input.text().strip()

        if not text:
            self.validation_label.hide()
            self.save_btn.setEnabled(False)
            return

        # Basic validation: Gemini API keys typically start with "AIza"
        if len(text) < 10:
            self._show_validation("Key seems too short", "error")
            self.save_btn.setEnabled(False)
            return

        # Check for common mistakes
        if text.startswith('"') or text.startswith("'"):
            self._show_validation("Remove quotes from the key", "error")
            self.save_btn.setEnabled(False)
            return

        # Check for valid format
        if not re.match(r'^AIza[A-Za-z0-9_-]+$', text):
            if text.startswith("AIza"):
                self._show_validation(
                    "Key contains invalid characters",
                    "error"
                )
            else:
                self._show_validation(
                    "API keys typically start with 'AIza'",
                    "warning"
                )
            # Still allow saving in case format changes
            self.save_btn.setEnabled(True)
            return

        # Valid key
        self._show_validation("Looks good!", "success")
        self.save_btn.setEnabled(True)

    def _show_validation(self, message: str, state: str) -> None:
        """Show validation message with appropriate styling.

        Args:
            message: The validation message.
            state: 'success', 'warning', or 'error'.
        """
        colors = {
            "success": get_color('success'),
            "warning": get_color('warning'),
            "error": get_color('error'),
        }
        color = colors.get(state, get_color('text_secondary'))
        caption_style = TYPOGRAPHY_SCALE["caption"]

        self.validation_label.setText(message)
        self.validation_label.setStyleSheet(f"""
            QLabel {{
                font-family: {caption_style["font_family"]};
                font-size: {px(caption_style["size_px"])};
                color: {color};
                padding: {px(SPACING_SCALE["xxs"])} 0;
            }}
        """)
        self.validation_label.show()

    def _save_and_continue(self) -> None:
        """Save the API key and close the dialog."""
        api_key = self.api_key_input.text().strip()

        # Clean up common input mistakes
        api_key = api_key.strip("'\"").strip()

        if save_api_key(api_key):
            logger.info("API key saved successfully")
            self.accept()
        else:
            self._show_validation(
                "Failed to save API key. Please try again.",
                "error"
            )

    def get_api_key(self) -> str:
        """Get the entered API key.

        Returns:
            The cleaned API key.
        """
        return self.api_key_input.text().strip().strip("'\"").strip()
