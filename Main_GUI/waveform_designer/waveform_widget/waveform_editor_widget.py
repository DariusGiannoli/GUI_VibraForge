# waveform_editor_widget.py
# Graph-only editor widget (all controls moved to the menubar)

from __future__ import annotations

import os, json, typing as t
import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QPushButton, QButtonGroup
from PyQt6 import uic
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QFormLayout, QDialog,
    QDialogButtonBox, QDoubleSpinBox, QFileDialog, QMessageBox,QComboBox,
)
from PyQt6.QtWidgets import QSlider, QHBoxLayout, QLabel
from PyQt6.QtGui import QFont


# --- Data model & helpers ---------------------------------------------------
from ..event_designer.core import (
    HapticEvent, EventCategory, WaveformData, ParameterModifications,
    ActuatorMapping, ActuatorPattern, EventMetadata,
    MIME_WAVEFORM,                 # for drag/drop
    generate_builtin_waveform,     # for oscillators
    resample_to,                   # for compose()
    load_csv_waveform,             # for CSV drops
)



# --------------------------------------------------------------------------
# Parameter dialogs (used when the user drops an oscillator)
# --------------------------------------------------------------------------
class BaseParamsDialog(QDialog):
    """Frequency / Amplitude / Duration / Sample rate dialog."""
    def __init__(self, parent=None, *, title="Parameters",
                 freq=100.0, amp=1.0, dur=1.0, sr=1000.0):
        super().__init__(parent)
        self.setWindowTitle(title)
        form = QFormLayout(self)

        self.sp_freq = QDoubleSpinBox(); self.sp_freq.setRange(0.01, 50_000.0); self.sp_freq.setValue(freq)
        self.sp_amp  = QDoubleSpinBox(); self.sp_amp.setRange(0.0, 10.0); self.sp_amp.setDecimals(4); self.sp_amp.setValue(amp)
        self.sp_dur  = QDoubleSpinBox(); self.sp_dur.setRange(0.01, 60.0); self.sp_dur.setValue(dur)
        self.sp_sr   = QDoubleSpinBox(); self.sp_sr.setRange(50.0, 200_000.0); self.sp_sr.setValue(sr)

        form.addRow("Frequency (Hz)", self.sp_freq)
        form.addRow("Amplitude",      self.sp_amp)
        form.addRow("Duration (s)",   self.sp_dur)
        form.addRow("Sample rate",    self.sp_sr)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        form.addRow(bb)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)

    def values(self) -> dict:
        return dict(
            frequency=self.sp_freq.value(),
            amplitude=self.sp_amp.value(),
            duration=self.sp_dur.value(),
            sample_rate=self.sp_sr.value(),
        )


class ChirpParamsDialog(BaseParamsDialog):
    """Adds f0/f1 for Chirp."""
    def __init__(self, parent=None, **kw):
        super().__init__(parent, title="Chirp Parameters", **kw)
        self.sp_f0 = QDoubleSpinBox(); self.sp_f0.setRange(0.01, 50_000.0); self.sp_f0.setValue(kw.get("freq", 100.0))
        self.sp_f1 = QDoubleSpinBox(); self.sp_f1.setRange(0.01, 50_000.0); self.sp_f1.setValue(kw.get("freq", 200.0))
        self.layout().insertRow(0, "Start freq f0 (Hz)", self.sp_f0)
        self.layout().insertRow(1, "End freq f1 (Hz)",   self.sp_f1)

    def values(self) -> dict:
        base = super().values()
        base.update(f0=self.sp_f0.value(), f1=self.sp_f1.value())
        return base


class FMParamsDialog(BaseParamsDialog):
    """Adds fm/beta for FM."""
    def __init__(self, parent=None, **kw):
        super().__init__(parent, title="FM Parameters", **kw)
        self.sp_fm   = QDoubleSpinBox(); self.sp_fm.setRange(0.01, 50_000.0); self.sp_fm.setValue(5.0)
        self.sp_beta = QDoubleSpinBox(); self.sp_beta.setRange(0.0, 100.0);   self.sp_beta.setValue(1.0)
        self.layout().insertRow(0, "Modulating freq fm (Hz)", self.sp_fm)
        self.layout().insertRow(1, "Index beta",              self.sp_beta)

    def values(self) -> dict:
        base = super().values()
        base.update(fm=self.sp_fm.value(), beta=self.sp_beta.value())
        return base


class PWMParamsDialog(BaseParamsDialog):
    """Adds duty for PWM."""
    def __init__(self, parent=None, **kw):
        super().__init__(parent, title="PWM Parameters", **kw)
        self.sp_duty = QDoubleSpinBox(); self.sp_duty.setRange(0.0, 1.0); self.sp_duty.setSingleStep(0.01); self.sp_duty.setValue(0.5)
        self.layout().insertRow(0, "Duty cycle", self.sp_duty)

    def values(self) -> dict:
        base = super().values()
        base.update(duty=self.sp_duty.value())
        return base


# --------------------------------------------------------------------------
# Smart display helpers (type-aware decimation/rendering)
# --------------------------------------------------------------------------
def detect_signal_type_from_name_and_data(signal_name: str | None, y: np.ndarray) -> str:
    if signal_name:
        nl = signal_name.lower()
        if "square" in nl: return "square"
        if "triangle" in nl: return "triangle"
        if "saw" in nl: return "sawtooth"
        if "sine" in nl or "sin" in nl: return "sine"
        if "pwm" in nl or "pulse" in nl: return "square"
        if "noise" in nl: return "noise"
        if "chirp" in nl or "fm" in nl: return "sine"
    return detect_signal_type_from_data(y)

def detect_signal_type_from_data(y: np.ndarray) -> str:
    if len(y) < 10: return "generic"
    y_norm = (y - np.mean(y)) / (np.std(y) + 1e-12)
    if np.mean(np.abs(y_norm) > 0.7) > 0.4: return "square"
    sd2 = np.abs(np.diff(y, 2))
    if sd2.size > 0:
        linearity_ratio = np.mean(sd2 < np.std(sd2) * 0.3)
        if linearity_ratio > 0.6:
            d1 = np.diff(y)
            return "sawtooth" if (np.abs(np.mean(d1)) / (np.std(d1) + 1e-12)) > 0.5 else "triangle"
    return "sine"

def render_square_wave(x, y, target_points):
    if len(x) < 2: return x, y
    transitions, thr = [0], np.std(y) * 0.5
    for i in range(1, len(y)):
        if abs(y[i] - y[i - 1]) > thr:
            transitions.extend([i - 1, i])
    transitions = sorted(set(transitions + [len(x) - 1]))
    xx, yy = [], []
    for i in range(len(transitions) - 1):
        s, e = transitions[i], transitions[i + 1]
        xx.append(x[s]); yy.append(y[s])
        if e > s + 1:
            plateau = max(2, min(50, target_points // (len(transitions) * 2)))
            for j in range(1, plateau):
                t_ = j / plateau
                xx.append(x[s] + t_ * (x[e] - x[s])); yy.append(y[s])
        if abs(y[e] - y[s]) > thr:
            xx.append(x[e] - (x[e] - x[s]) * 0.001); yy.append(y[s])
            xx.append(x[e]); yy.append(y[e])
    if not xx or xx[-1] != x[-1]:
        xx.append(x[-1]); yy.append(y[-1])
    return np.array(xx), np.array(yy)

def render_linear_segments(x, y, target_points):
    if len(x) < 2: return x, y
    xn = np.linspace(x[0], x[-1], target_points)
    yn = np.interp(xn, x, y); return xn, yn

def render_noise_signal(x, y, target_points):
    if len(x) >= target_points:
        step = max(1, len(x) // target_points)
        idx = list(range(0, len(x), step))
        if idx[-1] != len(x) - 1: idx.append(len(x) - 1)
        return x[idx], y[idx]
    return x, y

def render_smooth_signal(x, y, target_points):
    from scipy import interpolate
    xn = np.linspace(x[0], x[-1], target_points)
    try:
        if len(x) >= 4:
            y2 = interpolate.CubicSpline(x, y, bc_type="natural")(xn)
        else:
            y2 = np.interp(xn, x, y)
        return xn, y2
    except Exception:
        return xn, np.interp(xn, x, y)

def create_faithful_display_signal(x, y, target_points=1000, signal_name=None):
    if len(x) <= 2: return x, y
    x_clean, idx = np.unique(x, return_index=True)
    y_clean = y[idx]
    if len(x_clean) <= 2: return x_clean, y_clean
    kind = detect_signal_type_from_name_and_data(signal_name, y_clean)
    if kind == "square": return render_square_wave(x_clean, y_clean, target_points)
    if kind in ("triangle", "sawtooth"): return render_linear_segments(x_clean, y_clean, target_points)
    if kind == "noise": return render_noise_signal(x_clean, y_clean, target_points)
    return render_smooth_signal(x_clean, y_clean, target_points)

def intelligent_downsample_by_signal_type(x, y, max_points=300):
    return create_faithful_display_signal(x, y, max_points)

# --------------------------------------------------------------------------
# Draggable control points
# --------------------------------------------------------------------------
class _EditableScatter(pg.ScatterPlotItem):
    def __init__(self, x, y, *, color: str, callback: t.Callable[[np.ndarray, np.ndarray], None]):
        super().__init__(x=x, y=y, symbol="o", size=12,
                         brush=pg.mkBrush(color), pen=pg.mkPen("white", width=2))
        self._callback = callback
        self._drag_index: int | None = None

    def _to_xy(self):
        xs, ys = self.getData()
        return np.array(xs, float), np.array(ys, float)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            pts = self.pointsAt(ev.pos())
            if pts:
                self._drag_index = self.points().index(pts[0])
            ev.accept()
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._drag_index is None:
            super().mouseMoveEvent(ev); return
        pos = self.mapToView(ev.pos())
        x, y = self._to_xy()
        x[self._drag_index] = float(pos.x()); y[self._drag_index] = float(pos.y())
        order = np.argsort(x); x, y = x[order], y[order]
        self.setData(x=x, y=y); self._callback(x, y); ev.accept()

    def mouseReleaseEvent(self, ev):
        self._drag_index = None
        super().mouseReleaseEvent(ev)

# --------------------------------------------------------------------------
# Main widget (graph-only canvas)
# --------------------------------------------------------------------------
class WaveformEditorWidget(QWidget):
    playRequested = pyqtSignal(object)
    parameters_changed = pyqtSignal()
    device_test_requested = pyqtSignal(int)  # main window will emit this from the Device menu
    _X_PAD = 0.02      # 2% of duration
    _Y_PAD = 0.08      # 8% of amplitude range
    _MIN_Y_SPAN = 0.2  # minimum vertical span

   
    X_PAD = _X_PAD
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.current_event: HapticEvent | None = None

        self._scroll_frac = 0.0  # 0..1 (left position)
        self._zoom_frac   = 1.0  # 0..1 (window width as fraction of full duration)
        self._x0 = 0.0
        self._x1 = 1.0
        self._xpad = 0.0

        # Load UI
        self._load_ui()

        # Default view mode (set before setting up curves!)
        self._view_mode = "Amplitude"

        # Create plot
        self._setup_plot_widget()
        self._setup_dual_axes_and_curves()
        self._amp_scatter: _EditableScatter | None = None
        self._freq_scatter: _EditableScatter | None = None

        # Hide all canvas controls
        self._hide_header_controls()
        self._ensure_parameter_cards_visible()
        self._connect_spinboxes()

        # Default view mode (changed via menubar -> set_view_mode)
        self._view_mode = "Amplitude"

    def _setup_horizontal_navigator(self):
        """Adds Zoom (right=more zoom) and Pan sliders under the plot."""
        container = QWidget(self)
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 6, 0, 0)
        row.setSpacing(10)

        # Zoom: 1..100, where 100 = maximum zoom (smallest window)
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal, container)
        self.zoom_slider.setRange(1, 100)
        self.zoom_slider.setSingleStep(1)
        self.zoom_slider.setPageStep(5)
        self.zoom_slider.setToolTip("Zoom: right = more zoom (smaller time window)")
        self.zoom_slider.valueChanged.connect(self._on_zoom_changed)

        # Pan: 0..1000 normalized position in the timeline
        self.pan_slider = QSlider(Qt.Orientation.Horizontal, container)
        self.pan_slider.setRange(0, 1000)
        self.pan_slider.setSingleStep(1)
        self.pan_slider.setPageStep(25)
        self.pan_slider.setToolTip("Pan horizontally along the timeline")
        self.pan_slider.valueChanged.connect(self._on_pan_changed)

        row.addWidget(QLabel("Zoom"))
        row.addWidget(self.zoom_slider, 2)
        row.addSpacing(8)
        row.addWidget(QLabel("Pan"))
        row.addWidget(self.pan_slider, 4)

        # Attach under the plot
        if hasattr(self, "plot_layout"):
            self.plot_layout.addWidget(container)
        else:
            self.layout().addWidget(container)

        self._nav_container = container

        # ---- Default positions ----
        # Zoom at maximum of the bar (most zoomed-in), Pan slightly advanced (~20%)
        self.zoom_slider.setValue(self.zoom_slider.maximum())
        self.pan_slider.setValue(int(0.20 * self.pan_slider.maximum()))
        self._zoom_frac = self._window_frac_from_zoom_val(self.zoom_slider.value())
        self._scroll_frac = self.pan_slider.value() / float(self.pan_slider.maximum())
    
    def _auto_zoom(self):
        """Tightly fit X/Y to the currently plotted data (Amplitude + Frequency)."""
        if not self.current_event or not self.current_event.waveform_data:
            return

        wf = self.current_event.waveform_data
        p  = self.current_event.parameter_modifications
        pi = self.plot_widget.getPlotItem()
        pi.enableAutoRange('xy', False)

        # ---- X range (time) ----
        dur = float(wf.duration) * float(p.duration_scale or 1.0)
        x0, x1 = 0.0, max(1e-6, dur)
        xpad = max(1e-6, (x1 - x0) * self._X_PAD)
        self._apply_x_from_state()

        # ---- Y range (amplitude, left axis) ----
        y = None
        if wf.amplitude:
            amp_mod = self.current_event.get_modified_waveform()
            if amp_mod is not None:
                y = np.asarray(amp_mod, float)
            else:
                y = np.asarray([pt["amplitude"] for pt in wf.amplitude], float)

        if y is None or y.size == 0:
            ymin, ymax = -1.0, 1.0
        else:
            # symmetrical range around 0 looks better for bipolar signals
            a = float(np.max(np.abs(y)))
            a = 1.0 if a < 1e-9 else a
            ymin, ymax = -a, +a

        yspan = max(self._MIN_Y_SPAN, (ymax - ymin))
        ypad  = yspan * self._Y_PAD
        # ---- X range (time) ----
        dur = float(wf.duration) * float(p.duration_scale or 1.0)
        x0, x1 = 0.0, max(1e-6, dur)
        xpad = max(1e-6, (x1 - x0) * self._X_PAD)

        # Save and apply via sliders (keeps Y auto-sized, X controlled by pan/zoom)
        self._x0, self._x1, self._xpad = x0, x1, xpad
        self._apply_x_from_state()
        pi.vb.setYRange(ymin - ypad, ymax + ypad, padding=0)

        # ---- Y range for frequency (right axis) ----
        if wf.frequency:
            f_mod = self.current_event.get_modified_frequency()
            f = np.asarray(f_mod if f_mod is not None else
                           [pt["frequency"] for pt in wf.frequency], float)
            if f.size:
                fmin, fmax = float(np.min(f)), float(np.max(f))
                if fmin == fmax:
                    fmin -= 1.0; fmax += 1.0
                fpad = max(0.5, (fmax - fmin) * 0.10)
                self.vb_right.setYRange(fmin - fpad, fmax + fpad, padding=0)

    # ---- Menubar hooks -----------------------------------------------------
    def set_view_mode(self, mode: str):
        """Called by the main window View menu: 'Amplitude' | 'Frequency' | 'Both'."""
        self._view_mode = mode
        self._apply_view_visibility()
        self._auto_zoom()
        if self.current_event:
            self.plot_event(self.current_event)

    def clear_plot(self):
        """View → Clear Plot."""
        self._on_clear_clicked()

    def save_csv(self):
        """View → Save Signal (CSV)."""
        self._on_save_csv()
    
    # Put this helper inside WaveformEditorWidget
    def _window_frac_from_zoom_val(self, val: int) -> float:
        """
        Map zoom slider (1..100) to visible window fraction (1.0..0.05).
        1   -> show 100% of the duration (no zoom)
        100 -> show 5% of the duration (max zoom)
        """
        vmin, vmax = 1.0, 100.0
        val = float(max(vmin, min(vmax, val)))
        min_frac, max_frac = 0.05, 1.0
        alpha = (val - vmin) / (vmax - vmin)         # 0..1
        return max(min_frac, max_frac - (max_frac - min_frac) * alpha)

    def open_modifiers_dialog(self):
        """View → Modifiers… (non-destructive)."""
        if not self.current_event:
            QMessageBox.information(self, "Modifiers", "No waveform to edit yet.")
            return
        # Simple inline dialog using current parameter_modifications values
        p = self.current_event.parameter_modifications
        dlg = QDialog(self); dlg.setWindowTitle("Modifiers (Post-processing)")
        form = QFormLayout(dlg)

        def spin(minv, maxv, val, step=0.1, dec=3):
            s = QDoubleSpinBox(); s.setRange(minv, maxv); s.setValue(val); s.setSingleStep(step); s.setDecimals(dec); return s

        sp_intensity  = spin(0.0, 10.0, p.intensity_multiplier, 0.1, 3); sp_intensity.setToolTip("Linear amplitude multiplier.")
        sp_offset     = spin(-2.0, 2.0,  p.amplitude_offset,     0.05, 3); sp_offset.setToolTip("DC offset, added after scaling.")
        sp_dur_scale  = spin(0.1, 10.0,  p.duration_scale,       0.1, 3);  sp_dur_scale.setToolTip("Time-stretch factor.")
        sp_freq_shift = spin(-5000.0, 5000.0, p.frequency_shift, 1.0, 2);  sp_freq_shift.setToolTip("Constant frequency offset (Hz).")
        sp_attack     = spin(0.0, 10.0,  p.attack_time,          0.05, 2)
        sp_decay      = spin(0.0, 10.0,  p.decay_time,           0.05, 2)
        sp_sustain    = spin(0.0, 1.0,   p.sustain_level,        0.05, 2)
        sp_release    = spin(0.0, 10.0,  p.release_time,         0.05, 2)

        form.addRow("Intensity ×",      sp_intensity)
        form.addRow("Offset",           sp_offset)
        form.addRow("Duration ×",       sp_dur_scale)
        form.addRow("Freq shift (Hz)",  sp_freq_shift)
        form.addRow("Attack (s)",       sp_attack)
        form.addRow("Decay (s)",        sp_decay)
        form.addRow("Sustain (0..1)",   sp_sustain)
        form.addRow("Release (s)",      sp_release)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok, parent=dlg)
        form.addRow(bb)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            p.intensity_multiplier = float(sp_intensity.value())
            p.amplitude_offset     = float(sp_offset.value())
            p.duration_scale       = float(sp_dur_scale.value())
            p.frequency_shift      = float(sp_freq_shift.value())
            p.attack_time          = float(sp_attack.value())
            p.decay_time           = float(sp_decay.value())
            p.sustain_level        = float(sp_sustain.value())
            p.release_time         = float(sp_release.value())
            self.parameters_changed.emit()
            self.plot_event(self.current_event)

    # ---- UI / Plot setup ---------------------------------------------------
    def _load_ui(self):
        ui_path = os.path.join(os.path.dirname(__file__), "waveform_editor.ui")
        uic.loadUi(ui_path, self)

    def _setup_plot_widget(self):
        """Create the PyQtGraph plot and insert into the .ui placeholder."""
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground(QColor(255, 255, 255))
        self.plot_widget.setAntialiasing(True)
        self.plot_widget.showGrid(x=True, y=True, alpha=0.15)

        axis_pen = pg.mkPen(color=(52, 58, 64, 180), width=1.25)
        self.plot_widget.getAxis("left").setPen(axis_pen)
        self.plot_widget.getAxis("bottom").setPen(axis_pen)
        self.plot_widget.getAxis("left").setTextPen(axis_pen)
        self.plot_widget.getAxis("bottom").setTextPen(axis_pen)
        self.plot_widget.setLabel("left", "Amplitude")
        self.plot_widget.setLabel("bottom", "Time (s)")

                # Make the plot visually larger
        self.plot_widget.setMinimumHeight(560)  # bigger canvas

        # Thicker axes text (PyQtGraph 0.13+ has setTickFont; guard in try)
        try:
            f = QFont(self.plot_widget.font())
            f.setPointSize(max(11, f.pointSize() + 2))
            self.plot_widget.getAxis("left").setTickFont(f)
            self.plot_widget.getAxis("bottom").setTickFont(f)
        except Exception:
            pass

        if hasattr(self, "plot_layout"):
            self.plot_layout.addWidget(self.plot_widget)
            self._add_inline_toolbar()
            self._setup_horizontal_navigator()
        else:
            lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.addWidget(self.plot_widget)

    def _setup_dual_axes_and_curves(self):
        """Left axis = amplitude. Right axis (secondary ViewBox) = frequency."""
        pi = self.plot_widget.getPlotItem()
        pi.enableAutoRange('xy', False)
        pi.showAxis('right')
        self.right_axis = pi.getAxis('right'); self.right_axis.setLabel('Frequency (Hz)')
        self.right_axis.setPen(pg.mkPen('#dc3545'))

        self.vb_right = pg.ViewBox()
        pi.scene().addItem(self.vb_right)
        self.right_axis.linkToView(self.vb_right)
        self.vb_right.setXLink(pi.vb)

        def _update_right_view():
            self.vb_right.setGeometry(pi.vb.sceneBoundingRect())
            self.vb_right.linkedViewChanged(pi.vb, self.vb_right.XAxis)

        pi.vb.sigResized.connect(_update_right_view)
        _update_right_view()

        self.curve_amp_org = pg.PlotDataItem(pen=pg.mkPen('#94a3b8', width=1.5,
                                                        style=Qt.PenStyle.DashLine))
        self.curve_amp_mod = pg.PlotDataItem(pen=pg.mkPen('#0d6efd', width=2.5))
        pi.addItem(self.curve_amp_org); pi.addItem(self.curve_amp_mod)
        self.curve_amp_mod.setBrush(None)  # ⟵ pas de zone remplie

        # Curves (right)
        self.curve_freq_org = pg.PlotDataItem(pen=pg.mkPen('#198754', width=1.5,
                                                        style=Qt.PenStyle.DashLine))
        self.curve_freq_mod = pg.PlotDataItem(pen=pg.mkPen('#dc3545', width=2.0))
        self.vb_right.addItem(self.curve_freq_org); self.vb_right.addItem(self.curve_freq_mod)

        # Downsampling pour toutes les courbes (évite l’effet peigne)
        for c in (self.curve_amp_org, self.curve_amp_mod, self.curve_freq_org, self.curve_freq_mod):
            c.setClipToView(True)

        # Ligne zéro discrète
        self.zero_line = pg.InfiniteLine(angle=0, pos=0, pen=pg.mkPen((0, 0, 0, 60)))
        pi.addItem(self.zero_line)
    
    def _apply_x_from_state(self):
        """Apply current zoom/pan to X range (Y range unchanged)."""
        pi = self.plot_widget.getPlotItem()
        dur = max(1e-9, self._x1 - self._x0)
        win = max(0.01, min(1.0, self._zoom_frac)) * dur
        leftmax = max(0.0, dur - win)
        left = min(max(0.0, self._scroll_frac) * leftmax, leftmax)
        x_left = self._x0 + left
        x_right = x_left + win
        pi.vb.setXRange(x_left - self._xpad, x_right + self._xpad, padding=0)
        if hasattr(self, "pan_slider"):
            self.pan_slider.setEnabled(leftmax > 1e-9)

    def _on_zoom_changed(self, val: int):
        self._zoom_frac = self._window_frac_from_zoom_val(val)
        self._apply_x_from_state()

    def _on_pan_changed(self, val: int):
        self._scroll_frac = float(val) / float(self.pan_slider.maximum() or 1)
        self._apply_x_from_state()

    def _hide_header_controls(self):
        """
        Hide any header/tool rows that might still be in the .ui (old graph selector, etc.),
        but DO NOT hide the parameter group boxes under the plot.
        """
        to_hide = [
            "graph_selector",          # old combo
            "graph_selector_widget",   # container that includes the 'View:' label
            "view_label",              # label inside the old header
            "toolbarWidget",
            "topBar",
            "controlsRow",
        ]
        for name in to_hide:
            if hasattr(self, name):
                try:
                    getattr(self, name).setVisible(False)
                except Exception:
                    pass
    
    def _ensure_parameter_cards_visible(self):
            """
            Make sure the parameter group boxes under the plot are visible again.
            Works with either the old or newer object names.
            """
            groups = [
                "amplitudeGroup", "timingGroup", "adsrGroup", "resetGroup",
                "groupAmplitude", "groupTiming", "groupEnvelope", "groupReset",
            ]
            for name in groups:
                if hasattr(self, name):
                    try:
                        getattr(self, name).setVisible(True)
                    except Exception:
                        pass
        
    def _set_param(self, name: str, value: float):
        """Update a ParameterModifications field, re-render, and notify listeners."""
        if not self.current_event:
            return
        setattr(self.current_event.parameter_modifications, name, float(value))
        self.parameters_changed.emit()
        self.plot_event(self.current_event)

    def _connect_spinboxes(self):
        """Connect parameter cards (under the plot) to the live model if present in the .ui."""
        # Amplitude
        if hasattr(self, "intensity_spinbox"):
            self.intensity_spinbox.valueChanged.connect(lambda v: self._set_param("intensity_multiplier", v))
        if hasattr(self, "offset_spinbox"):
            # using amplitude_offset as a simple offset; if you use perceptual_loudness instead, swap field name
            self.offset_spinbox.valueChanged.connect(lambda v: self._set_param("amplitude_offset", v))

        # Timing / Frequency
        if hasattr(self, "duration_spinbox"):
            self.duration_spinbox.valueChanged.connect(lambda v: self._set_param("duration_scale", v))
        if hasattr(self, "freq_shift_spinbox"):
            self.freq_shift_spinbox.valueChanged.connect(lambda v: self._set_param("frequency_shift", v))

        # ADSR
        if hasattr(self, "attack_spinbox"):
            self.attack_spinbox.valueChanged.connect(lambda v: self._set_param("attack_time", v))
        if hasattr(self, "decay_spinbox"):
            self.decay_spinbox.valueChanged.connect(lambda v: self._set_param("decay_time", v))
        if hasattr(self, "sustain_spinbox"):
            self.sustain_spinbox.valueChanged.connect(lambda v: self._set_param("sustain_level", v))
        if hasattr(self, "release_spinbox"):
            self.release_spinbox.valueChanged.connect(lambda v: self._set_param("release_time", v))

        # Reset button
        if hasattr(self, "reset_button"):
            self.reset_button.clicked.connect(self._reset_parameters)
        
        if hasattr(self, "resetGroup"):
            from PyQt6.QtWidgets import QPushButton
            self.play_button = QPushButton("▶ Play Waveform", self.resetGroup)
            self.resetGroup.layout().addWidget(self.play_button)
            # Appelle le hardware directement
            self.play_button.clicked.connect(self._on_play_waveform)

            # (bonus) si le .ui contient déjà un bouton Play, on le câble aussi
            for name in ("playWaveformButton", "btnPlay", "playButton"):
                if hasattr(self, name):
                    try:
                        getattr(self, name).clicked.connect(self._on_play_waveform)
                    except Exception:
                        pass


    # Add this method somewhere in the class:
    def _emit_play_waveform(self):
        if not getattr(self, "current_event", None) or not getattr(self.current_event, "waveform_data", None):
            QMessageBox.information(self, "Play", "No waveform loaded.")
            return
        self.playRequested.emit(self.current_event)

        
    def _add_inline_toolbar(self):
        """Small toolbar above the plot: View (combo) + Clear."""
        bar = QWidget(self)
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 6)
        row.setSpacing(10)

        # Single "View:" + combo
        row.addWidget(QLabel("View:"))
        self.view_combo_inline = QComboBox(bar)
        self.view_combo_inline.addItems(["Amplitude", "Frequency", "Both"])
        row.addWidget(self.view_combo_inline)

        row.addStretch(1)

        # Play button (hardware)
        self.btn_play = QPushButton("Play", bar)
        self.btn_play.clicked.connect(self._on_play_waveform)
        row.addWidget(self.btn_play)

        # Clear button
        self.btn_clear = QPushButton("Clear", bar)
        self.btn_clear.clicked.connect(self._on_clear_clicked)
        row.addWidget(self.btn_clear)

        # Initial selection based on current mode
        try:
            idx = self.view_combo_inline.findText(self._view_mode)
            if idx >= 0:
                self.view_combo_inline.setCurrentIndex(idx)
        except Exception:
            pass

        # Wire: change view when user selects from dropdown
        self.view_combo_inline.currentTextChanged.connect(self.set_view_mode)

        # Insert toolbar at the top of the plot area
        if hasattr(self, "plot_layout"):
            self.plot_layout.insertWidget(0, bar)  # above the plot
        else:
            self.layout().insertWidget(0, bar)

        self._plot_toolbar = bar
    
    def _on_view_button_clicked(self, button):
        # Button text matches our modes: "Amplitude" | "Frequency" | "Both"
        self.set_view_mode(button.text())
        
    
    def _on_play_waveform(self):
        """Play current waveform on device; defaults to actuator 0."""
        if not self.current_event or not getattr(self.current_event, "waveform_data", None):
            QMessageBox.information(self, "Play", "No waveform loaded.")
            return

        mainwin = self.window()
        if mainwin and hasattr(mainwin, "play_waveform_on_device"):
            try:
                # Force A0 if rien n'est configuré
                if not getattr(mainwin, "device_targets", None):
                    mainwin.device_targets = [0]
                mainwin.play_waveform_on_device(self.current_event)
                return
            except Exception as e:
                print("play_waveform_on_device error:", e)

        # ----- Fallback direct (impulsion 250 ms sur A0) -----
        api = getattr(mainwin, "serial_api", None) if mainwin else None
        if not api or not getattr(api, "connected", False):
            QMessageBox.warning(self, "Device", "Please connect to a device first.")
            return

        try:
            # Duty = RMS de la waveform (jamais 0 si signal ≠ 0)
            wf = self.current_event.waveform_data
            amps = [p["amplitude"] for p in getattr(wf, "amplitude", [])] or [0.5]
            a = np.asarray(amps, dtype=float)
            rms = float(np.sqrt(np.mean(np.square(a))))
            rms = float(np.clip(rms, 0.0, 1.0))
            duty = int(max(1, min(15, round(rms * 15.0))))
            freq_code = int(getattr(mainwin, "device_freq_code", 4))

            api.send_command(0, duty, freq_code, 1)
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(250, lambda: api.send_command(0, 0, 0, 0))
        except Exception as e:
            QMessageBox.critical(self, "Play error", str(e))




    def _reset_parameters(self):
        """Reset all modifiers to defaults and refresh the UI."""
        if not self.current_event:
            return
        self.current_event.parameter_modifications = ParameterModifications()
        self._sync_spinboxes_from_params()
        self.parameters_changed.emit()
        self.plot_event(self.current_event)

    def _sync_spinboxes_from_params(self):
        """Write ParameterModifications values into the spinboxes (if they exist)."""
        p = self.current_event.parameter_modifications if self.current_event else ParameterModifications()
        mapping = [
            ("intensity_spinbox",   p.intensity_multiplier),
            ("offset_spinbox",      p.amplitude_offset),      # or p.perceptual_loudness if you prefer
            ("duration_spinbox",    p.duration_scale),
            ("freq_shift_spinbox",  p.frequency_shift),
            ("attack_spinbox",      p.attack_time),
            ("decay_spinbox",       p.decay_time),
            ("sustain_spinbox",     p.sustain_level),
            ("release_spinbox",     p.release_time),
        ]
        for name, val in mapping:
            if hasattr(self, name):
                w = getattr(self, name)
                try:
                    w.blockSignals(True); w.setValue(float(val)); w.blockSignals(False)
                except Exception:
                    pass

    # ---- Drag & Drop -------------------------------------------------------
    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME_WAVEFORM):
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dropEvent(self, e):
        try:
            payload = json.loads(bytes(e.mimeData().data(MIME_WAVEFORM)).decode("utf-8"))
        except Exception:
            return
        kind = payload.get("kind")
        if kind == "osc":
            self._handle_osc_drop(payload.get("name", "Sine")); e.acceptProposedAction()
        elif kind == "file":
            self._handle_file_drop(payload.get("path")); e.acceptProposedAction()
        else:
            super().dropEvent(e)

    def _compose_into_event(self, t: np.ndarray, y: np.ndarray, sr: float):
        """Multiply into current event (resampling as needed) or replace if empty."""
        if not self.current_event:
            return
        y = np.asarray(y, float); t = np.asarray(t, float); sr = float(sr)
        wf = self.current_event.waveform_data

        if wf and wf.amplitude:
            y1 = np.array([p["amplitude"] for p in wf.amplitude], dtype=float)
            sr1 = float(wf.sample_rate)
            y2 = resample_to(y, sr, sr1)
            n = min(y1.size, y2.size)
            if n == 0:
                return
            y1[:n] *= y2[:n]
            t1 = np.arange(y1.size, dtype=float) / sr1
            wf.amplitude = [{"time": float(tt), "amplitude": float(yy)} for tt, yy in zip(t1, y1)]
            wf.duration = float(y1.size / sr1)
        else:
            duration = float(t[-1] - t[0]) if t.size > 1 else (y.size / sr if sr > 0 else 0.0)
            amp_pts = [{"time": float(tt), "amplitude": float(yy)} for tt, yy in zip(t, y)]
            freq_pts = [{"time": 0.0, "frequency": 0.0}, {"time": duration, "frequency": 0.0}]
            self.current_event.waveform_data = WaveformData(amp_pts, freq_pts, duration, sr)

        self.plot_event(self.current_event)

    def _handle_osc_drop(self, name: str):
        """Ask parameters based on the oscillator type, then compose."""
        nl = (name or "Sine").lower()
        if nl == "chirp":
            dlg = ChirpParamsDialog(self)
        elif nl == "fm":
            dlg = FMParamsDialog(self)
        elif nl == "pwm":
            dlg = PWMParamsDialog(self)
        else:
            dlg = BaseParamsDialog(self, title=f"{name} Parameters")
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        params = dlg.values()
        t, y, sr = generate_builtin_waveform(name, **params)
        self._compose_into_event(t, y, sr)

    def _handle_file_drop(self, path: str | None):
        """Load CSV/JSON and compose."""
        if not path or not os.path.isfile(path):
            QMessageBox.warning(self, "Drop error", "Invalid file.")
            return
        try:
            if path.lower().endswith(".csv"):
                t, y, sr = load_csv_waveform(path)
            else:
                obj = json.load(open(path, "r", encoding="utf-8"))
                if "waveform_data" in obj:
                    wf = obj["waveform_data"]
                    y = np.asarray([p["amplitude"] for p in wf["amplitude"]], dtype=float)
                    sr = float(wf.get("sample_rate", 1000.0))
                    t = np.arange(y.size, dtype=float) / sr if y.size else np.zeros(0, dtype=float)
                else:
                    y = np.asarray(obj["amplitude"], dtype=float)
                    sr = float(obj["sample_rate"])
                    t = np.arange(y.size, dtype=float) / sr
            self._compose_into_event(t, y, sr)
        except Exception as e:
            QMessageBox.critical(self, "Load failed", str(e))

    # ---- View handlers -----------------------------------------------------
    def _on_clear_clicked(self):
        if not self.current_event or not getattr(self.current_event, "waveform_data", None):
            self.plot_widget.clear()
            self._setup_dual_axes_and_curves()
            self._amp_scatter = None; self._freq_scatter = None
            return
        wf = self.current_event.waveform_data
        dur = float(getattr(wf, "duration", 0.0) or 0.0)
        wf.amplitude = [{"time": 0.0, "amplitude": 0.0}, {"time": max(0.0, dur), "amplitude": 0.0}]
        wf.frequency = [{"time": 0.0, "frequency": 0.0}, {"time": max(0.0, dur), "frequency": 0.0}]
        self.plot_event(self.current_event)

    def _on_save_csv(self):
        if not self.current_event or not getattr(self.current_event, "waveform_data", None):
            QMessageBox.information(self, "Save CSV", "Nothing to save.")
            return
        wf = self.current_event.waveform_data
        if not wf.amplitude:
            QMessageBox.information(self, "Save CSV", "Amplitude is empty.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save Signal as CSV", "signal.csv", "CSV (*.csv)")
        if not path:
            return
        t = np.array([p["time"] for p in wf.amplitude], dtype=float)
        y = np.array([p["amplitude"] for p in wf.amplitude], dtype=float)
        try:
            np.savetxt(path, np.column_stack([t, y]), delimiter=",", header="t,amplitude", comments="")
        except Exception as e:
            QMessageBox.critical(self, "Save CSV", str(e))

    # ---- Public API --------------------------------------------------------
    def set_event(self, evt: HapticEvent):
        self.current_event = evt
        self._sync_spinboxes_from_params()
        self.plot_event(evt)

    def refresh(self):
        if self.current_event:
            self.plot_event(self.current_event)

    # ---- Main plotting -----------------------------------------------------
    def _apply_view_visibility(self):
        show_amp  = self._view_mode in ("Amplitude", "Both")
        show_freq = self._view_mode in ("Frequency", "Both")
        for it in (self.curve_amp_org, self.curve_amp_mod): it.setVisible(show_amp)
        for it in (self.curve_freq_org, self.curve_freq_mod): it.setVisible(show_freq)
        self.plot_widget.getPlotItem().getAxis('right').setVisible(show_freq)

    def _set_curve_data(self, curve, x, y):
        try:
            curve.setData(x, y, downsampleMethod='peak')
        except TypeError:
            curve.setData(x, y)
    def plot_event(self, event: HapticEvent):
        """Render the current event (original + modified curves) and refresh zoom."""
        self.current_event = event
        pi = self.plot_widget.getPlotItem()

        # Remove previous editable handles
        if getattr(self, "_amp_scatter", None):
            try: pi.removeItem(self._amp_scatter)
            except Exception: pass
            self._amp_scatter = None
        if getattr(self, "_freq_scatter", None):
            try: self.vb_right.removeItem(self._freq_scatter)
            except Exception: pass
            self._freq_scatter = None

        # Nothing to show
        if not event or not event.waveform_data:
            for c in (self.curve_amp_org, self.curve_amp_mod, self.curve_freq_org, self.curve_freq_mod):
                self._set_curve_data(c, [], [])
            self._apply_view_visibility()
            self._auto_zoom()
            return

        wf = event.waveform_data
        p  = event.parameter_modifications
        name = getattr(event.metadata, "name", "")

        # ---------- Amplitude ----------
        if wf.amplitude:
            t_a  = np.asarray([pt["time"] for pt in wf.amplitude], dtype=float)
            a    = np.asarray([pt["amplitude"] for pt in wf.amplitude], dtype=float)

            t_disp, a_disp = create_faithful_display_signal(t_a, a, target_points=2000, signal_name=name)
            self._set_curve_data(self.curve_amp_org, t_disp, a_disp)

            a_mod = event.get_modified_waveform()
            if a_mod is not None:
                t_mod = t_a * float(p.duration_scale or 1.0)
                tmd, amd = create_faithful_display_signal(t_mod, a_mod, target_points=2000, signal_name=name)
                self._set_curve_data(self.curve_amp_mod, tmd, amd)

                # Low-density editable handles
                if len(t_a) > 15:
                    step = max(1, len(t_a) // 12)
                    idx  = list(range(0, len(t_a), step))
                    if idx[-1] != len(t_a) - 1:
                        idx.append(len(t_a) - 1)
                    t_edit, a_edit = t_a[idx], a[idx]
                else:
                    t_edit, a_edit = t_a, a
                self._amp_scatter = _EditableScatter(t_edit, a_edit, color="#fd7e14", callback=self._amp_moved)
                pi.addItem(self._amp_scatter)
            else:
                self._set_curve_data(self.curve_amp_mod, [], [])
        else:
            self._set_curve_data(self.curve_amp_org, [], [])
            self._set_curve_data(self.curve_amp_mod, [], [])

        # ---------- Frequency ----------
        if wf.frequency:
            t_f = np.asarray([pt["time"] for pt in wf.frequency], dtype=float)
            f   = np.asarray([pt["frequency"] for pt in wf.frequency], dtype=float)

            tfd, fd = create_faithful_display_signal(t_f, f, target_points=1200, signal_name=name)
            self._set_curve_data(self.curve_freq_org, tfd, fd)

            f_mod = event.get_modified_frequency()
            if f_mod is not None:
                t_mod = t_f * float(p.duration_scale or 1.0)
                tmd, fmd = create_faithful_display_signal(t_mod, f_mod, target_points=1200, signal_name=name)
                self._set_curve_data(self.curve_freq_mod, tmd, fmd)

                if len(t_f) > 10:
                    step = max(1, len(t_f) // 8)
                    idx  = list(range(0, len(t_f), step))
                    if idx[-1] != len(t_f) - 1:
                        idx.append(len(t_f) - 1)
                    t_edit, f_edit = t_f[idx], f[idx]
                else:
                    t_edit, f_edit = t_f, f
                self._freq_scatter = _EditableScatter(t_edit, f_edit, color="#20c997", callback=self._freq_moved)
                self.vb_right.addItem(self._freq_scatter)
            else:
                self._set_curve_data(self.curve_freq_mod, [], [])
        else:
            self._set_curve_data(self.curve_freq_org, [], [])
            self._set_curve_data(self.curve_freq_mod, [], [])

        # Finalize
        self._apply_view_visibility()
        self._auto_zoom()

    # ---- Editable callbacks -----------------------------------------------
    def _amp_moved(self, x: np.ndarray, y: np.ndarray):
        if not self.current_event: return
        self.current_event.waveform_data.amplitude = [{"time": float(tx), "amplitude": float(ay)} for tx, ay in zip(x, y)]
        self.plot_event(self.current_event)

    def _freq_moved(self, x: np.ndarray, y: np.ndarray):
        if not self.current_event: return
        self.current_event.waveform_data.frequency = [{"time": float(tx), "frequency": float(fy)} for tx, fy in zip(x, y)]
        self.plot_event(self.current_event)


# --------------------------------------------------------------------------
# Demo
# --------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    w = WaveformEditorWidget()
    evt = HapticEvent.new_basic_oscillator("Sine")
    w.set_event(evt)
    w.resize(1200, 800)
    w.show()
    sys.exit(app.exec())