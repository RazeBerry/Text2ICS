import sys
import os
from datetime import datetime, timedelta
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                           QTextEdit, QPushButton, QLabel, QMessageBox,
                           QProgressBar, QHBoxLayout, QSizePolicy)
from PyQt6.QtGui import QKeySequence, QShortcut, QIcon, QDragEnterEvent, QDropEvent, QPixmap, QPainter, QBrush, QColor
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QMetaObject, QEasingCurve, QMimeData, QBuffer, pyqtSlot, Q_ARG
import time
from typing import Optional, List, Dict, Any
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
import dateutil.parser
from dateutil.relativedelta import relativedelta

# Import the CalendarAPIClient from the new module
from api_client import CalendarAPIClient

# Add at the top of file
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"  # Proper HiDPI support
os.environ["QT_API"] = "pyqt6"  # Explicitly request PyQt6

# Apple Design System - Proper Typography Scale
TYPOGRAPHY_SCALE = {
    "title": {
        "size": "28px", 
        "weight": "600", 
        "line_height": "1.2", 
        "letter_spacing": "-0.02em"
    },
    "headline": {
        "size": "17px", 
        "weight": "600", 
        "line_height": "1.3"
    },
    "body": {
        "size": "15px", 
        "weight": "400", 
        "line_height": "1.4"
    },
    "caption": {
        "size": "13px", 
        "weight": "400", 
        "line_height": "1.3"
    },
    "footnote": {
        "size": "11px", 
        "weight": "400", 
        "line_height": "1.2"
    }
}

# Apple Design System - 8pt Grid Spacing
SPACING_SCALE = {
    "xs": "8px",    # 1 unit
    "sm": "16px",   # 2 units  
    "md": "24px",   # 3 units
    "lg": "32px",   # 4 units
    "xl": "48px",   # 6 units
    "xxl": "64px"   # 8 units
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
    "sm": "8px",
    "md": "12px", 
    "lg": "16px"
}

SHADOW = {
    "sm": "0 1px 3px rgba(0, 0, 0, 0.1)",
    "md": "0 4px 6px rgba(0, 0, 0, 0.1)",
    "lg": "0 10px 25px rgba(0, 0, 0, 0.1)"
}

class ImageAttachmentArea(QLabel):
    """Custom widget for handling image drag and drop"""
    # Add a signal to notify when images are added/cleared
    images_changed = pyqtSignal(bool)  # True when images added, False when cleared
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(int(SPACING_SCALE["xxl"].replace("px", "")))
        self.setStyleSheet(f"""
            QLabel {{
                border: 2px dashed {COLORS['border_medium']};
                border-radius: {BORDER_RADIUS["md"]};
                padding: {SPACING_SCALE["md"]};
                background-color: {COLORS['background_secondary']};
                color: {COLORS['text_tertiary']};
                font-size: {TYPOGRAPHY_SCALE["body"]["size"]};
            }}
            QLabel:hover {{
                border-color: {COLORS['accent_blue']};
                background-color: {COLORS['background_tertiary']};
            }}
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
        self.setStyleSheet(f"""
            QLabel {{
                border: 2px dashed {COLORS['accent_blue']};  /* Change border to blue */
                border-radius: {BORDER_RADIUS["md"]};
                padding: {SPACING_SCALE["md"]};
                background-color: rgba(0, 122, 255, 0.1);  /* Light blue background */
                color: {COLORS['text_primary']};  /* Brighter text */
                font-weight: {TYPOGRAPHY_SCALE["body"]["weight"]};  /* Make text bold */
                font-size: {TYPOGRAPHY_SCALE["body"]["size"]};  /* Slightly larger font */
                line-height: {TYPOGRAPHY_SCALE["body"]["line_height"]};
            }}
            QLabel:hover {{
                border-color: {COLORS['accent_blue']};
                background-color: rgba(0, 122, 255, 0.15);
            }}
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
                border-radius: {BORDER_RADIUS["md"]};
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
            int(SPACING_SCALE["lg"].replace("px", "")), 
            int(SPACING_SCALE["md"].replace("px", "")), 
            int(SPACING_SCALE["lg"].replace("px", "")), 
            int(SPACING_SCALE["md"].replace("px", ""))
        ) # Follow 8pt grid: 32, 24, 32, 24
        outer_layout.setSpacing(int(SPACING_SCALE["md"].replace("px", ""))) # 24px spacing between sections

        # --- 1. Top Title/Subtitle Section ---
        title_layout = QVBoxLayout()
        title_layout.setSpacing(int(SPACING_SCALE["xs"].replace("px", ""))) # 8px between title and subtitle
        title_layout.setContentsMargins(0, 0, 0, int(SPACING_SCALE["sm"].replace("px", ""))) # 16px margin below title section

        title_label = QLabel("Create a Calendar Event")
        title_label.setStyleSheet(f"""
            QLabel {{
                font-size: {TYPOGRAPHY_SCALE["title"]["size"]}; /* Larger font */
                font-weight: {TYPOGRAPHY_SCALE["title"]["weight"]}; /* Semibold */
                color: {COLORS["text_primary"]};
                qproperty-alignment: 'AlignCenter';
            }}
        """)

        subtitle_label = QLabel("Type freely or drop a photo. We'll do the rest.")
        subtitle_label.setStyleSheet(f"""
            QLabel {{
                font-size: {TYPOGRAPHY_SCALE["body"]["size"]};
                color: {COLORS["text_secondary"]};
                qproperty-alignment: 'AlignCenter';
            }}
        """)

        title_layout.addWidget(title_label)
        title_layout.addWidget(subtitle_label)
        outer_layout.addLayout(title_layout)

        # --- 2. Main Content Area (Horizontal Split) ---
        content_layout = QHBoxLayout()
        content_layout.setSpacing(int(SPACING_SCALE["lg"].replace("px", ""))) # 32px spacing between the two columns

        # --- 2a. Left Panel: Event Details ---
        left_panel_layout = QVBoxLayout()
        left_panel_layout.setSpacing(int(SPACING_SCALE["sm"].replace("px", ""))) # 16px spacing between elements

        event_details_title = QLabel("Event Details")
        event_details_title.setStyleSheet(f"""
            QLabel {{
                font-size: {TYPOGRAPHY_SCALE["headline"]["size"]};
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
                border-radius: {BORDER_RADIUS["md"]};
                padding: 0px;
            }}
        """)
        example_input_layout = QVBoxLayout(example_input_container)
        example_input_layout.setContentsMargins(
            int(SPACING_SCALE["sm"].replace("px", "")), 
            int(SPACING_SCALE["sm"].replace("px", "")), 
            int(SPACING_SCALE["sm"].replace("px", "")), 
            int(SPACING_SCALE["sm"].replace("px", ""))
        ) # 16px margins all around
        example_input_layout.setSpacing(int(SPACING_SCALE["xs"].replace("px", ""))) # 8px spacing inside the container

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
        
        self.text_input.setStyleSheet(f"""
            QTextEdit {{
                color: {COLORS["text_primary"]};
                background-color: transparent;
                border: none;
                font-size: {TYPOGRAPHY_SCALE["body"]["size"]};
                line-height: {TYPOGRAPHY_SCALE["body"]["line_height"]};
                padding: {SPACING_SCALE["xs"]} 0px;
            }}
            QTextEdit:focus {{
                border: none;
                outline: none;
                background-color: transparent;
            }}
            QScrollBar:vertical {{
                background: {COLORS["background_secondary"]};
                width: 8px;
                border-radius: 4px;
                margin: 2px;
            }}
            QScrollBar::handle:vertical {{
                background: {COLORS["border_medium"]};
                border-radius: 4px;
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
        self.text_input.textChanged.connect(self.update_live_preview)

        # Add only the text input widget to the layout
        example_input_layout.addWidget(self.text_input)

        left_panel_layout.addWidget(example_input_container)


        # --- Preview Area ---
        preview_title = QLabel("This is what we'll create in your calendar")
        preview_title.setStyleSheet(f"""
            QLabel {{
                font-size: {TYPOGRAPHY_SCALE["caption"]["size"]};
                color: {COLORS["text_secondary"]};
                margin-top: {SPACING_SCALE["xs"]}; /* 8px space above preview */
            }}
        """)
        left_panel_layout.addWidget(preview_title)

        preview_container = QWidget()
        preview_container.setObjectName("previewContainer")
        preview_container.setStyleSheet(f"""
             #previewContainer {{
                 background-color: {COLORS["background_primary"]};
                 border: 1px solid {COLORS["border_light"]};
                 border-radius: {BORDER_RADIUS["lg"]}; /* More rounded corners */
                 padding: {SPACING_SCALE["sm"]} {SPACING_SCALE["md"]}; /* 16px vertical, 24px horizontal */
             }}
         """)
        preview_layout = QVBoxLayout(preview_container) # Changed to vertical layout for cleaner single line
        preview_layout.setContentsMargins(0,0,0,0)
        preview_layout.setSpacing(int(SPACING_SCALE["xs"].replace("px", ""))) # 8px spacing between elements

        # Single line preview with all info
        self.preview_event_title = QLabel("Event title • Date • Time")
        self.preview_event_title.setStyleSheet(f"color: {COLORS['text_tertiary']}; font-size: {TYPOGRAPHY_SCALE['body']['size']}; font-weight: {TYPOGRAPHY_SCALE['body']['weight']};")
        self.preview_event_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Remove the separate date and time labels - we'll combine everything into one line
        preview_layout.addWidget(self.preview_event_title)

        left_panel_layout.addWidget(preview_container)
        left_panel_layout.addStretch(1) # Push content up

        # --- 2b. Right Panel: Photo Attachments ---
        right_panel_layout = QVBoxLayout()
        right_panel_layout.setSpacing(int(SPACING_SCALE["sm"].replace("px", ""))) # 16px spacing between elements

        photo_title = QLabel("Photo Attachments")
        photo_title.setStyleSheet(f"""
            QLabel {{
                font-size: {TYPOGRAPHY_SCALE["headline"]["size"]};
                font-weight: {TYPOGRAPHY_SCALE["headline"]["weight"]};
                color: {COLORS["text_primary"]};
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
                border: 2px dashed {COLORS['border_medium']};
                border-radius: {BORDER_RADIUS["md"]};
                padding: {SPACING_SCALE["md"]};
                background-color: {COLORS['background_secondary']};
                color: {COLORS['text_tertiary']};
                font-size: {TYPOGRAPHY_SCALE["body"]["size"]};
            }}
            QLabel:hover {{
                border-color: {COLORS['accent_blue']};
                background-color: {COLORS['background_tertiary']};
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
                background-color: {COLORS['accent_blue']};
                color: white;
                border: none;
                border-radius: {BORDER_RADIUS["md"]}; 
                padding: {SPACING_SCALE["md"]} {SPACING_SCALE["xl"]};
                font-size: {TYPOGRAPHY_SCALE["body"]["size"]}; 
                font-weight: 600; /* Semi-bold for better accessibility */
                box-shadow: {SHADOW["sm"]};
            }}
            QPushButton:hover {{
                background-color: {COLORS['accent_blue_hover']};
                transform: translateY(-1px); /* Subtle lift effect */
            }}
            QPushButton:pressed {{
                background-color: {COLORS['accent_blue_pressed']};
                transform: translateY(0px); /* Reset lift on press */
            }}
            QPushButton:disabled {{
                background-color: {COLORS['accent_blue_disabled']};
                color: {COLORS['text_tertiary']};
                box-shadow: none;
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
                border-radius: {BORDER_RADIUS["md"]}; /* Match parent container */
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
                font-size: {TYPOGRAPHY_SCALE["caption"]["size"]};
                font-weight: {TYPOGRAPHY_SCALE["caption"]["weight"]};
                padding: {SPACING_SCALE["md"]} {SPACING_SCALE["lg"]};
                background-color: rgba(255, 255, 255, 0.7); /* White-ish box */
                border-radius: {BORDER_RADIUS["md"]};
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

    def update_live_preview(self):
        """Update preview in real-time as user types"""
        text = self.text_input.toPlainText().strip()
        
        if not text:
            # Reset to placeholder state
            self.preview_event_title.setText("Event title • Date • Time")
            self.preview_event_title.setStyleSheet(f"color: {COLORS['text_tertiary']}; font-size: {TYPOGRAPHY_SCALE['body']['size']}; font-weight: {TYPOGRAPHY_SCALE['body']['weight']};")
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
            self.preview_event_title.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: {TYPOGRAPHY_SCALE['body']['size']}; font-weight: {TYPOGRAPHY_SCALE['body']['weight']};")
        else:
            self.preview_event_title.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: {TYPOGRAPHY_SCALE['body']['size']}; font-weight: {TYPOGRAPHY_SCALE['body']['weight']};")

    def parse_event_text(self, text: str) -> Dict[str, Optional[str]]:
        """Parse natural language text to extract event information"""
        result = {
            'title': None,
            'date': None,
            'time': None,
            'location': None
        }
        
        text_lower = text.lower()
        
        # Extract time patterns
        time_patterns = [
            r'(\d{1,2}:\d{2}\s*(?:am|pm))',  # 7:30pm, 7:30 pm
            r'(\d{1,2}\s*(?:am|pm))',       # 7pm, 7 pm
            r'(\d{1,2}:\d{2})',             # 24-hour format 19:30
        ]
        
        for pattern in time_patterns:
            match = re.search(pattern, text_lower)
            if match:
                result['time'] = match.group(1).strip()
                break
        
        # Extract date patterns
        date_patterns = [
            r'(next\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))',
            r'(this\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))',
            r'((?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))',
            r'(tomorrow)',
            r'(today)',
            r'(next week)',
            r'(this week)',
            r'(\d{1,2}/\d{1,2})',           # 3/15, 03/15
            r'(\d{1,2}-\d{1,2})',           # 3-15, 03-15
            r'((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2})',  # Mar 30, March 30
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, text_lower)
            if match:
                date_str = match.group(1).strip()
                result['date'] = self.format_date_display(date_str)
                break
        
        # Extract potential title by removing date/time/common location words
        title_text = text
        if result['time']:
            title_text = re.sub(re.escape(result['time']), '', title_text, flags=re.IGNORECASE).strip()
        
        # Remove common date expressions
        date_remove_patterns = [
            r'\b(?:next|this)\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b',
            r'\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b',
            r'\b(?:tomorrow|today)\b',
            r'\b(?:next|this)\s+week\b',
            r'\d{1,2}/\d{1,2}',
            r'\d{1,2}-\d{1,2}',
            r'\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}\b',
        ]
        
        for pattern in date_remove_patterns:
            title_text = re.sub(pattern, '', title_text, flags=re.IGNORECASE).strip()
        
        # Remove common prepositions and clean up
        title_text = re.sub(r'\b(?:at|on|in|for|with)\s+', ' ', title_text, flags=re.IGNORECASE)
        title_text = re.sub(r'\s+', ' ', title_text).strip()
        
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
            days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
            for i, day in enumerate(days):
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
            
            # Try to parse other date formats
            try:
                parsed_date = dateutil.parser.parse(date_str, fuzzy=True)
                return parsed_date.strftime('%b %d')
            except:
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
