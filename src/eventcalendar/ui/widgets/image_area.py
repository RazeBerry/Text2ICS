"""Image attachment area widget for drag-and-drop image handling.

Anthropic-Inspired Design System
================================
A refined drop zone with warm terracotta accents, subtle dashed borders,
and atmospheric feedback states. The design feels inviting rather than
utilitarian.
"""

import logging
import os
import shutil
import tempfile
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import Qt, pyqtSignal, QByteArray, QPointF, QRectF, QSize
from PyQt6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from eventcalendar.config.constants import (
    MAX_IMAGE_ATTACHMENTS,
    MAX_IMAGE_PIXELS,
    SUPPORTED_IMAGE_EXTENSIONS,
)
from eventcalendar.core.image_preprocessing import validate_image_file
from eventcalendar.core.attachments import AttachmentStore, ImageAttachmentPayload
from eventcalendar.ui.theme.colors import get_color
from eventcalendar.ui.theme.scales import SPACING_SCALE, BORDER_RADIUS, FONT_SANS
from eventcalendar.ui.styles.base import px

logger = logging.getLogger(__name__)


class AttachmentStatusIcon(QWidget):
    """Draw a consistently centred attachment-state icon.

    Font symbols have platform-specific baselines and side bearings, which can
    make an otherwise centred label look crooked.  Painting the geometry in a
    fixed square keeps both states optically aligned on every platform.
    """

    _CANVAS_SIZE = 40

    def __init__(self, parent=None):
        super().__init__(parent)
        self._attached = False
        self.setFixedSize(self._CANVAS_SIZE, self._CANVAS_SIZE)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def sizeHint(self) -> QSize:
        """Return the square canvas used by both icon states."""
        return QSize(self._CANVAS_SIZE, self._CANVAS_SIZE)

    def set_attached(self, attached: bool) -> None:
        """Select the empty-image or attached-check state."""
        if self._attached == attached:
            return
        self._attached = attached
        self.update()

    def paintEvent(self, event) -> None:
        """Paint an image outline or checkmark on the same optical centre."""
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        color = QColor(get_color("accent" if self._attached else "border_medium"))
        pen = QPen(color, 2.25)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if self._attached:
            # The circle and path share the exact centre of the 40 px canvas.
            painter.drawEllipse(QPointF(20.0, 20.0), 11.0, 11.0)
            check = QPainterPath(QPointF(14.5, 20.0))
            check.lineTo(18.5, 24.0)
            check.lineTo(25.5, 16.5)
            painter.drawPath(check)
            return

        # A proper image pictogram reads more naturally than a bare square.
        frame = QRectF(8.5, 9.5, 23.0, 21.0)
        painter.drawRoundedRect(frame, 3.0, 3.0)
        painter.drawEllipse(QPointF(25.5, 15.5), 2.0, 2.0)
        landscape = QPainterPath(QPointF(11.5, 27.0))
        landscape.lineTo(17.0, 21.0)
        landscape.lineTo(20.5, 24.5)
        landscape.lineTo(23.0, 22.0)
        landscape.lineTo(28.5, 27.0)
        painter.drawPath(landscape)


class ImageAttachmentArea(QFrame):
    """Custom widget for handling image drag and drop.

    Features an Anthropic-inspired design with warm terracotta accents,
    elegant dashed borders, and refined typography.
    """

    # Signal emitted when images are added/cleared
    images_changed = pyqtSignal(bool)  # True when images added, False when cleared
    processing_changed = pyqtSignal(bool)
    _attachment_ready = pyqtSignal(object)

    def __init__(self, parent=None):
        """Initialize the image attachment area.

        Args:
            parent: Parent widget.
        """
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMinimumHeight(SPACING_SCALE["xxl"] * 2)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._attachments = AttachmentStore(MAX_IMAGE_ATTACHMENTS)
        self._pending_images = 0
        self._pending_sources: set[str] = set()
        self._attachment_generation = 0
        self._closing = False
        self._image_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="attachment_encoder",
        )
        self._attachment_ready.connect(self._finish_attachment)

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

        # Painted icon: explicit geometry avoids platform-dependent glyph
        # baselines and keeps the empty/attached states on the same centre.
        self.status_icon = AttachmentStatusIcon()
        layout.addWidget(
            self.status_icon,
            alignment=Qt.AlignmentFlag.AlignHCenter,
        )

        # Primary text - explicit sans-serif to match input placeholder
        self.primary_label = QLabel("Drop image here or click to browse")
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

        # Route clicks on labels to the parent frame for click-to-browse.
        for label in (self.section_label, self.primary_label, self.secondary_label):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

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
        self._attachment_generation += 1
        self._pending_images = 0
        self._pending_sources.clear()
        self.processing_changed.emit(False)
        self._attachments.clear()
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
        self.status_icon.set_attached(False)
        self.status_icon.update()
        self.primary_label.setText("Drop image here or click to browse")
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

        self.status_icon.set_attached(True)
        self.status_icon.update()

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

    def closeEvent(self, event) -> None:
        """Handle widget close event."""
        self.shutdown()
        super().closeEvent(event)

    def shutdown(self) -> None:
        """Cancel queued encodes and reject results from running ones."""
        if self._closing:
            return
        self._closing = True
        self.reset_state()
        self._image_executor.shutdown(wait=False, cancel_futures=True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Handle drag enter event."""
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            # Drag-enter runs on the Qt thread and can fire repeatedly. Use the
            # extension only as an interaction hint; validate contents once on drop.
            if all(self._has_supported_image_extension(url.toLocalFile()) for url in urls):
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
        if mime.hasUrls():
            if self._queue_file_urls(mime.urls()):
                event.acceptProposedAction()
                return

        if mime.hasImage() and self._queue_in_memory_image(mime.imageData()):
            event.acceptProposedAction()
            return

        if self.image_data:
            self.setStyleSheet(self._get_active_style())
        else:
            self.setStyleSheet(self._get_base_style())
        event.ignore()

    def mousePressEvent(self, event) -> None:
        """Open file picker on left-click for click-to-browse behavior."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._select_images_from_dialog()
            event.accept()
            return
        super().mousePressEvent(event)

    def _select_images_from_dialog(self) -> None:
        """Select image files from a native file picker."""
        parent = self.window() if self.window() is not None else self
        extension_list = sorted(SUPPORTED_IMAGE_EXTENSIONS)
        file_filter = f"Images ({' '.join(f'*{ext}' for ext in extension_list)})"
        file_paths, _ = QFileDialog.getOpenFileNames(
            parent,
            "Select Images",
            "",
            file_filter,
        )
        if not file_paths:
            return

        queued = False
        for file_path in file_paths:
            if not file_path:
                continue
            queued = self._queue_file_path(file_path) or queued
        if not queued:
            logger.debug("No selected images were eligible for preparation")

    def _add_images(self, images: List[ImageAttachmentPayload]) -> bool:
        """Add processed image payloads and refresh widget state."""
        if not images:
            return False
        accepted = self._attachments.add(images)
        if not accepted:
            logger.warning("Image attachment limit (%d) reached", MAX_IMAGE_ATTACHMENTS)
            return False
        if len(accepted) < len(images):
            logger.warning("Only %d images are allowed; ignored %d", MAX_IMAGE_ATTACHMENTS, len(images) - len(accepted))
        self.setStyleSheet(self._get_active_style())
        self._update_active_state()
        self.images_changed.emit(True)
        return True

    def _queue_file_urls(self, urls) -> bool:
        """Queue dropped file URLs for validation and snapshotting.

        Args:
            urls: List of QUrl objects.

        Returns:
            True when at least one path was queued.
        """
        queued = False
        for url in urls:
            queued = self._queue_file_path(url.toLocalFile()) or queued
        return queued

    def _queue_file_path(self, file_path: str) -> bool:
        """Snapshot one local image on the attachment worker."""
        if not self._has_supported_image_extension(file_path) or not os.path.exists(file_path):
            return False
        canonical = str(Path(file_path).resolve())
        if (
            self._attachments.contains_source(canonical)
            or canonical in self._pending_sources
            or self._attachments.remaining_capacity <= self._pending_images
        ):
            return False

        self._pending_sources.add(canonical)
        self._begin_preparation()
        future = self._image_executor.submit(self._create_payload_from_url, canonical)
        future.add_done_callback(
            lambda completed, token=self._attachment_generation, source=canonical: (
                self._publish_attachment_result(token, source, completed)
            )
        )
        return True

    @classmethod
    def _create_payload_from_url(cls, source) -> Optional[ImageAttachmentPayload]:
        """Validate and snapshot a file without touching widget state.

        Args:
            source: QUrl for the file or path-like object.

        Returns:
            ImageAttachmentPayload or None.
        """
        file_path = source.toLocalFile() if hasattr(source, "toLocalFile") else str(source)
        if not cls._has_supported_image_extension(file_path):
            return None
        if not os.path.exists(file_path):
            logger.warning("Dropped file does not exist: %s", Path(file_path).name)
            return None

        canonical = str(Path(file_path).resolve())

        try:
            validated = validate_image_file(canonical)
            temp_path = cls._copy_to_temp(canonical)
            return ImageAttachmentPayload(
                source_path=canonical,
                mime_type=validated.mime_type,
                temp_path=temp_path
            )
        except Exception as e:
            logger.error("Error preparing dropped file '%s': %s", Path(file_path).name, e)
            return None

    def _queue_in_memory_image(self, image_data) -> bool:
        """Queue an in-memory image without encoding pixels on the Qt thread."""
        image = self._extract_qimage(image_data)
        if image is None or image.isNull():
            return False
        if image.width() * image.height() > MAX_IMAGE_PIXELS:
            logger.error("In-memory image exceeds the %s-pixel limit", f"{MAX_IMAGE_PIXELS:,}")
            return False
        if self._attachments.remaining_capacity <= self._pending_images:
            logger.warning("Image attachment limit (%d) reached", MAX_IMAGE_ATTACHMENTS)
            return False

        generation = self._attachment_generation
        self._begin_preparation()

        future = self._image_executor.submit(self._encode_in_memory_image, QImage(image))
        future.add_done_callback(
            lambda completed, token=generation: self._publish_attachment_result(
                token,
                None,
                completed,
            )
        )
        return True

    def _begin_preparation(self) -> None:
        """Enter the shared pending state for file and in-memory work."""
        self._pending_images += 1
        self.processing_changed.emit(True)
        self.section_label.setText("PREPARING IMAGE")
        self.primary_label.setText("Preparing attachment…")
        self.secondary_label.setText("This runs in the background")

    @staticmethod
    def _encode_in_memory_image(image: QImage) -> ImageAttachmentPayload:
        """Encode and validate one image in a worker-owned temporary file."""
        temp_fd, temp_path = tempfile.mkstemp(suffix=".png")
        os.close(temp_fd)
        try:
            if not image.save(temp_path, "PNG"):
                raise ValueError("Qt could not encode the dropped image as PNG")
            validated = validate_image_file(temp_path)
            return ImageAttachmentPayload(
                source_path=temp_path,
                mime_type=validated.mime_type,
                temp_path=temp_path,
            )
        except Exception:
            Path(temp_path).unlink(missing_ok=True)
            raise

    def _publish_attachment_result(
        self,
        generation: int,
        source: Optional[str],
        future: Future,
    ) -> None:
        """Cross the worker/Qt boundary with a value, never widget mutation."""
        try:
            payload = future.result()
            result = (generation, source, payload, None)
        except CancelledError:
            result = (generation, source, None, "cancelled")
        except Exception as exc:
            result = (generation, source, None, str(exc))
        self._attachment_ready.emit(result)

    def _finish_attachment(self, result: object) -> None:
        """Adopt a worker-created payload or delete it when the request is stale."""
        generation, source, payload, error = result
        if generation != self._attachment_generation or self._closing:
            if payload is not None:
                self._attachments.dispose_unowned(payload)
            return

        self._pending_images = max(0, self._pending_images - 1)
        if source is not None:
            self._pending_sources.discard(source)
        self.processing_changed.emit(self._pending_images > 0)
        if error is not None:
            if error != "cancelled":
                logger.error("Error processing in-memory image: %s", error)
            if self.image_data:
                self._update_active_state()
            else:
                self._update_empty_state()
            return

        if payload is None:
            if self.image_data:
                self._update_active_state()
            else:
                self._update_empty_state()
            return
        self._add_images([payload])

    @property
    def image_data(self):
        """Immutable attachment snapshot exposed for legacy UI callers."""
        return self._attachments.payloads

    @property
    def has_pending_images(self) -> bool:
        """Whether background attachment preparation is still in progress."""
        return self._pending_images > 0

    def _extract_qimage(self, image_data) -> Optional[QImage]:
        """Extract a reentrant QImage from supported MIME payload shapes.

        Args:
            image_data: Image data in various formats.

        Returns:
            QImage or None.
        """
        if isinstance(image_data, QImage):
            return image_data
        if isinstance(image_data, QPixmap):
            return image_data.toImage()

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
                return maybe_image

        if raw_bytes:
            qimage = QImage.fromData(raw_bytes)
            if not qimage.isNull():
                return qimage

        return None

    @staticmethod
    def _has_supported_image_extension(file_path: str) -> bool:
        """Perform the cheap format-hint check used during drag interaction."""
        suffix = Path(file_path).suffix.lower()
        return bool(suffix and suffix in SUPPORTED_IMAGE_EXTENSIONS)

    @staticmethod
    def _copy_to_temp(source_path: str) -> str:
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
            Path(temp_path).unlink(missing_ok=True)
            raise
        return temp_path
