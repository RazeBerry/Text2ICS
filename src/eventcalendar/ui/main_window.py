"""Main application window for EventCalendarGenerator.

Anthropic-Inspired Design System
================================
A warm, editorial layout with generous whitespace, refined typography,
and thoughtful visual hierarchy. The design evokes sophistication
while remaining approachable and functional.
"""

import logging
import os
import tempfile
import threading
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QDesktopServices
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QPushButton, QLabel, QMessageBox, QSizePolicy, QFrame,
)

from eventcalendar.config.settings import UI_CONFIG
from eventcalendar.config.constants import (
    DATE_INDICATORS, TIME_INDICATORS, EVENT_INDICATORS
)
from eventcalendar.storage.key_manager import (
    check_and_warn_legacy_storage,
    delete_legacy_key_file,
    load_api_key,
)
from eventcalendar.ui.theme.colors import get_color
from eventcalendar.ui.theme.scales import (
    TYPOGRAPHY_SCALE, SPACING_SCALE, BORDER_RADIUS,
    FONT_SANS, set_app_font
)
from eventcalendar.ui.theme.manager import toggle_theme
from eventcalendar.ui.styles.base import px
from eventcalendar.ui.styles.manager import StyleManager
from eventcalendar.ui.styles.button_styles import ButtonStyles
from eventcalendar.ui.widgets.image_area import ImageAttachmentArea
from eventcalendar.ui.widgets.api_key_dialog import APIKeySetupDialog
from eventcalendar.ui.widgets.progress_overlay import ProcessingOverlay
from eventcalendar.ui.preview import parse_event_text, format_date_display
from eventcalendar.ui.error_messages import get_user_friendly_error
from eventcalendar.ui.event_creation_controller import EventCreationController, JobState

logger = logging.getLogger(__name__)


class NLCalendarCreator(QMainWindow):
    """Main window for the Natural Language Calendar Creator application.

    Features an Anthropic-inspired design with warm terracotta accents,
    editorial typography, and generous whitespace.
    """

    # Storage warmup runs outside Qt and crosses back through this signal.
    legacy_storage_signal = pyqtSignal(str)
    api_key_required_signal = pyqtSignal()

    def __init__(self, *, prompt_for_api_key: bool = False):
        """Initialize the main window."""
        super().__init__()
        self._prompt_for_api_key = prompt_for_api_key

        # Set app-wide default font (Qt stylesheets don't reliably set font-family on macOS)
        set_app_font(QApplication.instance(), "sans", 14)

        self._init_window_properties()
        self._init_thread_infrastructure()
        self._init_state()
        self._init_ui()
        self._connect_signals()
        QTimer.singleShot(0, self._warm_storage_state_async)

    def _init_window_properties(self) -> None:
        """Set window title, size, and other properties."""
        self.setWindowTitle("Calendar Event Creator")
        self.setMinimumSize(*UI_CONFIG.min_window_size)
        self.resize(*UI_CONFIG.default_window_size)

    def _init_thread_infrastructure(self) -> None:
        """Initialize the one-at-a-time event-creation controller."""
        self._creation_controller = EventCreationController(self)

    def _init_state(self) -> None:
        """Initialize application state."""
        self._prefetched_api_key: Optional[str] = None
        self._prefetch_ready = threading.Event()
        self._credential_lock = threading.Lock()
        self._credential_generation = 0
        self.style_manager = StyleManager()
        self._preview_title_style_active = ""
        self._preview_title_style_placeholder = ""
        self._preview_style_mode: Optional[str] = None
        self.overlay: Optional[ProcessingOverlay] = None
        self._temp_ics_paths: set[str] = set()
        self._closing = False
        self._ui_enabled = True
        self._attachments_processing = False

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
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(SPACING_SCALE["xs"])

        # Title - large, semi-bold sans-serif
        self.title_label = QLabel("Create a new event")
        self.title_label.setStyleSheet(f"""
            QLabel {{
                font-family: {FONT_SANS};
                font-size: 28px;
                font-weight: 600;
                letter-spacing: -0.01em;
                color: {get_color('text_primary')};
            }}
        """)
        header_layout.addWidget(self.title_label)

        # Subtitle - regular weight sans-serif (word wrap for small windows)
        self.subtitle_label = QLabel(
            "Describe your event naturally, or drop an image of a flyer"
        )
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setStyleSheet(f"""
            QLabel {{
                font-family: {FONT_SANS};
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
        # No alignment - let panels expand naturally

        # Left panel: text input (larger, primary)
        self._add_input_panel(content_layout)

        # Right panel: image drop (smaller, secondary)
        self._add_image_panel(content_layout)

        layout.addWidget(content_widget, 1)

    def _add_input_panel(self, layout: QHBoxLayout) -> None:
        """Add the left panel with text input and live preview."""
        left_panel = QWidget()
        left_panel.setMinimumWidth(220)  # Prevent panel from disappearing
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
        self.text_input.setMinimumHeight(80)  # Reduced to allow preview to show
        self.text_input.textChanged.connect(self._on_text_changed)
        card_layout.addWidget(self.text_input, 1)

        left_layout.addWidget(input_card, 1)

        # Live preview with terracotta accent
        preview_container = QFrame()
        preview_container.setObjectName("previewContainer")
        preview_container.setMinimumHeight(50)  # Prevent preview from disappearing
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
        self.preview_event_title.setWordWrap(True)
        self._rebuild_preview_title_styles()
        self._preview_style_mode = "placeholder"
        self.preview_event_title.setStyleSheet(self._preview_title_style_placeholder)
        preview_layout.addWidget(self.preview_event_title)

        left_layout.addWidget(preview_container)

        # 60/40 split: input panel takes more space
        layout.addWidget(left_panel, 3)

    def _add_image_panel(self, layout: QHBoxLayout) -> None:
        """Add the right panel with image attachment area."""
        right_panel = QWidget()
        right_panel.setMinimumWidth(160)  # Prevent panel from disappearing
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

        # Left side: utility actions (tertiary/ghost style)
        self.settings_button = QPushButton("Settings")
        self.settings_button.setMinimumHeight(36)
        self.settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_button.clicked.connect(self._show_settings)
        self.style_manager.register(
            "settings_button",
            self.settings_button,
            ButtonStyles.tertiary
        )
        button_layout.addWidget(self.settings_button)

        self.theme_button = QPushButton("Dark Mode")
        self.theme_button.setMinimumHeight(36)
        self.theme_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_button.clicked.connect(self._toggle_theme)
        self.style_manager.register(
            "theme_button",
            self.theme_button,
            ButtonStyles.tertiary
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
        """Lazily construct the self-contained processing overlay."""
        if self.overlay is not None:
            return
        self.overlay = ProcessingOverlay(self.centralWidget())
        self.overlay.cancel_requested.connect(self._creation_controller.cancel)

    def _setup_preview_timer(self) -> None:
        """Set up the debounced preview timer."""
        self._preview_timer = QTimer()
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(UI_CONFIG.preview_debounce_ms)
        self._preview_timer.timeout.connect(self.update_live_preview)

    def _build_preview_title_style(self, *, active: bool) -> str:
        """Build stylesheet for preview title text."""
        body_style = TYPOGRAPHY_SCALE["body"]
        color = get_color("text_primary" if active else "text_tertiary")
        return f"""
            QLabel {{
                font-family: {body_style["font_family"]};
                font-size: {px(body_style["size_px"])};
                color: {color};
            }}
        """

    def _rebuild_preview_title_styles(self) -> None:
        """Recompute cached preview title styles for current theme."""
        self._preview_title_style_active = self._build_preview_title_style(active=True)
        self._preview_title_style_placeholder = self._build_preview_title_style(active=False)

    def _connect_signals(self) -> None:
        """Wire up all signal/slot connections."""
        self.legacy_storage_signal.connect(self._handle_legacy_storage_notice)
        self.api_key_required_signal.connect(self._prompt_for_missing_api_key)
        self.image_area.processing_changed.connect(self._on_attachment_processing_changed)
        self._creation_controller.status_changed.connect(self._update_status)
        self._creation_controller.completed.connect(self._handle_creation_completed)
        self._creation_controller.failed.connect(self._handle_creation_failed)
        self._creation_controller.cancelled.connect(self._handle_creation_cancelled)
        self._creation_controller.state_changed.connect(self._handle_creation_state)

    def _warm_storage_state_async(self) -> None:
        """Warm key storage in background so startup stays responsive."""
        thread = threading.Thread(
            target=self._storage_warmup_worker,
            name="storage_warmup",
            daemon=True,
        )
        thread.start()

    def _storage_warmup_worker(self) -> None:
        """Background worker for keyring probing and legacy checks."""
        with self._credential_lock:
            generation = self._credential_generation
        try:
            loaded_key = load_api_key()
        except Exception:
            loaded_key = None
            logger.debug("API key prefetch failed during warmup", exc_info=True)

        # Import the relatively heavy Google SDK after first paint, in this
        # existing background warmup.  Client construction remains credential-
        # scoped and lazy, but the first Create click avoids a cold import stall.
        try:
            from eventcalendar.core import api_client as _api_client  # noqa: F401
        except Exception:
            logger.debug("Gemini SDK import warmup failed", exc_info=True)

        with self._credential_lock:
            if generation == self._credential_generation:
                self._prefetched_api_key = loaded_key
                self._prefetch_ready.set()
                should_prompt = not loaded_key
            else:
                should_prompt = False

        if self._prompt_for_api_key and should_prompt and not self._closing:
            self.api_key_required_signal.emit()

        try:
            warning = check_and_warn_legacy_storage()
            if warning:
                self.legacy_storage_signal.emit(warning)
        except Exception:
            logger.debug("Legacy storage check failed during warmup", exc_info=True)

    def _prompt_for_missing_api_key(self) -> None:
        """Preserve first-run onboarding without blocking the first window paint."""
        with self._credential_lock:
            cached_key = self._prefetched_api_key
        if self._closing or cached_key:
            return
        dialog = APIKeySetupDialog(self)
        if not dialog.exec():
            self.close()
            return
        self._publish_interactive_api_key(load_api_key())

    def _publish_interactive_api_key(self, api_key: Optional[str]) -> None:
        """Publish a foreground credential and supersede older warmups."""
        with self._credential_lock:
            self._credential_generation += 1
            self._prefetched_api_key = api_key
            self._prefetch_ready.set()

    def _invalidate_cached_api_key(self) -> None:
        """Invalidate credentials so an older warmup cannot republish them."""
        with self._credential_lock:
            self._credential_generation += 1
            self._prefetched_api_key = None
            self._prefetch_ready.clear()

    # --- Event Handlers ---

    def _on_text_changed(self) -> None:
        """Handle text input changes with debouncing."""
        self._preview_timer.start()

    def update_live_preview(self) -> None:
        """Update the live preview based on current input."""
        text = self.text_input.toPlainText().strip()

        if not text:
            self.preview_event_title.setText("Event title \u2022 Date \u2022 Time")
            if self._preview_style_mode != "placeholder":
                self.preview_event_title.setStyleSheet(self._preview_title_style_placeholder)
                self._preview_style_mode = "placeholder"
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
        if self._preview_style_mode != "active":
            self.preview_event_title.setStyleSheet(self._preview_title_style_active)
            self._preview_style_mode = "active"

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
        self.title_label.setStyleSheet(f"""
            QLabel {{
                font-family: {FONT_SANS};
                font-size: 28px;
                font-weight: 600;
                letter-spacing: -0.01em;
                color: {get_color('text_primary')};
                padding-bottom: {px(SPACING_SCALE["xxs"])};
            }}
        """)

        self.subtitle_label.setStyleSheet(f"""
            QLabel {{
                font-family: {FONT_SANS};
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

        # Update live preview text (force stylesheet refresh for theme colors)
        self._rebuild_preview_title_styles()
        self._preview_style_mode = None
        self.update_live_preview()

        # Update separator line (HLine frame)
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
        if self.overlay is not None:
            self.overlay.refresh_theme()

    def _clear_inputs(self) -> None:
        """Clear all input fields."""
        self.text_input.clear()
        self.image_area.reset_state()

    def _show_settings(self) -> None:
        """Show the settings/API key dialog."""
        dialog = APIKeySetupDialog(self)
        if dialog.exec():
            self._creation_controller.reset_client()
            self._invalidate_cached_api_key()
            self._warm_storage_state_async()

    def _handle_legacy_storage_notice(self, message: str) -> None:
        """Offer removal of a migrated plaintext key without deleting silently."""
        if self._closing:
            return
        if "migrated" not in message.lower():
            self._show_transient_notice(message, timeout_ms=0)
            return
        reply = QMessageBox.question(
            self,
            "Remove insecure key file?",
            f"{message}\n\nRemove the legacy plaintext Gemini credentials now? "
            "Other settings in the file will be preserved.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply == QMessageBox.StandardButton.Yes:
            success, result_message = delete_legacy_key_file()
            self._show_transient_notice(result_message, timeout_ms=8000 if success else 0)

    def _update_status(self, message: str) -> None:
        """Update the status display."""
        if self.overlay is not None:
            self.overlay.set_status(message)

    def _show_transient_notice(self, message: str, timeout_ms: int = 6000) -> None:
        """Show non-blocking notice in the status bar.

        A timeout_ms of 0 keeps the message up until the next notice replaces it.
        """
        try:
            self.statusBar().showMessage(message, timeout_ms)
        except Exception:
            logger.info("Notice: %s", message)

    def _set_ui_enabled(self, enabled: bool) -> None:
        """Enable or disable UI elements."""
        self._ui_enabled = enabled
        self.create_button.setEnabled(enabled and not self._attachments_processing)
        self.clear_button.setEnabled(enabled)
        self.text_input.setEnabled(enabled)
        self.settings_button.setEnabled(enabled)
        self.theme_button.setEnabled(enabled)
        self.image_area.setEnabled(enabled)

    def _on_attachment_processing_changed(self, processing: bool) -> None:
        """Keep submission unavailable until worker-owned attachments are durable."""
        self._attachments_processing = processing
        self.create_button.setEnabled(self._ui_enabled and not processing)
        if processing:
            self._show_transient_notice("Preparing image attachment…", timeout_ms=0)

    def _show_progress(self, show: bool) -> None:
        """Show or hide the progress overlay."""
        if show:
            if self.overlay is None:
                self._setup_overlay()
            if self.overlay is None:
                return
            self.overlay.start()
        elif self.overlay is not None:
            self.overlay.stop()

    # --- Event Processing ---

    def process_event(self) -> None:
        """Process the event creation request."""
        if self.image_area.has_pending_images:
            self._show_transient_notice("Please wait for image preparation to finish.")
            return
        # Ensure an API key is available (client initialization happens in worker thread)
        if not self._ensure_api_client():
            return
        with self._credential_lock:
            api_key = self._prefetched_api_key

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
        self._set_ui_enabled(False)
        self._show_progress(True)

        # Submit to the one-at-a-time controller
        image_payloads = list(self.image_area.image_data)
        try:
            self._creation_controller.submit(
                event_description,
                image_payloads,
                api_key or "",
            )
        except Exception as exc:
            self._set_ui_enabled(True)
            self._show_progress(False)
            self._handle_creation_failed(exc)

    def _ensure_api_client(self) -> bool:
        """Ensure an API key is available for event processing."""
        if self._prefetch_ready.is_set():
            with self._credential_lock:
                api_key = self._prefetched_api_key
        else:
            api_key = load_api_key()
            self._publish_interactive_api_key(api_key)

        if not api_key:
            dialog = APIKeySetupDialog(self)
            if dialog.exec():
                api_key = load_api_key()
                self._publish_interactive_api_key(api_key)
            else:
                return False

        return bool(api_key)

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

    def _handle_creation_completed(self, extraction) -> None:
        """Handle one successful worker result on the Qt thread."""
        if self._closing:
            return
        if extraction.events:
            self._finalize_events(extraction)
            return
        self._update_status("No events found")
        self._set_ui_enabled(True)
        self._show_progress(False)

    def _handle_creation_failed(self, error: Exception) -> None:
        """Render one terminal worker error at the controller boundary."""
        logger.error("Error creating event: %s", error)
        if self._closing:
            return
        self._update_status(get_user_friendly_error(error))
        self._set_ui_enabled(True)
        self._show_progress(False)

    def _handle_creation_cancelled(self) -> None:
        """Restore an immediately usable UI after user cancellation."""
        if self._closing:
            return
        self._update_status("Event creation cancelled.")
        self._set_ui_enabled(True)
        self._show_progress(False)

    def _handle_creation_state(self, state: JobState) -> None:
        """Keep UI state derived from the controller's explicit lifecycle."""
        if state is JobState.IDLE and not self._closing:
            self._set_ui_enabled(True)

    # --- Event Finalization ---

    def _finalize_events(self, extraction) -> None:
        """Finalize events by building ICS and opening calendar."""
        if self._closing:
            return
        compatible_events = extraction.events if hasattr(extraction, "events") else extraction
        event_models = tuple(getattr(extraction, "event_models", ()))
        events = event_models or compatible_events
        extraction_warnings = list(getattr(extraction, "warnings", []))
        try:
            self._update_status("Creating calendar events...")
            ics_content, created_count, warnings = self._build_merged_ics(events)
            warnings = [*extraction_warnings, *warnings]
            self._open_in_calendar(ics_content, created_count, len(compatible_events), warnings)
        except Exception as e:
            logger.error("Error finalizing events: %s", e)
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to create calendar event: {get_user_friendly_error(e)}"
            )
        finally:
            self._set_ui_enabled(True)
            self._show_progress(False)

    def _build_merged_ics(self, events) -> Tuple[str, int, List[str]]:
        """Build one merged calendar from validated models or legacy dictionaries.

        Returns:
            Tuple of (merged ICS content, number of events built, warnings).
        """
        from eventcalendar.core.ics_builder import build_merged_ics

        result = build_merged_ics(events)

        if result.ics_content is None:
            raise ValueError("Failed to create ICS files from event data")

        warnings = [*result.skipped_events, *result.warnings]
        if warnings:
            logger.warning("ICS warnings:\n%s", "\n".join(warnings))

        return result.ics_content, len(result.created_events), warnings

    def _open_in_calendar(
        self,
        ics_content: str,
        created_count: int,
        requested_count: int,
        warnings: List[str],
    ) -> None:
        """Write temp file and open with system calendar."""
        temp_path = self._write_temp_ics_file(ics_content)

        try:
            self._launch_calendar_app(temp_path)
            self._show_success(created_count, requested_count, warnings)
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
            self._temp_ics_paths.add(tf.name)
            return tf.name

    def _launch_calendar_app(self, file_path: str) -> None:
        """Ask the desktop to open the ICS file and verify it accepted the request."""
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(file_path)):
            raise OSError("The operating system did not accept the calendar file")

    def _show_success(
        self,
        created_count: int,
        requested_count: Optional[int] = None,
        warnings: Optional[List[str]] = None,
    ) -> None:
        """Report the outcome of event creation in the status bar.

        Inputs are cleared after the OS accepts the import request.  This avoids
        duplicate imports after a partial success; skipped items can be re-entered.
        """
        requested = requested_count if requested_count is not None else created_count
        warnings = warnings or []
        skipped = requested - created_count

        if skipped > 0:
            detail = warnings[0] if warnings else "see log for details"
            more = f" (+{len(warnings) - 1} more, see log)" if len(warnings) > 1 else ""
            self._show_transient_notice(
                f"Opened {created_count} of {requested} events for import - "
                f"{skipped} skipped: {detail}{more}. Re-enter skipped events only.",
                timeout_ms=0,
            )
            self._clear_inputs()
            return

        if warnings:
            more = f" (+{len(warnings) - 1} more)" if len(warnings) > 1 else ""
            noun = "Event" if created_count == 1 else f"{created_count} events"
            message = f"{noun} opened for import with warning: {warnings[0]}{more}"
            timeout_ms = 10000
        elif created_count == 1:
            message = "Event opened for calendar import."
            timeout_ms = 5000
        else:
            message = f"{created_count} events opened for calendar import."
            timeout_ms = 5000

        self._show_transient_notice(message, timeout_ms=timeout_ms)
        self._clear_inputs()

    def _schedule_temp_cleanup(self, file_path: str) -> None:
        """Schedule delayed deletion of temp file."""
        def cleanup():
            try:
                os.unlink(file_path)
                self._temp_ics_paths.discard(file_path)
            except FileNotFoundError:
                self._temp_ics_paths.discard(file_path)
            except Exception as e:
                logger.warning("Failed to delete temp file: %s", e)

        QTimer.singleShot(UI_CONFIG.temp_file_cleanup_delay_ms, cleanup)

    # --- Cleanup ---

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle window close event."""
        self._closing = True
        try:
            self._creation_controller.close()
        except Exception:
            logger.warning("Event-creation controller close failed", exc_info=True)
        try:
            self.image_area.shutdown()
        except Exception:
            logger.warning("Attachment shutdown failed", exc_info=True)
        finally:
            for temp_path in list(self._temp_ics_paths):
                try:
                    os.unlink(temp_path)
                except FileNotFoundError:
                    pass
                except Exception as exc:
                    logger.warning("Failed to delete temp ICS file %s: %s", temp_path, exc)
                finally:
                    self._temp_ics_paths.discard(temp_path)
            super().closeEvent(event)

    @property
    def api_client(self):
        """Compatibility view for legacy tests and source-checkout callers."""
        return self._creation_controller.client

    @api_client.setter
    def api_client(self, client) -> None:
        self._creation_controller.set_client_for_testing(client)

    # --- Backward Compatibility ---

    def parse_event_text(self, text: str) -> Dict[str, Optional[str]]:
        """Parse event text (backward compatibility wrapper).

        Uses the packaged implementation and has no checkout-root dependency.
        """
        ref_date = datetime.now()
        return parse_event_text(text, reference_date=ref_date)

    def format_date_display(self, date_str: str) -> Optional[str]:
        """Format date for display (backward compatibility wrapper).

        Uses the packaged implementation and has no checkout-root dependency.
        """
        ref_date = datetime.now()
        return format_date_display(date_str, reference_date=ref_date)
