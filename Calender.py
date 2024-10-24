import sys
import os
from datetime import datetime
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                           QTextEdit, QPushButton, QLabel, QMessageBox,
                           QProgressBar)
from PyQt6.QtGui import QKeySequence, QShortcut, QIcon
from PyQt6.QtCore import Qt, QTimer
import anthropic
import time
from typing import Optional
import subprocess
import random


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
                    max_tokens=1024,
                    temperature=0,
                    messages=[{
                        "role": "user",
                        "content": [{"type": "text", "text": f"""You are a specialized AI assistant tasked with creating .ics files for macOS calendar events. Your job is to generate the content of an .ics file based on the provided event details. This file will allow users to easily import events into their macOS Calendar application, complete with all necessary information and an alarm reminder. Today is {day_name}, {formatted_date}. Please use this as reference when processing relative dates (like "tomorrow" or "next week").

You will be provided with event details in the following variable:

<event_details>
{event_description}
</event_details>

Parse the event details carefully to extract all relevant information such as event title, date, time, location, description, and any other provided details.

To create the .ics file content, follow these steps:

1. Begin the file with the following lines:
   BEGIN:VCALENDAR
   VERSION:2.0
   PRODID:-//Your Company//Your Product//EN

2. Start the event with:
   BEGIN:VEVENT

3. Add the following fields, filling them out based on the provided event details:
   - UID: Generate a unique identifier (e.g., a UUID)
   - DTSTAMP: Current timestamp in the format YYYYMMDDTHHMMSSZ
   - DTSTART: Event start date and time in the format YYYYMMDDTHHMMSS
   - DTEND: Event end date and time in the format YYYYMMDDTHHMMSS
   - SUMMARY: Event title
   - LOCATION: Event location (if provided), Pay this field special attention.
   - DESCRIPTION: Event description (if provided)

4. Create an alarm for the event:
   BEGIN:VALARM
   ACTION:DISPLAY
   DESCRIPTION:Reminder
   TRIGGER:-PT30M
   END:VALARM

   This sets a reminder 30 minutes before the event. Adjust the TRIGGER value if a different reminder time is specified in the event details.

5. End the event and calendar sections:
   END:VEVENT
   END:VCALENDAR

6. Ensure all text is properly escaped. Replace any newline characters in the SUMMARY, LOCATION, or DESCRIPTION fields with "\n".

Present your final .ics file content within <ics_file> tags. Make sure to maintain proper indentation and formatting for readability. 

7. You only ouput the ICS FILE and nothing else. 

If any required information is missing from the event details, use reasonable defaults or omit the field if it's optional. If you're unable to create a valid .ics file due to insufficient information, explain what details are missing and what the user needs to provide."""}]
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

        # Disable input and show progress
        self.text_input.setEnabled(False)
        self.create_button.setEnabled(False)
        self.progress.show()
        self.progress.setRange(0, 0)  # Infinite progress
        self.progress_timer.start(50)  # Start progress animation
        
        try:
            # Call API with status callback
            ics_content = self.api_client.create_calendar_event(
                event_description,
                self.update_status
            )

            if not ics_content:
                raise Exception("Failed to get response from API after multiple retries")

            self.update_status("Generating calendar file...")
            
            # Save to file
            filename = f"event_{datetime.now().strftime('%Y%m%d_%H%M%S')}.ics"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(ics_content)

            self.update_status("Opening calendar application...")
            
            # Open with default calendar app
            subprocess.run(['open', filename])

            # Update success status
            self.update_status("Event created successfully!")

            # Clear input but DON'T hide the window
            self.text_input.clear()
            
        except Exception as e:
            # Show error in both status label and message box
            self.update_status("Error: Failed to create event")
            QMessageBox.critical(self, "Error", str(e))
            
        finally:
            # Reset UI state
            self.text_input.setEnabled(True)
            self.create_button.setEnabled(True)
            self.progress.hide()
            self.progress_timer.stop()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    
    # Set the application-wide icon
    app.setWindowIcon(QIcon("/Users/sihao/Downloads/icons8-calender-85.png"))
    
    window = NLCalendarCreator()
    window.show()
    sys.exit(app.exec())
