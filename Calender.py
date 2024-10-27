import sys
import os
from datetime import datetime
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                           QTextEdit, QPushButton, QLabel, QMessageBox,
                           QProgressBar)
from PyQt6.QtGui import QKeySequence, QShortcut, QIcon
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QMetaObject
import anthropic
import time
from typing import Optional
import subprocess
import random
import threading
import re


class CalendarAPIClient:
    """Separated API logic while maintaining synchronous structure"""
    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.base_delay = 1
        self.max_retries = 5

    def create_calendar_event(self, event_description: str, 
                            status_callback: callable) -> Optional[str]:
        """
        Create calendar event with enhanced error handling and status updates
        Returns: ics_content or None on failure
        """
        # Add these lines at the start of the method
        current_date = datetime.now()
        day_name = current_date.strftime("%A")
        formatted_date = current_date.strftime("%B %d, %Y")
        
        for attempt in range(self.max_retries):
            try:
                status_callback(f"Attempting to create event... (Try {attempt + 1}/{self.max_retries})")
                
                message = self.client.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=4096,
                    temperature=0,
                    messages=[{
                        "role": "user",
                        "content": [{"type": "text", "text": f"""
                                     "You are an AI assistant specialized in creating .ics files for macOS calendar events. Your task is to generate the content of one or more .ics files based on the provided event details. These files will allow users to easily import events into their macOS Calendar application, complete with all necessary information and alarm reminders.\n\nFirst, here are the event details you need to process:\n\n<event_description>\n{event_description}\n</event_description>\n\nToday's date is {day_name}, {formatted_date}. Use this as a reference when processing relative dates (like \"tomorrow\" or \"next week\").\n\nFollow these steps to create the .ics file content:\n\n1. Carefully parse the event details to identify if there are multiple events described. If so, separate them for individual processing.\n\n2. For each event, extract all relevant information such as event title, date, time, location, description, and any other provided details.\n\n3. Generate the .ics file content using the following strict formatting rules:\n\n   REQUIRED CALENDAR STRUCTURE:\n   - BEGIN:VCALENDAR\n   - VERSION:2.0 (mandatory)\n   - PRODID:-//Your identifier//EN (mandatory)\n   \n   REQUIRED EVENT FORMATTING:\n   - BEGIN:VEVENT\n   - UID: Generate unique using format YYYYMMDDTHHMMSSZ-identifier@domain\n   - DTSTAMP: Current time in format YYYYMMDDTHHMMSSZ\n   - DTSTART: Event start in format YYYYMMDDTHHMMSSZ\n   - DTEND: Event end in format YYYYMMDDTHHMMSSZ\n   - SUMMARY: Event title\n   - DESCRIPTION: Properly escaped text using backslash before commas, semicolons, and newlines (\\, \\; \\n)\n   \n   OPTIONAL BUT RECOMMENDED:\n   - LOCATION: Venue details with proper escaping\n   - CATEGORIES: Event type/category\n   \n   REMINDER STRUCTURE:\n   - BEGIN:VALARM\n   - ACTION:DISPLAY\n   - DESCRIPTION:Reminder\n   - TRIGGER:-PT30M (or your preferred timing)\n   - END:VALARM\n   \n   CRITICAL FORMATTING RULES:\n   1. ALL datetime fields MUST include:\n      - T between date and time (e.g., 20241025T130000Z)\n      - Z suffix for UTC timezone\n   2. NO spaces before or after colons\n   3. Line endings must be CRLF (\\\\r\\\\n)\n   4. Proper content escaping:\n      - Commas: text\\, more text\n      - Semicolons: text\\; more text\n      - Newlines: text\\n more text\n   \n   CLOSING STRUCTURE:\n   - END:VEVENT\n   - END:VCALENDAR\n\n4. Ensure all text is properly escaped, replacing any newline characters in the SUMMARY, LOCATION, or DESCRIPTION fields with \"\\n\".\n\n5. Wrap each complete .ics file content in numbered <ics_file_X> tags, where X is the event number (starting from 1).\n\nHere's a detailed breakdown of the .ics file structure:\n\n```\nBEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Your Company//Your Product//EN\nBEGIN:VEVENT\nUID:YYYYMMDDTHHMMSSZ-identifier@domain.com\nDTSTAMP:20241027T120000Z           # Current time, must include T and Z\nDTSTART:20241118T200000Z           # Must include T and Z\nDTEND:20241118T210000Z             # Must include T and Z\nSUMMARY:Event Title\nLOCATION:Location with\\, escaped commas\nDESCRIPTION:Description with\\, escaped commas\\; and semicolons\\nand newlines\nBEGIN:VALARM\nACTION:DISPLAY\nDESCRIPTION:Reminder\nTRIGGER:-PT30M\nEND:VALARM\nEND:VEVENT\nEND:VCALENDAR\n```\n\nIf any required information is missing from the event details, use reasonable defaults or omit the field if it's optional. If you're unable to create a valid .ics file due to insufficient information, explain what details are missing and what the user needs to provide.\n\nRemember to pay special attention to the LOCATION field, as it's particularly important for calendar events.\n\nBefore generating the final output, wrap your thought process in <thinking> tags. Include the following steps:\na. Identify and list each event separately\nb. For each event, extract and list all relevant details (title, date, time, location, description)\nc. Note any missing information and how it will be handled\nd. Outline the structure of the .ics file, including how each piece of information will be formatted\n\nYour final output should only contain the .ics file content(s) wrapped in the appropriate tags, with no additional explanation or commentary."
                """}]
                    }])

                return message.content[0].text if isinstance(message.content, list) else message.content

            except anthropic.APIError as e:
                if "rate_limit" in str(e):
                    delay = min(300, self.base_delay * (2 ** attempt))
                    jitter = delay * 0.1 * random.random()
                    status_callback(f"Rate limited, waiting {delay:.1f} seconds...")
                    time.sleep(delay + jitter)
                    continue
                if attempt < self.max_retries - 1:
                    continue
                raise
                
            except Exception as e:
                if attempt < self.max_retries - 1:
                    delay = self.base_delay * (2 ** attempt)
                    status_callback(f"Error occurred, retrying in {delay} seconds...")
                    time.sleep(delay)
                    continue
                raise
                
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
        self.setFixedSize(600, 300)

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
        self.api_client = CalendarAPIClient(
            api_key=os.getenv("ANTHROPIC_API_KEY")
        )

        # Create central widget and layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # Status label - initially hidden
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
        self.status_label.hide()  # Initially hidden
        layout.addWidget(self.status_label)

        # Update the instruction label styling and text
        instruction_label = QLabel(
            "Create a Calendar Event Using Natural Language!!"
        )
        instruction_label.setStyleSheet("""
            QLabel {
                font-size: 16px;
                font-weight: 600;
                color: #FFFFFF;
                margin-bottom: 4px;
            }
        """)
        layout.addWidget(instruction_label)

        # Add a subtitle label with example
        example_label = QLabel(
            "Examples:\n"
            "• Team standup on Monday at 10am for 30 minutes\n"
            "• Lunch with Sarah at Cafe Luna next Thursday 12:30pm\n"
            "• Dentist appointment on March 15th at 2pm"
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
        layout.addWidget(example_label)

        # Text input area
        self.text_input = QTextEdit()
        self.text_input.setFixedHeight(100)
        self.text_input.setStyleSheet("""
            QTextEdit {
                color: #FFFFFF;
                background-color: #2D2D2D;
                border: 1px solid #3F3F3F;
                border-radius: 8px;
                padding: 12px;
                margin: 8px 0;
                line-height: 1.6;
                font-size: 14px;
            }
            QTextEdit:focus {
                border: 1px solid #0A84FF;
                background-color: #363636;
            }
        """)
        self.text_input.setPlaceholderText("Type your event details here...")
        layout.addWidget(self.text_input)

        # Add progress bar
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(2)
        self.progress.hide()
        layout.addWidget(self.progress)

        # Add spacing
        layout.addSpacing(8)

        # Create button
        self.create_button = QPushButton("Create Event")
        self.create_button.clicked.connect(self.process_event)
        self.create_button.setStyleSheet("""
            QPushButton {
                background-color: #0A84FF;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 14px;
                font-weight: 500;
                min-height: 36px;
                letter-spacing: 0.2px;
            }
            QPushButton:hover {
                background-color: #0071E3;
                transform: scale(1.01);
                transition: all 0.15s ease;
            }
            QPushButton:pressed {
                background-color: #006CDC;
                transform: scale(0.99);
            }
        """)
        layout.addWidget(self.create_button)

        # Reduce spacing after button
        layout.addSpacing(4)

        # Window flags
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint)

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
        event_description = self.text_input.toPlainText()
        
        if not event_description.strip():
            self.status_label.setText("Please enter an event description")
            return

        # Use signals to update UI
        self.enable_ui_signal.emit(False)
        self.show_progress_signal.emit(True)

        # Run the API call in a separate thread
        threading.Thread(target=self._create_event_thread, args=(event_description,)).start()

    def _create_event_thread(self, event_description):
        try:
            # Get ICS content from API
            raw_content = self.api_client.create_calendar_event(
                event_description,
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
                
                # Generate unique filename for each event
                filename = f"event_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{idx}.ics"
                
                # Save to file
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(ics_content)
                
                # Open with default calendar app
                subprocess.run(['open', filename])
                
                self.update_status_signal.emit(f"Processed event {idx}/{len(ics_files)}")

            # Final success message
            event_text = "events" if len(ics_files) > 1 else "event"
            self.update_status_signal.emit(f"Successfully created {len(ics_files)} {event_text}!")

            # Clear input and update UI
            self.clear_input_signal.emit()
            
        except Exception as e:
            self.update_status_signal.emit("Error: Failed to create event(s)")
            QMetaObject.invokeMethod(self, "_show_error",
                                   Qt.ConnectionType.QueuedConnection,
                                   Q_ARG(str, str(e)))
        finally:
            self.enable_ui_signal.emit(True)
            self.show_progress_signal.emit(False)

    def _enable_ui(self, enabled: bool):
        """Enable or disable UI elements"""
        self.text_input.setEnabled(enabled)
        self.create_button.setEnabled(enabled)

    def _clear_input(self):
        """Clear the text input"""
        self.text_input.clear()

    def _show_progress(self, show: bool):
        """Show or hide progress bar"""
        if show:
            self.progress.show()
            self.progress.setRange(0, 0)
            self.progress_timer.start(50)
        else:
            self.progress.hide()
            self.progress_timer.stop()

    def _show_error(self, message: str):
        """Show error message box (called from main thread)"""
        QMessageBox.critical(self, "Error", message)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    
    # Set the application-wide icon
    app.setWindowIcon(QIcon("/Users/sihao/Downloads/icons8-calender-85.png"))
    
    window = NLCalendarCreator()
    window.show()
    
    # Start the main event loop
    sys.exit(app.exec())
