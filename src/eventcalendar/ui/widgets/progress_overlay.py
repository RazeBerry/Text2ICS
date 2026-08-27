"""Self-contained animated progress overlay for the main window."""

from __future__ import annotations

from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QParallelAnimationGroup,
    QPointF,
    QPropertyAnimation,
    QSequentialAnimationGroup,
    Qt,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from eventcalendar.ui.styles.button_styles import ButtonStyles
from eventcalendar.ui.styles.base import px
from eventcalendar.ui.theme.colors import get_color
from eventcalendar.ui.theme.scales import BORDER_RADIUS, SPACING_SCALE, TYPOGRAPHY_SCALE


class WaveDot(QWidget):
    """One animatable dot in the progress wave."""

    def __init__(self, color: str, size: int = 10, parent=None) -> None:
        super().__init__(parent)
        self._offset = 0.0
        self._color = QColor(color)
        self._size = size
        self.setFixedSize(size + 4, size * 3)

    @pyqtProperty(float)
    def offset(self) -> float:
        return self._offset

    @offset.setter
    def offset(self, value: float) -> None:
        self._offset = value
        self.update()

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(self._color)
        painter.setPen(QPen(Qt.PenStyle.NoPen))
        painter.drawEllipse(
            QPointF(self.width() / 2, self.height() / 2 + self._offset),
            self._size / 2,
            self._size / 2,
        )


class ProcessingOverlay(QWidget):
    """Own progress presentation, animation, and theme refresh as one unit."""

    cancel_requested = pyqtSignal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("processingOverlay")
        parent.installEventFilter(self)
        self._dots: list[WaveDot] = []
        self._opacities: list[QGraphicsOpacityEffect] = []
        self._animation = QParallelAnimationGroup(self)
        self._card = QFrame()
        self.label = QLabel("Processing...")
        self.cancel_button = QPushButton("Cancel")
        self._build()
        self.refresh_theme()
        self.hide()

    def _build(self) -> None:
        overlay_layout = QVBoxLayout(self)
        overlay_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        card_layout = QVBoxLayout(self._card)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.setSpacing(SPACING_SCALE["sm"])

        dots_container = QWidget()
        dots_container.setStyleSheet("background: transparent;")
        dots_layout = QHBoxLayout(dots_container)
        dots_layout.setContentsMargins(0, 0, 0, 0)
        dots_layout.setSpacing(SPACING_SCALE["sm"])
        dots_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        for _ in range(3):
            dot = WaveDot(get_color("accent"), size=10)
            opacity = QGraphicsOpacityEffect()
            opacity.setOpacity(1.0)
            dot.setGraphicsEffect(opacity)
            self._dots.append(dot)
            self._opacities.append(opacity)
            dots_layout.addWidget(dot)
        card_layout.addWidget(dots_container)

        wave_height = 8.0
        wave_duration = 600
        breath_duration = 1200
        for index, (dot, opacity) in enumerate(zip(self._dots, self._opacities)):
            animation = self._create_dot_animation(
                dot,
                opacity,
                index * (wave_duration // 3),
                wave_height,
                wave_duration,
                breath_duration,
            )
            self._animation.addAnimation(animation)

        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.label)
        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_button.clicked.connect(self._request_cancel)
        card_layout.addWidget(self.cancel_button, alignment=Qt.AlignmentFlag.AlignCenter)
        overlay_layout.addWidget(self._card)

    def _request_cancel(self) -> None:
        self.cancel_button.setEnabled(False)
        self.label.setText("Cancelling current network request...")
        self.cancel_requested.emit()

    @staticmethod
    def _create_dot_animation(
        dot: WaveDot,
        opacity: QGraphicsOpacityEffect,
        phase_delay: int,
        wave_height: float,
        wave_duration: int,
        breath_duration: int,
    ) -> QParallelAnimationGroup:
        wave = QSequentialAnimationGroup()
        up = QPropertyAnimation(dot, b"offset")
        up.setDuration(wave_duration // 2)
        up.setStartValue(0.0)
        up.setEndValue(-wave_height)
        up.setEasingCurve(QEasingCurve.Type.InOutSine)
        down = QPropertyAnimation(dot, b"offset")
        down.setDuration(wave_duration // 2)
        down.setStartValue(-wave_height)
        down.setEndValue(0.0)
        down.setEasingCurve(QEasingCurve.Type.InOutSine)
        wave.addAnimation(up)
        wave.addAnimation(down)
        wave.setLoopCount(-1)

        breath = QSequentialAnimationGroup()
        fade_out = QPropertyAnimation(opacity, b"opacity")
        fade_out.setDuration(breath_duration // 2)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.4)
        fade_out.setEasingCurve(QEasingCurve.Type.InOutSine)
        fade_in = QPropertyAnimation(opacity, b"opacity")
        fade_in.setDuration(breath_duration // 2)
        fade_in.setStartValue(0.4)
        fade_in.setEndValue(1.0)
        fade_in.setEasingCurve(QEasingCurve.Type.InOutSine)
        breath.addAnimation(fade_out)
        breath.addAnimation(fade_in)
        breath.setLoopCount(-1)

        group = QParallelAnimationGroup()
        wave_wrapper = QSequentialAnimationGroup()
        breath_wrapper = QSequentialAnimationGroup()
        if phase_delay:
            wave_wrapper.addPause(phase_delay)
            breath_wrapper.addPause(phase_delay)
        wave_wrapper.addAnimation(wave)
        breath_wrapper.addAnimation(breath)
        group.addAnimation(wave_wrapper)
        group.addAnimation(breath_wrapper)
        return group

    def set_status(self, message: str) -> None:
        self.label.setText(message)

    def eventFilter(self, watched, event) -> bool:
        if (
            watched is self.parentWidget()
            and event.type() == QEvent.Type.Resize
            and self.isVisible()
        ):
            self.setGeometry(watched.rect())
        return super().eventFilter(watched, event)

    def start(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        for dot, opacity in zip(self._dots, self._opacities):
            dot.offset = 0.0
            opacity.setOpacity(1.0)
        self.cancel_button.setEnabled(True)
        self.show()
        self.raise_()
        self._animation.start()

    def stop(self) -> None:
        self._animation.stop()
        self.hide()

    def refresh_theme(self) -> None:
        self.setStyleSheet(
            f"#processingOverlay {{ background-color: {get_color('surface_overlay')}; }}"
        )
        self._card.setStyleSheet(
            f"""
            QFrame {{
                background-color: {get_color('surface_elevated')};
                border-radius: {px(BORDER_RADIUS['lg'])};
                padding: {px(SPACING_SCALE['lg'])};
            }}
            """
        )
        headline = TYPOGRAPHY_SCALE["headline"]
        self.label.setStyleSheet(
            f"""
            QLabel {{
                font-family: {headline['font_family']};
                font-size: {px(headline['size_px'])};
                font-weight: {headline['weight']};
                color: {get_color('text_primary')};
            }}
            """
        )
        for dot in self._dots:
            dot.set_color(get_color("accent"))
        self.cancel_button.setStyleSheet(ButtonStyles.secondary())
