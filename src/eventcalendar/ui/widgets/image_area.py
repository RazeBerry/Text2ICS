"""Image attachment area widget for drag-and-drop image handling.

Anthropic-Inspired Design System
================================
A refined drop zone with warm terracotta accents, subtle dashed borders,
and atmospheric feedback states. The design feels inviting rather than
utilitarian.
"""

import base64
import logging
import mimetypes
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from PyQt6.QtCore import Qt, pyqtSignal, QByteArray
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QPixmap
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QFrame

from eventcalendar.config.constants import SUPPORTED_IMAGE_EXTENSIONS
from eventcalendar.ui.theme.colors import get_color
from eventcalendar.ui.theme.scales import SPACING_SCALE, BORDER_RADIUS, FONT_SANS
from eventcalendar.ui.styles.base import px

logger = logging.getLogger(__name__)


@dataclass
class ImageAttachmentPayload:
    """Payload for an attached image."""
    source_path: str
    mime_type: str
    temp_path: Optional[str] = None
    base64_data: Optional[str] = None

    def materialize(self, include_base64: bool = True) -> Tuple[str, str, Optional[str]]:
        """Get the file path, MIME type, and optionally base64 data.

        Returns:
            Tuple of (path, mime_type, base64_data).
        """
        path = self.temp_path or self.source_path
        if not path:
            raise ValueError("Image attachment is missing a file path")
        if include_base64 and self.base64_data is None:
            with open(path, "rb") as fh:
                self.base64_data = base64.b64encode(fh.read()).decode("utf-8")
        return path, self.mime_type, (self.base64_data if include_base64 else None)


class ImageAttachmentArea(QFrame):
    """Custom widget for handling image drag and drop.

    Features an Anthropic-inspired design with warm terracotta accents,
    elegant dashed borders, and refined typography.
    """

    # Signal emitted when images are added/cleared
    images_changed = pyqtSignal(bool)  # True when images added, False when cleared

    def __init__(self, parent=None):
        """Initialize the image attachment area.

        Args:
            parent: Parent widget.
        """
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMinimumHeight(SPACING_SCALE["xxl"] * 2)
        self.image_data: List[ImageAttachmentPayload] = []
        self._temp_paths: set = set()
        self._known_sources: set = set()

        self._setup_layout()
        self.setStyleSheet(self._get_base_style())
        self.reset_state()

    def _setup_layout(self) -> None:
        """Set up the internal layout with label, icon and text."""
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setSpacing(SPACING_SCALE["sm"])
        layout.setContentsMargins(
            SPACING_SCALE["md"], SPACING_SCALE["md"],
            SPACING_SCALE["md"], SPACING_SCALE["md"]
        )

        # Section label - using explicit sans-serif
        self.section_label = QLabel("ATTACH IMAGE")
        self.section_label.setStyleSheet(f"""
            QLabel {{
                font-family: {FONT_SANS};
                font-size: 12px;
                font-weight: 600;
                letter-spacing: 0.05em;
                color: {get_color('text_tertiary')};
            }}
        """)
        layout.addWidget(self.section_label)

        # Spacer to push content to center
        layout.addStretch(1)

        # Decorative icon - simple geometric shape
        self.icon_label = QLabel("\u25A1")  # Square symbol
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setStyleSheet(f"""
            QLabel {{
                font-family: {FONT_SANS};
                font-size: 28px;
                color: {get_color('border_medium')};
            }}
        """)
        layout.addWidget(self.icon_label)

        # Primary text - explicit sans-serif to match input placeholder
        self.primary_label = QLabel("Drop image here")
        self.primary_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.primary_label.setWordWrap(True)
        self.primary_label.setStyleSheet(f"""
            QLabel {{
                font-family: {FONT_SANS};
                font-size: 15px;
                font-weight: 400;
                color: {get_color('text_tertiary')};
            }}
        """)
        layout.addWidget(self.primary_label)

        # Secondary text - explicit sans-serif
        self.secondary_label = QLabel("Flyers, screenshots, or photos")
        self.secondary_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.secondary_label.setWordWrap(True)
        self.secondary_label.setStyleSheet(f"""
            QLabel {{
                font-family: {FONT_SANS};
                font-size: 13px;
                font-weight: 400;
                color: {get_color('text_placeholder')};
            }}
        """)
        layout.addWidget(self.secondary_label)

        # Bottom spacer
        layout.addStretch(1)

    def _get_base_style(self) -> str:
        """Generate base style with current theme colors."""
        return f"""
            ImageAttachmentArea {{
                border: 2px dashed {get_color('border_medium')};
                border-radius: {px(BORDER_RADIUS['lg'])};
                background-color: {get_color('background_secondary')};
            }}
            ImageAttachmentArea:hover {{
                border-color: {get_color('accent')};
                background-color: {get_color('background_tertiary')};
            }}
        """

    def _get_dragover_style(self) -> str:
        """Generate style for drag-over state."""
        return f"""
            ImageAttachmentArea {{
                border: 2px dashed {get_color('accent')};
                border-radius: {px(BORDER_RADIUS['lg'])};
                background-color: {get_color('glow_accent')};
            }}
        """

    def _get_active_style(self) -> str:
        """Generate style when images are attached."""
        return f"""
            ImageAttachmentArea {{
                border: 2px solid {get_color('accent')};
                border-radius: {px(BORDER_RADIUS['lg'])};
                background-color: {get_color('glow_accent')};
            }}
        """

    def refresh_theme(self) -> None:
        """Refresh styles after theme change."""
        if self.image_data:
            self.setStyleSheet(self._get_active_style())
            self._update_active_state()
        else:
            self.setStyleSheet(self._get_base_style())
            self._update_empty_state()

    def reset_state(self) -> None:
        """Reset the widget to its initial state."""
        self._cleanup_temp_files()
        self.image_data = []
        self._temp_paths.clear()
        self._known_sources.clear()
        self.setStyleSheet(self._get_base_style())
        self._update_empty_state()
        self.images_changed.emit(False)

    def _update_empty_state(self) -> None:
        """Update labels for empty state."""
        self.section_label.setText("ATTACH IMAGE")
        self.section_label.setStyleSheet(f"""
            QLabel {{
                font-family: {FONT_SANS};
                font-size: 12px;
                font-weight: 600;
                letter-spacing: 0.05em;
                color: {get_color('text_tertiary')};
            }}
        """)
        self.icon_label.setText("\u25A1")  # Empty square
        self.icon_label.setStyleSheet(f"""
            QLabel {{
                font-family: {FONT_SANS};
                font-size: 28px;
                color: {get_color('border_medium')};
            }}
        """)
        self.primary_label.setText("Drop image here")
        self.primary_label.setStyleSheet(f"""
            QLabel {{
                font-family: {FONT_SANS};
                font-size: 15px;
                font-weight: 400;
                color: {get_color('text_tertiary')};
            }}
        """)
        self.secondary_label.setText("Flyers, screenshots, or photos")
        self.secondary_label.setStyleSheet(f"""
            QLabel {{
                font-family: {FONT_SANS};
                font-size: 13px;
                font-weight: 400;
                color: {get_color('text_placeholder')};
            }}
        """)
        self.secondary_label.show()

    def _update_active_state(self) -> None:
        """Update labels when images are attached."""
        count = len(self.image_data)

        # Keep section label but update color to accent
        self.section_label.setText("IMAGE ATTACHED" if count == 1 else f"{count} IMAGES")
        self.section_label.setStyleSheet(f"""
            QLabel {{
                font-family: {FONT_SANS};
                font-size: 12px;
                font-weight: 600;
                letter-spacing: 0.05em;
                color: {get_color('accent')};
            }}
        """)

        self.icon_label.setText("\u2713")  # Checkmark
        self.icon_label.setStyleSheet(f"""
            QLabel {{
                font-family: {FONT_SANS};
                font-size: 28px;
                color: {get_color('accent')};
            }}
        """)

        if count == 1:
            self.primary_label.setText("1 image ready")
        else:
            self.primary_label.setText(f"{count} images ready")

        self.primary_label.setStyleSheet(f"""
            QLabel {{
                font-family: {FONT_SANS};
                font-size: 15px;
                font-weight: 500;
                color: {get_color('text_primary')};
            }}
        """)

        self.secondary_label.setText("Click Create Event to process")
        self.secondary_label.setStyleSheet(f"""
            QLabel {{
                font-family: {FONT_SANS};
                font-size: 13px;
                font-weight: 400;
                color: {get_color('text_secondary')};
            }}
        """)

    def _cleanup_temp_files(self) -> None:
        """Clean up temporary files."""
        for temp_path in list(self._temp_paths):
            try:
                Path(temp_path).unlink(missing_ok=True)
            except Exception as e:
                logger.warning("Failed to delete temp image file '%s': %s", temp_path, e)
            finally:
                self._temp_paths.discard(temp_path)

    def closeEvent(self, event) -> None:
        """Handle widget close event."""
        self._cleanup_temp_files()
        super().closeEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Handle drag enter event."""
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if all(self._is_supported_image(url.toLocalFile()) for url in urls):
                self.setStyleSheet(self._get_dragover_style())
                event.acceptProposedAction()
                return
        elif event.mimeData().hasImage():
            self.setStyleSheet(self._get_dragover_style())
            event.acceptProposedAction()
            return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:
        """Handle drag leave event."""
        if self.image_data:
            self.setStyleSheet(self._get_active_style())
        else:
            self.setStyleSheet(self._get_base_style())
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        """Process dropped images."""
        mime = event.mimeData()
        images = self._process_dropped_content(mime)

        if images:
            self.image_data.extend(images)
            self.setStyleSheet(self._get_active_style())
            self._update_active_state()
            self.images_changed.emit(True)
            event.acceptProposedAction()
        else:
            if self.image_data:
                self.setStyleSheet(self._get_active_style())
            else:
                self.setStyleSheet(self._get_base_style())
            event.ignore()

    def _process_dropped_content(self, mime) -> List[ImageAttachmentPayload]:
        """Extract images from dropped content.

        Args:
            mime: The MIME data from the drop event.

        Returns:
            List of image payloads.
        """
        # Try file URLs first
        if mime.hasUrls():
            images = self._process_file_urls(mime.urls())
            if images:
                return images

        # Fall back to in-memory image
        if mime.hasImage():
            image = self._process_in_memory_image(mime.imageData())
            if image:
                return [image]

        return []

    def _process_file_urls(self, urls) -> List[ImageAttachmentPayload]:
        """Process dropped file URLs.

        Args:
            urls: List of QUrl objects.

        Returns:
            List of image payloads.
        """
        images = []
        for url in urls:
            payload = self._create_payload_from_url(url)
            if payload:
                images.append(payload)
        return images

    def _create_payload_from_url(self, url) -> Optional[ImageAttachmentPayload]:
        """Create image payload from file URL.

        Args:
            url: QUrl for the file.

        Returns:
            ImageAttachmentPayload or None.
        """
        file_path = url.toLocalFile()
        if not self._is_supported_image(file_path):
            return None
        if not os.path.exists(file_path):
            logger.warning("Dropped file does not exist: %s", file_path)
            return None

        canonical = str(Path(file_path).resolve())
        if canonical in self._known_sources:
            return None  # Duplicate

        try:
            temp_path = self._copy_to_temp(canonical)
            mime_type = mimetypes.guess_type(file_path)[0] or 'image/jpeg'
            self._known_sources.add(canonical)
            self._temp_paths.add(temp_path)
            return ImageAttachmentPayload(
                source_path=canonical,
                mime_type=mime_type,
                temp_path=temp_path
            )
        except Exception as e:
            logger.error("Error preparing dropped file '%s': %s", file_path, e)
            return None

    def _process_in_memory_image(self, image_data) -> Optional[ImageAttachmentPayload]:
        """Convert in-memory image data to file-backed payload.

        Args:
            image_data: Image data from MIME.

        Returns:
            ImageAttachmentPayload or None.
        """
        pixmap = self._extract_pixmap(image_data)
        if pixmap is None or pixmap.isNull():
            return None

        try:
            temp_path = self._save_pixmap_to_temp(pixmap)
            self._temp_paths.add(temp_path)
            self._known_sources.add(temp_path)
            return ImageAttachmentPayload(
                source_path=temp_path,
                mime_type="image/png",
                temp_path=temp_path
            )
        except Exception as e:
            logger.error("Error processing in-memory image: %s", e)
            return None

    def _extract_pixmap(self, image_data) -> Optional[QPixmap]:
        """Extract QPixmap from various image data formats.

        Args:
            image_data: Image data in various formats.

        Returns:
            QPixmap or None.
        """
        from PyQt6.QtGui import QImage, QPixmap

        if isinstance(image_data, QImage):
            return QPixmap.fromImage(image_data)
        if isinstance(image_data, QPixmap):
            return image_data

        # Handle QByteArray/bytes payloads
        raw_bytes = None
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
                return QPixmap.fromImage(maybe_image)

        if raw_bytes:
            qimage = QImage.fromData(raw_bytes)
            if not qimage.isNull():
                return QPixmap.fromImage(qimage)

        return None

    def _save_pixmap_to_temp(self, pixmap: QPixmap) -> str:
        """Save a pixmap to a temporary file.

        Args:
            pixmap: QPixmap to save.

        Returns:
            Path to the temporary file.
        """
        from PyQt6.QtCore import QBuffer

        buffer = QBuffer()
        buffer.open(QBuffer.OpenModeFlag.WriteOnly)
        pixmap.save(buffer, "PNG")
        bdata = buffer.data()

        temp_fd, temp_path = tempfile.mkstemp(suffix=".png")
        with os.fdopen(temp_fd, 'wb') as f:
            f.write(bytes(bdata))
        buffer.close()

        return temp_path

    def update_preview(self) -> None:
        """Update the preview based on attached images."""
        if not self.image_data:
            self.reset_state()
            return

        self.setStyleSheet(self._get_active_style())
        self._update_active_state()

    def _is_supported_image(self, file_path: str) -> bool:
        """Check if the file is a supported image format.

        Args:
            file_path: Path to the file.

        Returns:
            True if supported.
        """
        suffix = Path(file_path).suffix.lower()
        return bool(suffix) and suffix in SUPPORTED_IMAGE_EXTENSIONS

    def _copy_to_temp(self, source_path: str) -> str:
        """Copy the file to a managed temporary location.

        Args:
            source_path: Path to the source file.

        Returns:
            Path to the temporary copy.
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
