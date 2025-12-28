"""Main application window for EventCalendarGenerator.

Anthropic-Inspired Design System
================================
A warm, editorial layout with generous whitespace, refined typography,
and thoughtful visual hierarchy. The design evokes sophistication
while remaining approachable and functional.
"""

import logging
import os
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QCloseEvent, QFont
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QPushButton, QLabel, QMessageBox, QSizePolicy, QFrame,
    QGraphicsOpacityEffect
)

from eventcalendar.config.settings import UI_CONFIG
from eventcalendar.config.constants import (
    DATE_INDICATORS, TIME_INDICATORS, EVENT_INDICATORS
)
from eventcalendar.core.api_client import CalendarAPIClient
from eventcalendar.core.ics_builder import build_ics_from_events, combine_ics_strings
from eventcalendar.storage.key_manager import load_api_key, check_and_warn_legacy_storage
from eventcalendar.ui.theme.colors import get_color
from eventcalendar.ui.theme.scales import (
    TYPOGRAPHY_SCALE, SPACING_SCALE, BORDER_RADIUS, SHADOW_SCALE
)
from eventcalendar.ui.theme.manager import ThemeManager, toggle_theme
from eventcalendar.ui.styles.base import px
from eventcalendar.ui.styles.manager import StyleManager
from eventcalendar.ui.styles.button_styles import ButtonStyles
from eventcalendar.ui.widgets.image_area import ImageAttachmentArea
from eventcalendar.ui.widgets.api_key_dialog import APIKeySetupDialog
from eventcalendar.ui.preview import parse_event_text, format_date_display
from eventcalendar.ui.error_messages import get_user_friendly_error

logger = logging.getLogger(__name__)


class NLCalendarCreator(QMainWindow):
    """Main window for the Natural Language Calendar Creator application.

    Features an Anthropic-inspired design with warm terracotta accents,
    editorial typography, and generous whitespace.
    """

    # Signals for thread-safe UI updates
    update_status_signal = pyqtSignal(str)
    enable_ui_signal = pyqtSignal(bool)
    clear_input_signal = pyqtSignal()
    show_progress_signal = pyqtSignal(bool)
    finalize_events_signal = pyqtSignal(list)

    def __init__(self):
        """Initialize the main window."""
        super().__init__()

        self._init_window_properties()
        self._init_thread_infrastructure()
        self._init_state()
        self._init_ui()
        self._connect_signals()
        self._check_legacy_storage()

    def _init_window_properties(self) -> None:
        """Set window title, size, and other properties."""
        self.setWindowTitle("Calendar Event Creator")
        self.setMinimumSize(*UI_CONFIG.min_window_size)
        self.resize(*UI_CONFIG.default_window_size)

    def _init_thread_infrastructure(self) -> None:
        """Initialize thread pool and synchronization primitives."""
        self._executor = ThreadPoolExecutor(
            max_workers=UI_CONFIG.executor_max_workers,
            thread_name_prefix="calendar_worker"
        )
        self._active_futures: set = set()
        self._threads_lock = threading.Lock()
        self._api_client_lock = threading.Lock()

    def _init_state(self) -> None:
        """Initialize application state."""
        self.api_client: Optional[CalendarAPIClient] = None
        self.style_manager = StyleManager()

    def _init_ui(self) -> None:
        """Build the complete UI tree with editorial layout."""
        main_container = self._create_main_container()
        outer_layout = QVBoxLayout(main_container)
        outer_layout.setSpacing(0)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        # Top decorative accent bar
        accent_bar = QFrame()
        accent_bar.setFixedHeight(3)
        accent_bar.setStyleSheet(f"background-color: {get_color('accent')};")
        outer_layout.addWidget(accent_bar)

        # Main content wrapper with generous padding
        content_wrapper = QWidget()
        content_wrapper.setObjectName("contentWrapper")
        content_layout = QVBoxLayout(content_wrapper)
        content_layout.setSpacing(SPACING_SCALE["lg"])
        content_layout.setContentsMargins(
            SPACING_SCALE["xl"], SPACING_SCALE["xl"],
            SPACING_SCALE["xl"], SPACING_SCALE["lg"]
        )

        self._add_header_section(content_layout)
        self._add_main_content(content_layout)
        self._add_footer_section(content_layout)

        outer_layout.addWidget(content_wrapper, 1)
        self._setup_overlay()
        self._setup_preview_timer()

    def _create_main_container(self) -> QWidget:
        """Create and configure the central widget."""
        main_container = QWidget(self)
        main_container.setObjectName("mainContainer")
        main_container.setStyleSheet(f"""
            #mainContainer {{
                background-color: {get_color('background_primary')};
            }}
            #contentWrapper {{
                background-color: {get_color('background_primary')};
            }}
        """)
        self.setCentralWidget(main_container)
        return main_container

    def _add_header_section(self, layout: QVBoxLayout) -> None:
        """Add header with clean sans-serif typography."""
        header = QWidget()
        header_layout = QVBoxLayout(header)
        # Add left margin to align with card content (card has 24px internal padding)
        header_layout.setContentsMargins(SPACING_SCALE["md"], 0, 0, 0)
        header_layout.setSpacing(SPACING_SCALE["xs"])

        # System sans-serif font for clean, native look
        SYSTEM_FONT = "-apple-system, BlinkMacSystemFont, 'SF Pro Display', system-ui, sans-serif"

        # Title - large, semi-bold sans-serif
        self.title_label = QLabel("Create a new event")
        self.title_label.setStyleSheet(f"""
            QLabel {{
                font-family: {SYSTEM_FONT};
                font-size: 28px;
                font-weight: 600;
                letter-spacing: -0.01em;
                color: {get_color('text_primary')};
            }}
        """)
        header_layout.addWidget(self.title_label)

        # Subtitle - regular weight sans-serif
        self.subtitle_label = QLabel(
            "Describe your event naturally, or drop an image of a flyer"
        )
        self.subtitle_label.setStyleSheet(f"""
            QLabel {{
                font-family: {SYSTEM_FONT};
                font-size: 15px;
                font-weight: 400;
                color: {get_color('text_secondary')};
            }}
        """)
        header_layout.addWidget(self.subtitle_label)

        layout.addWidget(header)

    def _add_main_content(self, layout: QVBoxLayout) -> None:
        """Add the main content area with asymmetric layout."""
        content_widget = QWidget()
        content_layout = QHBoxLayout(content_widget)
        content_layout.setSpacing(SPACING_SCALE["lg"])
        content_layout.setContentsMargins(0, 0, 0, 0)

        # Left panel: text input (larger, primary)
        self._add_input_panel(content_layout)

        # Right panel: image drop (smaller, secondary)
        self._add_image_panel(content_layout)

        layout.addWidget(content_widget, 1)

    def _add_input_panel(self, layout: QHBoxLayout) -> None:
        """Add the left panel with text input and live preview."""
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(SPACING_SCALE["sm"])

        # Input card with subtle elevation
        input_card = QFrame()
        input_card.setObjectName("inputCard")
        input_card.setStyleSheet(f"""
            #inputCard {{
                background-color: {get_color('background_secondary')};
                border: 1px solid {get_color('border_light')};
                border-radius: {px(BORDER_RADIUS["lg"])};
            }}
        """)
        card_layout = QVBoxLayout(input_card)
        card_layout.setContentsMargins(
            SPACING_SCALE["md"], SPACING_SCALE["md"],
            SPACING_SCALE["md"], SPACING_SCALE["md"]
        )
        card_layout.setSpacing(SPACING_SCALE["sm"])

        # Section label - store reference for theme updates
        self.input_label = QLabel("EVENT DESCRIPTION")
        label_style = TYPOGRAPHY_SCALE["label"]
        self.input_label.setStyleSheet(f"""
            QLabel {{
                font-family: {label_style["font_family"]};
                font-size: {px(label_style["size_px"])};
                font-weight: {label_style["weight"]};
                letter-spacing: {label_style["letter_spacing"]};
                color: {get_color('text_tertiary')};
            }}
        """)
        card_layout.addWidget(self.input_label)

        # Text input with refined styling
        self.text_input = QTextEdit()
        self.text_input.setPlaceholderText(
            "e.g., Coffee with Sarah tomorrow at 2pm"
        )
        body_style = TYPOGRAPHY_SCALE["body"]
        self.text_input.setStyleSheet(f"""
            QTextEdit {{
                border: none;
                background-color: transparent;
                font-family: {body_style["font_family"]};
                font-size: {px(body_style["size_px"])};
                line-height: {body_style["line_height"]};
                color: {get_color('text_primary')};
                selection-background-color: {get_color('glow_accent')};
            }}
            QTextEdit::placeholder {{
                color: {get_color('text_placeholder')};
            }}
        """)
        self.text_input.setMinimumHeight(140)
        self.text_input.textChanged.connect(self._on_text_changed)
        card_layout.addWidget(self.text_input, 1)

        left_layout.addWidget(input_card, 1)

        # Live preview with terracotta accent
        preview_container = QFrame()
        preview_container.setObjectName("previewContainer")
        preview_container.setStyleSheet(f"""
            #previewContainer {{
                background-color: {get_color('background_tertiary')};
                border-left: 3px solid {get_color('accent')};
                border-radius: {px(BORDER_RADIUS["sm"])};
                padding: {px(SPACING_SCALE["sm"])};
            }}
        """)
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(
            SPACING_SCALE["sm"], SPACING_SCALE["xs"],
            SPACING_SCALE["sm"], SPACING_SCALE["xs"]
        )
        preview_layout.setSpacing(SPACING_SCALE["xxs"])

        # Preview label - store reference for theme updates
        self.preview_label = QLabel("PREVIEW")
        self.preview_label.setStyleSheet(f"""
            QLabel {{
                font-family: {label_style["font_family"]};
                font-size: {px(TYPOGRAPHY_SCALE["footnote"]["size_px"])};
                font-weight: {label_style["weight"]};
                letter-spacing: {label_style["letter_spacing"]};
                color: {get_color('text_tertiary')};
            }}
        """)
        preview_layout.addWidget(self.preview_label)

        self.preview_event_title = QLabel("Event title \u2022 Date \u2022 Time")
        self.preview_event_title.setStyleSheet(f"""
            QLabel {{
                font-family: {body_style["font_family"]};
                font-size: {px(body_style["size_px"])};
                color: {get_color('text_tertiary')};
            }}
        """)
        preview_layout.addWidget(self.preview_event_title)

        left_layout.addWidget(preview_container)

        # 60/40 split: input panel takes more space
        layout.addWidget(left_panel, 3)

    def _add_image_panel(self, layout: QHBoxLayout) -> None:
        """Add the right panel with image attachment area."""
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)  # No spacing - label goes inside the area

        self.image_area = ImageAttachmentArea()
        self.image_area.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )
        right_layout.addWidget(self.image_area, 1)

        # 60/40 split: image panel takes less space
        layout.addWidget(right_panel, 2)

    def _add_footer_section(self, layout: QVBoxLayout) -> None:
        """Add the refined button bar with clear hierarchy."""
        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet(f"""
            QFrame {{
                background-color: {get_color('border_light')};
                max-height: 1px;
            }}
        """)
        layout.addWidget(separator)

        # Button bar with asymmetric layout
        button_layout = QHBoxLayout()
        button_layout.setSpacing(SPACING_SCALE["sm"])
        button_layout.setContentsMargins(0, SPACING_SCALE["sm"], 0, 0)

        # Left side: secondary actions (subtle)
        self.settings_button = QPushButton("Settings")
        self.settings_button.setMinimumHeight(40)
        self.settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_button.clicked.connect(self._show_settings)
        self.style_manager.register(
            "settings_button",
            self.settings_button,
            ButtonStyles.ghost
        )
        button_layout.addWidget(self.settings_button)

        self.theme_button = QPushButton("Dark Mode")
        self.theme_button.setMinimumHeight(40)
        self.theme_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_button.clicked.connect(self._toggle_theme)
        self.style_manager.register(
            "theme_button",
            self.theme_button,
            ButtonStyles.ghost
        )
        button_layout.addWidget(self.theme_button)

        button_layout.addStretch()

        # Right side: primary actions
        self.clear_button = QPushButton("Clear")
        self.clear_button.setMinimumHeight(44)
        self.clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_button.clicked.connect(self._clear_inputs)
        self.style_manager.register(
            "clear_button",
            self.clear_button,
            ButtonStyles.secondary
        )
        button_layout.addWidget(self.clear_button)

        self.create_button = QPushButton("Create Event")
        self.create_button.setMinimumHeight(44)
        self.create_button.setMinimumWidth(140)
        self.create_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.create_button.clicked.connect(self.process_event)
        self.style_manager.register(
            "create_button",
            self.create_button,
            ButtonStyles.accent
        )
        button_layout.addWidget(self.create_button)

        layout.addLayout(button_layout)

    def _setup_overlay(self) -> None:
        """Set up the processing overlay with warm styling."""
        self.overlay = QWidget(self.centralWidget())
        self.overlay.setStyleSheet(f"""
            QWidget {{
                background-color: {get_color('surface_overlay')};
            }}
        """)
        self.overlay.hide()

        overlay_layout = QVBoxLayout(self.overlay)
        overlay_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Processing card
        processing_card = QFrame()
        processing_card.setStyleSheet(f"""
            QFrame {{
                background-color: {get_color('surface_elevated')};
                border-radius: {px(BORDER_RADIUS["lg"])};
                padding: {px(SPACING_SCALE["lg"])};
            }}
        """)
        card_layout = QVBoxLayout(processing_card)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.setSpacing(SPACING_SCALE["sm"])

        # Animated terracotta dot
        self.loading_dot = QLabel("\u25CF")
        self.loading_dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.loading_dot.setStyleSheet(f"""
            QLabel {{
                color: {get_color('accent')};
                font-size: 24px;
            }}
        """)
        card_layout.addWidget(self.loading_dot)

        self.processing_label = QLabel("Processing...")
        headline_style = TYPOGRAPHY_SCALE["headline"]
        self.processing_label.setStyleSheet(f"""
            QLabel {{
                font-family: {headline_style["font_family"]};
                font-size: {px(headline_style["size_px"])};
                font-weight: {headline_style["weight"]};
                color: {get_color('text_primary')};
            }}
        """)
        self.processing_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.processing_label)

        overlay_layout.addWidget(processing_card)

    def _setup_preview_timer(self) -> None:
        """Set up the debounced preview timer."""
        self._preview_timer = QTimer()
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(UI_CONFIG.preview_debounce_ms)
        self._preview_timer.timeout.connect(self.update_live_preview)

    def _connect_signals(self) -> None:
        """Wire up all signal/slot connections."""
        self.update_status_signal.connect(self._update_status)
        self.enable_ui_signal.connect(self._set_ui_enabled)
        self.clear_input_signal.connect(self._clear_inputs)
        self.show_progress_signal.connect(self._show_progress)
        self.finalize_events_signal.connect(self._finalize_events)

    def _check_legacy_storage(self) -> None:
        """Check for legacy API key storage and warn user."""
        warning = check_and_warn_legacy_storage()
        if warning:
            QMessageBox.warning(self, "Security Notice", warning)

    # --- Event Handlers ---

    def _on_text_changed(self) -> None:
        """Handle text input changes with debouncing."""
        self._preview_timer.start()

    def update_live_preview(self) -> None:
        """Update the live preview based on current input."""
        text = self.text_input.toPlainText().strip()
        body_style = TYPOGRAPHY_SCALE["body"]

        if not text:
            self.preview_event_title.setText("Event title \u2022 Date \u2022 Time")
            self.preview_event_title.setStyleSheet(f"""
                QLabel {{
                    font-family: {body_style["font_family"]};
                    font-size: {px(body_style["size_px"])};
                    color: {get_color('text_tertiary')};
                }}
            """)
            return

        parsed = self.parse_event_text(text)

        # Build preview string
        parts = []
        if parsed["title"]:
            parts.append(parsed["title"])
        else:
            parts.append(text[:30] + "..." if len(text) > 30 else text)

        parts.append(parsed["date"] or "Date")
        parts.append(parsed["time"] or "Time")

        preview_text = " \u2022 ".join(parts)
        self.preview_event_title.setText(preview_text)
        self.preview_event_title.setStyleSheet(f"""
            QLabel {{
                font-family: {body_style["font_family"]};
                font-size: {px(body_style["size_px"])};
                color: {get_color('text_primary')};
            }}
        """)

    def _toggle_theme(self) -> None:
        """Toggle between light and dark theme."""
        new_theme = toggle_theme()
        self.theme_button.setText("Light Mode" if new_theme == "dark" else "Dark Mode")
        self._refresh_all_styles()

    def _refresh_all_styles(self) -> None:
        """Refresh all widget styles after theme change."""
        self.style_manager.refresh_all()
        self.image_area.refresh_theme()

        # Update main container background
        self.centralWidget().setStyleSheet(f"""
            #mainContainer {{
                background-color: {get_color('background_primary')};
            }}
            #contentWrapper {{
                background-color: {get_color('background_primary')};
            }}
        """)

        # Update accent bar (first child of main container)
        accent_bar = self.centralWidget().findChild(QFrame)
        if accent_bar:
            accent_bar.setStyleSheet(f"background-color: {get_color('accent')};")

        # Update title and subtitle with system sans-serif
        SYSTEM_FONT = "-apple-system, BlinkMacSystemFont, 'SF Pro Display', system-ui, sans-serif"
        self.title_label.setStyleSheet(f"""
            QLabel {{
                font-family: {SYSTEM_FONT};
                font-size: 28px;
                font-weight: 600;
                letter-spacing: -0.01em;
                color: {get_color('text_primary')};
                padding-bottom: {px(SPACING_SCALE["xxs"])};
            }}
        """)

        self.subtitle_label.setStyleSheet(f"""
            QLabel {{
                font-family: {SYSTEM_FONT};
                font-size: 15px;
                font-weight: 400;
                color: {get_color('text_secondary')};
            }}
        """)

        # Update input card
        input_card = self.centralWidget().findChild(QFrame, "inputCard")
        if input_card:
            input_card.setStyleSheet(f"""
                #inputCard {{
                    background-color: {get_color('background_secondary')};
                    border: 1px solid {get_color('border_light')};
                    border-radius: {px(BORDER_RADIUS["lg"])};
                }}
            """)

        # Update input label
        if hasattr(self, 'input_label'):
            label_style = TYPOGRAPHY_SCALE["label"]
            self.input_label.setStyleSheet(f"""
                QLabel {{
                    font-family: {label_style["font_family"]};
                    font-size: {px(label_style["size_px"])};
                    font-weight: {label_style["weight"]};
                    letter-spacing: {label_style["letter_spacing"]};
                    color: {get_color('text_tertiary')};
                }}
            """)

        # Update text input
        body_style = TYPOGRAPHY_SCALE["body"]
        self.text_input.setStyleSheet(f"""
            QTextEdit {{
                border: none;
                background-color: transparent;
                font-family: {body_style["font_family"]};
                font-size: {px(body_style["size_px"])};
                line-height: {body_style["line_height"]};
                color: {get_color('text_primary')};
                selection-background-color: {get_color('glow_accent')};
            }}
        """)

        # Update preview container
        preview_container = self.centralWidget().findChild(QFrame, "previewContainer")
        if preview_container:
            preview_container.setStyleSheet(f"""
                #previewContainer {{
                    background-color: {get_color('background_tertiary')};
                    border-left: 3px solid {get_color('accent')};
                    border-radius: {px(BORDER_RADIUS["sm"])};
                    padding: {px(SPACING_SCALE["sm"])};
                }}
            """)

        # Update preview label
        if hasattr(self, 'preview_label'):
            label_style = TYPOGRAPHY_SCALE["label"]
            self.preview_label.setStyleSheet(f"""
                QLabel {{
                    font-family: {label_style["font_family"]};
                    font-size: {px(TYPOGRAPHY_SCALE["footnote"]["size_px"])};
                    font-weight: {label_style["weight"]};
                    letter-spacing: {label_style["letter_spacing"]};
                    color: {get_color('text_tertiary')};
                }}
            """)

        # Update live preview text
        self.update_live_preview()

        # Update separator line
        separator = self.centralWidget().findChild(QFrame)
        # Find the separator (HLine frame)
        for child in self.centralWidget().findChildren(QFrame):
            if child.frameShape() == QFrame.Shape.HLine:
                child.setStyleSheet(f"""
                    QFrame {{
                        background-color: {get_color('border_light')};
                        max-height: 1px;
                    }}
                """)
                break

        # Update overlay
        self.overlay.setStyleSheet(f"""
            QWidget {{
                background-color: {get_color('surface_overlay')};
            }}
        """)

    def _clear_inputs(self) -> None:
        """Clear all input fields."""
        self.text_input.clear()
        self.image_area.reset_state()

    def _show_settings(self) -> None:
        """Show the settings/API key dialog."""
        dialog = APIKeySetupDialog(self)
        if dialog.exec():
            # Reload API client with new key
            with self._api_client_lock:
                self.api_client = None

    def _update_status(self, message: str) -> None:
        """Update the status display."""
        self.processing_label.setText(message)

    def _set_ui_enabled(self, enabled: bool) -> None:
        """Enable or disable UI elements."""
        self.create_button.setEnabled(enabled)
        self.clear_button.setEnabled(enabled)
        self.text_input.setEnabled(enabled)

    def _show_progress(self, show: bool) -> None:
        """Show or hide the progress overlay."""
        if show:
            self.overlay.setGeometry(self.centralWidget().rect())
            self.overlay.show()
            self.overlay.raise_()
        else:
            self.overlay.hide()

    # --- Event Processing ---

    def process_event(self) -> None:
        """Process the event creation request."""
        # Initialize API client if needed
        if not self._ensure_api_client():
            return

        # Get input data
        event_description = self.text_input.toPlainText().strip()
        has_images = bool(self.image_area.image_data)

        # Validate input
        if not event_description and not has_images:
            QMessageBox.warning(
                self,
                "No Input",
                "Please enter an event description or attach an image."
            )
            return

        # Check if text looks like an event
        if event_description and not has_images:
            if not self._validate_event_text(event_description):
                return

        # Disable UI and show progress
        self.enable_ui_signal.emit(False)
        self.show_progress_signal.emit(True)

        # Submit to thread pool
        future = self._executor.submit(self._create_event_thread)
        with self._threads_lock:
            self._active_futures.add(future)
        future.add_done_callback(self._on_future_done)

    def _ensure_api_client(self) -> bool:
        """Ensure API client is initialized."""
        with self._api_client_lock:
            if self.api_client is not None:
                return True

            api_key = load_api_key()
            if not api_key:
                dialog = APIKeySetupDialog(self)
                if dialog.exec():
                    api_key = load_api_key()
                else:
                    return False

            if api_key:
                try:
                    self.api_client = CalendarAPIClient(api_key)
                    return True
                except Exception as e:
                    logger.error("Failed to initialize API client: %s", e)
                    QMessageBox.critical(
                        self,
                        "Error",
                        f"Failed to initialize API client: {e}"
                    )

            return False

    def _validate_event_text(self, text: str) -> bool:
        """Validate that text looks like an event description."""
        text_lower = text.lower()

        has_date = any(ind in text_lower for ind in DATE_INDICATORS)
        has_time = any(ind in text_lower for ind in TIME_INDICATORS)
        has_event_word = any(ind in text_lower for ind in EVENT_INDICATORS)

        if not (has_date or has_time or has_event_word):
            reply = QMessageBox.question(
                self,
                "Not an Event?",
                "This doesn't look like an event description. Continue anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            return reply == QMessageBox.StandardButton.Yes

        return True

    def _create_event_thread(self) -> None:
        """Worker thread for event creation."""
        try:
            event_description = self.text_input.toPlainText().strip()
            image_data = [
                img.materialize() for img in self.image_area.image_data
            ]

            def status_callback(msg: str) -> None:
                self.update_status_signal.emit(msg)

            events = self.api_client.get_event_data(
                event_description,
                image_data,
                status_callback
            )

            if events:
                self.finalize_events_signal.emit(events)
            else:
                self.update_status_signal.emit("No events found")
                self.enable_ui_signal.emit(True)
                self.show_progress_signal.emit(False)

        except Exception as e:
            logger.error("Error creating event: %s", e)
            self.update_status_signal.emit(get_user_friendly_error(e))
            self.enable_ui_signal.emit(True)
            self.show_progress_signal.emit(False)

    def _on_future_done(self, future: Future) -> None:
        """Callback when a future completes."""
        with self._threads_lock:
            self._active_futures.discard(future)

    # --- Event Finalization ---

    def _finalize_events(self, events: List[Dict]) -> None:
        """Finalize events by building ICS and opening calendar."""
        try:
            self.update_status_signal.emit("Creating calendar events...")
            ics_content = self._build_merged_ics(events)
            self._open_in_calendar(ics_content, len(events))
        except Exception as e:
            logger.error("Error finalizing events: %s", e)
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to create calendar event: {get_user_friendly_error(e)}"
            )
        finally:
            self.enable_ui_signal.emit(True)
            self.show_progress_signal.emit(False)

    def _build_merged_ics(self, events: List[Dict]) -> str:
        """Build ICS strings and merge them."""
        ics_strings, warnings = build_ics_from_events(events)

        if not ics_strings:
            raise ValueError("Failed to create ICS files from event data")

        if warnings:
            warning_text = "\n".join(warnings)
            QMessageBox.warning(self, "Warnings", warning_text)

        return combine_ics_strings(ics_strings)

    def _open_in_calendar(self, ics_content: str, event_count: int) -> None:
        """Write temp file and open with system calendar."""
        temp_path = self._write_temp_ics_file(ics_content)

        try:
            self._launch_calendar_app(temp_path)
            self._show_success(event_count)
            self._schedule_temp_cleanup(temp_path)
        except Exception as e:
            logger.error("Failed to open calendar: %s", e)
            # Try to clean up immediately
            try:
                os.unlink(temp_path)
            except Exception:
                pass
            raise

    def _write_temp_ics_file(self, content: str) -> str:
        """Create temporary ICS file with proper encoding."""
        with tempfile.NamedTemporaryFile(
            mode='wb',
            delete=False,
            suffix=".ics"
        ) as tf:
            tf.write(content.encode('utf-8'))
            return tf.name

    def _launch_calendar_app(self, file_path: str) -> None:
        """Platform-specific calendar app launch."""
        if sys.platform == "darwin":
            subprocess.Popen(["open", file_path], start_new_session=True)
        elif sys.platform.startswith("win"):
            os.startfile(file_path)
        else:
            subprocess.Popen(["xdg-open", file_path], start_new_session=True)

    def _show_success(self, event_count: int) -> None:
        """Show success message."""
        if event_count == 1:
            message = "Event created successfully!"
        else:
            message = f"{event_count} events created successfully!"

        QMessageBox.information(self, "Success", message)
        self._clear_inputs()

    def _schedule_temp_cleanup(self, file_path: str) -> None:
        """Schedule delayed deletion of temp file."""
        def cleanup():
            try:
                os.unlink(file_path)
            except Exception as e:
                logger.warning("Failed to delete temp file: %s", e)

        QTimer.singleShot(UI_CONFIG.temp_file_cleanup_delay_ms, cleanup)

    # --- Cleanup ---

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle window close event."""
        # Shutdown thread pool
        self._executor.shutdown(wait=False)
        super().closeEvent(event)

    # --- Backward Compatibility ---

    def parse_event_text(self, text: str) -> Dict[str, Optional[str]]:
        """Parse event text (backward compatibility wrapper).

        Uses the module-level datetime for monkeypatching compatibility.
        """
        # Import datetime from the module that created this instance
        # This allows tests to monkeypatch Calender.datetime
        import Calender
        ref_date = Calender.datetime.now()
        return parse_event_text(text, reference_date=ref_date)

    def format_date_display(self, date_str: str) -> Optional[str]:
        """Format date for display (backward compatibility wrapper).

        Uses the module-level datetime for monkeypatching compatibility.
        """
        import Calender
        ref_date = Calender.datetime.now()
        return format_date_display(date_str, reference_date=ref_date)
