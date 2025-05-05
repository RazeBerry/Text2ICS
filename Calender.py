import sys
import os
from datetime import datetime
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                           QTextEdit, QPushButton, QLabel, QMessageBox,
                           QProgressBar, QHBoxLayout, QSizePolicy)
from PyQt6.QtGui import QKeySequence, QShortcut, QIcon, QDragEnterEvent, QDropEvent, QPixmap, QPainter, QBrush, QColor
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QMetaObject, QEasingCurve, QMimeData, QBuffer, pyqtSlot, Q_ARG
import time
from typing import Optional, List
import random
import threading
import re
import base64
import mimetypes
from pathlib import Path
import tempfile
import subprocess
from string import Formatter
import uuid # Import uuid

# Import the CalendarAPIClient from the new module
from api_client import CalendarAPIClient

# Add at the top of file
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"  # Proper HiDPI support
os.environ["QT_API"] = "pyqt6"  # Explicitly request PyQt6

# Add specific styling constants (optional, but good practice)
BORDER_RADIUS = "12px"
PANEL_BACKGROUND = "#FFFFFF" # Assuming the panels are on a white background in the image
TEXT_COLOR_PRIMARY = "#000000" # Black for main text
TEXT_COLOR_SECONDARY = "#8A8A8E" # Gray for subtitles, detected info
TEXT_COLOR_PLACEHOLDER = "#C7C7CC" # Lighter gray for placeholders
BUTTON_COLOR = "#007AFF" # Apple blue
BUTTON_HOVER_COLOR = "#006EE6"
BORDER_COLOR_LIGHT = "#E5E5EA"
BORDER_COLOR_DASHED = "#C7C7CC"

class ImageAttachmentArea(QLabel):
    """Custom widget for handling image drag and drop"""
    # Add a signal to notify when images are added/cleared
    images_changed = pyqtSignal(bool)  # True when images added, False when cleared
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(100)
        self.setStyleSheet("""
            QLabel {
                border: 2px dashed #3F3F3F;
                border-radius: 8px;
                padding: 12px;
                background-color: #2D2D2D;
                color: #86868B;
            }
            QLabel:hover {
                border-color: #0A84FF;
                background-color: #363636;
            }
        """)
        self.reset_state()

    def reset_state(self):
        self.setText("Drag & Drop Images Here")
        self.image_data = []
        self.images_changed.emit(False)  # Notify that images were cleared
        
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if all(url.toLocalFile().lower().endswith(('.png', '.jpg', '.jpeg', '.gif')) for url in urls):
                event.acceptProposedAction()
        elif event.mimeData().hasImage():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        """
        Processes dropped images, prioritizing file URLs over in-memory image data
        to prevent duplicate processing of the same image.
        """
        mime = event.mimeData()
        valid_images = []
        seen_base64 = set()
        urls_processed = False  # Flag to track if URLs were successfully handled

        # --- PRIORITIZE FILE URLS ---
        if mime.hasUrls():
            for url in mime.urls():
                file_path = url.toLocalFile()
                # Only process supported image types
                if file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                    try:
                        # Check if the file still exists
                        if not os.path.exists(file_path):
                            print(f"Warning: file '{file_path}' does not exist. Skipping.")
                            continue
                        
                        with open(file_path, 'rb') as f:
                            image_raw = f.read()
                        mime_type = mimetypes.guess_type(file_path)[0] or 'image/jpeg'
                        base64_data = base64.b64encode(image_raw).decode("utf-8")
                        
                        # Still check for duplicates among multiple dropped files
                        if base64_data in seen_base64:
                            continue
                        
                        seen_base64.add(base64_data)
                        
                        # Create a temporary file with the original extension
                        ext = os.path.splitext(file_path)[1] if os.path.splitext(file_path)[1] else ".jpg"
                        temp_fd, temp_path = tempfile.mkstemp(suffix=ext)
                        with os.fdopen(temp_fd, 'wb') as tmp:
                            tmp.write(image_raw)
                        
                        valid_images.append((temp_path, mime_type, base64_data))
                        urls_processed = True  # Mark that we processed at least one URL
                    except Exception as e:
                        print(f"Error reading file '{file_path}':", e)

        # --- PROCESS IN-MEMORY IMAGE ONLY IF NO URLs WERE PROCESSED ---
        if not urls_processed and mime.hasImage():
            try:
                from PyQt6.QtGui import QImage, QPixmap
                image_data = mime.imageData()
                if isinstance(image_data, QImage):
                    pixmap = QPixmap.fromImage(image_data)
                else:
                    pixmap = QPixmap(image_data)
                    
                if not pixmap.isNull():
                    # Save the pixmap to an in-memory buffer as PNG
                    buffer = QBuffer()
                    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
                    pixmap.save(buffer, "PNG")
                    bdata = buffer.data()
                    base64_data = base64.b64encode(bytes(bdata)).decode("utf-8")
                    
                    # Create a temporary file to store the image data
                    temp_fd, temp_path = tempfile.mkstemp(suffix=".png")
                    with os.fdopen(temp_fd, 'wb') as f:
                        f.write(bytes(bdata))
                    valid_images.append((temp_path, "image/png", base64_data))
                    buffer.close()
            except Exception as e:
                print("Error processing in-memory image:", e)

        # Update UI if any images were successfully added
        if valid_images:
            self.image_data.extend(valid_images)
            self.update_preview()
            self.images_changed.emit(True)

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
        self.setStyleSheet("""
            QLabel {
                border: 2px dashed #0A84FF;  /* Change border to blue */
                border-radius: 8px;
                padding: 12px;
                background-color: rgba(10, 132, 255, 0.1);  /* Light blue background */
                color: #FFFFFF;  /* Brighter text */
                font-weight: bold;  /* Make text bold */
                font-size: 14px;  /* Slightly larger font */
                line-height: 1.4;
            }
            QLabel:hover {
                border-color: #0A84FF;
                background-color: rgba(10, 132, 255, 0.15);
            }
        """)


class PulsingLoadingIndicator(QWidget):
    """Custom animated loading indicator with pulsing dots"""
    
    def __init__(self, parent=None, dot_count=3):
        super().__init__(parent)
        self.setFixedSize(60, 20)  # Small footprint
        
        self.dot_count = dot_count
        self.animation_offset = 0
        self.dot_size = 6
        self.dot_spacing = 10
        self.animation_speed = 150  # ms
        
        self.animation_timer = QTimer(self)
        self.animation_timer.timeout.connect(self.update_animation)
        
        # Set widget background to transparent
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
    def start_animation(self):
        self.animation_timer.start(self.animation_speed)
        
    def stop_animation(self):
        self.animation_timer.stop()
        
    def update_animation(self):
        self.animation_offset = (self.animation_offset + 1) % self.dot_count
        self.update()  # Trigger repaint
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Calculate total width of all dots
        total_width = self.dot_count * self.dot_size + (self.dot_count - 1) * self.dot_spacing
        
        # Center the dots horizontally
        start_x = (self.width() - total_width) // 2
        center_y = self.height() // 2
        
        # Draw each dot
        for i in range(self.dot_count):
            # Calculate opacity based on animation offset
            opacity = 0.3 + 0.7 * (1.0 - (abs(self.animation_offset - i) % self.dot_count) / self.dot_count)
            
            # Set the dot color with proper opacity
            color = QColor(255, 255, 255, int(opacity * 255))
            painter.setBrush(QBrush(color))
            painter.setPen(Qt.PenStyle.NoPen)
            
            # Draw the dot
            x = start_x + i * (self.dot_size + self.dot_spacing)
            painter.drawEllipse(x, center_y - self.dot_size // 2, self.dot_size, self.dot_size)


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

        # --- Main Container Widget ---
        # Use a QWidget as the central widget for easier styling control
        main_container = QWidget(self)
        main_container.setObjectName("mainContainer") # For specific styling
        main_container.setStyleSheet(f"""
            #mainContainer {{
                background-color: #F2F2F7; /* Light gray background like the image */
                border-radius: {BORDER_RADIUS};
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
        outer_layout.setContentsMargins(30, 20, 30, 20) # Add padding around everything
        outer_layout.setSpacing(15) # Spacing between sections

        # --- 1. Top Title/Subtitle Section ---
        title_layout = QVBoxLayout()
        title_layout.setSpacing(4)
        title_layout.setContentsMargins(0, 0, 0, 10) # Margin below title section

        title_label = QLabel("Create a Calendar Event")
        title_label.setStyleSheet(f"""
            QLabel {{
                font-size: 24px; /* Larger font */
                font-weight: 600; /* Semibold */
                color: {TEXT_COLOR_PRIMARY};
                qproperty-alignment: 'AlignCenter';
            }}
        """)

        subtitle_label = QLabel("Type freely or drop a photo. We'll do the rest.")
        subtitle_label.setStyleSheet(f"""
            QLabel {{
                font-size: 14px;
                color: {TEXT_COLOR_SECONDARY};
                qproperty-alignment: 'AlignCenter';
            }}
        """)

        title_layout.addWidget(title_label)
        title_layout.addWidget(subtitle_label)
        outer_layout.addLayout(title_layout)

        # --- 2. Main Content Area (Horizontal Split) ---
        content_layout = QHBoxLayout()
        content_layout.setSpacing(25) # Spacing between the two columns

        # --- 2a. Left Panel: Event Details ---
        left_panel_layout = QVBoxLayout()
        left_panel_layout.setSpacing(15)

        event_details_title = QLabel("Event Details")
        event_details_title.setStyleSheet(f"""
            QLabel {{
                font-size: 16px;
                font-weight: 600;
                color: {TEXT_COLOR_PRIMARY};
            }}
        """)
        left_panel_layout.addWidget(event_details_title)

        # --- Example Input/Detected Area ---
        # Use a QWidget as a styled container
        example_input_container = QWidget()
        example_input_container.setObjectName("exampleInputContainer")
        example_input_container.setStyleSheet(f"""
            #exampleInputContainer {{
                background-color: {PANEL_BACKGROUND};
                border: 1px solid {BORDER_COLOR_LIGHT};
                border-radius: 8px;
                padding: 0px;
            }}
        """)
        example_input_layout = QVBoxLayout(example_input_container)
        example_input_layout.setContentsMargins(12, 8, 12, 8) # Adjusted inner margins
        example_input_layout.setSpacing(6) # Better spacing inside the container

        # Replace QLabel with an actual editable QTextEdit for input
        self.text_input = QTextEdit()
        self.text_input.setPlaceholderText("e.g. Dinner with Mia at Balthasar next Friday 7:30pm") # Keep multiline placeholder
        self.text_input.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.text_input.setAcceptRichText(False) # Explicitly disable rich text input
        self.text_input.setStyleSheet(f"""
            QTextEdit {{
                color: {TEXT_COLOR_PRIMARY};
                background-color: transparent; /* Keep transparent to blend with container */
                border: none; /* No border on the text edit itself */
                font-size: 14px;
                padding: 4px 0px; /* Minimal padding */
            }}
            QTextEdit:focus {{
                border: none;
                outline: none; /* Remove focus outline */
            }}
        """)
        # Adjust height slightly - might need tweaking based on font/padding
        self.text_input.setFixedHeight(100) # Increased height

        # Add only the text input widget to the layout
        example_input_layout.addWidget(self.text_input)

        left_panel_layout.addWidget(example_input_container)


        # --- Preview Area ---
        preview_title = QLabel("This is what we'll create in\nyour calendar")
        preview_title.setWordWrap(True)
        preview_title.setStyleSheet(f"""
            QLabel {{
                font-size: 13px;
                color: {TEXT_COLOR_SECONDARY};
                margin-top: 5px; /* Space above preview */
            }}
        """)
        left_panel_layout.addWidget(preview_title)

        preview_container = QWidget()
        preview_container.setObjectName("previewContainer")
        preview_container.setStyleSheet(f"""
             #previewContainer {{
                 background-color: {PANEL_BACKGROUND};
                 border: 1px solid {BORDER_COLOR_LIGHT};
                 border-radius: 8px;
                 padding: 10px 12px; /* Slightly less padding */
             }}
         """)
        preview_layout = QHBoxLayout(preview_container) # Horizontal layout for preview
        preview_layout.setContentsMargins(0,0,0,0)
        preview_layout.setSpacing(10)

        preview_event_title = QLabel("Dinner with Mia")
        preview_event_title.setStyleSheet(f"color: {TEXT_COLOR_PRIMARY}; font-size: 14px; font-weight: 500;")

        preview_date = QLabel("Mar 30")
        preview_date.setStyleSheet(f"color: {TEXT_COLOR_SECONDARY}; font-size: 13px;")

        preview_time = QLabel("7:30 PM–9:00 PM")
        preview_time.setStyleSheet(f"color: {TEXT_COLOR_SECONDARY}; font-size: 13px;")

        preview_layout.addWidget(preview_event_title, 1) # Title takes available space
        preview_layout.addWidget(preview_date)
        preview_layout.addWidget(preview_time)

        left_panel_layout.addWidget(preview_container)
        left_panel_layout.addStretch(1) # Push content up

        # --- 2b. Right Panel: Photo Attachments ---
        right_panel_layout = QVBoxLayout()
        right_panel_layout.setSpacing(15)

        photo_title = QLabel("Photo Attachments")
        photo_title.setStyleSheet(f"""
            QLabel {{
                font-size: 16px;
                font-weight: 600;
                color: {TEXT_COLOR_PRIMARY};
            }}
        """)
        right_panel_layout.addWidget(photo_title)

        # --- Image Drop Area ---
        # Re-use the existing ImageAttachmentArea, but update styling/text
        self.image_area = ImageAttachmentArea()
        self.image_area.setText("Drop image or\nscreenshot here\nto attach to event")
        self.image_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_area.setWordWrap(True)
        self.image_area.setStyleSheet(f"""
            QLabel {{
                border: 2px dashed {BORDER_COLOR_DASHED};
                border-radius: 8px;
                padding: 12px;
                background-color: {PANEL_BACKGROUND}; /* Match other panels */
                color: {TEXT_COLOR_PLACEHOLDER}; /* Placeholder text color */
                font-size: 14px;
                min-height: 150px; /* Ensure it has some height */
            }}
            QLabel:hover {{
                border-color: {BUTTON_COLOR}; /* Blue highlight on hover */
                background-color: #F7F7FC; /* Slightly different background on hover */
            }}
        """)
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
                background-color: {BUTTON_COLOR};
                color: white;
                border: none;
                border-radius: 8px; /* Slightly more rounded */
                padding: 10px 24px;
                font-size: 16px; /* Slightly larger font */
                font-weight: 500; /* Medium weight */
            }}
            QPushButton:hover {{
                background-color: {BUTTON_HOVER_COLOR};
            }}
            QPushButton:pressed {{
                background-color: #005AB3; /* Darker pressed state */
            }}
            QPushButton:disabled {{
                background-color: #BDBDBD; /* Gray out when disabled */
                color: #757575;
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
                border-radius: {BORDER_RADIUS}; /* Match parent container */
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
                color: {TEXT_COLOR_PRIMARY};
                font-size: 16px;
                font-weight: 500;
                padding: 15px 30px;
                background-color: rgba(255, 255, 255, 0.7); /* White-ish box */
                border-radius: 10px;
                border: 1px solid {BORDER_COLOR_LIGHT};
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
         print(f"Status Update: {message}") # Placeholder if status label removed
         # Update processing label if overlay is visible
         if not self.create_button.isEnabled():
             self.processing_label.setText(message)

    def _enable_ui(self, enabled: bool):
         # Enable/disable interactive elements
         print(f"DEBUG: _enable_ui called with enabled={enabled}") # DIAGNOSTIC
         self.text_input.setEnabled(enabled) # Enable/disable actual text input
         self.image_area.setEnabled(enabled)
         self.create_button.setEnabled(enabled)
         print(f"DEBUG: Widgets enabled state set to {enabled}") # DIAGNOSTIC

         if enabled:
             print("DEBUG: Attempting to hide overlay...") # DIAGNOSTIC
             self.overlay.hide()
             print(f"DEBUG: Overlay hidden. Is visible: {self.overlay.isVisible()}") # DIAGNOSTIC
         else:
             print("DEBUG: Attempting to show overlay...") # DIAGNOSTIC
             self.processing_label.setText("Processing...") # Reset overlay text
             self.overlay.raise_() # Ensure overlay is on top
             self.overlay.show()
             print(f"DEBUG: Overlay shown. Is visible: {self.overlay.isVisible()}") # DIAGNOSTIC

    def _clear_input(self):
         # Clear the actual input method
         self.text_input.clear()

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

        # Pass event description and image data to the thread
        threading.Thread(
            target=self._create_event_thread, 
            args=(event_description, self.image_area.image_data.copy())
        ).start()

    def _create_event_thread(self, event_description, image_data):
        try:
            # Get API client
            if not self.api_client:
                # Re-add API key check/initialization if necessary (assuming it's handled elsewhere or already initialized)
                # ... (initialization logic potentially needed here) ...
                # For now, assume self.api_client exists
                pass

            self.update_status_signal.emit("Requesting event details...")
            ics_strings: Optional[List[str]] = self.api_client.create_calendar_event(
                event_description,
                image_data,
                lambda message: self.update_status_signal.emit(message)
            )

            if not ics_strings:
                raise Exception("API returned no event data or failed after retries")

            event_count = len(ics_strings)
            event_text = "event" if event_count == 1 else "events"
            self.update_status_signal.emit(f"Processing {event_count} {event_text}...")
            print(f"DEBUG: Received {event_count} wrapped ICS string(s) from API.")

            # --- Assemble the combined ICS content CORRECTLY ---
            combined_vevents = []
            
            # Helper function to ensure a unique UID for each VEVENT
            def _force_new_uid(vevent: str) -> str:
                new_uid = f"{uuid.uuid4()}@nl-calendar"
                # replace the first UID:… line (RFC5545 §3.8.4.7)
                # Use re.IGNORECASE just in case the API returns 'uid:' instead of 'UID:'
                return re.sub(r"^UID:.*$", f"UID:{new_uid}", vevent, count=1, flags=re.MULTILINE | re.IGNORECASE)

            for i, single_ics in enumerate(ics_strings):
                # Extract content between BEGIN:VEVENT and END:VEVENT
                match = re.search(r"BEGIN:VEVENT(.*?)END:VEVENT", single_ics, re.DOTALL | re.IGNORECASE) # Added IGNORECASE here too for robustness
                if match:
                    vevent_content = match.group(0) # Includes BEGIN/END VEVENT
                    # Ensure a unique UID before appending
                    combined_vevents.append(_force_new_uid(vevent_content))
                    print(f"DEBUG: Extracted and processed VEVENT {i+1} with new UID.")
                else:
                    print(f"Warning: Could not extract VEVENT from ICS string {i+1}:\n{single_ics[:200]}...")
            
            if not combined_vevents:
                 raise Exception("Failed to extract any valid VEVENT blocks from API response.")

            # Construct the final single ICS file content
            final_ics_content = (
                "BEGIN:VCALENDAR\r\n"
                "VERSION:2.0\r\n"
                "PRODID:-//NL Calendar Creator//EN\r\n"
                # Optional: Add CALSCALE as suggested for robustness
                "CALSCALE:GREGORIAN\r\n"
                + "\r\n".join(combined_vevents) +  # Join extracted VEVENT blocks with CRLF
                "\r\nEND:VCALENDAR"
            )
            
            print(f"DEBUG: Final combined ICS content (first 10000 chars):\n------\n{final_ics_content[:10000]}\n------")

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
                    print(f"DEBUG: Using Popen for: open {temp_path}")
                    subprocess.Popen(["open", temp_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    successful_import_initiated = True
                elif sys.platform.startswith("win"):
                    print(f"DEBUG: Using os.startfile for {temp_path}")
                    os.startfile(temp_path) # type: ignore
                    print(f"DEBUG: os.startfile finished.") # Note: This happens immediately, not after import
                    successful_import_initiated = True
                else: # Assume Linux/other POSIX
                    # Keep xdg-open but use Popen for consistency
                    command = ["xdg-open", temp_path]
                    print(f"DEBUG: Using Popen for: {' '.join(command)}")
                    subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    successful_import_initiated = True

                # 3. Schedule deletion on the GUI thread much later
                if temp_path and successful_import_initiated:
                    print(f"DEBUG: Scheduling deletion of {temp_path} in 60 seconds via main thread.")
                    # Use invokeMethod to call the scheduling method on the main thread
                    QMetaObject.invokeMethod(
                        self,
                        "_schedule_temp_file_deletion",
                        Qt.ConnectionType.QueuedConnection,
                        Q_ARG(str, temp_path) # Wrap argument with Q_ARG
                    )

            except FileNotFoundError:
                self.update_status_signal.emit("Error: Could not create temporary event file.")
                print("Error: Failed to create temp event file.")
                # Ensure temp_path is cleaned up if creation failed mid-way (though unlikely with NamedTemporaryFile context)
                if temp_path and os.path.exists(temp_path):
                    try: os.unlink(temp_path)
                    except OSError: pass # Ignore cleanup error if creation failed
            except OSError as os_err:
                # Error could be from os.startfile or Popen if command not found
                self.update_status_signal.emit(f"Error: Could not open event file: {os_err}")
                print(f"Error initiating open for {temp_path}: {os_err}")
                # Clean up if opening failed
                if temp_path and os.path.exists(temp_path):
                    try: os.unlink(temp_path)
                    except OSError: pass
            # Remove CalledProcessError handler as Popen doesn't raise it directly here
            # except subprocess.CalledProcessError as proc_err: ...
            except Exception as e:
                self.update_status_signal.emit(f"Unexpected error processing event file: {e}")
                print(f"Unexpected error with temp file {temp_path}: {e}")
                # Clean up on generic error
                if temp_path and os.path.exists(temp_path):
                    try: os.unlink(temp_path)
                    except OSError: pass
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
            print(f"Error in _create_event_thread: {e}")
            self.update_status_signal.emit(error_message)
            QTimer.singleShot(0, lambda: self._show_error(error_message))
        finally:
            self.enable_ui_signal.emit(True)

    @pyqtSlot(str) # Decorate as a slot invokable via invokeMethod
    def _schedule_temp_file_deletion(self, file_path: str):
        """Schedules the deletion of the temp file from the main GUI thread."""
        print(f"DEBUG: Main thread received request to schedule deletion for {file_path}")
        # This QTimer.singleShot is now called safely from the main thread
        QTimer.singleShot(60_000, lambda p=file_path: self._delete_temp_file(p))

    def _delete_temp_file(self, file_path: str):
        """Actually deletes the temp file, handling potential errors."""
        try:
            print(f"DEBUG: Main thread attempting to delete {file_path}")
            Path(file_path).unlink(missing_ok=True)
            print(f"DEBUG: Main thread successfully deleted {file_path}")
        except OSError as e:
            print(f"Warning: Main thread failed to delete temp file {file_path}: {e}")
        except Exception as e:
            print(f"Warning: Unexpected error deleting temp file {file_path} from main thread: {e}")

    def _show_error(self, message: str):
        """Show error message box (called from main thread)"""
        QMessageBox.critical(self, "Error", message)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    
    # Set the application-wide icon
    app.setWindowIcon(QIcon("calendar-svg-simple.png"))
    
    window = NLCalendarCreator()
    window.show()
    
    # Start the main event loop
    sys.exit(app.exec())
