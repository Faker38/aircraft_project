"""Smooth scrolling helpers for page and content scroll areas."""

from __future__ import annotations

from PySide6.QtCore import QAbstractAnimation, QEasingCurve, QEvent, QObject, QPropertyAnimation, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QAbstractItemView, QAbstractScrollArea, QFrame, QScrollArea


DEFAULT_SCROLL_DURATION_MS = 180
DEFAULT_SCROLL_STEP = 24
DEFAULT_SCROLL_STEP_MULTIPLIER = 2.0


class _SmoothScrollController(QObject):
    """Intercept wheel input and animate scrollbar movement."""

    def __init__(
        self,
        scroll_area: QAbstractScrollArea,
        *,
        duration_ms: int = DEFAULT_SCROLL_DURATION_MS,
        step: int = DEFAULT_SCROLL_STEP,
        multiplier: float = DEFAULT_SCROLL_STEP_MULTIPLIER,
    ) -> None:
        """Initialize the controller for a scrollable widget."""

        super().__init__(scroll_area)
        self._scroll_area = scroll_area
        self._scroll_bar = scroll_area.verticalScrollBar()
        self._step = step
        self._multiplier = multiplier
        self._target_value = self._scroll_bar.value()

        self._animation = QPropertyAnimation(self._scroll_bar, b"value", self)
        self._animation.setDuration(duration_ms)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        scroll_area.viewport().installEventFilter(self)
        self._scroll_bar.sliderPressed.connect(self._stop_animation)
        self._scroll_bar.rangeChanged.connect(self._clamp_target_value)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Animate wheel scrolling for the bound widget."""

        try:
            viewport = self._scroll_area.viewport()
        except RuntimeError:
            return False

        if watched is viewport and event.type() == QEvent.Type.Wheel:
            wheel_event = event if isinstance(event, QWheelEvent) else None
            if wheel_event is None:
                return super().eventFilter(watched, event)

            if self._scroll_bar.maximum() <= self._scroll_bar.minimum():
                return False

            if wheel_event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                return False

            delta_y = self._extract_vertical_delta(wheel_event)
            if delta_y == 0:
                return False

            self._animate_scroll(-delta_y)
            wheel_event.accept()
            return True

        return super().eventFilter(watched, event)

    def _extract_vertical_delta(self, event: QWheelEvent) -> int:
        """Convert wheel input into a pixel delta."""

        pixel_delta = event.pixelDelta().y()
        if pixel_delta:
            return pixel_delta

        angle_delta = event.angleDelta().y()
        if not angle_delta:
            return 0

        steps = angle_delta / 120.0
        return int(steps * self._step * self._multiplier)

    def _animate_scroll(self, delta: int) -> None:
        """Animate the vertical scrollbar to a new clamped position."""

        start_value = self._scroll_bar.value()
        base_value = self._target_value if self._animation.state() == QAbstractAnimation.State.Running else start_value
        minimum = self._scroll_bar.minimum()
        maximum = self._scroll_bar.maximum()
        self._target_value = max(minimum, min(maximum, int(base_value + delta)))

        if self._target_value == start_value:
            return

        self._animation.stop()
        self._animation.setStartValue(start_value)
        self._animation.setEndValue(self._target_value)
        self._animation.start()

    def _stop_animation(self) -> None:
        """Stop any running animation before manual scrollbar dragging."""

        if self._animation.state() == QAbstractAnimation.State.Running:
            self._animation.stop()
        self._target_value = self._scroll_bar.value()

    def _clamp_target_value(self) -> None:
        """Clamp the stored target value after scrollbar range updates."""

        self._target_value = max(
            self._scroll_bar.minimum(),
            min(self._scroll_bar.maximum(), self._target_value),
        )


class SmoothScrollArea(QScrollArea):
    """QScrollArea with animated wheel scrolling and tuned step sizes."""

    def __init__(self, parent=None) -> None:
        """Initialize the smooth scrolling area."""

        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        configure_scrollable(self)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        """Keep page-step sizing aligned with the visible viewport height."""

        super().resizeEvent(event)
        viewport_height = self.viewport().height()
        self.verticalScrollBar().setPageStep(max(DEFAULT_SCROLL_STEP * 6, viewport_height - 40))


def configure_scrollable(widget: QAbstractScrollArea) -> QAbstractScrollArea:
    """Apply consistent scroll behavior and step sizing to a scrollable widget."""

    vertical_bar = widget.verticalScrollBar()
    horizontal_bar = widget.horizontalScrollBar()
    vertical_bar.setSingleStep(DEFAULT_SCROLL_STEP)
    horizontal_bar.setSingleStep(DEFAULT_SCROLL_STEP)

    viewport_height = widget.viewport().height()
    vertical_bar.setPageStep(max(DEFAULT_SCROLL_STEP * 6, viewport_height - 40))

    if isinstance(widget, QAbstractItemView):
        widget.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        widget.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

    if getattr(widget, "_smooth_scroll_controller", None) is None:
        widget._smooth_scroll_controller = _SmoothScrollController(widget)

    return widget
