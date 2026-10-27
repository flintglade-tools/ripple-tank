#!/usr/bin/env python3
"""Native Qt Ripple Tank. Numerical state belongs exclusively to the Rust core."""
import ctypes
import json
import math
import os
from pathlib import Path
import sys
import time
import tempfile

from PySide6 import QtCore, QtGui, QtWidgets as W

ROOT = Path(__file__).resolve().parents[1]
MAX_FILE = 32 * 1024 * 1024
PRESETS = {"Double slit": "double-slit", "Single slit": "single-slit", "Two sources": "two-sources",
           "Shallow lens": "lens", "Point source": "single", "Pulse": "pulse", "Empty tank": "empty"}
LOADED = "Opened file"
VIEWS = {"height": "Height", "intensity": "Intensity", "depth": "Depth"}
TOOLS = {"pulse": "Pulse", "source": "Source", "wall": "Wall", "depth": "Depth", "erase": "Erase", "probe": "Probe"}
TOOL_HINTS = {
    "pulse": "Click the field to drop a 0.3 mm Gaussian pulse.",
    "source": "Click the field to place a 3 Hz point source, then edit it under Sources.",
    "wall": "Click or drag to draw a solid barrier.",
    "depth": "Click or drag to paint still-water depth.",
    "erase": "Click or drag to remove walls and restore the base depth.",
    "probe": "Click the field to move the probe. Its trace restarts.",
}
BRUSH_TOOLS = ("pulse", "wall", "depth", "erase")
BOUNDARIES = {"sponge": "Damped rim", "reflective": "Reflective walls", "periodic": "Periodic"}
C = {"bg": "#171a1c", "panel": "#1e2124", "raised": "#26292d", "line": "#2f3236", "strong": "#41454a",
     "text": "#eef0f3", "secondary": "#9fa5ac", "muted": "#8a9096", "accent": "#bdccdd", "ink": "#0c1722",
     "tray": "#10151b", "warn": "#e4b750", "danger": "#e8605b", "wall": "#a0aeb9", "ruler": "#8a9096",
     "tick": "#3d444c", "grid": "#262d34", "frame": "#2c3640", "curve": "#d9e3ea"}


def atomic_write(filename, text):
    path = Path(filename)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf8", dir=path.parent, prefix=".ripple-save-", delete=False) as f:
            temp_path = Path(f.name)
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


# The engine places normalized coordinate v at cell coordinate v·(n−1); cell i spans [i, i+1).
def to_frac(v, n):
    return (v * (n - 1) + 0.5) / n


def to_norm(f, n):
    return min(1.0, max(0.0, (f * n - 0.5) / (n - 1)))


def extent(c):
    return c["width_m"], c["width_m"] * c["ny"] / c["nx"]


def tidy(v):
    text = repr(float(f"{v:.12g}"))
    return text[:-2] if text.endswith(".0") else text


def fixed(v, n):
    text = f"{v:.{n}f}"
    if text.startswith("-") and float(text) == 0:
        text = text[1:]
    return text.replace("-", "−")


def nice_step(raw, steps=(1, 2, 5, 10)):
    p = 10 ** math.floor(math.log10(raw))
    return next(m for m in steps if m * p >= raw) * p


def joules(v):
    a = abs(v)
    if not a:
        return "0 J"
    f, p = (1, "") if a >= 1 else (1e-3, "m") if a >= 1e-3 else (1e-6, "µ") if a >= 1e-6 else (1e-9, "n") if a >= 1e-9 else (1e-12, "p")
    return f"{v / f:.4g} {p}J".replace("-", "−")


def colormap(view, t):
    """Mirrors the engine's RGBA colormap (src/lib.rs render) so the key matches the field exactly."""
    if view == "depth":
        return 16 + 20 * t, 40 + 100 * t, 55 + 175 * t
    if view == "intensity":
        v = math.sqrt(t)
        return 16 + 95 * v, 21 + 195 * v, 27 + 225 * v
    v = 2 * t - 1
    return (16 + 232 * v, 21 + 152 * v, 27 + 71 * v) if v >= 0 else (16 - 80 * v, 21 - 181 * v, 27 - 223 * v)


def tabular(widget):
    widget.setFont(tabular_font(widget.font()))
    return widget


def tabular_font(font, pixels=None):
    font = QtGui.QFont(font)
    font.setFeature(QtGui.QFont.Tag("tnum"), 1)
    if pixels:
        font.setPixelSize(pixels)
    return font


def label(text="", name=None, wrap=False):
    widget = W.QLabel(text)
    if name:
        widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


def draw_icon(name, color, size=20):
    """Tool and transport glyphs drawn with QPainter (no SVG module dependency)."""
    pm = QtGui.QPixmap(size * 2, size * 2)
    pm.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    p.scale(2 * size / 20, 2 * size / 20)
    ink = QtGui.QColor(color)
    pen = QtGui.QPen(ink, 1.5, QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap, QtCore.Qt.PenJoinStyle.RoundJoin)
    faint = QtGui.QPen(pen)
    faint.setColor(QtGui.QColor(ink.red(), ink.green(), ink.blue(), 128))
    p.setPen(pen)
    p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    dot = lambda x, y, r: (p.setPen(QtCore.Qt.PenStyle.NoPen), p.setBrush(ink), p.drawEllipse(QtCore.QPointF(x, y), r, r), p.setBrush(QtCore.Qt.BrushStyle.NoBrush), p.setPen(pen))
    if name == "pulse":
        dot(10, 10, 1.9)
        p.drawEllipse(QtCore.QPointF(10, 10), 5, 5)
        p.setPen(faint)
        p.drawEllipse(QtCore.QPointF(10, 10), 8.3, 8.3)
    elif name == "source":
        dot(5, 10, 2.1)
        p.drawArc(QtCore.QRectF(0, 5, 10, 10), 50 * 16, -100 * 16)
        p.setPen(faint)
        p.drawArc(QtCore.QRectF(-4, 1, 18, 18), 50 * 16, -100 * 16)
    elif name == "wall":
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(ink)
        p.drawRoundedRect(QtCore.QRectF(7.6, 1.8, 4.8, 6.6), 1, 1)
        p.drawRoundedRect(QtCore.QRectF(7.6, 11.6, 4.8, 6.6), 1, 1)
    elif name == "depth":
        p.setPen(faint)
        p.drawLine(QtCore.QPointF(2, 4.5), QtCore.QPointF(18, 4.5))
        p.setPen(pen)
        p.drawPolyline(QtGui.QPolygonF([QtCore.QPointF(2, 16.5), QtCore.QPointF(7.5, 16.5), QtCore.QPointF(10.5, 10), QtCore.QPointF(18, 10)]))
    elif name == "erase":
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(3.4, 12.4), QtCore.QPointF(10, 5.8), QtCore.QPointF(15.6, 11.4), QtCore.QPointF(11, 16), QtCore.QPointF(7, 16)]))
        p.setPen(faint)
        p.drawLine(QtCore.QPointF(8.6, 16), QtCore.QPointF(17.2, 16))
    elif name == "probe":
        p.drawEllipse(QtCore.QPointF(10, 10), 3.3, 3.3)
        for a, b in [((10, 1.5), (10, 5.9)), ((10, 14.1), (10, 18.5)), ((1.5, 10), (5.9, 10)), ((14.1, 10), (18.5, 10))]:
            p.drawLine(QtCore.QPointF(*a), QtCore.QPointF(*b))
    else:
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(ink)
        shapes = {"play": [[(5.6, 3.2), (5.6, 16.8), (16.5, 10)]],
                  "pause": [[(5, 3.5), (8.8, 3.5), (8.8, 16.5), (5, 16.5)], [(11.2, 3.5), (15, 3.5), (15, 16.5), (11.2, 16.5)]],
                  "step": [[(3.8, 3.5), (12.5, 10), (3.8, 16.5)], [(13.8, 3.5), (16.3, 3.5), (16.3, 16.5), (13.8, 16.5)]]}[name]
        for shape in shapes:
            p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(x, y) for x, y in shape]))
    p.end()
    pm.setDevicePixelRatio(2)
    return pm


def icon(name, off=C["secondary"], on=C["text"]):
    result = QtGui.QIcon()
    result.addPixmap(draw_icon(name, off), QtGui.QIcon.Mode.Normal, QtGui.QIcon.State.Off)
    result.addPixmap(draw_icon(name, on), QtGui.QIcon.Mode.Normal, QtGui.QIcon.State.On)
    return result


class Engine:
    def __init__(self):
        base = Path(getattr(sys, "_MEIPASS", ROOT))
        options = [base / "libflintglade_ripple.so", ROOT / "target/release/libflintglade_ripple.so"]
        path = next((p for p in options if p.is_file()), None)
        if path is None:
            raise RuntimeError("Rust engine missing. Build with cargo build --release first.")
        self.lib = ctypes.CDLL(str(path))
        for name in ["input_ptr", "output_ptr", "pixels_ptr"]:
            getattr(self.lib, "ripple_" + name).restype = ctypes.c_void_p
        for name in ["output_len", "pixels_len", "request"]:
            getattr(self.lib, "ripple_" + name).restype = ctypes.c_uint32
        self.lib.ripple_request.argtypes = [ctypes.c_uint32]
        self.last = None

    def request(self, value):
        data = json.dumps(value, allow_nan=False, separators=(",", ":")).encode()
        if len(data) > MAX_FILE:
            raise ValueError("Experiment exceeds 32 MiB")
        ctypes.memmove(self.lib.ripple_input_ptr(), data, len(data))
        self.lib.ripple_request(len(data))
        result = json.loads(ctypes.string_at(self.lib.ripple_output_ptr(), self.lib.ripple_output_len()))
        if not result.get("ok"):
            raise ValueError(result.get("error", "Engine error"))
        self.last = result
        return result

    def image(self):
        c = self.last["config"]
        data = ctypes.string_at(self.lib.ripple_pixels_ptr(), self.lib.ripple_pixels_len())
        return QtGui.QImage(data, c["nx"], c["ny"], c["nx"] * 4, QtGui.QImage.Format.Format_RGBA8888).copy()


class Spin(W.QDoubleSpinBox):
    """Number box that only reacts to the mouse wheel when focused, so scrolling a panel never edits physics."""

    def __init__(self, lo, hi, step, decimals, value=None):
        super().__init__()
        self.setRange(lo, hi)
        self.setSingleStep(step)
        self.setDecimals(decimals)
        self.setKeyboardTracking(False)
        self.setButtonSymbols(W.QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setMinimumWidth(84)
        tabular(self)
        if value is not None:
            self.setValue(value)

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class Check(W.QCheckBox):
    """Checkbox painted directly, so its box stays visible under the transparent stylesheet."""

    def sizeHint(self):
        return QtCore.QSize(26 + self.fontMetrics().horizontalAdvance(self.text()) + 6, max(24, self.fontMetrics().height() + 8))

    def minimumSizeHint(self):
        return self.sizeHint()

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        box = QtCore.QRectF(2.5, (self.height() - 16) / 2, 16, 16)
        on, enabled = self.isChecked(), self.isEnabled()
        p.setPen(QtGui.QPen(QtGui.QColor(C["accent"] if on else C["strong"]), 1))
        p.setBrush(QtGui.QColor(C["accent"] if on else C["raised"]))
        if not enabled:
            p.setOpacity(0.45)
        p.drawRoundedRect(box, 3, 3)
        if on:
            p.setPen(QtGui.QPen(QtGui.QColor(C["ink"]), 1.8, QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap, QtCore.Qt.PenJoinStyle.RoundJoin))
            p.drawPolyline(QtGui.QPolygonF([box.topLeft() + QtCore.QPointF(*xy) for xy in [(4, 8.5), (7, 11.5), (12.2, 5)]]))
        if self.hasFocus():
            p.setPen(QtGui.QPen(QtGui.QColor(C["accent"]), 2))
            p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(box.adjusted(-2.5, -2.5, 2.5, 2.5), 4, 4)
        p.setPen(QtGui.QColor(C["text"]))
        p.drawText(QtCore.QRectF(26, 0, self.width() - 26, self.height()), QtCore.Qt.AlignmentFlag.AlignVCenter, self.text())


class Segmented(W.QWidget):
    """Exclusive buttons with a QComboBox-like value API (currentText/setCurrentText/currentTextChanged)."""
    currentTextChanged = QtCore.Signal(str)

    def __init__(self, items, vertical=False, icons=False, name="seg"):
        super().__init__()
        layout = W.QVBoxLayout(self) if vertical else W.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4 if vertical else 2)
        self.group = W.QButtonGroup(self)
        self.buttons = {}
        for value, text in items.items():
            button = W.QToolButton()
            button.setObjectName(name)
            button.setText(text)
            button.setCheckable(True)
            button.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
            button.setAccessibleName(text)
            if icons:
                button.setIcon(icon(value))
                button.setIconSize(QtCore.QSize(20, 20))
                button.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.clicked.connect(lambda _=False, v=value: self._pick(v))
            self.group.addButton(button)
            layout.addWidget(button)
            self.buttons[value] = button
        if vertical:
            layout.addStretch()
        self._value = next(iter(items))
        self.buttons[self._value].setChecked(True)

    def currentText(self):
        return self._value

    def setCurrentText(self, value):
        if value in self.buttons:
            self.buttons[value].setChecked(True)
            self._pick(value)

    def _pick(self, value):
        if value != self._value:
            self._value = value
            self.currentTextChanged.emit(value)


class Field(W.QWidget):
    """Calibrated tank: engine pixels, centimetre rulers, numbered drivers, probe and true-size tool footprint."""
    applied = QtCore.Signal(float, float)
    toggled = QtCore.Signal()
    TOP, LEFT, PAD = 20, 34, 8

    def __init__(self):
        super().__init__()
        self.setMinimumSize(320, 220)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAccessibleName("Water field")
        self.setAccessibleDescription("Arrow keys move the cursor, Shift for larger steps; Enter applies the tool; Space plays or pauses.")
        self.image = None
        self.sources = []
        self.probe = (0.72, 0.5)
        self.cursor = (0.5, 0.5)
        self.box = QtCore.QRectF()
        self.dragging = False
        self.continuous = False
        self.config = None
        self.selected = 0
        self.tool = "pulse"
        self.brush = 0.03
        self.hover = None

    def layout_box(self):
        aspect = self.image.width() / self.image.height()
        aw, ah = self.width() - self.LEFT - self.PAD, self.height() - self.TOP - self.PAD
        w = max(1.0, min(aw, ah * aspect))
        h = w / aspect
        self.box = QtCore.QRectF(self.LEFT + (aw - w) / 2, self.TOP + (ah - h) / 2, w, h)

    def at(self, pos):
        c = self.config
        return QtCore.QPointF(self.box.left() + to_frac(pos[0], c["nx"]) * self.box.width(),
                              self.box.top() + to_frac(pos[1], c["ny"]) * self.box.height())

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor(C["tray"]))
        if self.image is None or self.config is None:
            return
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
        self.layout_box()
        box, c = self.box, self.config
        p.drawImage(box, self.image)
        p.setPen(QtGui.QPen(QtGui.QColor(C["accent"] if self.hasFocus() else C["frame"]), 2 if self.hasFocus() else 1))
        p.drawRect(box.adjusted(-1, -1, 1, 1))
        self.paint_rulers(p)
        p.save()
        p.setClipRect(box)
        w_m = extent(c)[0]
        for i, source in enumerate(self.sources):
            chosen = i == self.selected
            color = C["accent"] if chosen else C["text"]
            dash = None if source["enabled"] else [3, 3]
            point = self.at((source["x"], source["y"]))
            if source["kind"] == "plane":
                self.ink(p, lambda: p.drawLine(QtCore.QPointF(point.x(), box.top()), QtCore.QPointF(point.x(), box.bottom())), color, 2 if chosen else 1.2, dash)
                self.tag(p, str(i + 1), point.x() + 5, box.top() + 14, color)
            else:
                r = max(5.0, source["radius_m"] / w_m * box.width())
                self.ink(p, lambda: p.drawEllipse(point, r, r), color, 2 if chosen else 1.3, dash)
                self.tag(p, str(i + 1), point.x() + r * 0.75 + 3, point.y() - r * 0.75 - 2, color)
        self.cross(p, self.at(self.probe), C["text"])
        if self.hasFocus():
            q = self.at(self.cursor)
            self.ink(p, lambda: p.drawRect(QtCore.QRectF(q.x() - 6, q.y() - 6, 12, 12)), C["accent"], 1.4)
            self.footprint(p, self.cursor)
        if self.hover is not None:
            self.footprint(p, self.hover)
        p.restore()

    def paint_rulers(self, p):
        box, (w_m, h_m) = self.box, extent(self.config)
        wc, hc = w_m * 100, h_m * 100
        step = nice_step(wc * 46 / box.width())
        p.setFont(tabular_font(self.font(), 11))
        p.setPen(QtGui.QPen(QtGui.QColor(C["tick"]), 1))
        i = 0
        while i * step / 2 <= wc + 1e-9:
            x = box.left() + i * step / 2 / wc * box.width()
            p.drawLine(QtCore.QPointF(x, box.top() - 2), QtCore.QPointF(x, box.top() - (4 if i % 2 else 7)))
            i += 1
        i = 0
        while i * step / 2 <= hc + 1e-9:
            y = box.top() + i * step / 2 / hc * box.height()
            p.drawLine(QtCore.QPointF(box.left() - 2, y), QtCore.QPointF(box.left() - (4 if i % 2 else 7), y))
            i += 1
        p.setPen(QtGui.QColor(C["ruler"]))
        metrics = p.fontMetrics()
        v = step
        while v <= wc + 1e-9:
            x = box.left() + v / wc * box.width()
            if x < box.right() - 12:
                text = tidy(v)
                p.drawText(QtCore.QPointF(x - metrics.horizontalAdvance(text) / 2, box.top() - 9), text)
            v += step
        v = step
        while v <= hc + 1e-9:
            y = box.top() + v / hc * box.height()
            if y < box.bottom() - 6:
                text = tidy(v)
                p.drawText(QtCore.QPointF(box.left() - 9 - metrics.horizontalAdvance(text), y + metrics.ascent() / 2 - 1), text)
            v += step
        p.drawText(QtCore.QPointF(box.left() - 7 - metrics.horizontalAdvance("cm"), box.top() - 8), "cm")

    @staticmethod
    def ink(p, draw, color, width, dash=None):
        for pen_color, pen_width in [(QtGui.QColor(6, 9, 12, 184), width + 2.5), (QtGui.QColor(color), width)]:
            pen = QtGui.QPen(pen_color, pen_width)
            if dash:
                pen.setDashPattern([d / pen_width for d in dash])
            p.setPen(pen)
            p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            draw()

    @staticmethod
    def tag(p, text, x, y, color):
        font = p.font()
        font.setPixelSize(11)
        font.setWeight(QtGui.QFont.Weight.DemiBold)
        path = QtGui.QPainterPath()
        path.addText(QtCore.QPointF(x, y), font, text)
        p.setPen(QtGui.QPen(QtGui.QColor(6, 9, 12, 204), 3))
        p.drawPath(path)
        p.fillPath(path, QtGui.QColor(color))

    def cross(self, p, q, color, arm=9, gap=3.5):
        def draw():
            for a, b in [((-arm, 0), (-gap, 0)), ((gap, 0), (arm, 0)), ((0, -arm), (0, -gap)), ((0, gap), (0, arm))]:
                p.drawLine(q + QtCore.QPointF(*a), q + QtCore.QPointF(*b))
        self.ink(p, draw, color, 1.4)

    def footprint(self, p, pos):
        q = self.at(pos)
        if self.tool == "probe":
            return self.cross(p, q, C["accent"], 7, 2.5)
        r = max(5.0, 0.008 / extent(self.config)[0] * self.box.width()) if self.tool == "source" else max(2.0, self.brush * self.box.width())
        self.ink(p, lambda: p.drawEllipse(q, r, r), C["accent"], 1.2, [4, 3])

    def norm(self, point):
        c = self.config
        return (to_norm((point.x() - self.box.left()) / self.box.width(), c["nx"]),
                to_norm((point.y() - self.box.top()) / self.box.height(), c["ny"]))

    def apply_at(self, point):
        if self.config is not None and self.box.contains(point) and self.box.width() > 0:
            self.cursor = self.norm(point)
            self.applied.emit(*self.cursor)

    def mousePressEvent(self, event):
        if event.button() != QtCore.Qt.MouseButton.LeftButton:
            return
        self.setFocus()
        self.dragging = True
        self.apply_at(event.position())

    def mouseMoveEvent(self, event):
        inside = self.config is not None and self.box.contains(event.position())
        self.hover = self.norm(event.position()) if inside else None
        self.update()
        if self.dragging and self.continuous:
            self.apply_at(event.position())

    def mouseReleaseEvent(self, event):
        self.dragging = False

    def leaveEvent(self, event):
        self.hover = None
        self.update()

    def focusInEvent(self, event):
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self.update()
        super().focusOutEvent(event)

    def keyPressEvent(self, event):
        k = 0.05 if event.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier else 0.01
        dx, dy = {QtCore.Qt.Key.Key_Left: (-k, 0), QtCore.Qt.Key.Key_Right: (k, 0),
                  QtCore.Qt.Key.Key_Up: (0, -k), QtCore.Qt.Key.Key_Down: (0, k)}.get(event.key(), (0, 0))
        if dx or dy:
            self.cursor = (min(1, max(0, self.cursor[0] + dx)), min(1, max(0, self.cursor[1] + dy)))
            self.update()
        elif event.key() in [QtCore.Qt.Key.Key_Enter, QtCore.Qt.Key.Key_Return]:
            self.applied.emit(*self.cursor)
        elif event.key() == QtCore.Qt.Key.Key_Space:
            self.toggled.emit()
        else:
            super().keyPressEvent(event)


class ColorBar(W.QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(10)
        self.setMinimumWidth(72)
        self.setMaximumWidth(180)
        self.setSizePolicy(W.QSizePolicy.Policy.Expanding, W.QSizePolicy.Policy.Fixed)
        self.view = "height"

    def sizeHint(self):
        return QtCore.QSize(160, 10)

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        n = self.width()
        for i in range(n):
            p.fillRect(i, 0, 1, self.height(), QtGui.QColor(*[int(v) for v in colormap(self.view, i / max(1, n - 1))]))


class Trace(W.QWidget):
    """Probe height over simulation time, autoscaled to a labelled nice full scale."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(96)
        self.points = []
        self.setAccessibleName("Probe height over simulation time")

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        x0, x1, y0, y1 = 50, w - 2, 4, h - 18
        mid = (y0 + y1) / 2
        p.fillRect(QtCore.QRectF(x0, y0, x1 - x0, y1 - y0), QtGui.QColor(C["tray"]))
        p.setFont(tabular_font(self.font(), 11))
        ready = len(self.points) >= 2 and self.points[-1][0] > self.points[0][0]
        scale = nice_step(max(1e-5, max(abs(v) for _, v in self.points)), (1, 2, 2.5, 5, 10)) if ready else 1e-4
        Y = lambda v: mid - v / scale * (y1 - y0) / 2
        p.setPen(QtGui.QPen(QtGui.QColor(C["grid"]), 1))
        for f in (-1, -0.5, 0.5, 1):
            p.drawLine(QtCore.QPointF(x0, Y(f * scale)), QtCore.QPointF(x1, Y(f * scale)))
        p.setPen(QtGui.QPen(QtGui.QColor(C["tick"]), 1))
        p.drawLine(QtCore.QPointF(x0, mid), QtCore.QPointF(x1, mid))
        p.setPen(QtGui.QColor(C["ruler"]))
        m = p.fontMetrics()
        mm = tidy(float(f"{scale * 1000:.3g}"))
        right = lambda text, y: p.drawText(QtCore.QPointF(x0 - 6 - m.horizontalAdvance(text), y + m.ascent() / 2 - 1), text)
        right(f"+{mm}", Y(scale) + 4)
        right("0", mid)
        right(f"−{mm}", Y(-scale) - 4)
        right("mm", (Y(scale / 2) + mid) / 2 + 1)
        if not ready:
            return
        t0, t1 = self.points[0][0], self.points[-1][0]
        X = lambda t: x0 + (t - t0) / (t1 - t0) * (x1 - x0)
        p.drawText(QtCore.QPointF(x0, h - 3), f"{t0:.2f} s")
        end = f"{t1:.2f} s"
        p.drawText(QtCore.QPointF(x1 - m.horizontalAdvance(end), h - 3), end)
        curve = QtGui.QPainterPath()
        for i, (t, v) in enumerate(self.points):
            curve.moveTo(X(t), Y(v)) if i == 0 else curve.lineTo(X(t), Y(v))
        area = QtGui.QPainterPath(curve)
        area.lineTo(X(t1), mid)
        area.lineTo(X(t0), mid)
        area.closeSubpath()
        # Area above zero in the crest color, below zero in the trough color, as in the field colormap.
        for top, color in [(True, QtGui.QColor(248, 173, 98, 66)), (False, QtGui.QColor(96, 202, 250, 61))]:
            p.save()
            p.setClipRect(QtCore.QRectF(x0, y0 if top else mid, x1 - x0, (mid - y0) if top else (y1 - mid)))
            p.fillPath(area, color)
            p.restore()
        p.setPen(QtGui.QPen(QtGui.QColor(C["curve"]), 1.4))
        p.drawPath(curve)
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(QtGui.QColor(C["text"]))
        p.drawEllipse(QtCore.QPointF(X(t1), Y(self.points[-1][1])), 2.6, 2.6)


class Window(W.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ripple Tank · Flintglade Labs")
        self.setMinimumSize(960, 680)
        self.resize(1320, 860)
        self.engine = Engine()
        self.ready = False
        self.running = False
        self.loaded_snapshot = None
        self._last_config = None
        self._last_sources = None
        self._legend_key = None
        self.compute_ms = None
        self.field = Field()
        self.trace = Trace()
        self.field.applied.connect(self.apply_tool)
        self.field.toggled.connect(self.toggle)
        self.message = label("Ready", "status")
        self.message.setAccessibleName("Status")
        self.grid_info = tabular(label("", "muted"))
        self.statusBar().addWidget(self.message, 1)
        self.statusBar().addPermanentWidget(self.grid_info)
        self.statusBar().setSizeGripEnabled(False)

        stage = W.QFrame()
        stage.setObjectName("stage")
        column = W.QVBoxLayout(stage)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self.build_transport())
        bench = W.QWidget()
        bench.setObjectName("bench")
        row = W.QHBoxLayout(bench)
        row.setContentsMargins(10, 6, 12, 4)
        row.setSpacing(8)
        self.tool = Segmented(TOOLS, vertical=True, icons=True, name="tool")
        self.tool.layout().setContentsMargins(0, Field.TOP, 0, 0)
        self.tool.currentTextChanged.connect(self.set_tool)
        row.addWidget(self.tool)
        row.addWidget(self.field, 1)
        column.addWidget(bench, 1)
        column.addWidget(self.build_legend())
        column.addWidget(self.build_probe())

        side = W.QWidget()
        side_column = W.QVBoxLayout(side)
        side_column.setContentsMargins(0, 0, 0, 0)
        side_column.setSpacing(10)
        side_column.addWidget(self.build_readouts())
        self.tabs = W.QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setExpanding(True)
        self.tabs.tabBar().setDrawBase(False)
        self.tabs.addTab(self.scroll(self.build_tool_tab()), "Tool")
        self.tabs.addTab(self.scroll(self.build_sources_tab()), "Sources")
        self.tabs.addTab(self.scroll(self.build_water_tab()), "Water")
        rack = W.QFrame()
        rack.setObjectName("panel")
        rack_layout = W.QVBoxLayout(rack)
        rack_layout.setContentsMargins(1, 1, 1, 1)
        rack_layout.addWidget(self.tabs)
        side_column.addWidget(rack, 1)
        side.setMinimumWidth(276)
        side.setMaximumWidth(380)

        splitter = W.QSplitter(QtCore.Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(stage)
        splitter.addWidget(side)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([1000, 320])
        root = W.QWidget()
        layout = W.QVBoxLayout(root)
        layout.setContentsMargins(10, 10, 10, 8)
        layout.addWidget(splitter)
        self.setCentralWidget(root)
        self.build_menus()
        self.set_tool(self.tool.currentText())
        self.ready = True
        self.perform({"op": "new", "preset": "double-slit"}, reset_trace=True, note="Paused. Press Play or F5 to run.")
        self.update_probe()
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    # ---- construction ---------------------------------------------------------------------------
    def build_transport(self):
        bar = W.QWidget()
        bar.setObjectName("transport")
        row = W.QHBoxLayout(bar)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(6)
        self.play = W.QPushButton("Play")
        self.play.setObjectName("primary")
        self.play.setIcon(QtGui.QIcon(draw_icon("play", C["ink"], 14)))
        self.play.setToolTip("Play or pause (F5)")
        self.play.clicked.connect(self.toggle)
        step = W.QPushButton("Step")
        step.setIcon(QtGui.QIcon(draw_icon("step", C["text"], 14)))
        step.setToolTip("Advance one time step (F6)")
        step.clicked.connect(self.step_once)
        self.scenario = W.QComboBox()
        self.scenario.addItems(PRESETS)
        self.scenario.setAccessibleName("Experiment")
        self.scenario.setMinimumWidth(128)
        self.scenario.currentTextChanged.connect(self.preset)
        reset = W.QPushButton("Reset")
        reset.setToolTip("Rebuild the experiment, or restore an opened file to its saved state (Ctrl+R)")
        reset.clicked.connect(self.reset_experiment)
        clear = W.QPushButton("Clear waves")
        clear.setToolTip("Remove waves; keep walls, depth and sources")
        clear.clicked.connect(self.clear_waves)
        self.pace = W.QSpinBox()
        self.pace.setRange(1, 32)
        self.pace.setValue(8)
        self.pace.setButtonSymbols(W.QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.pace.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.pace.setAccessibleName("Pace, steps per frame")
        self.pace.setMinimumWidth(44)
        for widget in [self.play, step, self.scenario, reset, clear]:
            row.addWidget(widget)
        row.addStretch(1)
        row.addWidget(label("Pace", "secondary"))
        row.addWidget(self.pace)
        row.addWidget(label("steps / frame", "muted"))
        return bar

    def build_legend(self):
        bar = W.QWidget()
        bar.setObjectName("bench")
        column = W.QVBoxLayout(bar)
        column.setContentsMargins(10, 2, 12, 10)
        column.setSpacing(4)
        row = W.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        column.addLayout(row)
        self.view = Segmented(VIEWS, name="seg")
        self.view.currentTextChanged.connect(self.change_view)
        self.scale_quantity = label("Surface height")
        self.scale_low = tabular(label("−0.3 mm", "secondary"))
        self.colorbar = ColorBar()
        self.scale_high = tabular(label("+0.3 mm", "secondary"))
        swatch = label("", "wall")
        swatch.setFixedSize(12, 10)
        self.clip = label("Peak beyond the color scale; colors clip", "warn", wrap=True)
        self.clip.setVisible(False)
        row.addWidget(self.view)
        row.addSpacing(10)
        for widget in [self.scale_quantity, self.scale_low, self.colorbar, self.scale_high]:
            row.addWidget(widget)
        row.addSpacing(8)
        row.addWidget(swatch)
        row.addWidget(label("Solid", "secondary"))
        row.addStretch(1)
        column.addWidget(self.clip)
        return bar

    def build_probe(self):
        box = W.QWidget()
        box.setObjectName("probe")
        column = W.QVBoxLayout(box)
        column.setContentsMargins(14, 8, 14, 10)
        column.setSpacing(4)
        head = W.QHBoxLayout()
        head.setSpacing(14)
        head.addWidget(label("Probe", "h3"))
        self.probe_pos = tabular(label("", "muted"))
        self.probe_depth = tabular(label("", "muted"))
        self.probe_value = tabular(label("0 mm", "value"))
        self.probe_value.setAccessibleName("Probe height")
        head.addWidget(self.probe_pos)
        head.addWidget(self.probe_depth)
        head.addStretch(1)
        head.addWidget(self.probe_value)
        column.addLayout(head)
        self.trace.setMinimumHeight(104)
        column.addWidget(self.trace)
        return box

    def build_readouts(self):
        panel = W.QFrame()
        panel.setObjectName("panel")
        grid = W.QGridLayout(panel)
        grid.setContentsMargins(14, 10, 14, 10)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(8)
        self.readouts = {}
        specs = [("time", "Time", None), ("dt", "Time step Δt", None), ("courant", "Courant", "Gravity-wave Courant number √(gH)·Δt/Δx"),
                 ("compute", "Compute", None), ("height", "Peak |η|", None),
                 ("ratio", "Peak η/H", "Largest displacement relative to local still-water depth; the linear model assumes η ≪ H"),
                 ("energy", "Energy", None), ("volume", "Volume Δ", "Displaced volume relative to the still surface. Sources, the damped rim and wall edits change it.")]
        for i, (key, name, tip) in enumerate(specs):
            cell = W.QVBoxLayout()
            cell.setSpacing(1)
            title = label(name, "secondary")
            value = tabular(label("—", "value"))
            sub = tabular(label("", "sub"))
            value.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
            value.setAccessibleName(name)
            if tip:
                for widget in (title, value):
                    widget.setToolTip(tip)
            for widget in (title, value, sub):
                cell.addWidget(widget)
            grid.addLayout(cell, i // 2, i % 2)
            self.readouts[key] = (value, sub)
        return panel

    @staticmethod
    def scroll(widget):
        area = W.QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(W.QFrame.Shape.NoFrame)
        area.setWidget(widget)
        return area

    @staticmethod
    def unit_row(grid, row, name, widget, unit=""):
        text = label(name, "secondary")
        text.setBuddy(widget)
        grid.addWidget(text, row, 0)
        grid.addWidget(widget, row, 1)
        grid.addWidget(label(unit, "muted"), row, 2)
        return text

    def build_tool_tab(self):
        page = W.QWidget()
        column = W.QVBoxLayout(page)
        column.setContentsMargins(14, 12, 14, 12)
        column.setSpacing(10)
        self.tool_name = label("Pulse", "h2")
        self.tool_hint = label("", "secondary", wrap=True)
        column.addWidget(self.tool_name)
        column.addWidget(self.tool_hint)
        grid = W.QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(0, 1)
        self.brush = Spin(1.6, 160, 1, 1, 24)
        self.brush.valueChanged.connect(self.update_brush)
        self.paint_depth = Spin(0.5, 200, 0.5, 2, 3)
        self.brush_row = [self.unit_row(grid, 0, "Brush radius", self.brush, "mm"), self.brush, grid.itemAtPosition(0, 2).widget()]
        self.depth_row = [self.unit_row(grid, 1, "Paint depth", self.paint_depth, "mm"), self.paint_depth, grid.itemAtPosition(1, 2).widget()]
        column.addLayout(grid)
        coords = W.QGroupBox("Apply at coordinates")
        cgrid = W.QGridLayout(coords)
        cgrid.setContentsMargins(10, 8, 10, 10)
        cgrid.setColumnStretch(0, 1)
        self.at_x = Spin(0, 80, 1, 2, 40)
        self.at_y = Spin(0, 48, 1, 2, 24)
        self.unit_row(cgrid, 0, "x", self.at_x, "cm")
        self.unit_row(cgrid, 1, "y", self.at_y, "cm")
        self.apply_button = W.QPushButton("Apply pulse here")
        self.apply_button.clicked.connect(self.apply_at_coordinates)
        cgrid.addWidget(self.apply_button, 2, 0, 1, 3)
        column.addWidget(coords)
        keys = label("On the focused field, arrow keys move the cursor (Shift for larger steps), Enter applies the tool and Space plays or pauses.", "muted", wrap=True)
        column.addWidget(keys)
        column.addStretch(1)
        return page

    def build_sources_tab(self):
        page = W.QWidget()
        column = W.QVBoxLayout(page)
        column.setContentsMargins(14, 12, 14, 12)
        column.setSpacing(10)
        self.source_list = W.QListWidget()
        self.source_list.setAccessibleName("Sources")
        self.source_list.setMaximumHeight(132)
        self.source_list.currentRowChanged.connect(self.select_source)
        self.source_empty = label("No sources. Choose the Source tool, then click the field.", "secondary", wrap=True)
        column.addWidget(self.source_list)
        column.addWidget(self.source_empty)
        self.source_editor = W.QWidget()
        editor = W.QVBoxLayout(self.source_editor)
        editor.setContentsMargins(0, 4, 0, 0)
        editor.setSpacing(10)
        self.source_enabled = Check("Driving")
        self.source_enabled.toggled.connect(self.edit_source)
        editor.addWidget(self.source_enabled)
        grid = W.QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)
        self.freq = Spin(0.05, 40, 0.1, 2, 3)
        self.amp = Spin(0, 2, 0.01, 3, 0.15)
        self.source_radius = Spin(0.5, 100, 0.5, 2, 8)
        self.phase = Spin(-360, 360, 15, 1, 0)
        self.source_x = Spin(0, 80, 0.5, 2, 14.6)
        self.source_y = Spin(0, 48, 0.5, 2, 24)
        for i, (name, box, unit) in enumerate([("Frequency", self.freq, "Hz"), ("Drive height", self.amp, "mm"), ("Radius", self.source_radius, "mm"),
                                               ("Phase", self.phase, "°"), ("x", self.source_x, "cm"), ("y", self.source_y, "cm")]):
            box.valueChanged.connect(self.edit_source)
            text = label(name, "secondary")
            text.setBuddy(box)
            field = W.QHBoxLayout()
            field.setSpacing(6)
            field.addWidget(box, 1)
            field.addWidget(label(unit, "muted"))
            grid.addWidget(text, (i // 2) * 2, i % 2)
            grid.addLayout(field, (i // 2) * 2 + 1, i % 2)
            if i in (1, 3):
                grid.setRowMinimumHeight((i // 2) * 2 + 2, 6)
        editor.addLayout(grid)
        self.remove_button = W.QPushButton("Remove source")
        self.remove_button.setObjectName("quiet")
        self.remove_button.clicked.connect(self.remove_source)
        editor.addWidget(self.remove_button)
        column.addWidget(self.source_editor)
        column.addStretch(1)
        return page

    def build_water_tab(self):
        page = W.QWidget()
        column = W.QVBoxLayout(page)
        column.setContentsMargins(14, 12, 14, 12)
        column.setSpacing(10)
        grid = W.QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(0, 1)
        self.controls = {}
        for row, (key, name, lo, hi, step, decimals, factor, unit) in enumerate([
            ("depth_m", "Still depth H", 0.5, 200, 0.5, 2, 1000, "mm"),
            ("gravity", "Gravity g", 0.1, 30, 0.1, 2, 1, "m/s²"),
            ("surface_tension", "Surface tension σ", 0, 100, 1, 1, 1000, "mN/m"),
            ("damping", "Drag γ", 0, 10, 0.02, 3, 1, "s⁻¹"),
        ]):
            box = Spin(lo, hi, step, decimals)
            box.valueChanged.connect(lambda value, k=key, f=factor: self.set_config(k, value / f))
            self.controls[key] = (box, factor)
            self.unit_row(grid, row, name, box, unit)
        self.boundary = W.QComboBox()
        for value, text in BOUNDARIES.items():
            self.boundary.addItem(text, value)
        self.boundary.currentIndexChanged.connect(lambda _: self.set_config("boundary", self.boundary.currentData()))
        self.unit_row(grid, 4, "Boundary", self.boundary)
        self.grid = W.QComboBox()
        for n in [128, 200, 320, 512]:
            self.grid.addItem(f"{n} × {round(n*0.6)}", n)
        self.grid.setCurrentIndex(1)
        self.grid.currentIndexChanged.connect(self.new_grid)
        self.unit_row(grid, 5, "Grid", self.grid)
        column.addLayout(grid)
        column.addWidget(label("Changing the grid restarts the experiment. Depth rescales painted regions in proportion.", "muted", wrap=True))
        column.addStretch(1)
        return page

    def build_menus(self):
        def action(menu, text, slot, shortcut=None, checkable=False):
            item = QtGui.QAction(text, self)
            if shortcut:
                item.setShortcut(QtGui.QKeySequence(shortcut))
            item.setCheckable(checkable)
            item.triggered.connect(slot)
            menu.addAction(item)
            return item
        bar = self.menuBar()
        file_menu = bar.addMenu("&File")
        action(file_menu, "&Open experiment…", self.open_file, "Ctrl+O")
        action(file_menu, "&Save experiment…", self.save_file, "Ctrl+S")
        action(file_menu, "&Export field as CSV…", self.export_csv, "Ctrl+E")
        file_menu.addSeparator()
        action(file_menu, "&Quit", self.close, "Ctrl+Q")
        sim = bar.addMenu("&Simulation")
        self.play_action = action(sim, "&Play", self.toggle, "F5")
        action(sim, "&Step", self.step_once, "F6")
        sim.addSeparator()
        action(sim, "&Clear waves", self.clear_waves)
        action(sim, "&Reset experiment", self.reset_experiment, "Ctrl+R")
        view_menu = bar.addMenu("&View")
        group = QtGui.QActionGroup(self)
        self.view_actions = {}
        for i, (value, text) in enumerate(VIEWS.items()):
            item = action(view_menu, f"&{text}", lambda _=False, v=value: self.view.setCurrentText(v), f"Ctrl+{i + 1}", True)
            group.addAction(item)
            self.view_actions[value] = item
        self.view_actions["height"].setChecked(True)

    # ---- engine round trips ---------------------------------------------------------------------
    def say(self, text, error=False):
        self.message.setText(text)
        self.message.setProperty("kind", "error" if error else "")
        self.message.style().unpolish(self.message)
        self.message.style().polish(self.message)

    def sync(self, result, force=False):
        c, d, view = result["config"], result["diagnostics"], result["view"]
        with QtCore.QSignalBlocker(self.view):
            self.view.setCurrentText(view)
        self.view_actions[view].setChecked(True)
        w_m, h_m = extent(c)
        config_changed = self._last_config != c
        if force or config_changed:
            for key, (box, factor) in self.controls.items():
                if force or not box.hasFocus():
                    with QtCore.QSignalBlocker(box):
                        box.setValue(c[key] * factor)
            with QtCore.QSignalBlocker(self.boundary):
                self.boundary.setCurrentIndex(self.boundary.findData(c["boundary"]))
            with QtCore.QSignalBlocker(self.grid):
                index = self.grid.findData(c["nx"])
                if index < 0 or round(c["nx"] * 0.6) != c["ny"]:
                    text = f"{c['nx']} × {c['ny']} (opened file)"
                    index = self.grid.findText(text)
                    if index < 0:
                        self.grid.addItem(text, c["nx"])
                        index = self.grid.count() - 1
                self.grid.setCurrentIndex(index)
            wmm = w_m * 1000
            for box, lo, hi in [(self.brush, math.ceil(wmm * 0.2) / 100, math.floor(wmm * 20) / 100),
                                (self.at_x, 0, w_m * 100), (self.source_x, 0, w_m * 100),
                                (self.at_y, 0, h_m * 100), (self.source_y, 0, h_m * 100)]:
                with QtCore.QSignalBlocker(box):
                    box.setRange(lo, hi)
            self.field.config = dict(c)
            self.update_brush()
            self.grid_info.setText(f"{c['nx']} × {c['ny']} cells    Δx {fixed(w_m / c['nx'] * 1000, 2)} mm    {fixed(w_m * 100, 1)} × {fixed(h_m * 100, 1)} cm")
            self._last_config = dict(c)
        if self._legend_key != (view, c["depth_m"]):
            self.scale_quantity.setText({"height": "Surface height", "depth": "Water depth"}.get(view, "RMS height"))
            self.scale_low.setText("−0.3 mm" if view == "height" else "0 mm")
            self.scale_high.setText("+0.3 mm" if view == "height" else f"{c['depth_m'] * 2000:.1f} mm" if view == "depth" else "0.3 mm")
            self.colorbar.view = view
            self.colorbar.update()
            self._legend_key = (view, c["depth_m"])
        self.clip.setVisible(view == "height" and d["max_height_m"] > 0.0003)
        if force or config_changed or self._last_sources != result["sources"]:
            self._last_sources = [dict(source) for source in result["sources"]]
            self.rebuild_sources()
        self.field.sources = result["sources"]
        self.field.image = self.engine.image()
        self.field.update()
        r = self.readouts
        r["time"][0].setText(f"{d['time_s']:.3f} s")
        r["time"][1].setText(f"{d['steps']:,} steps")
        r["dt"][0].setText(f"{d['dt_s'] * 1000:.3f} ms")
        r["courant"][0].setText(f"{d['courant']:.3f}" if math.isfinite(d.get("courant", math.nan)) else "—")
        r["compute"][0].setText(f"{self.compute_ms:.1f} ms" if self.compute_ms else "—")
        r["compute"][1].setText(f"per {self.pace.value()}-step batch" if self.compute_ms else "")
        r["height"][0].setText(f"{d['max_height_m'] * 1000:.3f} mm")
        ratio = d.get("max_height_depth_ratio", math.nan)
        r["ratio"][0].setText(f"{ratio * 100:.2f} %" if math.isfinite(ratio) else "—")
        r["ratio"][0].setProperty("kind", "warn" if ratio > 0.1 else "")
        r["ratio"][0].style().unpolish(r["ratio"][0])
        r["ratio"][0].style().polish(r["ratio"][0])
        r["energy"][0].setText(joules(d["energy_j"]))
        r["volume"][0].setText(f"{fixed(d['mass_m3'] * 1e6, 4)} mL")

    def perform(self, value, reset_trace=False, note="Ready"):
        try:
            result = self.engine.request(value)
            if reset_trace:
                self.trace.points.clear()
            self.sync(result, force=value.get("op") in {"new", "preset", "load"})
            if value.get("op") in {"new", "preset", "load", "paint", "pulse", "clear", "set", "sources"}:
                self.update_probe()
            if note is not None:
                self.say(note)
            return result
        except (ValueError, OSError) as error:
            self.set_running(False)
            self.say(str(error), error=True)
            return None

    def set_running(self, running):
        self.running = running
        self.play.setText("Pause" if running else "Play")
        self.play.setIcon(QtGui.QIcon(draw_icon("pause" if running else "play", C["ink"], 14)))
        self.play_action.setText("&Pause" if running else "&Play")
        if not running:
            self.compute_ms = None

    def toggle(self):
        self.set_running(not self.running)
        self.say("Running" if self.running else "Paused")

    def step_once(self):
        self.set_running(False)
        self.perform({"op": "advance", "steps": 1})
        self.update_probe()

    def clear_waves(self):
        self.perform({"op": "clear"}, reset_trace=True, note="Waves cleared; walls, depth and sources kept")
        self.update_probe()

    def tick(self):
        if self.running and not self.isMinimized():
            start = time.perf_counter()
            if self.perform({"op": "advance", "steps": self.pace.value()}, note=None) is None:
                return
            self.compute_ms = (time.perf_counter() - start) * 1000
            self.update_probe()

    def update_probe(self):
        try:
            r = self.engine.request({"op": "probe", "x": self.field.probe[0], "y": self.field.probe[1]})
            c, t, sample = r["config"], r["diagnostics"]["time_s"], r["probe"]
            v = sample["height_m"]
            if not self.trace.points or t > self.trace.points[-1][0]:
                self.trace.points.append((t, v))
                self.trace.points = self.trace.points[-600:]
            elif t == self.trace.points[-1][0]:
                self.trace.points[-1] = (t, v)
            self.trace.update()
            w_m, h_m = extent(c)
            ix, iy = (math.floor(v * (n - 1) + 0.5) for v, n in zip(self.field.probe, (c["nx"], c["ny"])))
            self.probe_pos.setText(f"x {fixed((ix + 0.5) / c['nx'] * w_m * 100, 1)} cm, y {fixed((iy + 0.5) / c['ny'] * h_m * 100, 1)} cm")
            self.probe_depth.setText("Inside a wall" if sample["solid"] else f"H {fixed(sample['depth_m'] * 1000, 2)} mm")
            self.probe_value.setText(f"{fixed(v * 1000, 4)} mm")
        except ValueError as error:
            self.say(str(error), error=True)

    # ---- controls -------------------------------------------------------------------------------
    def reset_experiment(self):
        self.set_running(False)
        if self.scenario.currentText() == LOADED and self.loaded_snapshot is not None:
            with QtCore.QSignalBlocker(self.view):
                self.view.setCurrentText("height")
            self.perform({"op": "load", "snapshot": self.loaded_snapshot}, reset_trace=True, note="Restored the opened file")
        else:
            self.perform({"op": "preset", "name": PRESETS[self.scenario.currentText()]}, reset_trace=True)
        self.update_probe()

    def preset(self, name):
        if self.ready and name in PRESETS:
            self.perform({"op": "preset", "name": PRESETS[name]}, reset_trace=True)
            self.update_probe()

    def change_view(self, value):
        self.perform({"op": "view", "name": value})

    def set_config(self, key, value):
        if self.ready:
            if self.perform({"op": "set", "config": {key: value}}, note="Parameters updated") is None:
                self._last_config = None
                self.sync(self.engine.request({"op": "status"}))

    def new_grid(self):
        if not self.ready:
            return
        c = dict(self.engine.last["config"])
        nx = self.grid.currentData()
        ny = int(self.grid.currentText().split(" × ")[1].split()[0])
        c.update(nx=nx, ny=ny)
        if self.scenario.currentText() not in PRESETS:
            with QtCore.QSignalBlocker(self.scenario):
                self.scenario.setCurrentText("Empty tank")
        with QtCore.QSignalBlocker(self.view):
            self.view.setCurrentText("height")
        self.set_running(False)
        self.perform({"op": "new", "config": c, "preset": PRESETS[self.scenario.currentText()]}, reset_trace=True)
        self.update_probe()

    def set_tool(self, tool):
        self.field.tool = tool
        self.field.continuous = tool in ["wall", "depth", "erase"]
        self.tool_name.setText(TOOLS[tool])
        self.tool_hint.setText(TOOL_HINTS[tool])
        for widget in self.brush_row:
            widget.setVisible(tool in BRUSH_TOOLS)
        for widget in self.depth_row:
            widget.setVisible(tool == "depth")
        self.apply_button.setText("Move probe here" if tool == "probe" else "Place source here" if tool == "source" else f"Apply {TOOLS[tool].lower()} here")
        self.field.update()

    def brush_radius(self):
        return min(0.2, max(0.002, self.brush.value() / 1000 / self.engine.last["config"]["width_m"]))

    def update_brush(self, *_):
        if self.engine.last is not None:
            self.field.brush = self.brush_radius()
            self.field.update()

    def rebuild_sources(self):
        sources = self.engine.last["sources"]
        old = self.source_list.currentRow()
        with QtCore.QSignalBlocker(self.source_list):
            self.source_list.clear()
            for i, s in enumerate(sources):
                kind = "Plane wave" if s["kind"] == "plane" else "Point"
                detail = f"{fixed(s['amplitude_m'] * 1000, 3)} mm" if s["enabled"] else "off"
                item = W.QListWidgetItem(f"{i + 1}   {kind}, {tidy(round(s['frequency_hz'], 3))} Hz   {detail}")
                if not s["enabled"]:
                    item.setForeground(QtGui.QColor(C["muted"]))
                self.source_list.addItem(item)
            self.source_list.setCurrentRow(min(max(0, old), len(sources) - 1))
        self.tabs.setTabText(1, f"Sources  {len(sources)}")
        self.source_list.setVisible(bool(sources))
        self.source_empty.setVisible(not sources)
        self.source_editor.setVisible(bool(sources))
        self.select_source()

    def select_source(self, *_):
        if not self.ready:
            return
        sources, c = self.engine.last["sources"], self.engine.last["config"]
        i = self.source_list.currentRow()
        self.field.selected = i
        self.field.update()
        valid = 0 <= i < len(sources)
        for box in [self.freq, self.amp, self.phase, self.source_radius, self.source_x, self.source_y, self.source_enabled, self.remove_button]:
            box.setEnabled(valid)
        if not valid:
            return
        source = sources[i]
        w_m, h_m = extent(c)
        with QtCore.QSignalBlocker(self.source_enabled):
            self.source_enabled.setChecked(source["enabled"])
        for box, value in [(self.freq, source["frequency_hz"]), (self.amp, source["amplitude_m"] * 1000),
                           (self.phase, math.degrees(math.remainder(source["phase_rad"], math.tau))),
                           (self.source_radius, source["radius_m"] * 1000),
                           (self.source_x, to_frac(source["x"], c["nx"]) * w_m * 100),
                           (self.source_y, to_frac(source["y"], c["ny"]) * h_m * 100)]:
            with QtCore.QSignalBlocker(box):
                box.setValue(value)
        self.source_y.setEnabled(source["kind"] != "plane")

    def edit_source(self, *_):
        if not self.ready:
            return
        # Send the whole list but change only the edited field, so exact imported values survive.
        sources = [dict(s) for s in self.engine.last["sources"]]
        c = self.engine.last["config"]
        w_m, h_m = extent(c)
        i = self.source_list.currentRow()
        if 0 <= i < len(sources):
            updates = [(self.freq, "frequency_hz", lambda: self.freq.value()),
                       (self.amp, "amplitude_m", lambda: self.amp.value() / 1000),
                       (self.phase, "phase_rad", lambda: math.radians(self.phase.value())),
                       (self.source_radius, "radius_m", lambda: self.source_radius.value() / 1000),
                       (self.source_x, "x", lambda: to_norm(self.source_x.value() / 100 / w_m, c["nx"])),
                       (self.source_y, "y", lambda: to_norm(self.source_y.value() / 100 / h_m, c["ny"])),
                       (self.source_enabled, "enabled", lambda: self.source_enabled.isChecked())]
            for widget, key, value in updates:
                if widget is self.sender():
                    sources[i][key] = value()
                    self.perform({"op": "sources", "sources": sources})
                    break

    def remove_source(self):
        sources = [dict(s) for s in self.engine.last["sources"]]
        i = self.source_list.currentRow()
        if 0 <= i < len(sources):
            sources.pop(i)
            self.perform({"op": "sources", "sources": sources}, note=f"Source {i + 1} removed")

    def apply_at_coordinates(self):
        c = self.engine.last["config"]
        w_m, h_m = extent(c)
        x, y = to_norm(self.at_x.value() / 100 / w_m, c["nx"]), to_norm(self.at_y.value() / 100 / h_m, c["ny"])
        self.field.cursor = (x, y)
        self.apply_tool(x, y)

    def apply_tool(self, x, y):
        tool = self.tool.currentText()
        c = self.engine.last["config"]
        w_m, h_m = extent(c)
        for box, value in [(self.at_x, to_frac(x, c["nx"]) * w_m * 100), (self.at_y, to_frac(y, c["ny"]) * h_m * 100)]:
            with QtCore.QSignalBlocker(box):
                box.setValue(value)
        if tool == "probe":
            self.field.probe = (x, y)
            self.trace.points.clear()
            self.field.update()
            self.update_probe()
        elif tool == "pulse":
            self.perform({"op": "pulse", "x": x, "y": y, "radius": self.brush_radius(), "amplitude_m": 0.0003})
        elif tool == "source":
            sources = [dict(s) for s in self.engine.last["sources"]]
            sources.append(dict(x=x, y=y, frequency_hz=3, amplitude_m=0.00015, phase_rad=0, kind="point", enabled=True))
            result = self.perform({"op": "sources", "sources": sources}, note=f"Source {len(sources)} added")
            if result:
                self.source_list.setCurrentRow(len(sources) - 1)
        else:
            self.perform({"op": "paint", "x": x, "y": y, "radius": self.brush_radius(),
                          "tool": tool, "depth_m": self.paint_depth.value() / 1000})

    # ---- files ----------------------------------------------------------------------------------
    def save_file(self):
        self.set_running(False)
        filename, _ = W.QFileDialog.getSaveFileName(self, "Save experiment", "tank.ripple.json", "Ripple experiment (*.ripple.json)")
        if filename:
            self.write_snapshot(filename)

    def write_snapshot(self, filename):
        try:
            result = self.engine.request({"op": "snapshot"})
            atomic_write(filename, json.dumps(result["snapshot"], allow_nan=False, separators=(",", ":")))
            self.say(f"Saved {Path(filename).name}")
        except (ValueError, OSError) as error:
            self.say(str(error), error=True)

    def open_file(self):
        self.set_running(False)
        filename, _ = W.QFileDialog.getOpenFileName(self, "Open experiment", "", "Ripple experiment (*.ripple.json *.json)")
        if filename:
            self.load_snapshot(filename)

    def load_snapshot(self, filename):
        try:
            with open(filename, "rb") as f:
                raw = f.read(MAX_FILE+1)
            if len(raw) > MAX_FILE:
                raise ValueError("Experiment exceeds 32 MiB")
            snapshot = json.loads(raw)
            result = self.perform({"op": "load", "snapshot": snapshot}, reset_trace=True)
            if result:
                self.loaded_snapshot = snapshot
                with QtCore.QSignalBlocker(self.view):
                    self.view.setCurrentText("height")
                with QtCore.QSignalBlocker(self.scenario):
                    if self.scenario.findText(LOADED) < 0:
                        self.scenario.addItem(LOADED)
                    self.scenario.setCurrentText(LOADED)
                self.sync(result)
                self.say(f"Loaded {Path(filename).name}")
                self.update_probe()
        except (ValueError, OSError) as error:
            self.say(str(error), error=True)

    def export_csv(self):
        self.set_running(False)
        filename, _ = W.QFileDialog.getSaveFileName(self, "Export field", "field.csv", "CSV (*.csv)")
        if filename:
            try:
                result = self.engine.request({"op": "csv"})
                atomic_write(filename, result["csv"])
                self.say(f"Exported {Path(filename).name}")
            except (ValueError, OSError) as error:
                self.say(str(error), error=True)


STYLE = f"""
QWidget {{ background: transparent; color: {C['text']}; font-size: 13px; }}
QMainWindow, QDialog, QStatusBar {{ background: {C['bg']}; }}
QFrame#stage, QFrame#panel {{ background: {C['panel']}; border: 1px solid {C['line']}; border-radius: 8px; }}
QScrollArea {{ border: 0; }}
QWidget#transport {{ border-bottom: 1px solid {C['line']}; }}
QWidget#bench {{ background: {C['tray']}; }}
QWidget#probe {{ border-top: 1px solid {C['line']}; }}
QLabel {{ background: transparent; }}
QLabel#secondary {{ color: {C['secondary']}; }}
QLabel#muted {{ color: {C['muted']}; font-size: 12px; }}
QLabel#sub {{ color: {C['muted']}; font-size: 11px; }}
QLabel#value {{ font-size: 15px; font-weight: 600; }}
QLabel#value[kind="warn"] {{ color: {C['warn']}; }}
QLabel#warn {{ color: {C['warn']}; font-size: 12px; }}
QLabel#h2 {{ font-size: 15px; font-weight: 600; }}
QLabel#h3 {{ font-weight: 600; }}
QLabel#wall {{ background: {C['wall']}; border-radius: 2px; }}
QLabel#status {{ color: {C['secondary']}; padding: 2px 4px; }}
QLabel#status[kind="error"] {{ color: {C['danger']}; }}
QPushButton, QComboBox, QAbstractSpinBox {{ background: {C['raised']}; border: 1px solid {C['strong']}; border-radius: 6px; padding: 5px 10px; min-height: 22px; }}
QPushButton:hover, QComboBox:hover {{ border-color: {C['accent']}; }}
QPushButton:focus, QComboBox:focus, QAbstractSpinBox:focus, QListWidget:focus {{ border: 2px solid {C['accent']}; }}
QPushButton:disabled, QAbstractSpinBox:disabled, QCheckBox:disabled {{ color: {C['muted']}; }}
QPushButton#primary {{ background: {C['accent']}; color: {C['ink']}; border-color: {C['accent']}; font-weight: 600; min-width: 72px; }}
QPushButton#primary:focus {{ border: 2px solid {C['text']}; }}
QPushButton#quiet {{ background: transparent; color: {C['secondary']}; }}
QAbstractSpinBox {{ padding: 5px 8px; selection-background-color: #3a4a5a; }}
QComboBox QAbstractItemView {{ background: {C['raised']}; border: 1px solid {C['strong']}; selection-background-color: #34404c; outline: 0; }}
QToolButton#tool {{ color: {C['secondary']}; background: transparent; border: 1px solid transparent; border-radius: 6px; padding: 6px 2px 4px; min-width: 58px; font-size: 12px; }}
QToolButton#tool:hover {{ color: {C['text']}; background: rgba(255,255,255,10); }}
QToolButton#tool:checked {{ color: {C['text']}; background: rgba(189,204,221,30); border-color: rgba(189,204,221,128); }}
QToolButton#tool:focus {{ border: 2px solid {C['accent']}; }}
QToolButton#seg {{ color: {C['secondary']}; background: {C['raised']}; border: 1px solid {C['strong']}; border-radius: 6px; padding: 4px 10px; }}
QToolButton#seg:checked {{ color: {C['ink']}; background: {C['accent']}; border-color: {C['accent']}; }}
QToolButton#seg:focus {{ border: 2px solid {C['text']}; }}
QTabWidget::pane {{ border: 0; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{ background: transparent; color: {C['secondary']}; padding: 10px 12px; border: 0; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {C['text']}; border-bottom: 2px solid {C['accent']}; }}
QTabBar::tab:focus {{ color: {C['text']}; }}
QListWidget {{ background: {C['panel']}; border: 1px solid {C['line']}; border-radius: 6px; padding: 2px; outline: 0; }}
QListWidget::item {{ padding: 6px 6px; border-radius: 5px; }}
QListWidget::item:selected {{ background: rgba(189,204,221,34); color: {C['text']}; }}
QGroupBox {{ border: 1px solid {C['line']}; border-radius: 6px; margin-top: 18px; padding-top: 4px; color: {C['secondary']}; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 2px; padding: 0 2px; }}
QCheckBox {{ spacing: 8px; }}
QStatusBar {{ color: {C['secondary']}; border-top: 1px solid {C['line']}; }}
QStatusBar::item {{ border: 0; }}
QMenuBar {{ background: {C['bg']}; border-bottom: 1px solid {C['line']}; }}
QMenuBar::item {{ padding: 5px 10px; background: transparent; }}
QMenuBar::item:selected {{ background: {C['raised']}; }}
QMenu {{ background: {C['panel']}; border: 1px solid {C['strong']}; padding: 4px; }}
QMenu::item {{ padding: 6px 24px 6px 18px; border-radius: 4px; }}
QMenu::item:selected {{ background: #34404c; }}
QMenu::separator {{ height: 1px; background: {C['line']}; margin: 4px 8px; }}
QSplitter::handle {{ background: transparent; width: 10px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {C['strong']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QToolTip {{ color: {C['text']}; background: {C['raised']}; border: 1px solid {C['strong']}; padding: 4px; }}
"""


def configure(app):
    """Fusion with a graphite palette, so natively drawn parts (arrows, checks, scroll bars) match the stylesheet."""
    app.setStyle("Fusion")
    R = QtGui.QPalette.ColorRole
    palette = QtGui.QPalette()
    for role, color in [(R.Window, C["bg"]), (R.WindowText, C["text"]), (R.Base, C["raised"]), (R.AlternateBase, C["panel"]),
                        (R.Text, C["text"]), (R.Button, C["raised"]), (R.ButtonText, C["text"]), (R.BrightText, C["text"]),
                        (R.Highlight, C["accent"]), (R.HighlightedText, C["ink"]), (R.ToolTipBase, C["raised"]),
                        (R.ToolTipText, C["text"]), (R.PlaceholderText, C["muted"]), (R.Light, C["strong"]),
                        (R.Midlight, C["line"]), (R.Mid, C["line"]), (R.Dark, C["tray"]), (R.Shadow, "#000000"), (R.Link, C["accent"])]:
        palette.setColor(role, QtGui.QColor(color))
    for role in (R.Text, R.ButtonText, R.WindowText):
        palette.setColor(QtGui.QPalette.ColorGroup.Disabled, role, QtGui.QColor(C["muted"]))
    app.setPalette(palette)
    font = app.font()
    font.setFamilies(["Public Sans", "Inter", "Noto Sans", "Cantarell", "DejaVu Sans"])
    app.setFont(font)
    app.setStyleSheet(STYLE)


def main():
    app = W.QApplication(sys.argv)
    configure(app)
    app.setApplicationName("Flintglade Ripple Tank")
    try:
        window = Window()
        window.show()
    except (ValueError, OSError, RuntimeError) as error:
        W.QMessageBox.critical(None, "Ripple Tank", str(error))
        return 1
    if len(sys.argv) == 3 and sys.argv[1] == "--verify-dir":
        destination = Path(sys.argv[2])
        destination.mkdir(parents=True, exist_ok=True)
        def verify():
            try:
                window.scenario.setCurrentText("Pulse")
                window.perform({"op": "advance", "steps": 128})
                saved = window.engine.request({"op": "snapshot"})["snapshot"]
                window.write_snapshot(destination / "packaged.ripple.json")
                window.perform({"op": "clear"})
                window.load_snapshot(destination / "packaged.ripple.json")
                assert window.engine.request({"op": "snapshot"})["snapshot"] == saved
                window.grab().save(str(destination / "packaged.png"))
                report = {"ok": True, "native_widgets": True, "restart_exact": True,
                          "diagnostics": window.engine.last["diagnostics"]}
                atomic_write(destination / "packaged-result.json", json.dumps(report))
                print(json.dumps(report), flush=True)
                app.exit(0)
            except Exception as error:
                print(json.dumps({"ok": False, "error": str(error)}), flush=True)
                app.exit(1)
        QtCore.QTimer.singleShot(100, verify)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
