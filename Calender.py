import sys
import os
from datetime import datetime
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                           QTextEdit, QPushButton, QLabel, QMessageBox,
                           QProgressBar, QHBoxLayout)
from PyQt6.QtGui import QKeySequence, QShortcut, QIcon, QDragEnterEvent, QDropEvent, QPixmap, QPainter, QBrush, QColor
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QMetaObject, QEasingCurve, QMimeData, QBuffer
import time
from typing import Optional
import random
import threading
import re
import base64
import mimetypes
from pathlib import Path
import tempfile
from string import Formatter

# Add at the top of file
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"  # Proper HiDPI support
os.environ["QT_API"] = "pyqt6"  # Explicitly request PyQt6

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

    def dropEvent(self, event: QDropEvent):
        """
        Robust drop event handler that processes both in-memory images and file URLs.
        It deduplicates images if the same image is provided via both methods.
        """
        mime = event.mimeData()
        valid_images = []
        seen_base64 = set()

        # Process in-memory image data first.
        if mime.hasImage():
            try:
                from PyQt6.QtGui import QImage, QPixmap
                image_data = mime.imageData()
                if isinstance(image_data, QImage):
                    pixmap = QPixmap.fromImage(image_data)
                else:
                    pixmap = QPixmap(image_data)
                if not pixmap.isNull():
                    # Save the pixmap to an in-memory buffer as PNG.
                    buffer = QBuffer()
                    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
                    pixmap.save(buffer, "PNG")
                    bdata = buffer.data()
                    base64_data = base64.b64encode(bytes(bdata)).decode("utf-8")
                    # Record the processed data to avoid duplicates.
                    seen_base64.add(base64_data)
                    # Create a temporary file to store the image data.
                    temp_fd, temp_path = tempfile.mkstemp(suffix=".png")
                    with os.fdopen(temp_fd, 'wb') as f:
                        f.write(bytes(bdata))
                    valid_images.append((temp_path, "image/png", base64_data))
                    buffer.close()
            except Exception as e:
                print("Error processing in-memory image:", e)

        # Process dropped file URLs and deduplicate if already added.
        if mime.hasUrls():
            for url in mime.urls():
                file_path = url.toLocalFile()
                # Only process supported image types.
                if file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                    try:
                        # Check if the file still exists.
                        if not os.path.exists(file_path):
                            print(f"Warning: file '{file_path}' does not exist. Skipping.")
                            continue
                        with open(file_path, 'rb') as f:
                            image_raw = f.read()
                        mime_type = mimetypes.guess_type(file_path)[0] or 'image/jpeg'
                        base64_data = base64.b64encode(image_raw).decode("utf-8")
                        # If this image has already been added via in-memory data, skip it.
                        if base64_data in seen_base64:
                            continue
                        seen_base64.add(base64_data)
                        # Write the image data to a temporary file.
                        ext = os.path.splitext(file_path)[1] if os.path.splitext(file_path)[1] else ".jpg"
                        temp_fd, temp_path = tempfile.mkstemp(suffix=ext)
                        with os.fdopen(temp_fd, 'wb') as tmp:
                            tmp.write(image_raw)
                        valid_images.append((temp_path, mime_type, base64_data))
                    except Exception as e:
                        print(f"Error reading file '{file_path}':", e)

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


class CalendarAPIClient:
    # Class-level constant for SYSTEM instructions
    SYSTEM_PROMPT = """
Follow these steps to create the .ics file content:

1. Carefully parse the event details to identify if there are multiple events described. If so, separate them for individual processing.

2. For each event, extract all relevant information such as event title, date, time, location, description, and any other provided details. If the event involves flights between different cities, be aware that the departure and arrival times may be in different time zones. Adjust the event times accordingly by converting them to UTC, ensuring accurate reflection of time differences. Employ a chain-of-thought process with reflection and verification to ensure proper handling of these time differences.

3. Generate the .ics file content using the following strict formatting rules:
   REQUIRED CALENDAR STRUCTURE:
   - BEGIN:VCALENDAR
   - VERSION:2.0 (mandatory)
   - PRODID:-//Your identifier//EN (mandatory)
   
   REQUIRED EVENT FORMATTING:
   - BEGIN:VEVENT
   - UID: Generate unique using format YYYYMMDDTHHMMSSZ-identifier@domain
   - DTSTAMP: Current time in format YYYYMMDDTHHMMSSZ
   - DTSTART: Event start in format YYYYMMDDTHHMMSSZ
   - DTEND: Event end in format YYYYMMDDTHHMMSSZ
   - SUMMARY: Event title
   - DESCRIPTION: Properly escaped text using backslash before commas, semicolons, and newlines (\, \; \n)
   
   OPTIONAL BUT RECOMMENDED:
   - LOCATION: Venue details with proper escaping
   - CATEGORIES: Event type/category
   
   REMINDER STRUCTURE:
   - BEGIN:VALARM
   - ACTION:DISPLAY
   - DESCRIPTION:Reminder
   - TRIGGER:-PT30M (or your preferred timing)
   - END:VALARM
   
   CRITICAL FORMATTING RULES:
   1. DATETIME FIELD REQUIREMENTS (STRICTLY ENFORCED):
      - MANDATORY 'T' separator between date and time components
      - Format must be: YYYYMMDD'T'HHMMSS'Z'
      - Examples of CORRECT format:
        * 20241025T130000Z  ✓ (correct with T separator)
        * 20250101T090000Z  ✓ (correct with T separator)
      - Examples of INCORRECT format:
        * 20241025130000Z   ✗ (missing T separator)
        * 2024-10-25T13:00:00Z  ✗ (contains hyphens and colons)
        * 20241025 130000Z  ✗ (contains space instead of T)
      - The 'Z' suffix is required for UTC timezone
      - This format is REQUIRED for ALL datetime fields:
        * DTSTART
        * DTEND
        * DTSTAMP
        * UID (when using timestamp)

   2. EXAMPLE OF CORRECT FORMATTING:
      ```ics
      BEGIN:VCALENDAR
      VERSION:2.0
      PRODID:-//Example Corp//Calendar App//EN
      BEGIN:VEVENT
      UID:20240325T123000Z-flight123@example.com
      DTSTAMP:20240325T123000Z
      DTSTART:20240401T090000Z
      DTEND:20240401T100000Z
      SUMMARY:Flight BA123
      DESCRIPTION:British Airways | Economy\\nDeparture: T2\\nArrival: T5
      END:VEVENT
      END:VCALENDAR
      ```

   3. VALIDATION REQUIREMENTS:
      - Every datetime field MUST include the T separator
      - No exceptions are allowed for any datetime fields
      - Calendar applications will reject files without proper T separators
      - Always validate before creating the ICS file

4. Ensure all text is properly escaped, replacing any newline characters in the SUMMARY, LOCATION, or DESCRIPTION fields with "\\n".
5. Wrap each complete .ics file content in numbered <ics_file_X> tags, where X is the event number (starting from 1).

Here's a detailed breakdown of the .ics file structure:

BEGIN:VCALENDAR\r\n
VERSION:2.0\r\n
PRODID:-//Your Company//Your Product//EN\r\n
BEGIN:VEVENT\r\n
UID:YYYYMMDDTHHMMSSZ-identifier@domain.com\r\n
DTSTAMP:20250207T120000Z           # Current time, must include T and Z\r\n
DTSTART:20250207T200000Z           # Must include T and Z\r\n
DTEND:20250207T210000Z             # Must include T and Z\r\n
SUMMARY:Event Title\r\n
LOCATION:Location with\\, escaped commas\r\n
DESCRIPTION:Description with\\, escaped commas\\; and semicolons\\nand newlines\r\n
BEGIN:VALARM\r\n
ACTION:DISPLAY\r\n
DESCRIPTION:Reminder\r\n
TRIGGER:-PT30M\r\n
END:VALARM\r\n
END:VEVENT\r\n
END:VCALENDAR
"""

    # Class-level template for USER prompts (with dynamic placeholders)
    USER_PROMPT_TEMPLATE = """
<event_description>
{event_description}
</event_description>

Today's date is {day_name}, {formatted_date}.
"""

    def __init__(self, api_key: str):
        # Import genai here for lazy loading and store as instance variable
        import google.generativeai as genai
        self.genai = genai
        
        # Configure the API key
        self.genai.configure(api_key=api_key)
        
        self.generation_config = {
            "temperature": 0,
            "top_p": 0.3,
            "top_k": 64,
            "max_output_tokens": 8192,
            "response_mime_type": "text/plain",
        }

        # Validation layer: Ensure USER_PROMPT_TEMPLATE contains the required keys.
        template_keys = [fn for _, fn, _, _ in Formatter().parse(self.USER_PROMPT_TEMPLATE) if fn]
        required_keys = {'event_description', 'day_name', 'formatted_date'}
        assert set(template_keys) == required_keys, f"Template mismatch! Expected keys {required_keys} but got {set(template_keys)}"

        self.model = self.genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            generation_config=self.generation_config,
            system_instruction=self.SYSTEM_PROMPT
        )
        self.base_delay = 1
        self.max_retries = 5

    def upload_to_gemini(self, path, mime_type=None):
        """Uploads the given file to Gemini."""
        file = self.genai.upload_file(path, mime_type=mime_type)
        print(f"Uploaded file '{file.display_name}' as: {file.uri}")
        return file

    def create_calendar_event(self, event_description: str, image_data: list[tuple[str, str, str]],
                              status_callback: callable) -> Optional[str]:
        """
        Create calendar event with enhanced error handling and status updates.
        This method supports both text and image attachments.
        """
        # If no text is provided but there are attached images, use a default description.
        if not event_description and image_data:
            event_description = "Event details are provided via attached images."

        current_date = datetime.now()
        day_name = current_date.strftime("%A")
        formatted_date = current_date.strftime("%B %d, %Y")

        # Build the dynamic prompt using the class-level USER_PROMPT_TEMPLATE.
        api_prompt = self.USER_PROMPT_TEMPLATE.format(
            event_description=event_description,
            day_name=day_name,
            formatted_date=formatted_date
        )

        for attempt in range(self.max_retries):
            try:
                status_callback(f"Attempting to create event... (Try {attempt + 1}/{self.max_retries})")
                print(f"DEBUG: Attempt {attempt + 1}/{self.max_retries}")
                print("DEBUG: Generated API prompt (first 200 chars):", api_prompt[:200])

                # Prepare chat history (add any uploaded image parts if images are provided)
                history = []
                if image_data:
                    image_parts = []
                    for img in image_data:
                        # Unpack tuple: (file_path, mime_type, base64_data)
                        file_path, mime_type, _ = img  
                        uploaded_file = self.upload_to_gemini(file_path, mime_type=mime_type)
                        image_parts.append(uploaded_file)
                    history.append({
                        "role": "user",
                        "parts": image_parts
                    })

                # Start the chat session with the provided image history (if any)
                chat_session = self.model.start_chat(history=history)
                # Send the text prompt as the follow-up message.
                message = chat_session.send_message(api_prompt)
                
                # Try to obtain the text response.
                response_text = getattr(message, 'text', None)
                if response_text is None:
                    response_text = str(message)
                
                print("DEBUG: API Response:", response_text)
                print("DEBUG: API call successful on attempt", attempt + 1)
                return response_text

            except Exception as e:
                print(f"DEBUG: Exception on attempt {attempt + 1}: {e}")
                if attempt < self.max_retries - 1:
                    delay = self.base_delay * (2 ** attempt)
                    status_callback(f"Error occurred, retrying in {delay} seconds...")
                    print(f"DEBUG: Retrying in {delay} seconds...")
                    time.sleep(delay)
                    continue
                print("DEBUG: Max retries reached. Raising exception.")
                raise

        print("DEBUG: Failed to create calendar event after retries.")
        return None


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
        self.setWindowTitle("Natural Language Calendar Event")
        self.setFixedSize(1000, 500)  # Slightly larger window for better proportions

        # Remove problematic WA_DontShowOnScreen attribute
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background-color: #1E1E1E;")
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        # Fix parent widget for main layout
        main_layout = QHBoxLayout(central_widget)
        
        # Force equal width for both panels
        left_panel = QWidget()
        left_panel.setFixedWidth(460)  # (1000 - 40 margins - 20 spacing) / 2 = 460
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)  # Spacing between elements
        
        right_panel = QWidget()
        right_panel.setFixedWidth(460)  # Equal width as left panel
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # Status label (spans both panels)
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("""
            QLabel {
                color: #86868B;
                font-size: 13px;
                font-weight: 500;
                letter-spacing: -0.08px;
                padding: 6px 12px;
                border-radius: 6px;
                background-color: rgba(255, 255, 255, 0.05);
                backdrop-filter: blur(10px);
                border: 1px solid rgba(255, 255, 255, 0.1);
                transition: all 0.2s ease;
            }
        """)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.hide()
        
        # Left panel components
        instruction_label = QLabel("Create a Calendar Event Using Natural Language or Photos!")
        instruction_label.setStyleSheet("""
            QLabel {
                font-size: 16px;
                font-weight: 600;
                color: #FFFFFF;
                margin-bottom: 4px;
            }
        """)
        
        example_label = QLabel(
            "Examples:\n"
            "• Schedule a weekly team sync every Tuesday at 10am until end of quarter\n"
            "• Dinner reservation at Osteria next Friday at 7:30pm for 2 hours\n"
            "• Vacation in Hawaii from July 15th to 22nd with flight details in the notes\n"
            "• Birthday party at Central Park next Saturday 3-6pm, bring snacks and games"
        )
        example_label.setStyleSheet("""
            QLabel {
                font-size: 12px;
                color: #8E8E93;
                font-style: italic;
                margin-bottom: 16px;
                line-height: 1.6;
            }
        """)
        
        self.text_input = QTextEdit()
        self.text_input.setStyleSheet("""
            QTextEdit {
                color: #FFFFFF;
                background-color: #2D2D2D;
                border: 1px solid #3F3F3F;
                border-radius: 8px;
                padding: 12px;
                line-height: 1.6;
                font-size: 14px;
            }
            QTextEdit:focus {
                border: 1px solid #0A84FF;
                background-color: #363636;
            }
        """)
        self.text_input.setPlaceholderText("Type your event details here...")
        
        # Add components to left panel
        left_layout.addWidget(instruction_label, 0)  # 0 = no stretch
        left_layout.addWidget(example_label, 0)
        left_layout.addWidget(self.text_input, 1)  # 1 = stretch to fill space
        
        # Progress bar
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(3)
        self.progress.hide()
        self.progress.setStyleSheet("""
            QProgressBar {
                border: none;
                background: rgba(45, 45, 45, 0.3);
                border-radius: 1.5px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #0A84FF,
                    stop:0.4 #60A5FA,
                    stop:0.6 #60A5FA,
                    stop:1 #0A84FF);
                border-radius: 1.5px;
            }
        """)
        
        # Create Event button - now part of left panel
        self.create_button = QPushButton("Create Event")
        self.create_button.clicked.connect(self.process_event)
        self.create_button.setFixedHeight(40)  # Taller button
        self.create_button.setStyleSheet("""
            QPushButton {
                background-color: #0A84FF;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 14px;
                font-weight: 500;
                letter-spacing: 0.2px;
            }
            QPushButton:hover {
                background-color: #0071E3;
            }
            QPushButton:pressed {
                background-color: #006CDC;
            }
        """)

        # Add progress and button to left panel
        left_layout.addWidget(self.progress)
        left_layout.addWidget(self.create_button)
        
        # Right panel components
        image_label = QLabel("Photo Attachments of Events")
        image_label.setStyleSheet("""
            QLabel {
                font-size: 16px;
                font-weight: 600;
                color: #FFFFFF;
                margin-bottom: 4px;
            }
        """)
        
        self.image_area = ImageAttachmentArea()
        self.image_area.setMinimumHeight(350)  # Taller to match text input area
        
        self.clear_attachments_btn = QPushButton("Clear Attachments")
        self.clear_attachments_btn.clicked.connect(self.clear_attachments)
        self.clear_attachments_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF3B30;
                color: white;
                padding: 4px 12px;
                font-size: 12px;
                border-radius: 6px;
                max-width: 150px;
            }
            QPushButton:hover {
                background-color: #FF453A;
            }
        """)
        self.clear_attachments_btn.hide()
        
        # Add components to right panel
        right_layout.addWidget(image_label, 0)
        right_layout.addWidget(self.image_area, 1)  # 1 = stretch to fill space
        right_layout.addWidget(self.clear_attachments_btn, 0, Qt.AlignmentFlag.AlignCenter)
        
        # Main horizontal layout
        main_layout.addWidget(left_panel)
        main_layout.addWidget(right_panel)
        
        # Final layout with status label
        final_layout = QVBoxLayout()
        final_layout.addWidget(self.status_label)
        final_layout.addLayout(main_layout)
        
        # Set the final layout
        central_widget.setLayout(final_layout)

        # Initialize progress animation
        self.progress_animation = None
        self.progress_value = 0

        # Add critical style rules back
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1E1E1E;
                border: 1px solid #3F3F3F;
                border-radius: 12px;
            }
            ImageAttachmentArea {
                min-height: 350px;
            }
            QTextEdit {
                margin: 8px 0;
            }
        """)
        
        # Defer UI refresh
        QTimer.singleShot(100, self.refresh_ui)

        # Initialize api_client as None
        self.api_client = None

        # Add overlay widget for processing state
        self.overlay = QWidget(self)
        self.overlay.setStyleSheet("""
            QWidget {
                background-color: rgba(30, 30, 30, 0.85);
                border-radius: 12px;
            }
        """)
        self.overlay.hide()

        # Create layout for overlay content
        overlay_layout = QVBoxLayout(self.overlay)
        overlay_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Add processing label
        self.processing_label = QLabel("Processing Request...")
        self.processing_label.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 16px;
                font-weight: bold;
                padding: 20px 35px;
                background-color: rgba(10, 132, 255, 0.15);
                border-radius: 10px;
                border: 1px solid rgba(255, 255, 255, 0.15);
                min-width: 250px;
                max-width: 400px;
            }
        """)
        self.processing_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        overlay_layout.addWidget(self.processing_label)
        
        # Add animated loading indicator
        self.loading_indicator = PulsingLoadingIndicator(self.overlay)
        overlay_layout.addWidget(self.loading_indicator, 0, Qt.AlignmentFlag.AlignCenter)
        overlay_layout.setSpacing(15)  # Add space between label and indicator
        
        # Connect signals to slots
        self.update_status_signal.connect(self.update_status)
        self.enable_ui_signal.connect(self._enable_ui)
        self.clear_input_signal.connect(self._clear_input)
        self.show_progress_signal.connect(self._show_progress)

        # Make sure the overlay covers the entire window
        self.overlay.resize(self.size())

    def refresh_ui(self):
        """Trigger full UI update after initial layout"""
        self.updateGeometry()
        self.repaint()

    def _update_progress(self):
        """Update progress bar animation"""
        self.progress_value = (self.progress_value + 1) % 100
        self.progress.setValue(self.progress_value)

    def update_status(self, message: str):
        """Update status label and processing label with animation"""
        if message:
            self.status_label.setText(message)
            self.status_label.show()
            
            # Update the processing label with the current status
            # Add an animated ellipsis effect if the message indicates waiting
            waiting_indicators = ["processing", "creating", "generating", "waiting", "preparing"]
            
            if any(indicator in message.lower() for indicator in waiting_indicators):
                # The loading indicator will show animation, so keep text clean
                self.processing_label.setText(message)
            else:
                # For completion messages, no need for ellipsis
                self.processing_label.setText(message)
        else:
            self.status_label.hide()
        
        # Force immediate UI update
        QApplication.processEvents()

    def show_window(self):
        """Show the window and bring it to front"""
        self.show()
        self.activateWindow()

    def process_event(self):
        """Process the natural language input and create calendar event"""
        # Initialize API client on first use
        if not self.api_client:
            api_key = os.environ.get('GEMINI_API_KEY')
            if not api_key:
                raise RuntimeError("Missing environment variable gemini_api_key")
            self.api_client = CalendarAPIClient(api_key=api_key)

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
        self.show_progress_signal.emit(True)

        # Pass image data to the thread
        threading.Thread(
            target=self._create_event_thread, 
            args=(event_description, self.image_area.image_data.copy())
        ).start()

    def _create_event_thread(self, event_description, image_data):
        try:
            # Lazy load subprocess
            import subprocess
            
            # Get the directory where Calender.py is located.
            script_dir = Path(__file__).parent.absolute()
            
            # Get ICS content from API.
            raw_content = self.api_client.create_calendar_event(
                event_description,
                image_data,
                lambda message: self.update_status_signal.emit(message)
            )

            if not raw_content:
                raise Exception("Failed to get response from API after multiple retries")

            # Imitate catching the "<ics_file_X>" mechanism:
            # Look for content enclosed in <ics_file_1>, <ics_file_2>, etc.
            ics_files = re.findall(r'<ics_file_\d+>(.*?)</ics_file_\d+>', raw_content, re.DOTALL)

            # If the wrapped tags aren't present, assume the entire response is a single valid ICS event.
            if not ics_files:
                ics_files = [raw_content.strip()]

            self.update_status_signal.emit(f"Processing {len(ics_files)} event(s)...")

            # Process each ICS file.
            for idx, ics_content in enumerate(ics_files, 1):
                # Clean up the content.
                ics_content = ics_content.strip()

                # Generate a unique filename for each event.
                filename = script_dir / f"event_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{idx}.ics"
                
                # Save the ICS content to a file.
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(ics_content)
                
                # Open the file with the default calendar application.
                subprocess.run(['open', str(filename)])
                
                self.update_status_signal.emit(f"Processed event {idx}/{len(ics_files)}")

            event_text = "events" if len(ics_files) > 1 else "event"
            self.update_status_signal.emit(f"Successfully created {len(ics_files)} {event_text}!")

            # Clear the text input and update the UI.
            self.clear_input_signal.emit()

        except Exception as e:
            self.update_status_signal.emit("Error: Failed to create event(s)")
            QTimer.singleShot(0, self._show_error, Qt.ConnectionType.QueuedConnection, Q_ARG(str, str(e)))
        finally:
            self.enable_ui_signal.emit(True)
            self.show_progress_signal.emit(False)
            # Clear attachments after processing.
            self.clear_attachments()

    def _enable_ui(self, enabled: bool):
        """Enable or disable UI elements with overlay"""
        self.text_input.setEnabled(enabled)
        self.create_button.setEnabled(enabled)
        self.image_area.setEnabled(enabled)
        
        if enabled:
            self.overlay.hide()
            self.loading_indicator.stop_animation()
            self.processing_label.setText("Processing Request...")
        else:
            # Show overlay with blur effect
            self.overlay.show()
            
            # Start the loading animation
            self.loading_indicator.start_animation()

    def _clear_input(self):
        """Clear the text input"""
        self.text_input.clear()

    def _show_progress(self, show: bool):
        """Show or hide progress bar with smooth animation"""
        if show:
            self.progress.show()
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self._animate_progress()
        else:
            self.progress_animation.stop()
            self.progress.hide()

    def _animate_progress(self):
        """Create smooth indeterminate progress animation"""
        # Lazy load QPropertyAnimation
        from PyQt6.QtCore import QPropertyAnimation
        
        current_value = self.progress.value()
        if current_value >= 100:
            self.progress.setValue(0)
            current_value = 0

        self.progress_animation = QPropertyAnimation(self.progress, b"value")
        self.progress_animation.setDuration(2000)
        self.progress_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.progress_animation.setStartValue(current_value)
        self.progress_animation.setEndValue(100)
        self.progress_animation.finished.connect(self._restart_progress_animation)
        self.progress_animation.start()

    def _restart_progress_animation(self):
        """Restart the progress animation when it finishes"""
        if self.progress.isVisible():  # Only restart if still processing
            self.progress.setValue(0)
            self._animate_progress()

    def _show_error(self, message: str):
        """Show error message box (called from main thread)"""
        QMessageBox.critical(self, "Error", message)

    def clear_attachments(self):
        """Clear all attached images"""
        self.image_area.reset_state()
        self.clear_attachments_btn.hide()

    def resizeEvent(self, event):
        """Handle resize events to keep overlay properly sized"""
        super().resizeEvent(event)
        self.overlay.resize(self.size())


if __name__ == '__main__':
    app = QApplication(sys.argv)
    
    # Set the application-wide icon
    app.setWindowIcon(QIcon("calendar-svg-simple.png"))
    
    window = NLCalendarCreator()
    window.show()
    
    # Start the main event loop
    sys.exit(app.exec())
