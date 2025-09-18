import time
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import (
    QObject, pyqtSignal, Qt, QTimer, QSize, QRectF, QPointF
)
from PyQt6.QtGui import (
    QPainter, QPen, QBrush, QColor,
    QKeySequence, QShortcut
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QLabel, QPushButton, QDoubleSpinBox, QFrame,
    QSizePolicy, QMessageBox, QInputDialog
)

from ..core.data_models import TimelineClip
from ..utils.workers import TimelineDeviceWorker

if TYPE_CHECKING:
    from .actuator_widgets import MultiCanvasSelector
    from .main_gui import HapticPatternGUI



class TimelineModel(QObject):
    changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._clips: list[TimelineClip] = []
        self._selected: Optional[TimelineClip] = None

    def clips(self) -> list[TimelineClip]:
        return list(self._clips)

    def clear(self):
        self._clips.clear()
        self._selected = None
        self.changed.emit()

    def add_clip_for_actuators(self, actuators: list[int],
                               event: Optional['HapticEvent'],
                               waveform_name: str,
                               start_s: float, end_s: float):
        start_s = max(0.0, float(start_s))
        end_s   = max(start_s, float(end_s))
        for a in sorted(set(int(x) for x in actuators)):
            self._clips.append(TimelineClip(a, start_s, end_s, waveform_name, event))
        self.changed.emit()

    def remove_clip(self, clip: TimelineClip):
        try:
            self._clips.remove(clip)
        except ValueError:
            pass
        if self._selected is clip:
            self._selected = None
        self.changed.emit()

    def set_selected(self, clip: Optional[TimelineClip]):
        self._selected = clip
        self.changed.emit()

    def selected(self) -> Optional[TimelineClip]:
        return self._selected

    def total_duration(self) -> float:
        if not self._clips: return 0.0
        return max((c.end_s for c in self._clips), default=0.0)

    def actuators(self) -> list[int]:
        return sorted({c.actuator for c in self._clips})

    # Preview helper: who is active at time t?
    def active_actuators_at(self, t_s: float) -> list[int]:
        out = []
        for c in self._clips:
            if c.start_s <= t_s <= c.end_s:
                out.append(c.actuator)
        return sorted(set(out))


class TimelineView(QWidget):
    """Lightweight visual timeline (rows by actuator, rectangles for clips)."""
    clip_clicked = pyqtSignal(object)  # emits TimelineClip or None

    def __init__(self, model: TimelineModel, parent=None):
        super().__init__(parent)
        self._model = model
        self._model.changed.connect(self.update)
        self.setMinimumHeight(160)
        self.setAutoFillBackground(True)
        self._px_per_second = 120.0
        self._margin_l = 56
        self._row_h = 22
        self._row_gap = 8
        self._cursor_t = 0.0
        self.setMouseTracking(True)

    def set_seconds_per_pixel(self, sec_per_px: float):
        self._px_per_second = 1.0 / max(0.01, sec_per_px)
        self.update()

    def set_pixels_per_second(self, px_per_s: float):
        self._px_per_second = max(10.0, float(px_per_s))
        self.update()

    def set_cursor_time(self, t_s: float):
        self._cursor_t = max(0.0, float(t_s))
        self.update()

    def _rows_layout(self) -> list[int]:
        """Map actuators to row indices."""
        return self._model.actuators()

    def sizeHint(self):
        rows = len(self._rows_layout())
        height = 16 + rows * (self._row_h + self._row_gap) + 8
        width  = max(600, int(self._margin_l + self._model.total_duration() * self._px_per_second) + 40)
        return QSize(width, height)

    def minimumSizeHint(self):
        return QSize(600, 140)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), self.palette().base())

        # Grid/time marks
        total_s = self._model.total_duration()
        W = self.width() - self._margin_l - 8
        max_s = max(total_s, (W / self._px_per_second))
        step = 1.0
        # seconds grid
        p.setPen(QPen(QColor("#E5E7EB")))
        t = 0.0
        while t <= max_s + 1e-6:
            x = self._margin_l + int(t * self._px_per_second)
            p.drawLine(x, 6, x, self.height() - 6)
            p.setPen(QPen(QColor("#6B7280")))
            p.drawText(x + 2, 14, f"{t:.0f}s")
            p.setPen(QPen(QColor("#E5E7EB")))
            t += step

        # Rows
        rows = self._rows_layout()
        base_y = 24
        for ri, act in enumerate(rows):
            y = base_y + ri * (self._row_h + self._row_gap)
            # row label
            p.setPen(QPen(QColor("#374151")))
            p.drawText(6, y + int(self._row_h * 0.7), f"A{act}")
            # baseline
            p.setPen(QPen(QColor("#D1D5DB")))
            p.drawLine(self._margin_l, y + self._row_h, self.width() - 8, y + self._row_h)

        # Clips
        sel = self._model.selected()
        for clip in self._model.clips():
            try:
                ri = rows.index(clip.actuator)
            except ValueError:
                continue
            y = base_y + ri * (self._row_h + self._row_gap)
            x0 = self._margin_l + int(clip.start_s * self._px_per_second)
            x1 = self._margin_l + int(clip.end_s   * self._px_per_second)
            rect = QRectF(x0, y, max(12, x1 - x0), self._row_h)
            # fill
            p.setPen(QPen(QColor("#3B82F6"), 1))
            p.setBrush(QBrush(QColor("#93C5FD")))
            if sel is clip:
                p.setBrush(QBrush(QColor("#60A5FA")))
                p.setPen(QPen(QColor("#1D4ED8"), 2))
            p.drawRoundedRect(rect, 6, 6)
            # text
            p.setPen(QPen(QColor("#111827")))
            name = clip.waveform_name or "waveform"
            p.drawText(rect.adjusted(6, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter, f"{name} ({clip.start_s:.1f}–{clip.end_s:.1f}s)")

        # Playhead
        x_cursor = self._margin_l + int(self._cursor_t * self._px_per_second)
        p.setPen(QPen(QColor("#EF4444"), 2))
        p.drawLine(x_cursor, 6, x_cursor, self.height() - 6)

        p.end()

    def _hit_test(self, pos: QPointF) -> Optional[TimelineClip]:
        rows = self._rows_layout()
        base_y = 24
        for clip in self._model.clips():
            try:
                ri = rows.index(clip.actuator)
            except ValueError:
                continue
            y = base_y + ri * (self._row_h + self._row_gap)
            x0 = self._margin_l + int(clip.start_s * self._px_per_second)
            x1 = self._margin_l + int(clip.end_s   * self._px_per_second)
            rect = QRectF(x0, y, max(12, x1 - x0), self._row_h)
            if rect.contains(pos):
                return clip
        return None

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            c = self._hit_test(e.position())
            self.clip_clicked.emit(c)
        super().mousePressEvent(e)


class TimelinePanel(QWidget):
    """Compact panel placed UNDER the tabs; drives the Designer canvas."""
    def __init__(self, gui: 'HapticPatternGUI'):
        super().__init__(gui)
        self.gui = gui
        self._dev_thread = None
        self._dev_worker = None     

        # --- data / state ---
        self.model = TimelineModel()
        self.view = TimelineView(self.model)
        self.view.setMinimumHeight(280)

        self._preview_timer = QTimer(self)
        self._preview_timer.setInterval(30)  # ~33 FPS
        self._preview_timer.timeout.connect(self._on_preview_tick)
        self._preview_running = False
        self._preview_t0 = 0.0
        self._preview_len = 0.0

        self._dev_worker: Optional[TimelineDeviceWorker] = None
        self._canvas_selector = None

        # --- root layout ---
        root = QVBoxLayout(self)
        self.setContentsMargins(0, 0, 0, 0)     # panel flush to top
        root.setContentsMargins(6, 0, 6, 6)     # no top margin
        root.setSpacing(6)                      # small gap between buttons and timeline



        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)                 # tighter than before



        # Title label
        title_lbl = QLabel("Timeline")
        title_lbl.setStyleSheet("font-weight:600; font-size:11px;")
        title_lbl.setStyleSheet("font-weight:600;")
        title_row.addWidget(title_lbl)

        # Control spinboxes
        title_row.addWidget(QLabel("Start:"))
        self.startSpin = QDoubleSpinBox()
        self.startSpin.setFixedHeight(27)
        self.startSpin.setStyleSheet("font-size:10px; padding:0 4px;")
        self.startSpin.setMaximumWidth(72)
        self.startSpin.setRange(0.0, 3600.0)
        self.startSpin.setDecimals(2)
        self.startSpin.setSuffix(" s")
        self.startSpin.setMaximumWidth(80)
        title_row.addWidget(self.startSpin)

        title_row.addSpacing(6)
        title_row.addWidget(QLabel("Stop:"))
        self.endSpin = QDoubleSpinBox()
        self.endSpin.setFixedHeight(27)
        self.endSpin.setStyleSheet("font-size:10px; padding:0 4px;")
        self.endSpin.setMaximumWidth(72)
        self.endSpin.setRange(0.0, 3600.0)
        self.endSpin.setDecimals(2) 
        self.endSpin.setSuffix(" s")
        self.endSpin.setValue(2.0)
        self.endSpin.setMaximumWidth(80)
        title_row.addWidget(self.endSpin)


        # Action buttons (left side)
        self.btnAdd = QPushButton("Add clip")
        title_row.addWidget(self.btnAdd)

        self.btnRemove = QPushButton("Remove")
        title_row.addWidget(self.btnRemove)

        self.btnClear = QPushButton("Clear")
        title_row.addWidget(self.btnClear)

        # Stretch to push playback buttons to the right
        title_row.addStretch()

        # Playback buttons (right side)
        self.btnPreview = QPushButton("Play preview")
        self.btnPreview.setMaximumWidth(80)
        title_row.addWidget(self.btnPreview)

        self.btnDevice = QPushButton("Play on device")
        self.btnDevice.setMaximumWidth(85)
        title_row.addWidget(self.btnDevice)

        self.btnStop = QPushButton("Stop")
        self.btnStop.setMaximumWidth(40)
        title_row.addWidget(self.btnStop)

        self.btnSave = QPushButton("Save")
        self.btnSave.setMaximumWidth(40)
        title_row.addWidget(self.btnSave)

        root.addLayout(title_row)
        for b in (self.btnAdd, self.btnRemove, self.btnClear,
                self.btnPreview, self.btnDevice, self.btnStop, self.btnSave):
            b.setFixedHeight(22)
            b.setStyleSheet("font-size:10px; padding:0 6px; margin-right:6px;")

        # ───────────────────────────────── Timeline view  
        view_wrap = QFrame()
        view_wrap.setObjectName("TimelineViewWrap")
        view_wrap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        view_wrap.setFrameShape(QFrame.Shape.NoFrame)
        vlay = QVBoxLayout(view_wrap)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.setSpacing(0)
        vlay.addWidget(self.view)
        root.addWidget(view_wrap)

        # Stretch ratios
        root.setStretch(0, 0)   # title row with all controls
        root.setStretch(1, 1)   # timeline view (expands)



        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # Let the viewport and its wrapper grow with the panel
        self.view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # ───────────────────────────────── Wiring#  
        # # Default zoom and keyboard shortcuts (Cmd+ / Cmd− map to ZoomIn/ZoomOut)
        self._zoom_pxps = 70.0
        self.view.set_pixels_per_second(self._zoom_pxps)
        sc_in  = QShortcut(QKeySequence(QKeySequence.StandardKey.ZoomIn),  self)
        sc_out = QShortcut(QKeySequence(QKeySequence.StandardKey.ZoomOut), self)
        sc_in.activated.connect(lambda: self._nudge_zoom(+10.0))
        sc_out.activated.connect(lambda: self._nudge_zoom(-10.0))
        self.view.clip_clicked.connect(self._on_clip_clicked)
        self.btnAdd.clicked.connect(self._on_add_clip)
        self.btnRemove.clicked.connect(self._on_remove_clip)
        self.btnClear.clicked.connect(lambda: self.model.clear())
        self.btnPreview.clicked.connect(self._toggle_preview)
        self.btnDevice.clicked.connect(self._play_on_device)
        self.btnStop.clicked.connect(self.stop_all)
        self.btnSave.clicked.connect(self._save_to_library)
        


    # External wiring
    def attach_canvas_selector(self, sel):
        self._canvas_selector = sel

    def _nudge_zoom(self, delta: float):
        """Adjust timeline zoom in px/s with clamping."""
        self._zoom_pxps = float(max(20.0, min(500.0, self._zoom_pxps + delta)))
        self.view.set_pixels_per_second(self._zoom_pxps)

    
    def _ensure_dev_thread_stopped(self, timeout_ms: int = 1500):
        """Stop device worker thread (QThread subclass) if running."""
        if self._dev_worker:
            try:
                # cooperative stop if the worker exposes it
                if hasattr(self._dev_worker, "stop"):
                    self._dev_worker.stop()
            except Exception:
                pass
            try:
                if self._dev_worker.isRunning():
                    self._dev_worker.wait(timeout_ms)
            finally:
                self._dev_worker = None



    # Loading/saving
    def to_config(self) -> dict:
        return {
            "pattern_type": "Timeline",
            "actuators": self.model.actuators(),
            "intensity": int(self.gui.intensitySlider.value()),
            "frequency": int(self.gui.strokeFreqCode.value() if hasattr(self.gui, "strokeFreqCode") else self.gui.frequencySlider.value()),
            "timeline": [
                {
                    "actuator": c.actuator,
                    "start": float(c.start_s),
                    "end": float(c.end_s),
                    "waveform": {"source": "Waveform Library", "name": c.waveform_name}
                } for c in self.model.clips()
            ]
        }

    def load_from_config(self, cfg: dict):
        self.model.clear()
        # ensure Designer page (requirement)
        try:
            if self._canvas_selector:
                self._canvas_selector.canvasCombo.setCurrentIndex(0)
        except Exception:
            pass
        try:
            if self._canvas_selector:
                self._canvas_selector.load_actuator_configuration(cfg.get("actuators", []))
        except Exception:
            pass
        items = cfg.get("timeline", [])
        # Map waveform names to events using the current library
        for it in items:
            name = (it.get("waveform") or {}).get("name", "")
            # pick current GUI waveform if same name; else try to resolve
            ev = None
            try:
                # refresh list then try to find by text
                self.gui.refresh_waveforms()
                idx = self.gui.waveformComboBox.findText(name)
                if idx >= 0:
                    self.gui.waveformComboBox.setCurrentIndex(idx)
                    self.gui.update_waveform_info()
                    ev = self.gui.current_event
            except Exception:
                pass
            self.model.add_clip_for_actuators(
                [int(it.get("actuator", 0))],
                ev,
                name,
                float(it.get("start", 0.0)),
                float(it.get("end", 0.0))
            )

    # UI handlers
    def _on_clip_clicked(self, clip: Optional[TimelineClip]):
        self.model.set_selected(clip)
        if clip:
            self.startSpin.setValue(clip.start_s)
            self.endSpin.setValue(clip.end_s)

    def _require_designer_page(self) -> bool:
        """Ensure the active canvas is 'Designer' (index 0)."""
        try:
            if not self._canvas_selector:
                print("DEBUG: _canvas_selector is None")
                return False
            
            current_index = self._canvas_selector.stack.currentIndex()
            combo_index = self._canvas_selector.canvasCombo.currentIndex()
            combo_text = self._canvas_selector.canvasCombo.currentText()
            
            print(f"DEBUG: stack.currentIndex() = {current_index}")
            print(f"DEBUG: canvasCombo.currentIndex() = {combo_index}")
            print(f"DEBUG: canvasCombo.currentText() = '{combo_text}'")
            
            return current_index == 0
        except Exception as e:
            print(f"DEBUG: Exception in _require_designer_page: {e}")
            return False

    def _on_add_clip(self):
        if not self._require_designer_page():
            QMessageBox.warning(self, "Timeline", "Please use the Designer canvas for timeline assignment.")
            return
        if not self._canvas_selector:
            QMessageBox.warning(self, "Timeline", "Canvas selector not ready.")
            return
        acts = self._canvas_selector.get_selected_actuators()
        if not acts:
            QMessageBox.information(self, "Timeline", "Select at least one actuator on the Designer.")
            return
        start_s = float(self.startSpin.value())
        end_s   = float(self.endSpin.value())
        if end_s <= start_s:
            QMessageBox.warning(self, "Timeline", "Stop must be greater than Start.")
            return
        # Current waveform from the Waveform Selection
        ev   = self.gui.current_event
        wname= self.gui.waveformComboBox.currentText()
        if not ev:
            QMessageBox.warning(self, "Timeline", "Pick a waveform from the Waveform Library first.")
            return
        self.model.add_clip_for_actuators(acts, ev, wname, start_s, end_s)
        # convenience: next start at previous stop
        self.startSpin.setValue(end_s)
        # default end = start + waveform duration if available
        try:
            dur = float(ev.waveform_data.duration or 0.0)
            if dur > 0.0:
                self.endSpin.setValue(end_s + dur)
        except Exception:
            pass

    def _on_remove_clip(self):
        c = self.model.selected()
        if c:
            self.model.remove_clip(c)

    # Preview
    def _toggle_preview(self):
        if self._preview_running:
            self._preview_timer.stop()
            self._preview_running = False
            self.btnPreview.setText("Play preview")
            # clear highlights
            try:
                if self._canvas_selector:
                    self._canvas_selector.clear_preview()
            except Exception:
                pass
            return

        self._preview_len = max(0.01, self.model.total_duration())
        self._preview_t0  = time.perf_counter()
        self._preview_running = True
        self.btnPreview.setText("Stop preview")
        self._preview_timer.start()

    def _on_preview_tick(self):
        t = time.perf_counter() - self._preview_t0
        if t > self._preview_len:
            self._toggle_preview()
            return
        # update view + canvas highlight
        self.view.set_cursor_time(t)
        try:
            if self._canvas_selector:
                ids = self.model.active_actuators_at(t)
                self._canvas_selector.set_preview_active(ids)
        except Exception:
            pass
    
    def _on_device_tick(self, t):
        try:
            # accepter int(ms) ou float(s)
            tt = float(t)
            if tt > 1000:   # heuristique: si très grand, c'est sans doute en ms
                tt = tt / 1000.0
        except Exception:
            return

        # 1) avancer le curseur de la timeline
        self.view.set_cursor_time(tt)

        # 2) surligner les actuateurs actifs (même rendu que Preview)
        try:
            if self._canvas_selector:
                ids = self.model.active_actuators_at(tt)
                self._canvas_selector.set_preview_active(ids)
        except Exception:
            pass

    
    def closeEvent(self, e):
        self.stop_all()
        super().closeEvent(e)

    # Device playback
    def _play_on_device(self):
        # ensure previous run is fully stopped
        self._ensure_dev_thread_stopped()

        if not self.gui.api or not self.gui.api.connected:
            QMessageBox.warning(self, "Hardware", "Please connect to a device first.")
            return

        total = max(0.01, self.model.total_duration())
        Av    = int(self.gui.intensitySlider.value())
        fcode = int(self.gui.strokeFreqCode.value() if hasattr(self.gui, "strokeFreqCode") else self.gui.frequencySlider.value())

        self._dev_worker = TimelineDeviceWorker(self.gui.api, self.model, total, Av, fcode, tick_ms=50)
        self._dev_worker.log_message.connect(self.gui._log_info)
        self._dev_worker.tick.connect(self._on_device_tick)
        self._dev_worker.finished.connect(self._on_device_finished)
        self._dev_worker.start()

        self.gui._log_info(f"Timeline device playback: {len(self.model.clips())} clip(s), length ≈ {total:.2f}s")


    def _on_device_finished(self, ok: bool, msg: str):
        self._ensure_dev_thread_stopped()
        self.gui._log_info(f"Timeline finished → {msg}")
        self._dev_worker = None
        try:
            if self._canvas_selector:
                self._canvas_selector.clear_preview()
        except Exception:
            pass
        self.view.set_cursor_time(0.0)

    def stop_all(self):
        # stop preview
        if self._preview_running:
            self._toggle_preview()
        # stop device worker
        if self._dev_worker and self._dev_worker.isRunning():
            try:
                self._dev_worker.stop()
                self._dev_worker.wait(1000)
            except Exception:
                pass
            self._dev_worker = None
        # clear UI highlights
        try:
            if self._canvas_selector:
                self._canvas_selector.clear_preview()
        except Exception:
            pass
        self.view.set_cursor_time(0.0)

    # Save
    def _save_to_library(self):
        cfg = self.to_config()
        name, ok = QInputDialog.getText(self, "Save Sequence", "Name:")
        if not ok or not name.strip():
            return
        data = {
            'name': name.strip(),
            'description': "Timeline sequence",
            'timestamp': datetime.now().isoformat(),
            'config': cfg
        }
        if self.gui.pattern_manager.save_pattern(data['name'], data):
            QMessageBox.information(self, "Saved", f"Sequence '{data['name']}' saved to Pattern Library.")
            try:
                self.gui.pattern_visualization.refresh_patterns()
            except Exception:
                pass
        else:
            QMessageBox.critical(self, "Error", "Failed to save sequence.")