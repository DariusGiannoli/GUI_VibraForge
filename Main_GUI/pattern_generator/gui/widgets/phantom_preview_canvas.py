from __future__ import annotations
from typing import Dict, Tuple, List, Optional
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QTimer, QPointF
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QFont

from core.phantom_engine import PreviewBundle, PhantomStep

class PhantomPreviewCanvas(QWidget):
    """
    Pure preview widget (no hardware). It shows:
    - layout actuators
    - user path
    - sampled phantom points
    - current preview playback (which real actuators fire for each phantom)
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(520, 420)
        self._layout: Dict[int, Tuple[float,float]] = {}
        self._path: List[Tuple[float,float]] = []
        self._samples: List[Tuple[float,float]] = []
        self._steps: List[PhantomStep] = []
        self._playing_index: Optional[int] = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)

    # ------- data -------
    def set_bundle(self, bundle: PreviewBundle):
        self._layout = bundle.layout_positions
        self._path = bundle.path_points
        self._samples = [(pp.x, pp.y) for pp in bundle.samples]
        self._steps = bundle.steps
        self._playing_index = None
        self.update()

    # ------- playback (preview only) -------
    def preview_play(self, speed_ms: int = 40):
        if not self._steps:
            return
        self._playing_index = -1
        self._timer.start(max(20, speed_ms))

    def preview_stop(self):
        self._timer.stop()
        self._playing_index = None
        self.update()

    def _advance(self):
        if self._playing_index is None or not self._steps:
            self._timer.stop()
            return
        self._playing_index += 1
        if self._playing_index >= len(self._steps):
            self._timer.stop()
            self._playing_index = None
        self.update()

    # ------- drawing -------
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        margin = 24

        if not self._layout:
            p.drawText(20, 40, "No layout loaded.")
            return

        xs = [v[0] for v in self._layout.values()]
        ys = [v[1] for v in self._layout.values()]
        minx, maxx = min(xs), max(xs)
        miny, maxy = min(ys), max(ys)
        rngx = max(100.0, maxx - minx)
        rngy = max(100.0, maxy - miny)

        w = self.width() - 2*margin
        h = self.height() - 2*margin
        scale = min(w/rngx, h/rngy) * 0.95

        def to_screen(pt):
            return (margin + (pt[0]-minx)*scale,
                    margin + (pt[1]-miny)*scale)

        # title
        p.setPen(QPen(QColor(0,0,0)))
        f = QFont(); f.setBold(True); f.setPointSize(10)
        p.setFont(f)
        p.drawText(margin, 16, "Phantom Preview (no device)")

        # path
        if len(self._path) >= 2:
            p.setPen(QPen(QColor(0,150,255), 3))
            for a,b in zip(self._path[:-1], self._path[1:]):
                ax, ay = to_screen(a); bx, by = to_screen(b)
                p.drawLine(int(ax), int(ay), int(bx), int(by))

        # samples
        p.setBrush(QBrush(QColor(200,100,200)))
        p.setPen(QPen(QColor(0,0,0), 1))
        for sx, sy in self._samples:
            x, y = to_screen((sx, sy))
            p.drawEllipse(int(x-5), int(y-5), 10, 10)

        # actuators
        for aid, pos in self._layout.items():
            x, y = to_screen(pos)
            color = QColor(120,120,120)
            radius = 12
            if self._playing_index is not None and 0 <= self._playing_index < len(self._steps):
                step = self._steps[self._playing_index]
                if aid in (step.a1, step.a2, step.a3):
                    color = QColor(255,80,80)  # firing
                    radius = 15
            p.setBrush(QBrush(color)); p.setPen(QPen(QColor(0,0,0), 2))
            p.drawEllipse(int(x-radius), int(y-radius), radius*2, radius*2)
            p.setPen(QPen(QColor(255,255,255)))
            p.drawText(int(x-6), int(y+4), str(aid))

        # highlight current phantom + lines to actuators
        if self._playing_index is not None and 0 <= self._playing_index < len(self._steps):
            step = self._steps[self._playing_index]
            px, py = to_screen(step.phantom_pos)
            p.setBrush(QBrush(QColor(255,50,255)))
            p.setPen(QPen(QColor(0,0,0), 2))
            p.drawEllipse(int(px-10), int(py-10), 20, 20)

            # lines to physical actuators
            for a, label in [(step.a1, step.i1), (step.a2, step.i2), (step.a3, step.i3)]:
                ax, ay = to_screen(self._layout[a])
                p.setPen(QPen(QColor(150,0,150), 2, Qt.PenStyle.DashLine))
                p.drawLine(int(px), int(py), int(ax), int(ay))
                p.setPen(QPen(QColor(0,0,0)))
                p.drawText(int((px+ax)/2), int((py+ay)/2), f"{label}")