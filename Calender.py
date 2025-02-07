import sys
import os
from datetime import datetime
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                           QTextEdit, QPushButton, QLabel, QMessageBox,
                           QProgressBar, QHBoxLayout)
from PyQt6.QtGui import QKeySequence, QShortcut, QIcon, QDragEnterEvent, QDropEvent, QPixmap
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QMetaObject, QPropertyAnimation, QEasingCurve, QMimeData, QBuffer
import google.generativeai as genai
import time
from typing import Optional
import subprocess
import random
import threading
import re
import base64
import mimetypes
from pathlib import Path
import tempfile


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
        Robust drop event handler that first attempts to extract in-memory image data.
        It falls back to processing file URLs if in-memory data is not available.
        This version creates temporary copies of the images to ensure the file exists later.
        """
        mime = event.mimeData()
        valid_images = []

        # In-memory image data handling
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
                    # Create a temporary file to store the image data.
                    temp_fd, temp_path = tempfile.mkstemp(suffix=".png")
                    with os.fdopen(temp_fd, 'wb') as f:
                        f.write(bytes(bdata))
                    valid_images.append((temp_path, "image/png", base64_data))
                    buffer.close()
            except Exception as e:
                print("Error processing in-memory image:", e)

        # Fallback: process dropped file URLs.
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
    """Separated API logic while using Gemini API as service provider for calendar event creation."""
    def __init__(self, api_key: str):
        genai.configure(api_key=api_key)
        self.generation_config = {
            "temperature": 0,
            "top_p": 0.3,
            "top_k": 64,
            "max_output_tokens": 8192,
            "response_mime_type": "text/plain",
        }
        self.model = genai.GenerativeModel(
            model_name="gemini-2.0-flash-lite-preview-02-05",
            generation_config=self.generation_config,
            system_instruction="""You are an AI assistant specialized in creating .ics files for macOS calendar events. Your task is to generate the content of one or more .ics files based on the provided event details. These files will allow users to easily import events into their macOS Calendar application, complete with all necessary information and alarm reminders.

First, here are the event details you need to process:

<event_description>
{event_description}
</event_description>

Today's date is {day_name}, {formatted_date}. Use this as a reference when processing relative dates (like "tomorrow" or "next week").

Follow these steps to create the .ics file content:

1. Carefully parse the event details to identify if there are multiple events described. If so, separate them for individual processing.

2. For each event, extract all relevant information such as event title, date, time, location, description, and any other provided details.

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
   1. ALL datetime fields MUST include:
      - T between date and time (e.g., 20241025T130000Z)
      - Z suffix for UTC timezone
   2. NO spaces before or after colons
   3. Line endings must be CRLF (\r\n)
   4. Proper content escaping:
      - Commas: text\, more text
      - Semicolons: text\; more text
      - Newlines: text\n more text
   
   CLOSING STRUCTURE:
   - END:VEVENT
   - END:VCALENDAR

4. Ensure all text is properly escaped, replacing any newline characters in the SUMMARY, LOCATION, or DESCRIPTION fields with "\\n".
5. Wrap each complete .ics file content in numbered <ics_file_X> tags, where X is the event number (starting from 1).

Here's a detailed breakdown of the .ics file structure:

```
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Your Company//Your Product//EN
BEGIN:VEVENT
UID:YYYYMMDDTHHMMSSZ-identifier@domain.com
DTSTAMP:20241027T120000Z           # Current time, must include T and Z
DTSTART:20241118T200000Z           # Must include T and Z
DTEND:20241118T210000Z             # Must include T and Z
SUMMARY:Event Title
LOCATION:Location with\\, escaped commas
DESCRIPTION:Description with\\, escaped commas\\; and semicolons\\nand newlines
BEGIN:VALARM
ACTION:DISPLAY
DESCRIPTION:Reminder
TRIGGER:-PT30M
END:VALARM
END:VEVENT
END:VCALENDAR
```
"""
        )
        self.base_delay = 1
        self.max_retries = 5

    def upload_to_gemini(self, path, mime_type=None):
        """Uploads the given file to Gemini.
        
        See https://ai.google.dev/gemini-api/docs/prompting_with_media
        """
        file = genai.upload_file(path, mime_type=mime_type)
        print(f"Uploaded file '{file.display_name}' as: {file.uri}")
        return file

    def create_calendar_event(self, event_description: str, image_data: list[tuple[str, str, str]],
                              status_callback: callable) -> Optional[str]:
        """
        Create calendar event with enhanced error handling and status updates.
        Modified to support both text and image attachments.
        Args:
            event_description: Text description of the event.
            image_data: List of tuples containing (file_path, mime_type, base64_data).
                        (Note: Updated dropEvent should store the file_path in addition to the original data.)
            status_callback: Callback for status updates.
        Returns: ics_content or None on failure.
        """
        print("DEBUG: create_calendar_event called with event_description length:", len(event_description),
              "and", len(image_data), "images")
        current_date = datetime.now()
        day_name = current_date.strftime("%A")
        formatted_date = current_date.strftime("%B %d, %Y")
        
        # Build the API prompt as before:
        api_prompt = f"""You are an AI assistant specialized in creating .ics files for macOS calendar events. Your task is to generate the content of one or more .ics files based on the provided event details. These files will allow users to easily import events into their macOS Calendar application, complete with all necessary information and alarm reminders.

First, here are the event details you need to process:

<event_description>
{event_description}
</event_description>

Today's date is {day_name}, {formatted_date}. Use this as a reference when processing relative dates (like "tomorrow" or "next week").

Follow these steps to create the .ics file content:

1. Carefully parse the event details to identify if there are multiple events described. If so, separate them for individual processing.

2. For each event, extract all relevant information such as event title, date, time, location, description, and any other provided details.

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
   1. ALL datetime fields MUST include:
      - T between date and time (e.g., 20241025T130000Z)
      - Z suffix for UTC timezone
   2. NO spaces before or after colons
   3. Line endings must be CRLF (\r\n)
   4. Proper content escaping:
      - Commas: text\, more text
      - Semicolons: text\; more text
      - Newlines: text\n more text
   
   CLOSING STRUCTURE:
   - END:VEVENT
   - END:VCALENDAR

4. Ensure all text is properly escaped, replacing any newline characters in the SUMMARY, LOCATION, or DESCRIPTION fields with "\\n".
5. Wrap each complete .ics file content in numbered <ics_file_X> tags, where X is the event number (starting from 1).

Here's a detailed breakdown of the .ics file structure:

BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Your Company//Your Product//EN
BEGIN:VEVENT
UID:YYYYMMDDTHHMMSSZ-identifier@domain.com
DTSTAMP:20250207T120000Z           # Current time, must include T and Z
DTSTART:20250207T200000Z           # Must include T and Z
DTEND:20250207T210000Z             # Must include T and Z
SUMMARY:Event Title
LOCATION:Location with\\, escaped commas
DESCRIPTION:Description with\\, escaped commas\\; and semicolons\\nand newlines
BEGIN:VALARM
ACTION:DISPLAY
DESCRIPTION:Reminder
TRIGGER:-PT30M
END:VALARM
END:VEVENT
END:VCALENDAR
"""
        
        for attempt in range(self.max_retries):
            try:
                status_callback(f"Attempting to create event... (Try {attempt + 1}/{self.max_retries})")
                print(f"DEBUG: Attempt {attempt + 1}/{self.max_retries}")
                print("DEBUG: Generated API prompt (first 200 chars):", api_prompt[:200])
                
                # Prepare chat history:
                history = []
                if image_data:
                    # Upload each image and accumulate the resulting file objects.
                    image_parts = []
                    for img in image_data:
                        # Unpack assuming each tuple is (file_path, mime_type, base64_data)
                        file_path, mime_type, _ = img  
                        uploaded_file = self.upload_to_gemini(file_path, mime_type=mime_type)
                        image_parts.append(uploaded_file)
                    # Attach the images in the initial history message.
                    history.append({
                        "role": "user",
                        "parts": image_parts
                    })
                
                # Start the chat session with the image history (if available).
                chat_session = self.model.start_chat(history=history)
                # Send the text prompt as a follow-up message.
                message = chat_session.send_message(api_prompt)
                
                # Instead of checking for a non-existent GenerativeContent type,
                # use getattr() to extract the text attribute if it exists.
                response_text = getattr(message, 'text', None)
                if response_text is None:
                    response_text = str(message)
                
                print("DEBUG: API Response (first 200 chars):", response_text[:200])
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

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main horizontal layout with equal spacing
        main_layout = QHBoxLayout(central_widget)
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
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
                align-self: center;
            }
            QPushButton:hover {
                background-color: #FF453A;
            }
        """)
        self.clear_attachments_btn.hide()
        
        # Add components to right panel
        right_layout.addWidget(image_label, 0)
        right_layout.addWidget(self.image_area, 1)  # 1 = stretch to fill space
        right_layout.addWidget(self.clear_attachments_btn, 0)
        
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
        self.progress_animation = QPropertyAnimation(self.progress, b"value")
        self.progress_animation.setDuration(2000)  # 2 seconds per cycle
        self.progress_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)

        # Previous styling remains the same
        self.setStyleSheet("""
            QWidget {
                font-family: 'Arial', 'Arial', sans-serif;
                font-size: 13px;
                color: #FFFFFF;
                background-color: #1E1E1E;
            }
            QLabel {
                font-size: 13px;
                color: #FFFFFF;
                background: transparent;
            }
            QTextEdit {
                color: #FFFFFF;
                background-color: #2D2D2D;
                border: 1px solid #3F3F3F;
                border-radius: 8px;
                padding: 12px;
                margin: 8px 0;
                line-height: 1.4;
            }
            QTextEdit:focus {
                border: 1px solid #0A84FF;
                background-color: #363636;
            }
            QPushButton {
                background-color: #0A84FF;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #0071E3;
            }
            QPushButton:pressed {
                background-color: #006CDC;
            }
            QProgressBar {
                border: none;
                background: #2D2D2D;
                height: 2px;
            }
            QProgressBar::chunk {
                background-color: #0A84FF;
            }
        """)

        # Initialize API client
        api_key = ""
        if not api_key:
            raise RuntimeError("Missing environment variable MY_API_KEY")
        self.api_client = CalendarAPIClient(api_key=api_key)

        # Keyboard shortcut
        self.shortcut = QShortcut(QKeySequence("Ctrl+Shift+E"), self)
        self.shortcut.activated.connect(self.show_window)

        # Progress animation
        self.progress_timer = QTimer()
        self.progress_timer.timeout.connect(self._update_progress)
        self.progress_value = 0

        # Connect the signal to the update_status method
        self.update_status_signal.connect(self.update_status)
        # Connect new signals
        self.enable_ui_signal.connect(self._enable_ui)
        self.clear_input_signal.connect(self._clear_input)
        self.show_progress_signal.connect(self._show_progress)

    def _update_progress(self):
        """Update progress bar animation"""
        self.progress_value = (self.progress_value + 1) % 100
        self.progress.setValue(self.progress_value)

    def update_status(self, message: str):
        """Update status label and process events"""
        if message:
            self.status_label.setText(message)
            self.status_label.show()
        else:
            self.status_label.hide()
        QApplication.processEvents()

    def show_window(self):
        """Show the window and bring it to front"""
        self.show()
        self.activateWindow()

    def process_event(self):
        """Process the natural language input and create calendar event"""
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
            # Get the directory where Calender.py is located
            script_dir = Path(__file__).parent.absolute()
            
            # Get ICS content from API
            raw_content = self.api_client.create_calendar_event(
                event_description,
                image_data,
                lambda message: self.update_status_signal.emit(message)
            )

            if not raw_content:
                raise Exception("Failed to get response from API after multiple retries")

            # Extract individual ICS files using regex
            ics_files = re.findall(r'<ics_file_\d+>(.*?)</ics_file_\d+>', 
                                  raw_content, re.DOTALL)

            if not ics_files:
                # Fallback for single event (no tags)
                ics_files = [raw_content]

            self.update_status_signal.emit(f"Processing {len(ics_files)} events...")

            # Process each ICS file
            for idx, ics_content in enumerate(ics_files, 1):
                # Clean up the content (remove any extra whitespace/newlines)
                ics_content = ics_content.strip()
                
                # Generate unique filename for each event, now with correct path
                filename = script_dir / f"event_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{idx}.ics"
                
                # Save to file
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(ics_content)
                
                # Open with default calendar app (convert Path to string)
                subprocess.run(['open', str(filename)])
                
                self.update_status_signal.emit(f"Processed event {idx}/{len(ics_files)}")

            # Final success message
            event_text = "events" if len(ics_files) > 1 else "event"
            self.update_status_signal.emit(f"Successfully created {len(ics_files)} {event_text}!")

            # Clear input and update UI
            self.clear_input_signal.emit()
            
        except Exception as e:
            self.update_status_signal.emit("Error: Failed to create event(s)")
            QTimer.singleShot(0, self._show_error, Qt.ConnectionType.QueuedConnection, Q_ARG(str, str(e)))
        finally:
            self.enable_ui_signal.emit(True)
            self.show_progress_signal.emit(False)
            # Clear attachments after successful creation
            self.clear_attachments()

    def _enable_ui(self, enabled: bool):
        """Enable or disable UI elements"""
        self.text_input.setEnabled(enabled)
        self.create_button.setEnabled(enabled)

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
        # Reset to start if needed
        current_value = self.progress.value()
        if current_value >= 100:
            self.progress.setValue(0)
            current_value = 0

        # Configure animation
        self.progress_animation.setStartValue(current_value)
        self.progress_animation.setEndValue(100)
        
        # Connect finished signal to restart animation
        self.progress_animation.finished.connect(self._restart_progress_animation)
        
        # Start animation
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


if __name__ == '__main__':
    app = QApplication(sys.argv)
    
    # Set the application-wide icon
    app.setWindowIcon(QIcon("calendar-svg-simple.png"))
    
    window = NLCalendarCreator()
    window.show()
    
    # Start the main event loop
    sys.exit(app.exec())

