import os
import json
import time
import math
from PyQt6.QtCore import Qt, QTimer, QPoint, QPointF, QRectF, QSize, pyqtSignal, QDateTime
from PyQt6.QtGui import (QPainter, QPen, QBrush, QColor, QFont, QImage, 
                        QPixmap, QKeySequence)
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
                           QLabel, QPushButton, QCheckBox, QSpinBox, QListWidget,
                           QListWidgetItem, QMenu, QMessageBox, QInputDialog,
                           QSizePolicy, QGridLayout)
from ..utils.managers import DrawingLibraryManager
from ..utils.workers import StrokePlaybackWorker

# Import circulaire résolu avec TYPE_CHECKING
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .actuator_widgets import MultiCanvasSelector

class DrawingCanvasOverlay(QWidget):
    """
    Freehand overlay on top of the actuator canvas.
    - Library drawings are persistent and colorized.
    - The user's own drawing: keep the last stroke after mouse release,
      but erase it automatically when starting a new stroke.
    - NEW:
      • Live phantom preview while drawing (cursor)
      • Right-click to drop a persistent phantom (P0, P1, …) with links to real actuators
      • Phantoms are saved/loaded/exported with the drawing

    """

        # Live-drawing hooks
    strokeStarted = pyqtSignal()
    pointDrawn = pyqtSignal(float, float)   # normalized x, y in [0,1]
    strokeEnded = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StaticContents)
        self.setMouseTracking(True)

        # Persistent library layer
        self._layer = QImage(self.size(), QImage.Format.Format_ARGB32_Premultiplied)
        self._layer.fill(Qt.GlobalColor.transparent)

        # One "live" stroke that persists until next press
        self._live = QImage(self.size(), QImage.Format.Format_ARGB32_Premultiplied)
        self._live.fill(Qt.GlobalColor.transparent)
        self._live_stroke: dict | None = None
        self._live_points: list[tuple[float, float]] = []

        # Temp while dragging (stroke preview)
        self._temp = QImage(self.size(), QImage.Format.Format_ARGB32_Premultiplied)
        self._temp.fill(Qt.GlobalColor.transparent)

        # NEW: HUD for ephemeral markers (phantom cursor preview)
        self._hud = QImage(self.size(), QImage.Format.Format_ARGB32_Premultiplied)
        self._hud.fill(Qt.GlobalColor.transparent)

        self._phantoms_layer = QImage(self.size(), QImage.Format.Format_ARGB32_Premultiplied)
        self._phantoms_layer.fill(Qt.GlobalColor.transparent)

        self._trajectory_enabled = False
        self._traj_max_phantoms = 30
        self._traj_sampling_ms = 50
        self._traj_last_drop_s = 0.0
        self._traj_last_pt = None  # (x,y) normalisé du dernier drop



        self._pen_width = 4
        self._is_erasing = False
        self._drawing = False
        self._last_pos = QPoint()

        # Actuator anchors visible in "standalone" mode (when not overlaying)
        self._nodes: list[tuple[int, float, float]] = []

        # If True, just overlay; if False, we paint nodes as a background
        self._overlay_mode = True

        # Stored strokes (library only)
        self._strokes: list[dict] = []

        # Palette for appended drawings
        self._palette = [
            "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
            "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"
        ]
        self._color_idx = 0

        # NEW: phantom rendering params + storage
        self._phantom_mode: str = "Phantom (3-Act, Park 2016)"
        self._phantom_gain: int = 8
        self._phantoms: list[dict] = []   # [{id:int, pt:(x,y), bursts:[(addr,intensity), ...]}]
        self._phantom_counter: int = 0

        self._draw_enabled = True
        self._traj_count = 0
        self._traj_last_drop_ms = None
        self._traj_session_ids: list[int] = []
        self._hud_only_while_drawing = True

        self.set_mouse_passthrough(True)

    # ----- basic config -----
    def set_overlay_mode(self, on: bool):
        self._overlay_mode = bool(on); self.update()
    
    def set_draw_enabled(self, on: bool):
        self._draw_enabled = bool(on)
        if not self._draw_enabled:
            self.clear_preview_marker()  # hide dashed links immediately

    def set_mouse_passthrough(self, on: bool):
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, bool(on))

    def set_nodes(self, nodes: list[tuple[int, float, float]]):
        self._nodes = nodes[:] if nodes else []; self.update()

    def set_pen_width(self, w: int):
        self._pen_width = max(1, int(w)); self.update()

    # ----- NEW: phantom preview settings -----
    def set_phantom_mode(self, mode: str):
        self._phantom_mode = str(mode or self._phantom_mode)

    def set_phantom_gain(self, av: int):
        self._phantom_gain = int(max(1, min(15, av)))

    # ----- persistence API -----
    def clear(self):
        self._strokes.clear()
        self._layer.fill(Qt.GlobalColor.transparent)
        self._live.fill(Qt.GlobalColor.transparent)
        self._temp.fill(Qt.GlobalColor.transparent)
        self._hud.fill(Qt.GlobalColor.transparent)
        self._phantoms_layer.fill(Qt.GlobalColor.transparent)
        self._live_stroke = None
        self._live_points = []
        # NEW: clear phantoms
        self._phantoms.clear()
        self._phantom_counter = 0
        self._traj_count = 0
        self._traj_last_drop_ms = None
        self.update()

    def to_json(self) -> dict:
        strokes = [dict(s) for s in self._strokes]
        if self._live_stroke and self._live_points:
            s = dict(self._live_stroke)
            s["points"] = list(self._live_points)
            strokes.append(s)
        return {
            "pen_default": self._pen_width,
            "strokes": strokes,
            "canvas": {"w": self.width(), "h": self.height()},
            "nodes": [{"id": i, "x": x, "y": y} for (i, x, y) in self._nodes],
            # NEW: persist phantoms
            "phantoms": [
                {"id": p["id"], "x": p["pt"][0], "y": p["pt"][1], "bursts": list(p["bursts"])}
                for p in self._phantoms
            ],
            "phantom_mode": self._phantom_mode,
            "phantom_gain": self._phantom_gain,
        }

    def load_json(self, data: dict):
        self.clear()
        # strokes
        for s in data.get("strokes", []):
            pts = list(s.get("points", []))
            width = int(s.get("width", 4))
            erase = bool(s.get("erase", False))
            color = s.get("color") or self._next_color()
            self._replay_stroke(pts, width, erase, color, record=True)
        # nodes
        nd = []
        for d in data.get("nodes", []):
            try: nd.append((int(d["id"]), float(d["x"]), float(d["y"])))
            except Exception: pass
        if nd: self._nodes = nd
        # NEW: phantoms
        self._phantom_mode = data.get("phantom_mode", self._phantom_mode)
        self._phantom_gain = int(data.get("phantom_gain", self._phantom_gain))
        for ph in data.get("phantoms", []):
            try:
                pid = int(ph.get("id", self._phantom_counter))
                pt = (float(ph["x"]), float(ph["y"]))
                bursts = [(int(a), int(i)) for (a, i) in ph.get("bursts", [])]
                self._phantoms.append({"id": pid, "pt": pt, "bursts": bursts})
                self._phantom_counter = max(self._phantom_counter, pid + 1)
                self._draw_persistent_phantom(pt, bursts, f"P{pid}")
            except Exception:
                pass
        self.update()

    def append_json(self, data: dict, color: str | None = None):
        draw_color = color or self._next_color()
        for s in data.get("strokes", []):
            pts = list(s.get("points", []))
            width = int(s.get("width", 4))
            erase = bool(s.get("erase", False))
            self._replay_stroke(pts, width, erase, draw_color, record=True)

    # ----- Qt events -----
    def resizeEvent(self, e):
        def _resize(img: QImage) -> QImage:
            new_img = QImage(self.size(), QImage.Format.Format_ARGB32_Premultiplied)
            new_img.fill(Qt.GlobalColor.transparent)
            p = QPainter(new_img)
            p.drawImage(0, 0, img.scaled(self.size(),
                                         Qt.AspectRatioMode.IgnoreAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation))
            p.end()
            return new_img
        if self._layer.size() != self.size(): self._layer = _resize(self._layer)
        if self._live.size()  != self.size(): self._live  = _resize(self._live)
        if self._temp.size()  != self.size(): self._temp  = _resize(self._temp)
        if self._hud.size()   != self.size(): self._hud   = _resize(self._hud)
        if self._phantoms_layer.size() != self.size():
            self._phantoms_layer = _resize(self._phantoms_layer)
        super().resizeEvent(e)

    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if not self._overlay_mode:
            p.fillRect(self.rect(), self.palette().base())
            self._paint_nodes(p)
        p.drawImage(0, 0, self._layer)  # library
        p.drawImage(0, 0, self._phantoms_layer) 
        p.drawImage(0, 0, self._live)   # last user stroke
        p.drawImage(0, 0, self._temp)   # current dragging
        p.drawImage(0, 0, self._hud)    # NEW: ephemeral phantom marker

        p.end()

    def mousePressEvent(self, e):
        """Left: start drawing (if draw-enabled) and optionally drop a trajectory phantom.
        Right: manual phantom drop (always allowed)."""
        if e.button() == Qt.MouseButton.LeftButton:
            self._drawing = True
            self.strokeStarted.emit()
            pos = e.position().toPoint()
            self._last_pos = pos
            pt_norm = self._to_norm(pos)

            # Start a new live stroke only when Draw mode is enabled
            if getattr(self, "_draw_enabled", True):
                self._live.fill(Qt.GlobalColor.transparent)
                self._hud.fill(Qt.GlobalColor.transparent)
                self._temp.fill(Qt.GlobalColor.transparent)
                self._live_points = [pt_norm]
                self._live_stroke = {
                    "points": [],
                    "width": int(self._pen_width),
                    "erase": False,
                    "color": "#111827"
                }
                # seed a tiny segment so the first dot is visible
                self._draw_temp_segment(self._last_pos, self._last_pos)

            # Trajectory mode: force a first phantom at the press location
            if getattr(self, "_trajectory_enabled", False):
                now_ms = time.perf_counter() * 1000.0
                # initialize counters if missing
                if getattr(self, "_traj_count", None) is None:
                    self._traj_count = 0
                if getattr(self, "_traj_last_drop_ms", None) is None:
                    self._traj_last_drop_ms = -1e9

                if self._traj_count < int(getattr(self, "_traj_max", 30)):
                    bursts = self._compute_bursts_for_pt(pt_norm)
                    label = f"P{self._phantom_counter}"
                    self._phantoms.append({"id": self._phantom_counter, "pt": pt_norm, "bursts": bursts})
                    self._traj_session_ids.append(self._phantom_counter)
                    self._phantom_counter += 1
                    self._traj_count += 1
                    self._traj_last_drop_ms = now_ms
                    self._draw_persistent_phantom(pt_norm, bursts, label)

            # Always show a HUD preview under the cursor
            try:
                bursts = self._compute_bursts_for_pt(pt_norm)
                node_map = {aid: (x, y) for (aid, x, y) in self._nodes}
                self.show_preview_marker(pt_norm, node_map, bursts)
            except Exception:
                pass

        elif e.button() == Qt.MouseButton.RightButton:
            # Manual phantom drop (independent from Draw/Trajectory toggles)
            pos = e.position().toPoint()
            pt_norm = self._to_norm(pos)
            try:
                bursts = self._compute_bursts_for_pt(pt_norm)
                label = f"P{self._phantom_counter}"
                self._phantoms.append({"id": self._phantom_counter, "pt": pt_norm, "bursts": bursts})
                self._traj_session_ids.append(self._phantom_counter)
                self._phantom_counter += 1
                self._draw_persistent_phantom(pt_norm, bursts, label)
                self.update()
            except Exception:
                pass

        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        """While dragging: draw stroke if enabled and emit trajectory phantoms at the sampling rate.
        Always render the HUD phantom preview at the cursor."""
        pos = e.position().toPoint()
        pt_norm = self._to_norm(pos)

        if self._drawing:
            # Draw stroke only when Draw mode is enabled
            if getattr(self, "_draw_enabled", True):
                self._draw_temp_segment(self._last_pos, pos)
                self._live_points.append(pt_norm)
                self.pointDrawn.emit(float(pt_norm[0]), float(pt_norm[1]))
                self._last_pos = pos

            # Trajectory mode: drop phantoms along the path according to sampling rate
            if getattr(self, "_trajectory_enabled", False):
                now_ms = time.perf_counter() * 1000.0
                last = getattr(self, "_traj_last_drop_ms", -1e9)
                sampling = float(getattr(self, "_traj_sampling_ms", 50))
                if self._traj_count < int(getattr(self, "_traj_max", 30)) and (now_ms - last) >= sampling:
                    try:
                        bursts = self._compute_bursts_for_pt(pt_norm)
                        label = f"P{self._phantom_counter}"
                        self._phantoms.append({"id": self._phantom_counter, "pt": pt_norm, "bursts": bursts})
                        self._traj_session_ids.append(self._phantom_counter)
                        self._phantom_counter += 1
                        self._traj_count += 1
                        self._traj_last_drop_ms = now_ms
                        self._draw_persistent_phantom(pt_norm, bursts, label)
                    except Exception:
                        pass

        # Show HUD links only WHILE actively drawing
        if self._drawing:
            try:
                bursts = self._compute_bursts_for_pt(pt_norm)
                node_map = {aid: (x, y) for (aid, x, y) in self._nodes}
                self.show_preview_marker(pt_norm, node_map, bursts)
            except Exception:
                pass
        else:
            # ensure it's hidden when not drawing
            self.clear_preview_marker()

        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        """Finish the live stroke (if any) and clear the HUD."""
        if e.button() == Qt.MouseButton.LeftButton and self._drawing:
            self._drawing = False
            self.strokeEnded.emit()

            # Commit the live stroke only when Draw mode is enabled
            if getattr(self, "_draw_enabled", True):
                p = QPainter(self._live)
                p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                p.drawImage(0, 0, self._temp)
                p.end()
                self._temp.fill(Qt.GlobalColor.transparent)

                if self._live_stroke is not None:
                    self._live_stroke["points"] = list(self._live_points)

            # Clear HUD circle/links
            if getattr(self, "_trajectory_enabled", False):
                self._redistribute_traj_phantoms_uniform()
            self._hud.fill(Qt.GlobalColor.transparent)
            self.update()

        super().mouseReleaseEvent(e)

    # ----- helper internals -----
    def _next_color(self) -> str:
        c = self._palette[self._color_idx % len(self._palette)]
        self._color_idx += 1
        return c

    def _draw_temp_segment(self, a: QPoint, b: QPoint):
        painter = QPainter(self._temp)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor("#111827"), self._pen_width,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawLine(a, b)
        painter.end()
        self.update()

    def _replay_stroke(self, points: list, width: int, erase: bool, color: str, record: bool):
        if not points: return
        painter = QPainter(self._layer)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if erase:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        else:
            painter.setPen(QPen(QColor(color), int(width),
                                Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        last = self._from_norm(points[0])
        for p in points[1:]:
            cur = self._from_norm(p)
            painter.drawLine(last, cur)
            last = cur
        painter.end()
        if record:
            self._strokes.append({"points": list(points), "width": int(width), "erase": bool(erase), "color": color})
        self.update()

    def export_png(self, path: str) -> bool:
        img = QImage(self.size(), QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.white)
        p = QPainter(img); p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._paint_nodes(p)
        p.drawImage(0, 0, self._layer)  # library strokes + persistent phantoms
        p.drawImage(0, 0, self._phantoms_layer)
        p.drawImage(0, 0, self._live)   # last user stroke
        p.end()
        return img.save(path)
    
    def enable_trajectory(self, on: bool):
        self._trajectory_enabled = bool(on)
        self._traj_last_drop_s = 0.0
        self._traj_last_pt = None

    def _maybe_drop_traj_phantom(self, pt_norm: tuple[float,float], force: bool = False):
        """Dépose un phantom persistant le long du tracé, si sampling + max OK."""
        if not self._trajectory_enabled:
            return
        if len(self._phantoms) >= self._traj_max_phantoms:
            return

        now = time.perf_counter()
        if not force and (now - self._traj_last_drop_s) < (self._traj_sampling_ms / 1000.0):
            return

        # évite les doublons trop proches
        if self._traj_last_pt is not None and not force:
            if math.hypot(pt_norm[0]-self._traj_last_pt[0], pt_norm[1]-self._traj_last_pt[1]) < 0.005:
                return

        bursts = self._compute_bursts_for_pt(pt_norm)
        label = f"P{self._phantom_counter}"
        self._phantoms.append({"id": self._phantom_counter, "pt": pt_norm, "bursts": bursts})
        self._traj_session_ids.append(self._phantom_counter)
        self._phantom_counter += 1
        self._draw_persistent_phantom(pt_norm, bursts, label)
        self._traj_last_drop_s = now
        self._traj_last_pt = pt_norm
        self.update()

    def _resample_polyline_uniform(self, pts: list[tuple[float,float]], n: int):
        if n <= 1 or len(pts) < 2:
            return pts[:1] * max(1, n)
        # distances cumulées
        d = [0.0]
        for a, b in zip(pts, pts[1:]):
            d.append(d[-1] + math.hypot(b[0]-a[0], b[1]-a[1]))
        L = d[-1] if d[-1] > 0 else 1e-9
        targets = [i * L / (n - 1) for i in range(n)]
        out, j = [], 0
        for t in targets:
            while j + 1 < len(d) and d[j+1] < t:
                j += 1
            if j + 1 >= len(d):
                out.append(pts[-1]); continue
            seg = d[j+1] - d[j]
            alpha = 0.0 if seg <= 0 else (t - d[j]) / seg
            x = pts[j][0] + alpha * (pts[j+1][0] - pts[j][0])
            y = pts[j][1] + alpha * (pts[j+1][1] - pts[j][1])
            out.append((x, y))
        return out

    def _redistribute_traj_phantoms_uniform(self):
        # rien à faire si pas en mode trajectoire
        if not getattr(self, "_trajectory_enabled", False):
            return
        if not self._traj_session_ids or len(self._live_points) < 2:
            # aucune session ou pas de trait utile
            self._traj_session_ids.clear()
            return

        n = min(len(self._traj_session_ids), int(self._traj_max_phantoms))
        samples = self._resample_polyline_uniform(self._live_points, n)

        # 1) retirer les anciens phantoms de la session courante
        ids_to_remove = set(self._traj_session_ids)
        self._phantoms = [p for p in self._phantoms if p["id"] not in ids_to_remove]
        self._traj_session_ids.clear()

        # 2) effacer et re-dessiner la couche persistante (pour garder les autres phantoms)
        self._phantoms_layer.fill(Qt.GlobalColor.transparent)
        for p in self._phantoms:
            self._draw_persistent_phantom(p["pt"], p["bursts"], f"P{p['id']}")

        # 3) ajouter n phantoms uniformément répartis sur le trait
        for pt in samples:
            bursts = self._compute_bursts_for_pt(pt)
            pid = self._phantom_counter
            self._phantoms.append({"id": pid, "pt": pt, "bursts": bursts})
            self._draw_persistent_phantom(pt, bursts, f"P{pid}")
            self._traj_session_ids.append(pid)
            self._phantom_counter += 1

        # cette session est maintenant “reconstruite” → on vide le marqueur
        self._traj_session_ids.clear()
        self.update()
    def set_traj_limits(self, max_phantoms: int, sampling_ms: int):
        self._traj_max_phantoms = int(max(1, max_phantoms))
        self._traj_sampling_ms = int(max(10, sampling_ms))

    def clear_strokes_only(self):
        """Efface uniquement le dessin (garde les phantoms)."""
        self._strokes.clear()
        self._layer.fill(Qt.GlobalColor.transparent)
        self._live.fill(Qt.GlobalColor.transparent)
        self._temp.fill(Qt.GlobalColor.transparent)
        self._hud.fill(Qt.GlobalColor.transparent)
        self._live_stroke = None
        self._live_points = []
        self.update()

    def clear_phantoms_only(self):
        """Efface uniquement les phantoms persistants."""
        self._phantoms.clear()
        self._phantoms_layer.fill(Qt.GlobalColor.transparent)
        self._phantom_counter = 0
        self.update()

    def _paint_nodes(self, p: QPainter):
        r = 16
        for nid, xn, yn in self._nodes:
            cx = int(xn * (self.width() - 48) + 24)
            cy = int(yn * (self.height() - 48) + 24)
            rect = QRectF(cx - r, cy - r, 2*r, 2*r)
            p.setPen(QPen(QColor("#374151"), 2))
            p.setBrush(QBrush(QColor("#E5E7EB")))
            p.drawEllipse(rect)
            p.setPen(QPen(QColor("#111827")))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(nid))

    def _to_norm(self, pt: QPoint) -> tuple[float, float]:
        return (max(0.0, min(1.0, pt.x() / max(1, self.width() - 1))),
                max(0.0, min(1.0, pt.y() / max(1, self.height() - 1))))

    def _from_norm(self, xy: tuple[float, float]) -> QPoint:
        return QPoint(int(xy[0] * (self.width() - 1)), int(xy[1] * (self.height() - 1)))

    # ===== NEW: phantom computation & drawing =====
    def _compute_bursts_for_pt(self, pt_norm: tuple[float, float]) -> list[tuple[int,int]]:
        """Compute (actuator_id, intensity) set for a phantom at pt_norm,
        using current phantom mode and gain, based on nearest anchors in self._nodes."""
        id_to_xy = {aid: (x, y) for (aid, x, y) in self._nodes}
        if not id_to_xy:
            return []
        # Distances
        items = []
        for aid, (x, y) in id_to_xy.items():
            d = math.hypot(pt_norm[0] - x, pt_norm[1] - y)
            items.append((aid, d))
        items.sort(key=lambda t: t[1])

        Av = int(self._phantom_gain)
        mode = self._phantom_mode or ""
        try:
            if mode.startswith("Physical"):
                a1, _ = items[0]
                return [(a1, Av)]
            elif "2-Act" in mode:
                (a1, d1), (a2, d2) = items[:2]
                from_this = StrokePlaybackWorker._phantom_intensities_2act(d1, d2, Av)
                return [(a1, from_this[0]), (a2, from_this[1])]
            else:
                (a1, d1), (a2, d2), (a3, d3) = items[:3]
                A1, A2, A3 = StrokePlaybackWorker._phantom_intensities_3act(d1, d2, d3, Av)
                return [(a1, A1), (a2, A2), (a3, A3)]
        except Exception:
            # fallback: nearest-1
            a1, _ = items[0]
            return [(a1, Av)]
# DrawingCanvasOverlay._draw_persistent_phantom
    def _draw_persistent_phantom(self, pt_norm: tuple[float,float],
                                bursts: list[tuple[int,int]], label: str):
        """Commit un phantom (cercle + label) en PERSISTANT, sans liens."""
        p = QPainter(self._phantoms_layer)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        c = self._from_norm(pt_norm)
        r = 12

        p.setPen(QPen(QColor("#E11D48"), 3))
        p.setBrush(QBrush(QColor(0, 0, 0, 0)))
        p.drawEllipse(QRectF(c.x()-r, c.y()-r, 2*r, 2*r))

        p.setPen(QPen(QColor("#7C3AED")))
        p.setFont(QFont("", 9, QFont.Weight.Bold))
        p.drawText(c + QPoint(14, 4), label)

        p.end()

    # ===== UPDATED: HUD preview used by GUI and by live drawing =====
    def show_preview_marker(self, pt_norm: tuple[float,float],
                            node_map: dict[int, tuple[float,float]],
                            bursts: list[tuple[int,int]]):
        """Draw an ephemeral preview (phantom circle + dashed links) on the HUD."""
        # if getattr(self, "_hud_only_while_drawing", False) and not getattr(self, "_drawing", False):
        #     # also clear any stale HUD
        #     self._hud.fill(Qt.GlobalColor.transparent)
        #     self.update()
        #     return
        self._hud.fill(Qt.GlobalColor.transparent)
        p = QPainter(self._hud)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # phantom (circle)
        c = self._from_norm(pt_norm)
        r = 10
        p.setPen(QPen(QColor("#E11D48"), 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(c.x()-r, c.y()-r, 2*r, 2*r))

        # links to active actuators (with intensity labels)
        for aid, inten in bursts:
            if aid in node_map:
                nx, ny = node_map[aid]
                npt = self._from_norm((nx, ny))
                p.setPen(QPen(QColor("#7C3AED"), 2, Qt.PenStyle.DashLine))
                p.drawLine(c, npt)
                p.setPen(QPen(QColor("#111827")))
                midx = int((c.x() + npt.x())/2)
                midy = int((c.y() + npt.y())/2)
                p.drawText(midx, midy, str(inten))
        p.end()
        self.update()

    def clear_preview_marker(self):
        self._hud.fill(Qt.GlobalColor.transparent)
        self.update()

class DrawingStudioTab(QWidget):
    """
    Minimal, focused Drawing Studio:
    - Top bar: Clear · Draw mode · Save
    - Library list (double-click to load; right-click to delete)
    - High-Density Trajectory Creation (no 'Stop Drawing' button)
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.lib = DrawingLibraryManager()
        self.canvas_selector: MultiCanvasSelector | None = None
        self._overlay: DrawingCanvasOverlay | None = None

        root = QVBoxLayout(self)
        root.setSpacing(6)
        root.setContentsMargins(6, 6, 6, 6)

    # ═══════════════════════════ Top bar (Clear · Save · Draw mode) - CORRECTED ═══════════════════════════
        hdr = QHBoxLayout()
        hdr.setContentsMargins(0, 0, 0, 0)
        hdr.setSpacing(6)

        self.btnClear = QPushButton("Clear")
        self.btnSave = QPushButton("Save")
        self.chkDraw = QCheckBox("Draw")
        self.chkLive = QCheckBox("Live Drawing")
        self.chkLive.setToolTip("When enabled, the stroke is played on the device while you draw.")
        self.chkDraw.setToolTip("Enable freehand drawing on the overlay.")

        # CORRECTION: Limiter la largeur des boutons
        self.btnClear.setMaximumWidth(80)
        self.btnSave.setMaximumWidth(80)
        
        hdr.addWidget(self.btnClear)
        hdr.addWidget(self.btnSave)
        hdr.addStretch()  # push Draw mode to the right
        hdr.addWidget(self.chkDraw)
        hdr.addWidget(self.chkLive)
        root.addLayout(hdr)

        # ═══════════════════════════ High-Density Trajectory Creation (no Stop) ═══════════════════════════
        trajGroup = QGroupBox("High-Density Trajectory Creation")
        tg = QGridLayout(trajGroup)
        tg.setContentsMargins(8, 6, 8, 6)
        tg.setSpacing(6)

        self.spinMaxPhantoms = QSpinBox()
        self.spinMaxPhantoms.setRange(1, 300)
        self.spinMaxPhantoms.setValue(30)
        # CORRECTION: Limiter la largeur du spinbox
        self.spinMaxPhantoms.setMaximumWidth(80)
        self.spinMaxPhantoms.setMinimumWidth(60)

        self.spinSampling = QSpinBox()
        self.spinSampling.setRange(10, 500)
        self.spinSampling.setSingleStep(10)
        self.spinSampling.setSuffix(" ms")
        self.spinSampling.setValue(50)
        # CORRECTION: Limiter la largeur du spinbox
        self.spinSampling.setMaximumWidth(80)
        self.spinSampling.setMinimumWidth(60)

        self.chkTrajectory = QCheckBox("Trajectory mode (phantoms)")
        self.btnClearPhantoms = QPushButton("Clear")
        # CORRECTION: Limiter la largeur du bouton
        self.btnClearPhantoms.setMaximumWidth(120)

        tg.addWidget(QLabel("Max Phantoms:"), 0, 0)
        tg.addWidget(self.spinMaxPhantoms, 0, 1)
        tg.addWidget(QLabel("Sampling Rate:"), 1, 0)
        tg.addWidget(self.spinSampling, 1, 1)

        # Move "Trajectory mode" next to "Clear Phantoms" to save vertical space
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(self.btnClearPhantoms)
        row.addSpacing(8)
        row.addWidget(self.chkTrajectory)
        row.addStretch()  # CORRECTION: Ajouter un stretch pour empêcher l'expansion
        tg.addLayout(row, 2, 0, 1, 3)
        
        # CORRECTION: Empêcher l'expansion des colonnes
        tg.setColumnStretch(2, 1)  # La colonne 2 prend l'espace supplémentaire
        
        self.chkTrajectory.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.btnClearPhantoms.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        root.addWidget(trajGroup)

        # ───────────────────────────────────── Drawing Library ─────────────────────────────────────
        libGroup = QGroupBox("Drawing Library")
        libLayout = QVBoxLayout(libGroup)

        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._on_list_context_menu)
        self.list.itemDoubleClicked.connect(lambda *_: self._do_load())

        libLayout.addWidget(self.list)
        root.addWidget(libGroup)

        # ───────────────────────────────────────── Wiring ──────────────────────────────────────────
        self.btnClear.clicked.connect(self._do_new)
        self.btnSave.clicked.connect(self._do_save)

        self.chkDraw.toggled.connect(self._set_drawing_enabled)
        self.chkLive.toggled.connect(self._on_live_toggled)
        # Live-drawing state
        self._live_enabled = False
        self._live_last_on_ms: dict[int, float] = {}
        self._live_last_intensity: dict[int, int] = {}
        self._live_throttle_ms = 15   # ms; do not re-send ON to same address faster than this


        self.chkTrajectory.toggled.connect(self._on_traj_toggled)
        self.spinMaxPhantoms.valueChanged.connect(self._apply_traj_limits)
        self.spinSampling.valueChanged.connect(self._apply_traj_limits)
        self.btnClearPhantoms.clicked.connect(
            lambda: (self._overlay and self._overlay.clear_phantoms_only())
        )
        # Permettre la désélection en cliquant dans une zone vide
        self.list.mousePressEvent = self._list_mouse_press_event
        # Réagir aux changements de sélection pour vider le canvas si besoin
        self.list.itemSelectionChanged.connect(self._on_selection_changed)

        # Initial list load
        self._refresh_list()
    
    def _on_selection_changed(self):
        """Réagir aux changements de sélection - vider le canvas si rien n'est sélectionné."""
        if not self.list.selectedItems():
            # Aucun élément sélectionné -> vider le canvas pour permettre un nouveau dessin
            if self._overlay and hasattr(self._overlay, "clear"):
                self._overlay.clear()

    # ───────────────────────────────────────── Public API ─────────────────────────────────────────
    def set_overlay_active(self, active: bool):
        """
        Called when switching tabs.
        Keep the overlay visible across tabs so previews/playback can render.
        Only grab the mouse when this tab is active AND Draw mode is on.
        """
        if not self._overlay:
            return
        self._overlay.setVisible(True)  # always visible
        self._overlay.set_mouse_passthrough(not (active and self.chkDraw.isChecked()))

    def bind_controls(self, gui):
        """Mirror phantom renderer + gain from the Waveform Lab controls."""
        self._gui = gui
        if self._overlay:
            self._overlay.set_phantom_mode(gui.strokeModeCombo.currentText())
            self._overlay.set_phantom_gain(gui.intensitySlider.value())

        def _apply():
            if self._overlay:
                self._overlay.set_phantom_mode(gui.strokeModeCombo.currentText())
                self._overlay.set_phantom_gain(gui.intensitySlider.value())

        gui.strokeModeCombo.currentTextChanged.connect(lambda *_: _apply())
        gui.intensitySlider.valueChanged.connect(lambda *_: _apply())

    def attach_canvas_selector(self, sel):
        self.canvas_selector = sel
        try:
            sel.canvasCombo.currentIndexChanged.connect(lambda *_: self._ensure_overlay_on_current_canvas())
        except Exception:
            pass
        self._ensure_overlay_on_current_canvas()

    # ───────────────────────────────────────── Internals ──────────────────────────────────────────
    def _on_list_context_menu(self, pos):
        # Ensure we have a selection; if none, select the item under the cursor
        if not self.list.selectedItems():
            it = self.list.itemAt(pos)
            if it:
                it.setSelected(True)
        if not self.list.selectedItems():
            return

        menu = QMenu(self)
        act_delete = menu.addAction("Delete")
        chosen = menu.exec(self.list.mapToGlobal(pos))
        if chosen == act_delete:
            self._do_delete()

    def _on_traj_toggled(self, on: bool):
        if self._overlay:
            self._overlay.enable_trajectory(on)
            self._overlay.set_traj_limits(self.spinMaxPhantoms.value(), self.spinSampling.value())
            # Reset current trajectory if overlay supports it
            if hasattr(self._overlay, "reset_trajectory"):
                self._overlay.reset_trajectory()
            # Mouse capture: capture when either Draw or Trajectory mode is ON (except Designer page)
            is_designer = (self.canvas_selector and self.canvas_selector.stack.currentIndex() == 0)
            self._overlay.set_mouse_passthrough(True if is_designer else not (self.chkDraw.isChecked() or on))

    def _ensure_overlay_on_current_canvas(self):
        """
        (Re)attach the drawing overlay to the currently active canvas widget,
        push all UI state (modes, limits), and set mouse-capture policy.
        """
        if self.canvas_selector is None:
            return

        host = self.canvas_selector.get_active_canvas_widget()
        if host is None:
            return

        # Reuse the overlay if already targeting the same host; otherwise recreate it
        if self._overlay and self._overlay.parent() is host:
            self._overlay.setGeometry(host.rect())
        else:
            # Dispose previous overlay if any
            if self._overlay:
                try:
                    self._overlay.setParent(None)
                    self._overlay.deleteLater()
                except Exception:
                    pass
                self._overlay = None

            # Create a fresh overlay bound to the active canvas
            self._overlay = DrawingCanvasOverlay(parent=host)
            self._wire_overlay_live_signals()
            self._overlay.set_overlay_mode(True)
            # Default pen width (since Pen UI was removed)
            try:
                self._overlay.set_pen_width(4)
            except Exception:
                pass

            # Mirror phantom renderer/gain from Waveform Lab, if available
            if hasattr(self, "_gui") and self._gui:
                try:
                    self._overlay.set_phantom_mode(self._gui.strokeModeCombo.currentText())
                    self._overlay.set_phantom_gain(self._gui.intensitySlider.value())
                except Exception:
                    pass

            # Keep the overlay sized with the host
            try:
                host.installEventFilter(self)
            except Exception:
                pass

        # Always visible; mouse capture handled separately
        self._overlay.setVisible(True)
        self._overlay.setGeometry(host.rect())
        self._overlay.raise_()

        # Update actuator anchors used for phantom computation
        try:
            self._overlay.set_nodes(self.canvas_selector.current_nodes())
        except Exception:
            pass

        # Push runtime modes & limits from the Drawing tab
        draw_on = bool(self.chkDraw.isChecked())
        traj_on = bool(self.chkTrajectory.isChecked())

        try:
            self._overlay.set_draw_enabled(draw_on)
        except Exception:
            pass
        try:
            self._overlay.enable_trajectory(traj_on)
        except Exception:
            pass
        try:
            self._overlay.set_traj_limits(self.spinMaxPhantoms.value(), self.spinSampling.value())
            if hasattr(self._overlay, "reset_trajectory"):
                self._overlay.reset_trajectory()
        except Exception:
            pass

        # Mouse capture policy
        is_designer = (self.canvas_selector.stack.currentIndex() == 0)
        try:
            if is_designer:
                # Designer page: never intercept (so you can place actuators)
                self._overlay.set_mouse_passthrough(True)
            else:
                # Capture when either Draw or Trajectory mode is ON
                self._overlay.set_mouse_passthrough(not (draw_on or traj_on))
        except Exception:
            pass

    def eventFilter(self, obj, ev):
        from PyQt6.QtCore import QEvent
        if self._overlay and ev.type() == QEvent.Type.Resize:
            self._overlay.setGeometry(obj.rect())
        return super().eventFilter(obj, ev)
    
    def _wire_overlay_live_signals(self):
        """Ensure overlay ↔ live handlers are connected exactly once."""
        if not getattr(self, "_overlay", None):
            return
        # Disconnect old bindings if they exist (safe guard)
        for sig_name in ("strokeStarted", "pointDrawn", "strokeEnded"):
            try:
                getattr(self._overlay, sig_name).disconnect()
            except Exception:
                pass
        self._overlay.strokeStarted.connect(self._live_on_stroke_started)
        self._overlay.pointDrawn.connect(self._live_on_point)
        self._overlay.strokeEnded.connect(self._live_on_stroke_ended)

    def _bursts_for_point(self, x: float, y: float):
        """
        Return a list[(address:int, intensity:int)] for a normalized point (x,y).
        Tries known overlay methods to stay identical to your normal drawing mapping.
        """
        ov = getattr(self, "_overlay", None)
        if not ov:
            return []
        for name in ("compute_bursts_for_point", "_compute_bursts_for_pt",
                    "bursts_for_point", "bursts_for_cursor"):
            fn = getattr(ov, name, None)
            if callable(fn):
                try:
                    return fn((float(x), float(y)))
                except TypeError:
                    return fn(float(x), float(y))
        return []
    
    def _on_live_toggled(self, on: bool):
        """Validate HW availability; arm/disarm live mode."""
        self._live_enabled = bool(on)
        if on and hasattr(self, "chkDraw") and not self.chkDraw.isChecked():
            self.chkDraw.setChecked(True)

        gui = getattr(self, "_gui", None) or self.window()
        api = getattr(gui, "api", None)
        connected = bool(getattr(api, "connected", False))
        busy = bool(getattr(gui, "is_running", False))

        if self._live_enabled:
            if not (api and connected):
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Hardware", "Please connect to a device first.")
                self.chkLive.setChecked(False)
                self._live_enabled = False
                return
            sw = getattr(gui, "_stroke_worker", None)
            if busy or (sw and sw.isRunning()):
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Busy", "A pattern is currently running. Stop it first.")
                self.chkLive.setChecked(False)
                self._live_enabled = False
                return

            # Fresh state
            self._live_last_on_ms.clear()
            self._live_last_intensity.clear()

    def _get_live_params(self) -> tuple[int, int]:
        """(pulse_ms, freq_code) derived from your current stroke controls."""
        pulse_ms = 50
        freq_code = 4
        gui = getattr(self, "_gui", None) or self.window()
        step_widget = getattr(gui, "strokeStepMs", None)
        freq_widget = getattr(gui, "strokeFreqCode", None)
        try:
            if step_widget is not None:
                pulse_ms = int(max(20, min(69, step_widget.value())))
        except Exception:
            pass
        try:
            if freq_widget is not None:
                freq_code = int(max(0, min(7, freq_widget.value())))
        except Exception:
            pass
        return pulse_ms, freq_code

    def _live_on_stroke_started(self):
        if not self._live_enabled:
            return
        self._live_last_on_ms.clear()
        self._live_last_intensity.clear()

    def _live_on_point(self, x: float, y: float):
        if not self._live_enabled:
            return

        gui = getattr(self, "_gui", None) or self.window()
        api = getattr(gui, "api", None)
        if not api or not getattr(api, "connected", False):
            return
        if getattr(gui, "is_running", False):
            return
        sw = getattr(gui, "_stroke_worker", None)
        if sw and sw.isRunning():
            return

        bursts = self._bursts_for_point(x, y)
        if not bursts:
            return

        self._live_send_bursts(bursts)

    def _live_on_stroke_ended(self):
        if not self._live_enabled:
            return
        pulse_ms, _ = self._get_live_params()
        now_ms = float(QDateTime.currentMSecsSinceEpoch())
        for addr in list(self._live_last_on_ms.keys()):
            last = self._live_last_on_ms.get(addr, -1e12)
            if (now_ms - last) >= (pulse_ms - 1):
                try:
                    gui = getattr(self, "_gui", None) or self.window()
                    api = getattr(gui, "api", None)
                    if api:
                        api.send_command(int(addr), 0, 0, 0)
                except Exception:
                    pass
                self._live_last_on_ms.pop(addr, None)
                self._live_last_intensity.pop(addr, None)
            else:
                delay = max(1, int(pulse_ms - (now_ms - last)))
                QTimer.singleShot(delay, lambda a=int(addr): self._live_off_if_expired(a))

    def _live_off_if_expired(self, addr: int):
        gui = getattr(self, "_gui", None) or self.window()
        api = getattr(gui, "api", None)
        if not api or not getattr(api, "connected", False):
            return
        pulse_ms, _ = self._get_live_params()
        now_ms = float(QDateTime.currentMSecsSinceEpoch())
        last = self._live_last_on_ms.get(addr, None)
        if last is None:
            return
        if (now_ms - last) >= (pulse_ms - 1):
            try:
                api.send_command(int(addr), 0, 0, 0)
            except Exception:
                pass
            self._live_last_on_ms.pop(addr, None)
            self._live_last_intensity.pop(addr, None)

    def _live_send_bursts(self, bursts: list[tuple[int, int]]):
        gui = getattr(self, "_gui", None) or self.window()
        api = getattr(gui, "api", None)
        if not api or not getattr(api, "connected", False):
            return

        pulse_ms, freq_code = self._get_live_params()
        now_ms = float(QDateTime.currentMSecsSinceEpoch())

        for addr, inten in bursts:
            addr = int(addr)
            inten = int(max(0, min(15, inten)))
            last_ms = self._live_last_on_ms.get(addr, -1e12)
            last_int = self._live_last_intensity.get(addr, -999)

            if (now_ms - last_ms) >= self._live_throttle_ms or inten != last_int:
                try:
                    api.send_command(addr, inten, freq_code, 1)
                except Exception:
                    pass
                self._live_last_on_ms[addr] = now_ms
                self._live_last_intensity[addr] = inten
                QTimer.singleShot(pulse_ms, lambda a=addr: self._live_off_if_expired(a))
    # ───────────────────────────────────────── Library ops ─────────────────────────────────────────
    def _refresh_list(self):
        self.list.clear()
        for name in self.lib.list():
            self.list.addItem(name)

    def _current_name(self) -> str | None:
        it = self.list.currentItem()
        return it.text() if it else None

    def _do_new(self):
        if self._overlay and hasattr(self._overlay, "clear"):
            self._overlay.clear()

    def _do_save(self):
        """
        Save does both jobs:
        - If a drawing is selected in the list → overwrite it.
        - Otherwise → prompt for a new name (formerly 'Save As…').
        """
        name = self._current_name()
        if not name:
            self._do_save_as()
            return
        self._save_named(name)
        self._refresh_list()

    # Internal helper (kept, no visible button)
    def _do_save_as(self):
        name, ok = QInputDialog.getText(self, "Save Drawing", "Name:")
        if not ok or not name.strip():
            return
        self._save_named(name.strip())
        self._refresh_list()

    def _save_named(self, name: str):
        if not self._overlay:
            QMessageBox.warning(self, "Save", "No overlay available.")
            return
        if hasattr(self._overlay, "to_json"):
            data = self._overlay.to_json()
            ok = self.lib.save_json(name, data)
            if ok:
                QMessageBox.information(self, "Saved", f"Drawing '{name}' saved.")
            else:
                QMessageBox.critical(self, "Error", "Failed to save drawing.")

    def _do_load(self):
        if not self._overlay:
            QMessageBox.warning(self, "Load", "No overlay available.")
            return
        items = self.list.selectedItems()
        if not items:
            return
        names = [it.text() for it in items]
        datas = [self.lib.load_json(n) for n in names]
        datas = [d for d in datas if d]

        if hasattr(self._overlay, "clear"):
            self._overlay.clear()
        for d in datas:
            self._overlay.append_json(d)
        
    def _list_mouse_press_event(self, event):
        """Gérer les clics de souris sur la liste pour permettre la désélection."""
        # Appeler d'abord le comportement normal
        from PyQt6.QtWidgets import QListWidget
        QListWidget.mousePressEvent(self.list, event)
        
        # Si on a cliqué dans une zone vide, désélectionner tout
        item_at_pos = self.list.itemAt(event.position().toPoint())
        if item_at_pos is None:
            self.list.clearSelection()
            self.list.setCurrentItem(None) 

    def _do_delete(self):
        items = self.list.selectedItems()
        if not items:
            return
        names = [it.text() for it in items]
        if QMessageBox.question(
            self, "Delete", f"Delete {len(names)} drawing(s)?"
        ) != QMessageBox.StandardButton.Yes:
            return
        for n in names:
            self.lib.delete(n)
        self._refresh_list()

    # ───────────────────────────────────────── Modes/limits ────────────────────────────────────────
    def _apply_traj_limits(self, *_):
        if self._overlay:
            self._overlay.set_traj_limits(self.spinMaxPhantoms.value(), self.spinSampling.value())

    def _set_drawing_enabled(self, on: bool):
        if self._overlay:
            self._overlay.set_draw_enabled(on)
            # Capture mouse when Draw or Trajectory is ON (except Designer)
            is_designer = (self.canvas_selector and self.canvas_selector.stack.currentIndex() == 0)
            self._overlay.set_mouse_passthrough(True if is_designer else not (on or self.chkTrajectory.isChecked()))