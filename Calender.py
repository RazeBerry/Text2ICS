import sys
import os
import logging
from datetime import datetime, timedelta
import copy
from dataclasses import dataclass
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                           QTextEdit, QPushButton, QLabel, QMessageBox,
                           QHBoxLayout, QSizePolicy)
from PyQt6.QtGui import QIcon, QDragEnterEvent, QDropEvent
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QMetaObject, QBuffer, pyqtSlot, Q_ARG, QByteArray
from typing import Optional, List, Dict
import threading
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

from api_client import CalendarAPIClient


logger = logging.getLogger(__name__)


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

# Apple Design System - Semantic Colors
COLORS = {
    "text_primary": "#000000",
    "text_secondary": "#8A8A8E", 
    "text_tertiary": "#C7C7CC",
    "text_placeholder": "#C7C7CC",
    "background_primary": "#FFFFFF",
    "background_secondary": "#F2F2F7",
    "background_tertiary": "#FFFFFF",
    "border_light": "#E5E5EA",
    "border_medium": "#D1D1D6",
    "accent_blue": "#007AFF",
    "accent_blue_hover": "#0056CC",
    "accent_blue_pressed": "#004499",
    "accent_blue_disabled": "#B0B0B0",
    "success_green": "#30D158",
    "warning_orange": "#FF9F0A",
    "error_red": "#FF3B30"
}

# Design tokens
BORDER_RADIUS = {
    "sm": 8,
    "md": 12,
    "lg": 16,
}

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
    
    BASE_STYLE = f"""
        QLabel {{
            border: 2px dashed {COLORS['border_medium']};
            border-radius: {px(BORDER_RADIUS['md'])};
            padding: {px(SPACING_SCALE['md'])};
            background-color: {COLORS['background_secondary']};
            color: {COLORS['text_tertiary']};
            font-size: {px(TYPOGRAPHY_SCALE['body']['size_px'])};
        }}
        QLabel:hover {{
            border-color: {COLORS['accent_blue']};
            background-color: {COLORS['background_tertiary']};
        }}
    """

    HIGHLIGHT_STYLE = f"""
        QLabel {{
            border: 2px dashed {COLORS['accent_blue']};
            border-radius: {px(BORDER_RADIUS['md'])};
            padding: {px(SPACING_SCALE['md'])};
            background-color: rgba(0, 122, 255, 0.1);
            color: {COLORS['text_primary']};
            font-weight: {TYPOGRAPHY_SCALE['body']['weight']};
            font-size: {px(TYPOGRAPHY_SCALE['body']['size_px'])};
            line-height: {TYPOGRAPHY_SCALE['body']['line_height']};
        }}
        QLabel:hover {{
            border-color: {COLORS['accent_blue']};
            background-color: rgba(0, 122, 255, 0.15);
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
        self.setStyleSheet(self.BASE_STYLE)
        self.reset_state()

    def reset_state(self):
        self._cleanup_temp_files()
        self.setText(self.DEFAULT_TEXT)
        self.setStyleSheet(self.BASE_STYLE)
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
            preview_text = "✨ 1 image ready to process!"
        else:
            preview_text = f"🎉 {count} images ready to go!"
            
        # Add a helpful secondary message
        secondary_text = "\n\nClick 'Create Event' to process"
        
        # Combine messages and set label
        self.setText(f"{preview_text}{secondary_text}")
        
        # Update styling to make it more noticeable
        self.setStyleSheet(self.HIGHLIGHT_STYLE)

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
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Create Calendar Event")
        self.setMinimumSize(600, 450) # Adjusted minimum size
        self.resize(700, 500) # Default size

        # Track background threads so we can manage their lifecycle.
        self._active_threads: set[threading.Thread] = set()
        self._threads_lock = threading.Lock()

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

        subtitle_label = QLabel("Type freely or drop a photo. We'll do the rest.")
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
        example_input_container = QWidget()
        example_input_container.setObjectName("exampleInputContainer")
        example_input_container.setStyleSheet(f"""
            #exampleInputContainer {{
                background-color: {COLORS["background_primary"]};
                border: 1px solid {COLORS["border_light"]};
                border-radius: {px(BORDER_RADIUS["md"])};
                padding: 0px;
            }}
        """)
        example_input_layout = QVBoxLayout(example_input_container)
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
        self.text_input.setFixedHeight(96) # Fixed height in pixels instead of calculation
        self.text_input.setMaximumHeight(96) # Ensure it never grows beyond this
        self.text_input.setMinimumHeight(96) # Ensure it never shrinks below this

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(120)
        self._preview_timer.timeout.connect(self.update_live_preview)

        self.text_input.setStyleSheet(f"""
            QTextEdit {{
                color: {COLORS["text_primary"]};
                background-color: transparent;
                border: none;
                font-size: {px(TYPOGRAPHY_SCALE["body"]["size_px"])};
                line-height: {TYPOGRAPHY_SCALE["body"]["line_height"]};
                padding: {px(SPACING_SCALE["xs"])} 0px;
            }}
            QTextEdit:focus {{
                border: none;
                outline: none;
                background-color: transparent;
            }}
            QScrollBar:vertical {{
                background: {COLORS["background_secondary"]};
                width: 8px;
                border-radius: {px(4)};
                margin: 2px;
            }}
            QScrollBar::handle:vertical {{
                background: {COLORS["border_medium"]};
                border-radius: {px(4)};
                min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {COLORS["text_tertiary"]};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                border: none;
                background: none;
            }}
        """)
        
        # Connect text changes to live preview update
        self.text_input.textChanged.connect(self._schedule_preview_update)

        # Add only the text input widget to the layout
        example_input_layout.addWidget(self.text_input)

        left_panel_layout.addWidget(example_input_container)


        # --- Preview Area ---
        preview_title = QLabel("This is what we'll create in your calendar")
        preview_title.setStyleSheet(f"""
            QLabel {{
                font-size: {px(TYPOGRAPHY_SCALE["caption"]["size_px"])};
                color: {COLORS["text_secondary"]};
                margin-top: {px(SPACING_SCALE["xs"])}; /* 8px space above preview */
            }}
        """)
        left_panel_layout.addWidget(preview_title)

        preview_container = QWidget()
        preview_container.setObjectName("previewContainer")
        preview_container.setStyleSheet(f"""
             #previewContainer {{
                 background-color: {COLORS["background_primary"]};
                 border: 1px solid {COLORS["border_light"]};
                 border-radius: {px(BORDER_RADIUS["lg"])};
             }}
         """)
        preview_layout = QVBoxLayout(preview_container)
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

        left_panel_layout.addWidget(preview_container)
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

        # --- 3. Bottom Create Button ---
        button_layout = QHBoxLayout()
        button_layout.addStretch(1) # Push button to the right/center
        self.create_button = QPushButton("Create Event")
        self.create_button.clicked.connect(self.process_event) # Connect signal
        self.create_button.setMinimumHeight(44) # Make button taller
        self.create_button.setMinimumWidth(150) # Give it some width
        self.create_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['accent_blue']};
                color: white;
                border: none;
                border-radius: {px(BORDER_RADIUS["md"])}; 
                padding: {px(SPACING_SCALE["md"])} {px(SPACING_SCALE["xl"])};
                font-size: {px(TYPOGRAPHY_SCALE["body"]["size_px"])}; 
                font-weight: 600; /* Semi-bold for better accessibility */
            }}
            QPushButton:hover {{
                background-color: {COLORS['accent_blue_hover']};
            }}
            QPushButton:pressed {{
                background-color: {COLORS['accent_blue_pressed']};
            }}
            QPushButton:disabled {{
                background-color: {COLORS['accent_blue_disabled']};
                color: {COLORS['text_tertiary']};
            }}
        """)
        button_layout.addWidget(self.create_button)
        button_layout.addStretch(1) # Push button to the left/center
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
        # self.show_progress_signal.connect(...) # Progress bar removed

        # Defer UI refresh if needed (less critical now with simpler layout)
        # QTimer.singleShot(10, self.refresh_ui)

        # Make the scheduling method invokable from other threads
        QMetaObject.connectSlotsByName(self)

    def _setup_overlay(self):
        """Sets up the overlay widget for processing indication."""
        # Keep the overlay logic, but hide it initially
        self.overlay = QWidget(self.centralWidget()) # Parent is the central widget
        self.overlay.setObjectName("overlayWidget")
        self.overlay.setStyleSheet(f"""
            #overlayWidget {{
                background-color: rgba(242, 242, 247, 0.85); /* Semi-transparent background */
                border-radius: {px(BORDER_RADIUS["md"])}; /* Match parent container */
            }}
        """)
        self.overlay.hide()

        overlay_layout = QVBoxLayout(self.overlay)
        overlay_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        overlay_layout.setSpacing(15)

        # Simplified processing indicator
        self.processing_label = QLabel("Processing...") # Simple text
        self.processing_label.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['text_primary']};
                font-size: {px(TYPOGRAPHY_SCALE["caption"]["size_px"])};
                font-weight: {TYPOGRAPHY_SCALE["caption"]["weight"]};
                padding: {px(SPACING_SCALE["md"])} {px(SPACING_SCALE["lg"])};
                background-color: rgba(255, 255, 255, 0.7); /* White-ish box */
                border-radius: {px(BORDER_RADIUS["md"])};
                border: 1px solid {COLORS['border_light']};
            }}
        """)
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

    def process_event(self):
        """Process the natural language input and create calendar event"""
        # Initialize API client on first use
        if not self.api_client:
            api_key = os.environ.get('GEMINI_API_KEY')
            if not api_key:
                QMessageBox.critical(
                    self,
                    "API Key Error",
                    "GEMINI_API_KEY environment variable not set. Please set it before continuing."
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
        
        # At this point, we have either text, images, or both - proceed with processing
        self.enable_ui_signal.emit(False)

        image_payloads = [copy.deepcopy(attachment) for attachment in self.image_area.image_data]

        # Pass event description and image data to the thread
        worker = threading.Thread(
            target=self._create_event_thread,
            args=(event_description, image_payloads),
            daemon=True
        )

        with self._threads_lock:
            self._active_threads.add(worker)

        worker.start()

    def _create_event_thread(self, event_description: str, image_data: List[ImageAttachmentPayload]):
        try:
            # Get API client
            if not self.api_client:
                # Re-add API key check/initialization if necessary (assuming it's handled elsewhere or already initialized)
                # ... (initialization logic potentially needed here) ...
                # For now, assume self.api_client exists
                pass

            prepared_images: List[tuple[str, str, str]] = []
            for attachment in image_data:
                try:
                    prepared_images.append(attachment.materialize())
                except Exception as exc:
                    logger.warning("Skipping image attachment due to error: %s", exc)

            self.update_status_signal.emit("Requesting event details...")
            ics_strings: Optional[List[str]] = self.api_client.create_calendar_event(
                event_description,
                prepared_images,
                lambda message: self.update_status_signal.emit(message)
            )

            if not ics_strings:
                raise Exception("API returned no event data or failed after retries")

            event_count = len(ics_strings)
            event_text = "event" if event_count == 1 else "events"
            self.update_status_signal.emit(f"Processing {event_count} {event_text}...")
            logger.debug("Received %s wrapped ICS string(s) from API.", event_count)

            # Merge all ICS payloads while preserving metadata/timezones.
            final_ics_content = combine_ics_strings(ics_strings)

            logger.debug("Final combined ICS content (first 10000 chars):\n------\n%s\n------", final_ics_content[:10000])

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
                self.update_status_signal.emit(f"Successfully initiated import for {event_count} {event_text}!")
                self.clear_input_signal.emit()
                if hasattr(self.image_area, 'reset_state'):
                    QTimer.singleShot(0, self.image_area.reset_state)
            # Error status is handled by emitted signals within the try/except blocks

        except Exception as e:
            error_message = f"Error creating events: {str(e)}"
            logger.exception("Error in _create_event_thread")
            self.update_status_signal.emit(error_message)
            QTimer.singleShot(0, lambda: self._show_error(error_message))
        finally:
            with self._threads_lock:
                self._active_threads.discard(threading.current_thread())
            self.enable_ui_signal.emit(True)

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
        QMessageBox.critical(self, "Error", message)

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


if __name__ == '__main__':
    app = QApplication(sys.argv)
    
    # Set the application-wide icon
    app.setWindowIcon(QIcon("calendar-svg-simple.png"))
    
    window = NLCalendarCreator()
    window.show()
    
    # Start the main event loop
    sys.exit(app.exec())
