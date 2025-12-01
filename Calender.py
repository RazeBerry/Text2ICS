import sys
import os
import logging
from datetime import datetime, timedelta
import copy
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, Future
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                           QTextEdit, QPushButton, QLabel, QMessageBox,
                           QHBoxLayout, QSizePolicy, QDialog, QLineEdit)
from PyQt6.QtGui import QIcon, QDragEnterEvent, QDropEvent, QKeyEvent, QCloseEvent, QDesktopServices
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QMetaObject, QBuffer, pyqtSlot, Q_ARG, QByteArray, QEvent, QUrl
from typing import Optional, List, Dict
import threading
import queue
import re
import base64
import mimetypes
from pathlib import Path
import tempfile
import subprocess
import uuid
import shutil
import dateutil.parser
from icalendar import Calendar
from dotenv import load_dotenv, set_key

from api_client import CalendarAPIClient, build_ics_from_events


logger = logging.getLogger(__name__)


# =============================================================================
# Design System - Theme Support
# =============================================================================

def px(value: int) -> str:
    """Return a CSS pixel value."""
    return f"{value}px"


TYPOGRAPHY_SCALE = {
    "title": {"size_px": 28, "weight": 600, "line_height": 1.2},
    "headline": {"size_px": 17, "weight": 600, "line_height": 1.3},
    "body": {"size_px": 15, "weight": 400, "line_height": 1.4},
    "caption": {"size_px": 13, "weight": 400, "line_height": 1.3},
    "footnote": {"size_px": 11, "weight": 400, "line_height": 1.2},
}

SPACING_SCALE = {
    "xs": 8,
    "sm": 16,
    "md": 24,
    "lg": 32,
    "xl": 48,
    "xxl": 64,
}

BORDER_RADIUS = {
    "sm": 8,
    "md": 12,
    "lg": 16,
}

# Anthropic Design System - Dual Theme Palettes
LIGHT_PALETTE = {
    "text_primary": "#1F1F1F",
    "text_secondary": "#6B7280",
    "text_tertiary": "#9CA3AF",
    "text_placeholder": "#9CA3AF",
    "background_primary": "#FFFFFF",
    "background_secondary": "#FAFAF9",
    "background_tertiary": "#F5F5F4",
    "border_light": "#E7E5E4",
    "border_medium": "#D6D3D1",
    "accent": "#D97706",
    "accent_hover": "#B45309",
    "accent_pressed": "#92400E",
    "accent_disabled": "#D6D3D1",
    "success": "#059669",
    "warning": "#D97706",
    "error": "#DC2626",
}

DARK_PALETTE = {
    "text_primary": "#FAFAFA",
    "text_secondary": "#A1A1AA",
    "text_tertiary": "#71717A",
    "text_placeholder": "#71717A",
    "background_primary": "#1F1F1F",
    "background_secondary": "#171717",
    "background_tertiary": "#262626",
    "border_light": "#2D2D2D",
    "border_medium": "#404040",
    "accent": "#F59E0B",
    "accent_hover": "#FBBF24",
    "accent_pressed": "#D97706",
    "accent_disabled": "#404040",
    "success": "#10B981",
    "warning": "#F59E0B",
    "error": "#EF4444",
}


# Thread-safe theme management
class ThemeManager:
    """Thread-safe theme state management."""
    _theme: str = "light"
    _lock: threading.Lock = threading.Lock()

    @classmethod
    def get_theme(cls) -> str:
        """Get current theme name (thread-safe)."""
        with cls._lock:
            return cls._theme

    @classmethod
    def set_theme(cls, theme: str) -> None:
        """Set the current theme (thread-safe)."""
        with cls._lock:
            if theme in ("light", "dark"):
                cls._theme = theme

    @classmethod
    def toggle_theme(cls) -> str:
        """Toggle between light and dark theme (thread-safe). Returns new theme name."""
        with cls._lock:
            cls._theme = "dark" if cls._theme == "light" else "light"
            return cls._theme


def get_color(key: str) -> str:
    """Get color from current theme palette."""
    palette = LIGHT_PALETTE if ThemeManager.get_theme() == "light" else DARK_PALETTE
    return palette.get(key, "#FF00FF")  # Magenta fallback for missing keys


# Backwards compatibility functions
def set_theme(theme: str) -> None:
    """Set the current theme ('light' or 'dark')."""
    ThemeManager.set_theme(theme)


def toggle_theme() -> str:
    """Toggle between light and dark theme. Returns new theme name."""
    return ThemeManager.toggle_theme()


# Backwards compatibility - COLORS dict that reads from current palette
class _DynamicColors:
    """Dynamic color accessor that reads from current theme."""
    def __getitem__(self, key: str) -> str:
        return get_color(key)
    def get(self, key: str, default: str = "") -> str:
        result = get_color(key)
        return result if result != "#FF00FF" else default


COLORS = _DynamicColors()


# =============================================================================
# API Key Management - Simple .env based configuration
# =============================================================================

def get_env_file_path() -> Path:
    """Get the path to the .env file in the app directory."""
    if getattr(sys, 'frozen', False):
        # Running as bundled executable
        return Path(sys._MEIPASS).parent / '.env'
    else:
        # Running in development
        return Path(__file__).parent / '.env'


def load_api_key() -> Optional[str]:
    """
    Load the Gemini API key from environment or .env file.
    Priority: 1) Environment variable, 2) .env file
    """
    # First check environment variable (allows override)
    env_key = os.environ.get('GEMINI_API_KEY')
    if env_key:
        return env_key

    # Try loading from .env file
    env_path = get_env_file_path()
    if env_path.exists():
        load_dotenv(env_path)
        return os.environ.get('GEMINI_API_KEY')

    return None


def save_api_key(api_key: str) -> bool:
    """Save the API key to the .env file."""
    try:
        env_path = get_env_file_path()

        # Create .env file if it doesn't exist
        if not env_path.exists():
            env_path.touch()

        # Save the key
        set_key(str(env_path), 'GEMINI_API_KEY', api_key)

        # Also set in current environment so app works immediately
        os.environ['GEMINI_API_KEY'] = api_key

        return True
    except Exception as e:
        logging.error("Failed to save API key: %s", e)
        return False


class APIKeySetupDialog(QDialog):
    """
    A friendly dialog to help users set up their Gemini API key.
    Designed to be idiot-proof and guide users through the process.
    Uses the app's theme system for consistent dark/light mode support.
    """

    GOOGLE_AI_STUDIO_URL = "https://aistudio.google.com/apikey"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Welcome - API Key Setup")
        self.setMinimumWidth(520)
        self.setModal(True)

        self._setup_ui()
        self._apply_theme()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(SPACING_SCALE["sm"])
        layout.setContentsMargins(
            SPACING_SCALE["lg"], SPACING_SCALE["lg"],
            SPACING_SCALE["lg"], SPACING_SCALE["lg"]
        )

        # Welcome header
        self.welcome_label = QLabel("Welcome to Calendar Event Creator!")
        layout.addWidget(self.welcome_label)

        # Explanation
        self.explanation_label = QLabel(
            "This app uses Google's Gemini AI to intelligently extract event details "
            "from your text and images. To get started, you'll need a free API key."
        )
        self.explanation_label.setWordWrap(True)
        layout.addWidget(self.explanation_label)

        layout.addSpacing(SPACING_SCALE["xs"])

        # Step 1
        self.step1_header = QLabel("Step 1: Get your free API key")
        layout.addWidget(self.step1_header)

        self.step1_desc = QLabel("Click the button below to open Google AI Studio and create your key:")
        self.step1_desc.setWordWrap(True)
        layout.addWidget(self.step1_desc)

        # Get API Key button (Google blue - consistent across themes)
        self.get_key_btn = QPushButton("Open Google AI Studio (Free)")
        self.get_key_btn.setMinimumHeight(44)
        self.get_key_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.get_key_btn.clicked.connect(self._open_google_ai_studio)
        layout.addWidget(self.get_key_btn)

        layout.addSpacing(SPACING_SCALE["sm"])

        # Step 2
        self.step2_header = QLabel("Step 2: Paste your API key here")
        layout.addWidget(self.step2_header)

        self.step2_desc = QLabel("Copy the API key from Google AI Studio and paste it below:")
        self.step2_desc.setWordWrap(True)
        layout.addWidget(self.step2_desc)

        # API Key input
        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("Paste your API key here (starts with 'AIza...')")
        self.api_key_input.setMinimumHeight(48)
        self.api_key_input.textChanged.connect(self._validate_input)
        layout.addWidget(self.api_key_input)

        # Validation message
        self.validation_label = QLabel("")
        self.validation_label.hide()
        layout.addWidget(self.validation_label)

        # Security note
        self.security_note = QLabel(
            "Your API key is stored locally in a .env file and never shared. "
            "You can change it anytime from the app settings."
        )
        self.security_note.setWordWrap(True)
        layout.addWidget(self.security_note)

        layout.addSpacing(SPACING_SCALE["sm"])

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(SPACING_SCALE["sm"])

        self.cancel_btn = QPushButton("Quit")
        self.cancel_btn.setMinimumHeight(44)
        self.cancel_btn.setMinimumWidth(100)
        self.cancel_btn.clicked.connect(self.reject)

        self.save_btn = QPushButton("Save & Continue")
        self.save_btn.setMinimumHeight(44)
        self.save_btn.setMinimumWidth(140)
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._save_and_continue)

        button_layout.addStretch()
        button_layout.addWidget(self.cancel_btn)
        button_layout.addWidget(self.save_btn)

        layout.addLayout(button_layout)

    def _apply_theme(self):
        """Apply current theme colors to all widgets."""
        # Dialog background
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {get_color('background_primary')};
            }}
        """)

        # Welcome header
        self.welcome_label.setStyleSheet(f"""
            QLabel {{
                font-size: {px(TYPOGRAPHY_SCALE["title"]["size_px"])};
                font-weight: {TYPOGRAPHY_SCALE["title"]["weight"]};
                color: {get_color('text_primary')};
                padding-bottom: {px(SPACING_SCALE["xs"])};
            }}
        """)

        # Explanation text
        self.explanation_label.setStyleSheet(f"""
            QLabel {{
                font-size: {px(TYPOGRAPHY_SCALE["body"]["size_px"])};
                color: {get_color('text_secondary')};
                line-height: {TYPOGRAPHY_SCALE["body"]["line_height"]};
            }}
        """)

        # Step headers
        step_header_style = f"""
            QLabel {{
                font-size: {px(TYPOGRAPHY_SCALE["headline"]["size_px"])};
                font-weight: {TYPOGRAPHY_SCALE["headline"]["weight"]};
                color: {get_color('text_primary')};
                padding-top: {px(SPACING_SCALE["xs"])};
            }}
        """
        self.step1_header.setStyleSheet(step_header_style)
        self.step2_header.setStyleSheet(step_header_style)

        # Step descriptions
        step_desc_style = f"""
            QLabel {{
                font-size: {px(TYPOGRAPHY_SCALE["body"]["size_px"])};
                color: {get_color('text_secondary')};
            }}
        """
        self.step1_desc.setStyleSheet(step_desc_style)
        self.step2_desc.setStyleSheet(step_desc_style)

        # Google button (blue accent - works in both themes)
        self.get_key_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #4285F4;
                color: white;
                border: none;
                border-radius: {px(BORDER_RADIUS["md"])};
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
        """)

        # API Key input field
        self.api_key_input.setStyleSheet(f"""
            QLineEdit {{
                border: 2px solid {get_color('border_medium')};
                border-radius: {px(BORDER_RADIUS["md"])};
                padding: {px(SPACING_SCALE["sm"])};
                font-size: {px(TYPOGRAPHY_SCALE["body"]["size_px"])};
                font-family: monospace;
                background-color: {get_color('background_secondary')};
                color: {get_color('text_primary')};
            }}
            QLineEdit:focus {{
                border-color: {get_color('accent')};
                background-color: {get_color('background_primary')};
            }}
            QLineEdit::placeholder {{
                color: {get_color('text_placeholder')};
            }}
        """)

        # Security note
        self.security_note.setStyleSheet(f"""
            QLabel {{
                font-size: {px(TYPOGRAPHY_SCALE["caption"]["size_px"])};
                color: {get_color('text_tertiary')};
                font-style: italic;
                padding-top: {px(SPACING_SCALE["xs"])};
            }}
        """)

        # Cancel button (secondary style)
        self.cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {get_color('background_secondary')};
                color: {get_color('text_primary')};
                border: 1px solid {get_color('border_medium')};
                border-radius: {px(BORDER_RADIUS["md"])};
                font-size: {px(TYPOGRAPHY_SCALE["body"]["size_px"])};
                font-weight: 500;
                padding: {px(SPACING_SCALE["xs"])} {px(SPACING_SCALE["md"])};
            }}
            QPushButton:hover {{
                background-color: {get_color('background_tertiary')};
                border-color: {get_color('text_tertiary')};
            }}
            QPushButton:pressed {{
                background-color: {get_color('border_light')};
            }}
        """)

        # Save button (primary accent style)
        self.save_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {get_color('accent')};
                color: white;
                border: none;
                border-radius: {px(BORDER_RADIUS["md"])};
                font-size: {px(TYPOGRAPHY_SCALE["body"]["size_px"])};
                font-weight: 600;
                padding: {px(SPACING_SCALE["xs"])} {px(SPACING_SCALE["md"])};
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
        """)

        # Update validation label with current theme
        self._update_validation_style()

    def _update_validation_style(self, state: str = "hidden"):
        """Update validation label style based on state."""
        if state == "error":
            self.validation_label.setStyleSheet(f"""
                QLabel {{
                    font-size: {px(TYPOGRAPHY_SCALE["caption"]["size_px"])};
                    color: {get_color('error')};
                    padding: {px(4)} 0;
                }}
            """)
        elif state == "warning":
            self.validation_label.setStyleSheet(f"""
                QLabel {{
                    font-size: {px(TYPOGRAPHY_SCALE["caption"]["size_px"])};
                    color: {get_color('warning')};
                    padding: {px(4)} 0;
                }}
            """)
        elif state == "success":
            self.validation_label.setStyleSheet(f"""
                QLabel {{
                    font-size: {px(TYPOGRAPHY_SCALE["caption"]["size_px"])};
                    color: {get_color('success')};
                    padding: {px(4)} 0;
                }}
            """)

    def _open_google_ai_studio(self):
        """Open Google AI Studio in the default browser."""
        QDesktopServices.openUrl(QUrl(self.GOOGLE_AI_STUDIO_URL))

    def _validate_input(self):
        """Validate the API key input."""
        key = self.api_key_input.text().strip()

        if not key:
            self.save_btn.setEnabled(False)
            self.validation_label.hide()
            return

        # Basic validation - Gemini API keys start with "AIza" and are ~39 chars
        if len(key) < 30:
            self.validation_label.setText("API key seems too short. Please check you copied the full key.")
            self._update_validation_style("error")
            self.validation_label.show()
            self.save_btn.setEnabled(False)
            return

        if not key.startswith("AIza"):
            self.validation_label.setText("Gemini API keys typically start with 'AIza'. Please verify your key.")
            self._update_validation_style("warning")
            self.validation_label.show()
            # Still allow saving - user might know better
            self.save_btn.setEnabled(True)
            return

        # Looks valid
        self.validation_label.setText("Looks good!")
        self._update_validation_style("success")
        self.validation_label.show()
        self.save_btn.setEnabled(True)

    def _save_and_continue(self):
        """Save the API key and close the dialog."""
        key = self.api_key_input.text().strip()

        if save_api_key(key):
            self.accept()
        else:
            QMessageBox.critical(
                self,
                "Error Saving Key",
                "Failed to save the API key. Please check file permissions and try again."
            )

    def get_api_key(self) -> Optional[str]:
        """Get the entered API key (only valid after dialog accepted)."""
        return self.api_key_input.text().strip()


def get_user_friendly_error(error: Exception) -> str:
    """Convert technical errors to user-friendly messages"""
    error_str = str(error).lower()
    error_type = type(error).__name__

    ERROR_MAPPINGS = {
        "invalid api key": "Your API key isn't working. Please check your GEMINI_API_KEY environment variable.",
        "api key": "There's an issue with your API key. Please verify it's set correctly.",
        "rate limit": "Too many requests. Please wait a minute and try again.",
        "quota": "API quota exceeded. You may need to wait or upgrade your API plan.",
        "network": "Can't reach the server. Please check your internet connection.",
        "connection": "Network connection failed. Check your internet and try again.",
        "timeout": "Request timed out. The server might be busy - please try again.",
        "json": "AI returned unexpected format. Try rephrasing your description or try again.",
        "permission": "Permission denied. Check file permissions and try again.",
        "file not found": "File not found. The image may have been moved or deleted.",
        "no event data": "Couldn't extract event details. Try being more specific (include date, time, title).",
    }

    # Check for matching error patterns
    for pattern, friendly_msg in ERROR_MAPPINGS.items():
        if pattern in error_str:
            return f"{friendly_msg}\n\nTechnical details: {error_type}: {str(error)}"

    # Default message for unknown errors
    return f"Something went wrong.\n\nTechnical details: {error_type}: {str(error)}\n\nPlease try again or contact support if this persists."


SUPPORTED_IMAGE_EXTENSIONS = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".heic",
    ".heif",
    ".tif",
    ".tiff",
    ".bmp",
)

TIME_PATTERNS = [
    re.compile(r"(\d{1,2}:\d{2}\s*(?:am|pm))", re.IGNORECASE),
    re.compile(r"(\d{1,2}\s*(?:am|pm))", re.IGNORECASE),
    re.compile(r"(\d{1,2}:\d{2})", re.IGNORECASE),
]

DATE_PATTERNS = [
    re.compile(r"(next\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))", re.IGNORECASE),
    re.compile(r"(this\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))", re.IGNORECASE),
    re.compile(r"((?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))", re.IGNORECASE),
    re.compile(r"(tomorrow)", re.IGNORECASE),
    re.compile(r"(today)", re.IGNORECASE),
    re.compile(r"(next week)", re.IGNORECASE),
    re.compile(r"(this week)", re.IGNORECASE),
    re.compile(r"(\d{1,2}/\d{1,2})", re.IGNORECASE),
    re.compile(r"(\d{1,2}-\d{1,2})", re.IGNORECASE),
    re.compile(r"((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2})", re.IGNORECASE),
]

DATE_REMOVE_PATTERNS = [
    re.compile(r"\b(?:next|this)\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.IGNORECASE),
    re.compile(r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.IGNORECASE),
    re.compile(r"\b(?:tomorrow|today)\b", re.IGNORECASE),
    re.compile(r"\b(?:next|this)\s+week\b", re.IGNORECASE),
    re.compile(r"\d{1,2}/\d{1,2}", re.IGNORECASE),
    re.compile(r"\d{1,2}-\d{1,2}", re.IGNORECASE),
    re.compile(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}\b", re.IGNORECASE),
]

SHORT_SLASH_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})$", re.IGNORECASE)
SHORT_DASH_DATE = re.compile(r"^(\d{1,2})-(\d{1,2})$", re.IGNORECASE)
MONTH_NAME_DATE = re.compile(r"^(?P<month>(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*)\s+(?P<day>\d{1,2})$", re.IGNORECASE)

PREPOSITION_PATTERN = re.compile(r"\b(?:at|on|in|for|with)\s+", re.IGNORECASE)
WHITESPACE_PATTERN = re.compile(r"\s+", re.IGNORECASE)

DAYS_OF_WEEK = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

MONTH_ABBREVIATIONS = {
    "jan": "Jan",
    "feb": "Feb",
    "mar": "Mar",
    "apr": "Apr",
    "may": "May",
    "jun": "Jun",
    "jul": "Jul",
    "aug": "Aug",
    "sep": "Sep",
    "oct": "Oct",
    "nov": "Nov",
    "dec": "Dec",
}


@dataclass
class ImageAttachmentPayload:
    source_path: Optional[str]
    mime_type: str
    temp_path: Optional[str] = None
    base64_data: Optional[str] = None

    def materialize(self) -> tuple[str, str, str]:
        path = self.temp_path or self.source_path
        if not path:
            raise ValueError("Image attachment is missing a file path")
        if self.base64_data is None:
            with open(path, "rb") as fh:
                self.base64_data = base64.b64encode(fh.read()).decode("utf-8")
        return path, self.mime_type, self.base64_data


def combine_ics_strings(ics_strings: List[str]) -> str:
    """Merge multiple ICS documents while preserving calendar metadata and TZ data."""
    if not ics_strings:
        raise ValueError("No ICS data provided to combine.")

    calendars: List[Calendar] = []
    for index, raw in enumerate(ics_strings):
        if raw is None:
            continue

        data = raw.encode("utf-8") if isinstance(raw, str) else raw
        try:
            calendars.append(Calendar.from_ical(data))
        except Exception as exc:  # pragma: no cover - defensive logging for debugging
            raise ValueError(f"Failed to parse ICS payload at index {index}: {exc}") from exc

    if not calendars:
        raise ValueError("No parseable ICS data provided.")

    merged_calendar = Calendar()

    for calendar in calendars:
        for prop, value in calendar.property_items():
            if merged_calendar.get(prop) is None:
                merged_calendar.add(prop, value)

    # Ensure mandatory headers exist if they were missing from the sources.
    if merged_calendar.get("PRODID") is None:
        merged_calendar.add("PRODID", "-//NL Calendar Creator//EN")
    if merged_calendar.get("VERSION") is None:
        merged_calendar.add("VERSION", "2.0")
    if merged_calendar.get("CALSCALE") is None:
        merged_calendar.add("CALSCALE", "GREGORIAN")

    seen_timezones: set[str] = set()

    for calendar in calendars:
        for component in calendar.subcomponents:
            component_copy = copy.deepcopy(component)

            if component_copy.name == "VTIMEZONE":
                tzid_raw = component_copy.get("TZID")
                tzid = str(tzid_raw) if tzid_raw else f"__anon_tz_{len(seen_timezones)}"
                if tzid in seen_timezones:
                    continue
                seen_timezones.add(tzid)
                merged_calendar.add_component(component_copy)
                continue

            if component_copy.name == "VEVENT":
                component_copy["UID"] = f"{uuid.uuid4()}@nl-calendar"
                merged_calendar.add_component(component_copy)
                continue

            merged_calendar.add_component(component_copy)

    final_bytes = merged_calendar.to_ical()
    final_text = final_bytes.decode("utf-8")
    # Normalise newline usage to CRLF as required by RFC5545.
    final_text = final_text.replace("\r\n", "\n").replace("\n", "\r\n")
    return final_text


class ImageAttachmentArea(QLabel):
    """Custom widget for handling image drag and drop"""
    # Add a signal to notify when images are added/cleared
    images_changed = pyqtSignal(bool)  # True when images added, False when cleared
    DEFAULT_TEXT = "Drop image or\nscreenshot here\nto attach to event"

    @staticmethod
    def _get_base_style() -> str:
        """Generate base style with current theme colors."""
        return f"""
            QLabel {{
                border: 2px dashed {get_color('border_medium')};
                border-radius: {px(BORDER_RADIUS['md'])};
                padding: {px(SPACING_SCALE['md'])};
                background-color: {get_color('background_secondary')};
                color: {get_color('text_tertiary')};
                font-size: {px(TYPOGRAPHY_SCALE['body']['size_px'])};
            }}
            QLabel:hover {{
                border-color: {get_color('accent')};
                background-color: {get_color('background_tertiary')};
            }}
        """

    @staticmethod
    def _get_highlight_style() -> str:
        """Generate highlight style with current theme colors."""
        # Use accent color for highlight with transparency
        accent = get_color('accent')
        return f"""
            QLabel {{
                border: 2px dashed {accent};
                border-radius: {px(BORDER_RADIUS['md'])};
                padding: {px(SPACING_SCALE['md'])};
                background-color: rgba(217, 119, 6, 0.1);
                color: {get_color('text_primary')};
                font-weight: {TYPOGRAPHY_SCALE['body']['weight']};
                font-size: {px(TYPOGRAPHY_SCALE['body']['size_px'])};
                line-height: {TYPOGRAPHY_SCALE['body']['line_height']};
            }}
            QLabel:hover {{
                border-color: {accent};
                background-color: rgba(217, 119, 6, 0.15);
            }}
        """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setMinimumHeight(SPACING_SCALE["xxl"])
        self.image_data: List[ImageAttachmentPayload] = []
        self._temp_paths: set[str] = set()
        self._known_sources: set[str] = set()
        self.setStyleSheet(self._get_base_style())
        self.reset_state()

    def refresh_theme(self):
        """Refresh styles after theme change."""
        if self.image_data:
            self.setStyleSheet(self._get_highlight_style())
        else:
            self.setStyleSheet(self._get_base_style())

    def reset_state(self):
        self._cleanup_temp_files()
        self.setText(self.DEFAULT_TEXT)
        self.setStyleSheet(self._get_base_style())
        self.image_data = []
        self._temp_paths.clear()
        self._known_sources.clear()
        self.images_changed.emit(False)  # Notify that images were cleared

    def _cleanup_temp_files(self):
        for temp_path in list(self._temp_paths):
            try:
                Path(temp_path).unlink(missing_ok=True)
            except Exception as e:
                logger.warning("Failed to delete temp image file '%s': %s", temp_path, e)
            finally:
                self._temp_paths.discard(temp_path)

    def closeEvent(self, event):
        self._cleanup_temp_files()
        super().closeEvent(event)
        
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if all(self._is_supported_image(url.toLocalFile()) for url in urls):
                event.acceptProposedAction()
        elif event.mimeData().hasImage():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent):
        """
        Processes dropped images, prioritizing file URLs over in-memory image data
        to prevent duplicate processing of the same image.
        """
        mime = event.mimeData()
        valid_images: List[ImageAttachmentPayload] = []
        urls_processed = False

        # --- PRIORITIZE FILE URLS ---
        if mime.hasUrls():
            for url in mime.urls():
                file_path = url.toLocalFile()
                if self._is_supported_image(file_path):
                    try:
                        if not os.path.exists(file_path):
                            logger.warning("Dropped file does not exist: %s", file_path)
                            continue

                        canonical_path = str(Path(file_path).resolve())
                        if canonical_path in self._known_sources:
                            continue

                        mime_type = mimetypes.guess_type(file_path)[0] or 'image/jpeg'
                        temp_path = self._copy_to_temp(canonical_path)
                        valid_images.append(
                            ImageAttachmentPayload(
                                source_path=canonical_path,
                                mime_type=mime_type,
                                temp_path=temp_path
                            )
                        )
                        self._temp_paths.add(temp_path)
                        self._known_sources.add(canonical_path)
                        urls_processed = True
                    except Exception as e:
                        logger.error("Error preparing dropped file '%s': %s", file_path, e)

        # --- PROCESS IN-MEMORY IMAGE ONLY IF NO URLs WERE PROCESSED ---
        if not urls_processed and mime.hasImage():
            try:
                from PyQt6.QtGui import QImage, QPixmap
                image_data = mime.imageData()
                pixmap: Optional[QPixmap] = None

                if isinstance(image_data, QImage):
                    pixmap = QPixmap.fromImage(image_data)
                elif isinstance(image_data, QPixmap):
                    pixmap = image_data
                else:
                    # Handle QByteArray/bytes payloads returned on some platforms.
                    raw_bytes: Optional[bytes] = None
                    if isinstance(image_data, QByteArray):
                        raw_bytes = bytes(image_data)
                    elif isinstance(image_data, (bytes, bytearray)):
                        raw_bytes = bytes(image_data)
                    elif hasattr(image_data, "data") and callable(image_data.data):
                        potential = image_data.data()
                        if isinstance(potential, (bytes, bytearray)):
                            raw_bytes = bytes(potential)
                    elif hasattr(image_data, "toImage"):
                        maybe_image = image_data.toImage()
                        if isinstance(maybe_image, QImage) and not maybe_image.isNull():
                            pixmap = QPixmap.fromImage(maybe_image)

                    if pixmap is None and raw_bytes:
                        qimage = QImage.fromData(raw_bytes)
                        if not qimage.isNull():
                            pixmap = QPixmap.fromImage(qimage)

                if pixmap and not pixmap.isNull():
                    buffer = QBuffer()
                    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
                    pixmap.save(buffer, "PNG")
                    bdata = buffer.data()
                    temp_fd, temp_path = tempfile.mkstemp(suffix=".png")
                    with os.fdopen(temp_fd, 'wb') as f:
                        f.write(bytes(bdata))
                    buffer.close()

                    valid_images.append(ImageAttachmentPayload(source_path=temp_path, mime_type="image/png", temp_path=temp_path))
                    self._temp_paths.add(temp_path)
                    self._known_sources.add(temp_path)
            except Exception as e:
                logger.error("Error processing in-memory image: %s", e)

        if valid_images:
            self.image_data.extend(valid_images)
            self.update_preview()
            self.images_changed.emit(True)
            event.acceptProposedAction()
        else:
            event.ignore()

    def update_preview(self):
        if not self.image_data:
            self.reset_state()
            return

        # Update alignment flag usage
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Create a more engaging preview message
        count = len(self.image_data)
        if count == 1:
            preview_text = "1 image ready to process"
        else:
            preview_text = f"{count} images ready to process"

        # Add a helpful secondary message
        secondary_text = "\n\nClick 'Create Event' to process"
        
        # Combine messages and set label
        self.setText(f"{preview_text}{secondary_text}")
        
        # Update styling to make it more noticeable
        self.setStyleSheet(self._get_highlight_style())

    def _is_supported_image(self, file_path: str) -> bool:
        suffix = Path(file_path).suffix.lower()
        return bool(suffix) and suffix in SUPPORTED_IMAGE_EXTENSIONS

    def _copy_to_temp(self, source_path: str) -> str:
        """
        Copy the provided file into a managed temporary location so the original
        may be deleted without breaking later uploads.
        """
        suffix = Path(source_path).suffix or ".img"
        temp_fd, temp_path = tempfile.mkstemp(suffix=suffix)
        try:
            with os.fdopen(temp_fd, "wb") as dest, open(source_path, "rb") as src:
                shutil.copyfileobj(src, dest)
        except Exception:
            try:
                Path(temp_path).unlink(missing_ok=True)
            finally:
                self._temp_paths.discard(temp_path)
            raise
        return temp_path

class NLCalendarCreator(QMainWindow):
    # Define a custom signal
    update_status_signal = pyqtSignal(str)
    # Add new signals for UI updates
    enable_ui_signal = pyqtSignal(bool)
    clear_input_signal = pyqtSignal()
    show_progress_signal = pyqtSignal(bool)
    # Signal to finalize events on the main thread
    finalize_events_signal = pyqtSignal(list)
    # Signal to show image warning dialog from worker threads
    image_warning_signal = pyqtSignal(str, int, object)
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Create Calendar Event")
        self.setMinimumSize(600, 450) # Adjusted minimum size
        self.resize(700, 500) # Default size

        # ThreadPoolExecutor for managed background work
        # This ensures proper cleanup on app exit (unlike daemon threads)
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="calendar_worker")
        self._active_futures: set[Future] = set()
        self._threads_lock = threading.Lock()

        # Lock for thread-safe API client initialization
        self._api_client_lock = threading.Lock()

        # Initialize preview references
        self.preview_event_title = None
        self.preview_date = None  
        self.preview_time = None

        # --- Main Container Widget ---
        # Use a QWidget as the central widget for easier styling control
        main_container = QWidget(self)
        main_container.setObjectName("mainContainer") # For specific styling
        main_container.setStyleSheet(f"""
            #mainContainer {{
                background-color: #F2F2F7; /* Light gray background like the image */
                border-radius: {px(BORDER_RADIUS["md"])};
                /* No border needed here if the window itself is frameless/styled */
            }}
            QLabel {{
                background-color: transparent; /* Ensure labels don't have unwanted backgrounds */
            }}
        """)
        self.setCentralWidget(main_container)

        # --- Overall Layout ---
        # Use a single QVBoxLayout for the main container
        outer_layout = QVBoxLayout(main_container)
        outer_layout.setContentsMargins(
            SPACING_SCALE["lg"],
            SPACING_SCALE["md"],
            SPACING_SCALE["lg"],
            SPACING_SCALE["md"],
        ) # Follow 8pt grid: 32, 24, 32, 24
        outer_layout.setSpacing(SPACING_SCALE["md"]) # 24px spacing between sections

        # --- 1. Top Title/Subtitle Section ---
        title_layout = QVBoxLayout()
        title_layout.setSpacing(SPACING_SCALE["xs"]) # 8px between title and subtitle
        title_layout.setContentsMargins(0, 0, 0, SPACING_SCALE["sm"]) # 16px margin below title section

        title_label = QLabel("Create a Calendar Event")
        title_label.setStyleSheet(f"""
            QLabel {{
                font-size: {px(TYPOGRAPHY_SCALE["title"]["size_px"])}; /* Larger font */
                font-weight: {TYPOGRAPHY_SCALE["title"]["weight"]}; /* Semibold */
                color: {COLORS["text_primary"]};
                qproperty-alignment: 'AlignCenter';
            }}
        """)

        subtitle_label = QLabel("Type freely or drop a photo. We'll do the rest.\nTip: Cmd+Enter to submit, Esc to clear")
        subtitle_label.setStyleSheet(f"""
            QLabel {{
                font-size: {px(TYPOGRAPHY_SCALE["body"]["size_px"])};
                color: {COLORS["text_secondary"]};
                qproperty-alignment: 'AlignCenter';
            }}
        """)

        title_layout.addWidget(title_label)
        title_layout.addWidget(subtitle_label)
        outer_layout.addLayout(title_layout)

        # --- 2. Main Content Area (Horizontal Split) ---
        content_layout = QHBoxLayout()
        content_layout.setSpacing(SPACING_SCALE["lg"]) # 32px spacing between the two columns

        # --- 2a. Left Panel: Event Details ---
        left_panel_layout = QVBoxLayout()
        left_panel_layout.setSpacing(SPACING_SCALE["sm"]) # 16px spacing between elements

        event_details_title = QLabel("Event Details")
        event_details_title.setStyleSheet(f"""
            QLabel {{
                font-size: {px(TYPOGRAPHY_SCALE["headline"]["size_px"])};
                font-weight: {TYPOGRAPHY_SCALE["headline"]["weight"]};
                color: {COLORS["text_primary"]};
            }}
        """)
        left_panel_layout.addWidget(event_details_title)

        # --- Example Input/Detected Area ---
        # Use a QWidget as a styled container
        self.input_container = QWidget()
        self.input_container.setObjectName("exampleInputContainer")
        self._apply_input_container_style()
        example_input_layout = QVBoxLayout(self.input_container)
        example_input_layout.setContentsMargins(
            SPACING_SCALE["sm"],
            SPACING_SCALE["sm"],
            SPACING_SCALE["sm"],
            SPACING_SCALE["sm"],
        ) # 16px margins all around
        example_input_layout.setSpacing(SPACING_SCALE["xs"]) # 8px spacing inside the container

        # Replace QLabel with an actual editable QTextEdit for input
        self.text_input = QTextEdit()
        self.text_input.setPlaceholderText("e.g. Dinner with Mia at Balthasar next Friday 7:30pm") # Keep multiline placeholder
        self.text_input.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.text_input.setAcceptRichText(False) # Explicitly disable rich text input
        self.text_input.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.text_input.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        # Set fixed size policies to prevent resizing behavior
        self.text_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.text_input.setFixedHeight(200) # Increased from 96px for better multi-event descriptions
        self.text_input.setMaximumHeight(200) # Ensure it never grows beyond this
        self.text_input.setMinimumHeight(200) # Ensure it never shrinks below this

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(120)
        self._preview_timer.timeout.connect(self.update_live_preview)

        self._apply_text_input_style()
        
        # Connect text changes to live preview update
        self.text_input.textChanged.connect(self._schedule_preview_update)

        # Add only the text input widget to the layout
        example_input_layout.addWidget(self.text_input)

        left_panel_layout.addWidget(self.input_container)


        # --- Preview Area ---
        preview_title = QLabel("Quick preview (AI may interpret differently)")
        preview_title.setStyleSheet(f"""
            QLabel {{
                font-size: {px(TYPOGRAPHY_SCALE["caption"]["size_px"])};
                color: {COLORS["text_secondary"]};
                margin-top: {px(SPACING_SCALE["xs"])}; /* 8px space above preview */
                font-style: italic;
            }}
        """)
        left_panel_layout.addWidget(preview_title)

        self.preview_container = QWidget()
        self.preview_container.setObjectName("previewContainer")
        self._apply_preview_container_style()
        preview_layout = QVBoxLayout(self.preview_container)
        preview_layout.setContentsMargins(
            SPACING_SCALE["sm"],
            SPACING_SCALE["sm"],
            SPACING_SCALE["sm"],
            SPACING_SCALE["sm"],
        )
        preview_layout.setSpacing(SPACING_SCALE["xs"])
        preview_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Single line preview with all info
        self.preview_event_title = QLabel("Event title • Date • Time")
        self.preview_event_title.setStyleSheet(
            f"color: {COLORS['text_tertiary']}; font-size: {px(TYPOGRAPHY_SCALE['body']['size_px'])}; "
            f"font-weight: {TYPOGRAPHY_SCALE['body']['weight']};"
        )
        self.preview_event_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Remove the separate date and time labels - we'll combine everything into one line
        preview_layout.addWidget(self.preview_event_title)

        left_panel_layout.addWidget(self.preview_container)
        left_panel_layout.addStretch(1) # Push content up

        # --- 2b. Right Panel: Photo Attachments ---
        right_panel_layout = QVBoxLayout()
        right_panel_layout.setSpacing(SPACING_SCALE["sm"]) # 16px spacing between elements

        photo_title = QLabel("Photo Attachments")
        photo_title.setStyleSheet(f"""
            QLabel {{
                font-size: {px(TYPOGRAPHY_SCALE["headline"]["size_px"])};
                font-weight: {TYPOGRAPHY_SCALE["headline"]["weight"]};
                color: {COLORS["text_primary"]};
            }}
        """)
        right_panel_layout.addWidget(photo_title)

        # --- Image Drop Area ---
        # Re-use the existing ImageAttachmentArea, but update styling/text
        self.image_area = ImageAttachmentArea()
        # Make image area take available vertical space
        self.image_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        right_panel_layout.addWidget(self.image_area, 1) # Add stretch factor

        # Add left and right panels to the main content layout
        content_layout.addLayout(left_panel_layout, 1) # Add stretch factor
        content_layout.addLayout(right_panel_layout, 1) # Add stretch factor

        # Add content layout to the outer layout
        outer_layout.addLayout(content_layout, 1) # Make content area expand vertically

        # --- 3. Bottom Buttons (Create Event + Clear) ---
        button_layout = QHBoxLayout()
        button_layout.addStretch(1) # Push buttons to center

        # Settings button (API key configuration)
        self.settings_button = QPushButton()
        self.settings_button.setFixedSize(36, 36)
        self.settings_button.setText("🔑")  # Key emoji - represents API key settings
        self.settings_button.setToolTip("Settings - Change API Key")
        self.settings_button.clicked.connect(self._show_settings)
        self._apply_settings_button_style()
        button_layout.addWidget(self.settings_button)

        button_layout.addSpacing(8)

        # Theme toggle button
        self.theme_toggle = QPushButton()
        self.theme_toggle.setFixedSize(36, 36)
        self.theme_toggle.clicked.connect(self._toggle_theme)
        self._apply_theme_toggle_style()
        button_layout.addWidget(self.theme_toggle)

        button_layout.addSpacing(SPACING_SCALE["sm"])

        # Clear button
        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self._clear_all_inputs)
        self.clear_button.setMinimumHeight(44)
        self.clear_button.setMinimumWidth(100)
        self._apply_clear_button_style()
        button_layout.addWidget(self.clear_button)

        # Add spacing between buttons
        button_layout.addSpacing(SPACING_SCALE["sm"])

        # Create Event button
        self.create_button = QPushButton("Create Event")
        self.create_button.clicked.connect(self.process_event) # Connect signal
        self.create_button.setMinimumHeight(44) # Make button taller
        self.create_button.setMinimumWidth(150) # Give it some width
        self._apply_create_button_style()
        button_layout.addWidget(self.create_button)
        button_layout.addStretch(1) # Push buttons to center
        outer_layout.addLayout(button_layout)

        # --- Initialization of other components (API client, overlay, etc.) ---
        # Keep these as they handle functionality, not the static look
        self.api_client = None
        # Setup overlay (keep as it's for dynamic state)
        self._setup_overlay()

        # Connect signals needed for dynamic behavior (keep these)
        self.update_status_signal.connect(self.update_status) # Status updates if needed
        self.enable_ui_signal.connect(self._enable_ui)
        self.clear_input_signal.connect(self._clear_input) # To clear the input field later
        self.finalize_events_signal.connect(self._finalize_events)
        self.image_warning_signal.connect(self._show_image_warning)
        # self.show_progress_signal.connect(...) # Progress bar removed

        # Defer UI refresh if needed (less critical now with simpler layout)
        # QTimer.singleShot(10, self.refresh_ui)

        # Make the scheduling method invokable from other threads
        QMetaObject.connectSlotsByName(self)

    def _get_create_button_style(self) -> str:
        """Generate create button style with current theme colors."""
        return f"""
            QPushButton {{
                background-color: {get_color('accent')};
                color: white;
                border: none;
                border-radius: {px(BORDER_RADIUS["md"])};
                padding: {px(SPACING_SCALE["sm"])} {px(SPACING_SCALE["md"])};
                font-size: {px(TYPOGRAPHY_SCALE["body"]["size_px"])};
                font-weight: 600;
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

    def _apply_create_button_style(self):
        """Apply current theme style to create button."""
        self.create_button.setStyleSheet(self._get_create_button_style())

    def _get_clear_button_style(self) -> str:
        """Generate clear button style with current theme colors."""
        return f"""
            QPushButton {{
                background-color: {get_color('background_secondary')};
                color: {get_color('text_primary')};
                border: 1px solid {get_color('border_medium')};
                border-radius: {px(BORDER_RADIUS["md"])};
                padding: {px(SPACING_SCALE["xs"])} {px(SPACING_SCALE["sm"])};
                font-size: {px(TYPOGRAPHY_SCALE["body"]["size_px"])};
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: {get_color('border_light')};
                border-color: {get_color('text_tertiary')};
            }}
            QPushButton:pressed {{
                background-color: {get_color('border_medium')};
            }}
        """

    def _apply_clear_button_style(self):
        """Apply current theme style to clear button."""
        self.clear_button.setStyleSheet(self._get_clear_button_style())

    def _get_settings_button_style(self) -> str:
        """Generate settings button style."""
        return f"""
            QPushButton {{
                background-color: {get_color('background_tertiary')};
                border: 1px solid {get_color('border_medium')};
                border-radius: 18px;
                font-size: 18px;
            }}
            QPushButton:hover {{
                background-color: {get_color('background_secondary')};
                border-color: {get_color('accent')};
            }}
            QPushButton:pressed {{
                background-color: {get_color('border_light')};
            }}
        """

    def _apply_settings_button_style(self):
        """Apply current theme style to settings button."""
        self.settings_button.setStyleSheet(self._get_settings_button_style())

    def _show_settings(self):
        """Show settings dialog to change API key."""
        dialog = APIKeySetupDialog(self)
        dialog.setWindowTitle("Settings - API Key")

        # Pre-fill with current key (masked)
        current_key = load_api_key()
        if current_key:
            # Show first 8 chars + masked rest for security
            masked = current_key[:8] + "*" * (len(current_key) - 8)
            dialog.api_key_input.setPlaceholderText(f"Current: {masked}")

        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Reset the API client so it picks up the new key
            with self._api_client_lock:
                self.api_client = None
            QMessageBox.information(
                self,
                "API Key Updated",
                "Your API key has been saved. It will be used for the next request."
            )

    def _get_theme_toggle_style(self) -> str:
        """Generate theme toggle button style."""
        return f"""
            QPushButton {{
                background-color: {get_color('background_tertiary')};
                border: 1px solid {get_color('border_medium')};
                border-radius: 18px;
                font-size: 16px;
            }}
            QPushButton:hover {{
                background-color: {get_color('border_light')};
            }}
        """

    def _apply_theme_toggle_style(self):
        """Apply current theme style to theme toggle."""
        icon = "☀️" if ThemeManager.get_theme() == "dark" else "🌙"
        self.theme_toggle.setText(icon)
        self.theme_toggle.setStyleSheet(self._get_theme_toggle_style())

    def _toggle_theme(self):
        """Toggle between light and dark theme."""
        toggle_theme()
        self._refresh_all_styles()

    def _refresh_all_styles(self):
        """Refresh all widget styles after theme change."""
        # Update main window background
        self.centralWidget().setStyleSheet(f"""
            QWidget {{
                background-color: {get_color('background_secondary')};
            }}
        """)

        # Update input containers
        self._apply_input_container_style()
        self._apply_text_input_style()
        self._apply_preview_container_style()

        # Update buttons
        self._apply_settings_button_style()
        self._apply_theme_toggle_style()
        self._apply_clear_button_style()
        self._apply_create_button_style()

        # Update overlay and processing label
        self._apply_overlay_style()
        self._apply_processing_label_style()

        # Update image area
        self.image_area.refresh_theme()

        # Refresh live preview with current theme colors
        self.update_live_preview()

        # Force repaint
        self.update()

    def _get_input_container_style(self) -> str:
        """Generate input container style with current theme colors."""
        return f"""
            #exampleInputContainer {{
                background-color: {get_color('background_primary')};
                border: 1px solid {get_color('border_light')};
                border-radius: {px(BORDER_RADIUS['md'])};
                padding: 0px;
            }}
        """

    def _apply_input_container_style(self):
        """Apply current theme style to input container."""
        self.input_container.setStyleSheet(self._get_input_container_style())

    def _get_text_input_style(self) -> str:
        """Generate text input style with current theme colors."""
        return f"""
            QTextEdit {{
                color: {get_color('text_primary')};
                background-color: transparent;
                border: none;
                font-size: {px(TYPOGRAPHY_SCALE['body']['size_px'])};
                line-height: {TYPOGRAPHY_SCALE['body']['line_height']};
                padding: {px(SPACING_SCALE['xs'])} 0px;
            }}
            QTextEdit:focus {{
                border: none;
                outline: none;
                background-color: transparent;
            }}
            QScrollBar:vertical {{
                background: {get_color('background_secondary')};
                width: 8px;
                border-radius: {px(4)};
                margin: 2px;
            }}
            QScrollBar::handle:vertical {{
                background: {get_color('border_medium')};
                border-radius: {px(4)};
                min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {get_color('text_tertiary')};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                border: none;
                background: none;
            }}
        """

    def _apply_text_input_style(self):
        """Apply current theme style to text input."""
        self.text_input.setStyleSheet(self._get_text_input_style())

    def _get_preview_container_style(self) -> str:
        """Generate preview container style with current theme colors."""
        return f"""
            #previewContainer {{
                background-color: {get_color('background_primary')};
                border: 1px solid {get_color('border_light')};
                border-radius: {px(BORDER_RADIUS['lg'])};
            }}
        """

    def _apply_preview_container_style(self):
        """Apply current theme style to preview container."""
        self.preview_container.setStyleSheet(self._get_preview_container_style())

    def _get_overlay_style(self) -> str:
        """Generate overlay style with current theme colors."""
        if ThemeManager.get_theme() == "light":
            bg = "rgba(250, 250, 249, 0.9)"
        else:
            bg = "rgba(23, 23, 23, 0.9)"
        return f"""
            #overlayWidget {{
                background-color: {bg};
                border-radius: {px(BORDER_RADIUS["md"])};
            }}
        """

    def _apply_overlay_style(self):
        """Apply current theme style to overlay."""
        self.overlay.setStyleSheet(self._get_overlay_style())

    def _get_processing_label_style(self) -> str:
        """Generate processing label style with current theme colors."""
        if ThemeManager.get_theme() == "light":
            bg = "rgba(255, 255, 255, 0.9)"
        else:
            bg = "rgba(31, 31, 31, 0.9)"
        return f"""
            QLabel {{
                color: {get_color('text_primary')};
                font-size: {px(TYPOGRAPHY_SCALE["caption"]["size_px"])};
                font-weight: {TYPOGRAPHY_SCALE["caption"]["weight"]};
                padding: {px(SPACING_SCALE["md"])} {px(SPACING_SCALE["lg"])};
                background-color: {bg};
                border-radius: {px(BORDER_RADIUS["md"])};
                border: 1px solid {get_color('border_light')};
            }}
        """

    def _apply_processing_label_style(self):
        """Apply current theme style to processing label."""
        self.processing_label.setStyleSheet(self._get_processing_label_style())

    def _setup_overlay(self):
        """Sets up the overlay widget for processing indication."""
        # Keep the overlay logic, but hide it initially
        self.overlay = QWidget(self.centralWidget()) # Parent is the central widget
        self.overlay.setObjectName("overlayWidget")
        self._apply_overlay_style()
        self.overlay.hide()

        overlay_layout = QVBoxLayout(self.overlay)
        overlay_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        overlay_layout.setSpacing(15)

        # Simplified processing indicator
        self.processing_label = QLabel("Processing...") # Simple text
        self._apply_processing_label_style()
        self.processing_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        overlay_layout.addWidget(self.processing_label)

        # Optional: Add a QProgressIndicator or similar if needed instead of the pulsing dots
        # self.loading_indicator = QProgressIndicator(self.overlay) # Example
        # overlay_layout.addWidget(self.loading_indicator, 0, Qt.AlignmentFlag.AlignCenter)

    def resizeEvent(self, event):
        """Handle resize events to keep overlay properly sized."""
        super().resizeEvent(event)
        # Ensure overlay covers the central widget
        self.overlay.resize(self.centralWidget().size())

    def keyPressEvent(self, event: QKeyEvent):
        """Handle keyboard shortcuts"""
        # Cmd+Enter (Mac) or Ctrl+Enter (Windows/Linux) to submit
        if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier or \
               event.modifiers() & Qt.KeyboardModifier.MetaModifier:
                if self.create_button.isEnabled():
                    self.process_event()
                event.accept()
                return

        # Esc to clear input (no confirmation - just clear!)
        if event.key() == Qt.Key.Key_Escape:
            self.text_input.clear()
            self.image_area.reset_state()
            event.accept()
            return

        # Pass other events to parent
        super().keyPressEvent(event)

    # Add placeholder methods required by signals if they were removed/changed
    def update_status(self, message: str):
         logger.debug("Status Update: %s", message)
         if not self.create_button.isEnabled():
             self.processing_label.setText(message)

    def _enable_ui(self, enabled: bool):
         # Enable/disable interactive elements
         logger.debug("_enable_ui called with enabled=%s", enabled)
         self.text_input.setEnabled(enabled) # Enable/disable actual text input
         self.image_area.setEnabled(enabled)
         self.create_button.setEnabled(enabled)
         logger.debug("Widgets enabled state set to %s", enabled)

         if enabled:
             logger.debug("Attempting to hide overlay...")
             self.overlay.hide()
             logger.debug("Overlay hidden. Is visible: %s", self.overlay.isVisible())
         else:
             logger.debug("Attempting to show overlay...")
             self.processing_label.setText("Processing...") # Reset overlay text
             self.overlay.raise_() # Ensure overlay is on top
             self.overlay.show()
             logger.debug("Overlay shown. Is visible: %s", self.overlay.isVisible())

    def _clear_input(self):
         # Clear the actual input method
         self.text_input.clear()
         # This will trigger the textChanged signal and reset the preview via update_live_preview()

    def _clear_all_inputs(self):
         """Clear all input fields (text and images)"""
         self.text_input.clear()
         self.image_area.reset_state()

    def process_event(self):
        """Process the natural language input and create calendar event"""
        # Thread-safe API client initialization on first use
        with self._api_client_lock:
            if not self.api_client:
                api_key = load_api_key()
                if not api_key:
                    # Show setup dialog
                    dialog = APIKeySetupDialog(self)
                    if dialog.exec() != QDialog.DialogCode.Accepted:
                        return  # User cancelled
                    api_key = load_api_key()  # Reload after setup
                    if not api_key:
                        QMessageBox.critical(
                            self,
                            "API Key Error",
                            "Failed to load API key. Please try again."
                        )
                        return
                try:
                    self.api_client = CalendarAPIClient(api_key=api_key)
                except Exception as e:
                    QMessageBox.critical(
                        self,
                        "API Client Error",
                        f"Failed to initialize the API client: {str(e)}"
                    )
                    return

        # Get text from the proper QTextEdit input
        event_description = self.text_input.toPlainText().strip()
        has_images = bool(self.image_area.image_data)

        # Case 1: No text AND no images
        if not event_description and not has_images:
            QMessageBox.warning(
                self,
                "Missing Input",
                "Please either:\n" +
                "• Enter an event description, or\n" +
                "• Attach images, or\n" +
                "• Both"
            )
            self.text_input.setFocus()
            return

        # Case 2: Text-only validation - check for event-like content
        if event_description and not has_images:
            text_lower = event_description.lower()

            # Check for date/time indicators
            date_indicators = ["today", "tomorrow", "monday", "tuesday", "wednesday", "thursday",
                             "friday", "saturday", "sunday", "next", "this", "week", "january",
                             "february", "march", "april", "may", "june", "july", "august",
                             "september", "october", "november", "december", "/", "-"]
            time_indicators = ["am", "pm", ":", "o'clock", "morning", "afternoon", "evening", "night"]
            event_indicators = ["meeting", "appointment", "lunch", "dinner", "call", "conference",
                              "event", "party", "class", "workshop", "session"]

            has_date = any(indicator in text_lower for indicator in date_indicators)
            has_time = any(indicator in text_lower for indicator in time_indicators)
            has_event_word = any(indicator in text_lower for indicator in event_indicators)

            # Warn if it doesn't look like an event description
            if not (has_date or has_time or has_event_word):
                reply = QMessageBox.question(
                    self,
                    "Doesn't Look Like An Event",
                    "Your text doesn't seem to include date, time, or event keywords.\n\n"
                    "Tip: Try including details like:\n"
                    "• When: 'tomorrow', 'Friday', 'Jan 15'\n"
                    "• Time: '3pm', '14:30', 'morning'\n"
                    "• What: 'meeting', 'lunch', 'appointment'\n\n"
                    "Continue anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.No:
                    return
        
        # At this point, we have either text, images, or both - proceed with processing
        self.enable_ui_signal.emit(False)

        # Acquire lock before accessing shared image data to prevent race conditions
        with self._threads_lock:
            image_payloads = [copy.deepcopy(attachment) for attachment in self.image_area.image_data]

            # Submit to executor instead of creating raw threads
            # This ensures proper cleanup on app exit
            future = self._executor.submit(
                self._create_event_thread,
                event_description,
                image_payloads
            )
            self._active_futures.add(future)

            # Add callback to clean up the future when done
            future.add_done_callback(self._on_future_done)

    def _create_event_thread(self, event_description: str, image_data: List[ImageAttachmentPayload]):
        try:
            # Get API client - should be initialized in process_event() before this thread starts
            if not self.api_client:
                error_msg = "API client not initialized. Please restart the application."
                self.update_status_signal.emit(error_msg)
                self.enable_ui_signal.emit(True)
                return

            prepared_images: List[tuple[str, str, str]] = []
            failed_images = 0
            for attachment in image_data:
                try:
                    prepared_images.append(attachment.materialize())
                except Exception as exc:
                    logger.warning("Skipping image attachment due to error: %s", exc)
                    failed_images += 1

            # Warn user about failed images and wait for decision
            USER_DECISION_TIMEOUT = 30  # seconds - reasonable timeout for user interaction
            if failed_images > 0:
                warning_msg = f"{failed_images} image(s) couldn't be processed. Continue with remaining images?"
                decision_queue: "queue.Queue[bool]" = queue.Queue(maxsize=1)
                self.image_warning_signal.emit(warning_msg, failed_images, decision_queue)
                try:
                    should_continue = decision_queue.get(timeout=USER_DECISION_TIMEOUT)
                except queue.Empty:
                    # Timeout - default to safe behavior (cancel) rather than raising
                    logger.warning("User did not respond to image warning dialog within %d seconds", USER_DECISION_TIMEOUT)
                    self.update_status_signal.emit("Event creation cancelled (dialog timeout)")
                    return
                if not should_continue:
                    self.update_status_signal.emit("Event creation cancelled")
                    return

            self.update_status_signal.emit("Requesting event details from AI...")
            events: Optional[List[Dict]] = self.api_client.get_event_data(
                event_description,
                prepared_images,
                lambda message: self.update_status_signal.emit(message)
            )

            if not events:
                raise Exception("API returned no event data or failed after retries")

            logger.debug("Received %s event(s) from API.", len(events))

            # Finalize events on the main thread immediately (no confirmation dialog)
            self.finalize_events_signal.emit(events)

        except Exception as e:
            logger.exception("Error in _create_event_thread")
            friendly_error = get_user_friendly_error(e)
            self.update_status_signal.emit("Error occurred")
            QTimer.singleShot(0, lambda: self._show_error(friendly_error))
        finally:
            with self._threads_lock:
                self._active_threads.discard(threading.current_thread())
            self.enable_ui_signal.emit(True)

    def _finalize_events(self, events: List[Dict]):
        """Build ICS files and open calendar (runs on main thread)"""
        try:
            self.enable_ui_signal.emit(False)
            self.update_status_signal.emit("Creating calendar events...")

            # Build ICS strings from the edited events
            ics_strings, warnings = build_ics_from_events(events)

            if not ics_strings:
                raise Exception("Failed to create ICS files from event data")

            # Show warnings if any
            if warnings:
                warning_text = "\n\n".join(warnings)
                QMessageBox.warning(
                    self,
                    "Event Creation Warnings",
                    f"Events created with warnings:\n\n{warning_text}",
                    QMessageBox.StandardButton.Ok
                )

            event_count = len(ics_strings)
            event_text = "event" if event_count == 1 else "events"
            logger.debug("Generated %s ICS string(s).", event_count)

            # Merge all ICS payloads while preserving metadata/timezones.
            final_ics_content = combine_ics_strings(ics_strings)

            logger.debug("Final combined ICS content (first 500 chars):\n------\n%s\n------", final_ics_content[:500])

            # --- Create, open, and clean up the single temp file ---
            temp_path: Optional[str] = None # Explicitly define type
            successful_import_initiated = False
            command: Optional[List[str]] = None # Explicitly define type
            try:
                # 1. create the file with delete=False, using binary mode
                with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix=".ics") as tf:
                    tf.write(final_ics_content.encode('utf-8')) # Encode to bytes
                    temp_path = tf.name
                
                self.update_status_signal.emit(f"Opening {event_count} {event_text} in calendar...")

                # 2. Ask Launch-Services (or equivalent) to open it
                if sys.platform == "darwin":
                    # Use Popen, don't wait, don't capture output, let default handler open it
                    logger.debug("Using Popen for: open %s", temp_path)
                    subprocess.Popen(["open", temp_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    successful_import_initiated = True
                elif sys.platform.startswith("win"):
                    logger.debug("Using os.startfile for %s", temp_path)
                    os.startfile(temp_path) # type: ignore
                    logger.debug("os.startfile finished.")  # Happens immediately
                    successful_import_initiated = True
                else: # Assume Linux/other POSIX
                    # Keep xdg-open but use Popen for consistency
                    command = ["xdg-open", temp_path]
                    logger.debug("Using Popen for: %s", ' '.join(command))
                    subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    successful_import_initiated = True

                # 3. Schedule deletion on the GUI thread much later
                if temp_path and successful_import_initiated:
                    logger.debug("Scheduling deletion of %s in 60 seconds via main thread.", temp_path)
                    # Use invokeMethod to call the scheduling method on the main thread
                    QMetaObject.invokeMethod(
                        self,
                        "_schedule_temp_file_deletion",
                        Qt.ConnectionType.QueuedConnection,
                        Q_ARG(str, temp_path) # Wrap argument with Q_ARG
                    )

            except FileNotFoundError:
                self.update_status_signal.emit("Error: Could not create temporary event file.")
                logger.error("Failed to create temp event file.")
                # Ensure temp_path is cleaned up if creation failed mid-way (though unlikely with NamedTemporaryFile context)
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.unlink(temp_path)
                    except OSError:
                        pass  # Ignore cleanup error if creation failed
            except OSError as os_err:
                # Error could be from os.startfile or Popen if command not found
                self.update_status_signal.emit(f"Error: Could not open event file: {os_err}")
                logger.error("Error initiating open for %s: %s", temp_path, os_err)
                # Clean up if opening failed
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.unlink(temp_path)
                    except OSError:
                        pass
            # Remove CalledProcessError handler as Popen doesn't raise it directly here
            # except subprocess.CalledProcessError as proc_err: ...
            except Exception as e:
                self.update_status_signal.emit(f"Unexpected error processing event file: {e}")
                logger.exception("Unexpected error with temp file %s", temp_path)
                # Clean up on generic error
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.unlink(temp_path)
                    except OSError:
                        pass
            finally:
                # File cleanup is now handled by the main thread via the scheduled timer
                pass # No immediate cleanup needed here anymore

            # Final status update
            if successful_import_initiated:
                success_msg = f"Successfully created {event_count} {event_text}!"
                self.update_status_signal.emit(success_msg)
                QTimer.singleShot(0, lambda: self._show_success(success_msg, event_count))
                # DON'T auto-clear input - let user decide
                if hasattr(self.image_area, 'reset_state'):
                    QTimer.singleShot(0, self.image_area.reset_state)
            # Error status is handled by emitted signals within the try/except blocks

        except Exception as e:
            logger.exception("Error in _finalize_events")
            friendly_error = get_user_friendly_error(e)
            self.update_status_signal.emit("Error occurred")
            self._show_error(friendly_error)
        finally:
            self.enable_ui_signal.emit(True)

    def _show_image_warning(self, message: str, failed_count: int, decision_queue: queue.Queue):
        """Show warning about failed image uploads and communicate decision back to worker thread."""
        reply = QMessageBox.warning(
            self,
            "Image Upload Warning",
            message,
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel
        )
        decision_queue.put(reply == QMessageBox.StandardButton.Ok)

    def _show_success(self, message: str, event_count: int):
        """Show success message after events created"""
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Information)
        msg_box.setWindowTitle("Success")
        msg_box.setText(message)
        msg_box.setInformativeText(f"Check your calendar application to see the {event_count} event(s).")
        msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg_box.setAccessibleName("Success Dialog")
        msg_box.setAccessibleDescription(f"{message}. Check your calendar application to see the {event_count} event(s).")
        msg_box.setStyleSheet(f"""
            QMessageBox {{
                background-color: {get_color("background_primary")};
            }}
            QLabel {{
                color: {get_color("text_primary")};
                font-size: {px(TYPOGRAPHY_SCALE["body"]["size_px"])};
            }}
            QPushButton {{
                background-color: {get_color("accent")};
                color: white;
                border-radius: {px(BORDER_RADIUS["sm"])};
                padding: {px(SPACING_SCALE["xs"])} {px(SPACING_SCALE["md"])};
                min-width: 80px;
            }}
            QPushButton:hover {{
                background-color: {get_color("accent_hover")};
            }}
        """)
        msg_box.exec()

    @pyqtSlot(str) # Decorate as a slot invokable via invokeMethod
    def _schedule_temp_file_deletion(self, file_path: str):
        """Schedules the deletion of the temp file from the main GUI thread."""
        logger.debug("Scheduling deletion for %s", file_path)
        # This QTimer.singleShot is now called safely from the main thread
        QTimer.singleShot(60_000, lambda p=file_path: self._delete_temp_file(p))

    def _delete_temp_file(self, file_path: str):
        """Actually deletes the temp file, handling potential errors."""
        try:
            logger.debug("Attempting to delete %s", file_path)
            Path(file_path).unlink(missing_ok=True)
            logger.debug("Successfully deleted %s", file_path)
        except OSError as e:
            logger.warning("Main thread failed to delete temp file %s: %s", file_path, e)
        except Exception as e:
            logger.warning("Unexpected error deleting temp file %s from main thread: %s", file_path, e)

    def _show_error(self, message: str):
        """Show error message box (called from main thread)"""
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Critical)
        msg_box.setWindowTitle("Error")
        msg_box.setText(message)
        msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg_box.setAccessibleName("Error Dialog")
        msg_box.setAccessibleDescription(f"An error occurred: {message}")
        msg_box.exec()

    def _on_future_done(self, future: Future):
        """Callback when a background task completes - cleans up tracking."""
        with self._threads_lock:
            self._active_futures.discard(future)

        # Log any unhandled exceptions from the future
        try:
            exc = future.exception()
            if exc is not None:
                logger.error("Background task failed with exception: %s", exc)
        except Exception:
            pass  # Future was cancelled or already retrieved

    def closeEvent(self, event: QCloseEvent):
        """Handle window close - gracefully shutdown the executor."""
        logger.debug("Application closing, shutting down executor...")

        # Shutdown the executor and wait for pending tasks
        # Use wait=True to allow tasks to complete, but with a timeout
        self._executor.shutdown(wait=False, cancel_futures=True)

        # Stop any pending timers
        if hasattr(self, '_preview_timer') and self._preview_timer.isActive():
            self._preview_timer.stop()

        super().closeEvent(event)

    def _schedule_preview_update(self):
        if self._preview_timer.isActive():
            self._preview_timer.stop()
        self._preview_timer.start()

    def update_live_preview(self):
        """Update preview in real-time as user types"""
        text = self.text_input.toPlainText().strip()

        if not text:
            # Reset to placeholder state
            self.preview_event_title.setText("Event title • Date • Time")
            self.preview_event_title.setStyleSheet(
                f"color: {COLORS['text_tertiary']}; font-size: {px(TYPOGRAPHY_SCALE['body']['size_px'])}; "
                f"font-weight: {TYPOGRAPHY_SCALE['body']['weight']};"
            )
            return

        # Parse the text and extract information
        parsed_info = self.parse_event_text(text)
        
        # Build single line preview
        preview_parts = []
        
        # Add title
        if parsed_info['title']:
            preview_parts.append(parsed_info['title'])
        else:
            # Extract first few words as potential title
            words = text.split()[:4]
            potential_title = ' '.join(words) + ('...' if len(text.split()) > 4 else '')
            preview_parts.append(potential_title)
        
        # Add date
        if parsed_info['date']:
            preview_parts.append(parsed_info['date'])
        else:
            preview_parts.append("Date")
            
        # Add time
        if parsed_info['time']:
            preview_parts.append(parsed_info['time'])
        else:
            preview_parts.append("Time")
        
        # Combine with bullet separator
        preview_text = " • ".join(preview_parts)
        
        # Update the single preview label
        self.preview_event_title.setText(preview_text)
        
        # Style based on whether we have real content or placeholders
        has_real_content = parsed_info['title'] or parsed_info['date'] or parsed_info['time']
        if has_real_content:
            self.preview_event_title.setStyleSheet(
                f"color: {COLORS['text_primary']}; font-size: {px(TYPOGRAPHY_SCALE['body']['size_px'])}; "
                f"font-weight: {TYPOGRAPHY_SCALE['body']['weight']};"
            )
        else:
            self.preview_event_title.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: {px(TYPOGRAPHY_SCALE['body']['size_px'])}; "
                f"font-weight: {TYPOGRAPHY_SCALE['body']['weight']};"
            )

    def parse_event_text(self, text: str) -> Dict[str, Optional[str]]:
        """Parse natural language text to extract event information"""
        result = {
            'title': None,
            'date': None,
            'time': None,
            'location': None
        }
        
        text_lower = text.lower()

        for pattern in TIME_PATTERNS:
            match = pattern.search(text_lower)
            if match:
                result['time'] = match.group(1).strip()
                break

        for pattern in DATE_PATTERNS:
            match = pattern.search(text_lower)
            if match:
                date_str = match.group(1).strip()
                result['date'] = self.format_date_display(date_str)
                break
        
        # Extract potential title by removing date/time/common location words
        title_text = text
        if result['time']:
            title_text = re.sub(re.escape(result['time']), '', title_text, flags=re.IGNORECASE).strip()

        # Remove common date expressions
        for pattern in DATE_REMOVE_PATTERNS:
            title_text = pattern.sub(' ', title_text)

        title_text = PREPOSITION_PATTERN.sub(' ', title_text)
        title_text = WHITESPACE_PATTERN.sub(' ', title_text).strip()

        if title_text and len(title_text) > 2:
            result['title'] = title_text

        return result

    def format_date_display(self, date_str: str) -> str:
        """Format date string for display in preview"""
        try:
            now = datetime.now()
            date_str_lower = date_str.lower().strip()
            
            # Handle relative dates
            if date_str_lower == 'today':
                return now.strftime('%b %d')
            elif date_str_lower == 'tomorrow':
                tomorrow = now + timedelta(days=1)
                return tomorrow.strftime('%b %d')
            elif 'next week' in date_str_lower:
                next_week = now + timedelta(weeks=1)
                return next_week.strftime('%b %d')
            elif 'this week' in date_str_lower:
                return now.strftime('%b %d')
            
            # Handle day names
            for i, day in enumerate(DAYS_OF_WEEK):
                if day in date_str_lower:
                    # Find next occurrence of this day
                    today_weekday = now.weekday()
                    target_weekday = i
                    days_ahead = target_weekday - today_weekday
                    
                    if 'next' in date_str_lower:
                        days_ahead += 7
                    elif days_ahead <= 0:  # This week but day has passed, assume next week
                        days_ahead += 7
                        
                    target_date = now + timedelta(days=days_ahead)
                    return target_date.strftime('%b %d')

            slash_match = SHORT_SLASH_DATE.match(date_str_lower)
            if slash_match:
                month, day = map(int, slash_match.groups())
                try:
                    candidate = datetime(now.year, month, day)
                    return candidate.strftime('%b %d')
                except ValueError:
                    pass

            dash_match = SHORT_DASH_DATE.match(date_str_lower)
            if dash_match:
                month, day = map(int, dash_match.groups())
                try:
                    candidate = datetime(now.year, month, day)
                    return candidate.strftime('%b %d')
                except ValueError:
                    pass

            month_match = MONTH_NAME_DATE.match(date_str_lower)
            if month_match:
                month_key = month_match.group('month')[:3].lower()
                day = int(month_match.group('day'))
                month_abbrev = MONTH_ABBREVIATIONS.get(month_key, month_key.title())
                return f"{month_abbrev} {day:02d}"
            
            # Try to parse other date formats
            try:
                parsed_date = dateutil.parser.parse(date_str, fuzzy=True, default=now)
                return parsed_date.strftime('%b %d')
            except (ValueError, TypeError):
                pass
                
        except Exception:
            pass
        
        return date_str.title()  # Return as-is but capitalize


def get_resource_path(filename: str) -> str:
    """Get absolute path to resource, works for dev and bundled app."""
    if getattr(sys, 'frozen', False):
        # Running as bundled executable
        base_path = Path(sys._MEIPASS)
    else:
        # Running in development
        base_path = Path(__file__).parent
    return str(base_path / filename)


if __name__ == '__main__':
    app = QApplication(sys.argv)

    # Set the application-wide icon
    icon_path = get_resource_path("calendar-icon.png")
    if Path(icon_path).exists():
        app.setWindowIcon(QIcon(icon_path))
    else:
        # Fallback to old icon if new one doesn't exist yet
        fallback_path = get_resource_path("calendar-svg-simple.png")
        if Path(fallback_path).exists():
            app.setWindowIcon(QIcon(fallback_path))

    # Load API key from .env on startup
    api_key = load_api_key()

    # If no API key, show setup dialog before main window
    if not api_key:
        setup_dialog = APIKeySetupDialog()
        if setup_dialog.exec() != QDialog.DialogCode.Accepted:
            sys.exit(0)  # User chose to quit

    window = NLCalendarCreator()
    window.show()

    # Start the main event loop
    sys.exit(app.exec())
