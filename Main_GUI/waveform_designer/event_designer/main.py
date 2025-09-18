# main.py
"""
Main application file for the Universal Haptic Waveform Designer
"""

import sys
import os
import time
import shutil
import numpy as np
from PyQt6.QtCore import Qt, QFileSystemWatcher, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, 
    QGroupBox, QLabel, QLineEdit, QTextEdit, QComboBox, QPushButton, 
    QFileDialog, QMessageBox, QTabWidget, QGridLayout, QDoubleSpinBox, 
    QDialog, QDialogButtonBox, QFormLayout, QSpinBox, QScrollArea,
    QWidgetAction, QFrame, QRadioButton, QInputDialog
)

# Import our custom modules
from .core import (
    safe_eval_equation, normalize_signal, load_csv_waveform, 
    resample_to, generate_builtin_waveform, common_time_grid
)
from .ui import (
    apply_ultra_clean_theme, load_ultra_clean_qss,
    CollapsibleSection, EventLibraryWidget, EditorDropProxy, EventLibraryManager
)

# Import event data model
from .core import HapticEvent, EventCategory, WaveformData

# Import communication API
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from communication import python_serial_api

class WaveformPlaybackThread(QThread):
    finished = pyqtSignal(bool, str)
    log = pyqtSignal(str)

    def __init__(self, api, event, actuators, freq_code: int, tick_ms: int = 50):
        super().__init__()
        self.api = api
        self.event = event
        self.actuators = [int(str(a).lstrip("A").lstrip("a")) for a in (actuators or [0])]
        self.freq_code = int(freq_code)
        self.tick_ms = int(max(5, tick_ms))
        self._stop = False

    def stop(self): self._stop = True

    def _extract_y(self):
        wd = getattr(self.event, "waveform_data", None)
        if wd is None:
            return np.array([], dtype=float), 0.0
        # 1) waveform modifiée si dispo
        try:
            gm = getattr(self.event, "get_modified_waveform", None)
            if callable(gm):
                y = np.asarray(gm(), dtype=float)
                sr = float(getattr(wd, "sample_rate", 1000.0))
                if y.size: return y, sr
        except Exception: pass
        # 2) méthode utilitaire
        try:
            y = np.asarray(wd.get_amplitude_array(), dtype=float)
            sr = float(getattr(wd, "sample_rate", 1000.0))
            if y.size: return y, sr
        except Exception: pass
        # 3) reconstruire des points
        try:
            amps = getattr(wd, "amplitude", None) or []
            if amps:
                t = np.array([p["time"] for p in amps], dtype=float)
                y = np.array([p["amplitude"] for p in amps], dtype=float)
                sr = float(getattr(wd, "sample_rate", 1000.0))
                if t.size > 1 and not np.allclose(np.diff(t), np.diff(t)[0]):
                    n = max(2, int(round(float(getattr(wd, "duration", t[-1] if t.size else 0.0)) * sr)))
                    tg = np.linspace(0.0, float(getattr(wd, "duration", t[-1] if t.size else 0.0)), n)
                    y = np.interp(tg, t, y)
                return y, sr
        except Exception: pass
        return np.array([], dtype=float), float(getattr(wd, "sample_rate", 1000.0))

    @staticmethod
    def _to_unit_nonneg(y: np.ndarray) -> np.ndarray:
        y = np.asarray(y, dtype=float)
        y = np.nan_to_num(y, nan=0.0, posinf=0.0, neginf=0.0)
        if y.size == 0: return y
        y_min, y_max = float(np.min(y)), float(np.max(y))
        if abs(y_max - y_min) < 1e-12:
            return np.zeros_like(y) if y_max <= 0.0 else np.ones_like(y)
        y = (y - y_min) / (y_max - y_min)
        return np.clip(y, 0.0, 1.0)

    def run(self):
        try:
            y, sr = self._extract_y()
            if y.size == 0:
                self.finished.emit(False, "Empty waveform"); return

            y = self._to_unit_nonneg(y)
            step = max(1, int(round(float(sr) * (self.tick_ms / 1000.0))))
            y = y[::step]

            duty_seq = np.rint(y * 15.0).astype(int)
            duty_seq = np.where((y > 1e-6) & (duty_seq == 0), 1, duty_seq)
            duty_seq = np.clip(duty_seq, 0, 15)

            for duty in duty_seq:
                if self._stop: break
                for addr in self.actuators:
                    try: self.api.send_command(int(addr), int(duty), self.freq_code, 1)
                    except Exception as e: self.log.emit(f"send_command error: {e}")
                self.msleep(self.tick_ms)

            for addr in self.actuators:
                try: self.api.send_command(int(addr), 0, 0, 0)
                except Exception: pass

            self.finished.emit(True, "Waveform done")
        except Exception as e:
            try:
                for addr in self.actuators: self.api.send_command(int(addr), 0, 0, 0)
            except Exception: pass
            self.finished.emit(False, str(e))



class BuiltinParamsDialog(QDialog):
    """
    Minimal per-oscillator param dialog (like the original):
    - Sine/Saw/Triangle/Square/PWM: Frequency, Amplitude, Duration (+ duty for PWM)
    - Chirp: f0, f1, Amplitude, Duration
    - FM: Carrier freq (fc), Mod freq (fm), beta, Amplitude, Duration
    - Noise: Amplitude, Duration
    Sample rate is NOT shown; we pass it from defaults/current event.
    """
    def __init__(self, parent, osc_name: str, *, defaults: dict, sr_default: float):
        super().__init__(parent)
        self.setWindowTitle(f"Customize {osc_name} Signal")
        self._osc = osc_name.lower()
        self._sr = float(sr_default)
        d = dict(defaults or {})

        main = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        # Common fields
        self.amp = QDoubleSpinBox(); self.amp.setRange(0.0, 1.0); self.amp.setDecimals(3); self.amp.setSingleStep(0.01)
        self.dur = QDoubleSpinBox(); self.dur.setRange(0.05, 20.0); self.dur.setDecimals(2); self.dur.setSingleStep(0.05)
        self.amp.setValue(float(d.get("amplitude", 1.0)))
        self.dur.setValue(float(d.get("duration", 1.0)))

        # Frequency (for most oscs)
        self.freq = QDoubleSpinBox(); self.freq.setRange(0.0, 400.0); self.freq.setDecimals(2); self.freq.setSingleStep(1.0)
        self.freq.setValue(float(d.get("frequency", 100.0)))
        self._row_freq_label = "Frequency (0–400Hz):"

        # Optional fields
        self.f0 = QDoubleSpinBox(); self.f0.setRange(0.0, 400.0); self.f0.setDecimals(2); self.f0.setSingleStep(1.0)
        self.f1 = QDoubleSpinBox(); self.f1.setRange(0.0, 400.0); self.f1.setDecimals(2); self.f1.setSingleStep(1.0)
        self.fm = QDoubleSpinBox(); self.fm.setRange(0.0, 50.0);  self.fm.setDecimals(2); self.fm.setSingleStep(0.5)
        self.beta = QDoubleSpinBox(); self.beta.setRange(0.0, 10.0); self.beta.setDecimals(2); self.beta.setSingleStep(0.1)
        self.duty = QDoubleSpinBox(); self.duty.setRange(0.0, 1.0); self.duty.setDecimals(3); self.duty.setSingleStep(0.01)

        self.f0.setValue(float(d.get("f0", 50.0)))
        self.f1.setValue(float(d.get("f1", 200.0)))
        self.fm.setValue(float(d.get("fm", 5.0)))
        self.beta.setValue(float(d.get("beta", 1.0)))
        self.duty.setValue(float(d.get("duty", 0.5)))

        k = self._osc
        if k == "chirp":
            form.addRow("Start freq f0 (Hz):", self.f0)
            form.addRow("End freq f1 (Hz):", self.f1)
            form.addRow("Amplitude (0–1):", self.amp)
            form.addRow("Duration (s):", self.dur)
        elif k == "fm":
            form.addRow("Carrier freq fc (Hz):", self.freq)
            form.addRow("Mod freq fm (Hz):", self.fm)
            form.addRow("beta (index):", self.beta)
            form.addRow("Amplitude (0–1):", self.amp)
            form.addRow("Duration (s):", self.dur)
        elif k == "pwm":
            form.addRow(self._row_freq_label, self.freq)
            form.addRow("Duty (0–1):", self.duty)
            form.addRow("Amplitude (0–1):", self.amp)
            form.addRow("Duration (s):", self.dur)
        elif k == "noise":
            form.addRow("Amplitude (0–1):", self.amp)
            form.addRow("Duration (s):", self.dur)
        else:
            # sine/saw/triangle/square
            form.addRow(self._row_freq_label, self.freq)
            form.addRow("Amplitude (0–1):", self.amp)
            form.addRow("Duration (s):", self.dur)

        main.addLayout(form)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        main.addWidget(bb)

    def result_params(self) -> dict:
        k = self._osc
        p = {
            "amplitude": float(self.amp.value()),
            "duration": float(self.dur.value()),
            "sample_rate": float(self._sr),
        }
        if k == "chirp":
            p["f0"] = float(self.f0.value()); p["f1"] = float(self.f1.value())
            p["frequency"] = float(self.f0.value())  # generator API expects "frequency" present
        elif k == "fm":
            p["frequency"] = float(self.freq.value())
            p["fm"] = float(self.fm.value()); p["beta"] = float(self.beta.value())
        elif k == "pwm":
            p["frequency"] = float(self.freq.value()); p["duty"] = float(self.duty.value())
        elif k != "noise":
            p["frequency"] = float(self.freq.value())
        return p



class UniversalEventDesigner(QMainWindow):
    """Main application window for the Universal Haptic Waveform Designer."""
    
    def __init__(self):
        super().__init__()
        self.current_event: HapticEvent | None = None
        self.current_file_path: str | None = None
        self.event_manager = EventLibraryManager()
        self.serial_api = python_serial_api()
        self.selected_port = None
        self.logs_visible = True
        self.export_watch_dir: str | None = None
        self.export_start_mtime: float = 0.0
        
        # File system watcher for Meta Haptics Studio integration
        self.dir_watcher = QFileSystemWatcher(self)
        self.dir_watcher.directoryChanged.connect(self._dir_changed)
        
        # Build UI
        self._build_menubar()
        self._build_ui()
        self.new_event()
        
        # Set placeholder text for math equation
        self.math_equation.setPlaceholderText(
            "Examples: sin(2*pi*f*t) | square(2*pi*f*t) | sawtooth(2*pi*f*t) | 0.5*sin(2*pi*f*t)+0.5*sin(4*pi*f*t)"
        )
        self._osc_prefs: dict[str, dict] = {} 
    
    def _parse_targets(self):
        txt = (self.targets_edit.text() or "").strip()
        ids = []
        for part in txt.replace(";", ",").split(","):
            part = part.strip()
            if not part:
                continue
            try:
                ids.append(int(str(part).lstrip("A").lstrip("a")))
            except Exception:
                pass
        if ids:
            self.device_targets = ids
            self.log_info_message(f"Targets set: {self.device_targets}")


    def _open_device_test_dialog(self):
        dlg = QDialog(self); dlg.setWindowTitle("Device Test")
        lay = QFormLayout(dlg)
        sp = QSpinBox(dlg); sp.setRange(0, 127)
        sp.setValue(self.device_targets[0] if getattr(self, "device_targets", None) else 0)
        lay.addRow("Actuator #:", sp)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, parent=dlg)
        lay.addRow(bb)
        bb.accepted.connect(lambda: (self._on_device_test(sp.value()), dlg.accept()))
        bb.rejected.connect(dlg.reject)
        dlg.exec()

    def _on_device_test(self, aid: int):
        if not (hasattr(self, "serial_api") and self.serial_api and self.serial_api.connected):
            QMessageBox.warning(self, "Device", "Please connect to a device first.")
            return
        try:
            self.serial_api.send_command(int(aid), 8, int(self.device_freq_code), 1)
            time.sleep(0.2)
            self.serial_api.send_command(int(aid), 0, 0, 0)
            self.log_info_message(f"Test pulse sent to actuator {aid}")
        except Exception as e:
            self.log_info_message(f"Device test error: {e}")
        
    
    def play_waveform_on_device(self, event):
        """Hardware playback of the given HapticEvent."""
        if not event or not getattr(event, "waveform_data", None):
            QMessageBox.information(self, "Play", "No waveform loaded.")
            return
        if not (hasattr(self, "serial_api") and self.serial_api and self.serial_api.connected):
            QMessageBox.warning(self, "Device", "Please connect to a device first.")
            return

        # Choix des cibles: mapping de l’event ou fallback paramètres Device
        acts = []
        try:
            am = getattr(event, "actuator_mapping", None)
            if am and getattr(am, "active_actuators", None):
                acts = [int(str(a).lstrip("A").lstrip("a")) for a in am.active_actuators]
        except Exception:
            acts = []
        if not acts:
            acts = list(getattr(self, "device_targets", [0]))

        # Stop un éventuel run en cours
        try:
            if getattr(self, "_play_thread", None) and self._play_thread.isRunning():
                self._play_thread.stop()
                self._play_thread.wait(800)
        except Exception:
            pass

        acts = []
        try:
            am = getattr(event, "actuator_mapping", None)
            if am and getattr(am, "active_actuators", None):
                acts = [int(str(a).lstrip("A").lstrip("a")) for a in am.active_actuators]
        except Exception:
            acts = []
        if not acts:
            acts = [0]   # ← force A0

        self._play_thread = WaveformPlaybackThread(
            self.serial_api, event, acts, int(getattr(self, "device_freq_code", 4)), tick_ms=50
        )
        self._play_thread.log.connect(self.log_info_message)
        self._play_thread.finished.connect(lambda ok, msg: self.log_info_message(f"Playback: {msg}"))
        self._play_thread.start()
        self.log_info_message(f"PLAY → actuators {acts}, freq_code {self.device_freq_code}")



    def _build_menubar(self):
        """Build the application menu bar."""
        mb = self.menuBar()
        
        # Device menu (compact)
        device_menu = mb.addMenu("Device")

        # ---- Port submenu ---------------------------------------------------------
        self._dev_ports_menu = device_menu.addMenu("Port")
        self._dev_ports_group = QActionGroup(self); self._dev_ports_group.setExclusive(True)
        self._dev_ports_actions = {}   # port -> QAction

        def _on_port_action(act: QAction):
            # QActionGroup.triggered nous donne directement l'action cochée
            port = act.text()
            self._select_port(port)

        self._dev_ports_group.triggered.connect(_on_port_action)

        # ---- Actuators (opens a small dialog) ------------------------------------
        self._act_targets_action = QAction(f"Actuators: {','.join(map(str, getattr(self, 'device_targets', [0])))}", self)
        self._act_targets_action.triggered.connect(self._choose_actuators)
        device_menu.addAction(self._act_targets_action)

        # ---- Freq code submenu (0..7) --------------------------------------------
        freq_menu = device_menu.addMenu("Freq code (0–7)")
        self._dev_freq_group = QActionGroup(self); self._dev_freq_group.setExclusive(True)
        for i in range(8):
            a = QAction(str(i), self, checkable=True)
            if i == int(getattr(self, "device_freq_code", 4)):
                a.setChecked(True)
            freq_menu.addAction(a)
            self._dev_freq_group.addAction(a)

        def _on_freq_action(act: QAction):
            try:
                self.device_freq_code = int(act.text())
            except Exception:
                self.device_freq_code = 4

        self._dev_freq_group.triggered.connect(_on_freq_action)

        device_menu.addSeparator()

        # ---- Actions --------------------------------------------------------------
        self.scan_action = QAction("Scan Ports", self)
        self.scan_action.triggered.connect(self.scan_devices)
        device_menu.addAction(self.scan_action)

        self.connect_action = QAction("Connect", self)
        self.connect_action.triggered.connect(self.toggle_connection)
        device_menu.addAction(self.connect_action)

        device_menu.addSeparator()

        self.act_device_test = QAction("Test Actuator…", self)
        self.act_device_test.triggered.connect(self._open_device_test_dialog)
        device_menu.addAction(self.act_device_test)

        # Scan initial
        QTimer.singleShot(100, self.scan_devices)

        # View menu
        view_menu = mb.addMenu("View")
        
        # Plot mode selection
        self.plot_mode_group = QActionGroup(self)
        self.plot_mode_group.setExclusive(True)

        act_amp = QAction("Amplitude", self, checkable=True)
        act_freq = QAction("Frequency", self, checkable=True)
        act_both = QAction("Both", self, checkable=True)

        for a in (act_amp, act_freq, act_both):
            self.plot_mode_group.addAction(a)
            view_menu.addAction(a)

        act_amp.setChecked(True)

        def _apply_plot_mode(action: QAction):
            if not hasattr(self, "drop_proxy"): 
                return
            mode = action.text()
            self.drop_proxy.editor.set_view_mode(mode)
            
        self.plot_mode_group.triggered.connect(_apply_plot_mode)

        view_menu.addSeparator()

        # View actions
        self.act_clear = QAction("Clear Plot", self)
        self.act_save = QAction("Save Signal (CSV)", self)
        view_menu.addAction(self.act_clear)
        view_menu.addAction(self.act_save)

        self.act_clear.triggered.connect(lambda: self.drop_proxy.editor.clear_plot())
        self.act_save.triggered.connect(lambda: self.drop_proxy.editor.save_csv())

        view_menu.addSeparator()

        self.act_modifiers = QAction("Modifiers…", self)
        view_menu.addAction(self.act_modifiers)
        self.act_modifiers.triggered.connect(lambda: self.drop_proxy.editor.open_modifiers_dialog())
        
        self.toggle_logs_action = QAction("Hide Logs", self)
        self.toggle_logs_action.triggered.connect(self.toggle_logs_visibility)
        view_menu.addAction(self.toggle_logs_action)
        
        # Initial device scan
        QTimer.singleShot(100, self.scan_devices)

    
    def _refresh_device_menu_labels(self):
        if hasattr(self, "_act_targets_action"):
            self._act_targets_action.setText(f"Actuators: {','.join(map(str, self.device_targets))}")

    def _choose_actuators(self):
        txt, ok = QInputDialog.getText(
            self, "Actuators", "Enter actuator IDs (e.g., 0,1,2):",
            text=",".join(map(str, getattr(self, "device_targets", [0])))
        )
        if not ok:
            return
        ids = []
        for part in (txt or "").replace(";", ",").split(","):
            part = part.strip()
            if not part:
                continue
            try:
                ids.append(int(part))
            except Exception:
                pass
        if ids:
            self.device_targets = ids
            self._refresh_device_menu_labels()
            self.log_info_message(f"Targets set: {self.device_targets}")

    def _select_port(self, port: str):
        self.selected_port = port
        act = self._dev_ports_actions.get(port)
        if act:
            act.setChecked(True)
        self.log_info_message(f"Port selected: {port}")


    def _build_ui(self):
        """Build the main user interface."""
        self.setWindowTitle("Universal Haptic Waveform Designer")
        self.setGeometry(100, 100, 1350, 800)
        self.setMinimumSize(1200, 700)
        
        self.setCentralWidget(QWidget())
        main = QHBoxLayout(self.centralWidget())
        main.setContentsMargins(12, 12, 12, 12)
        main.setSpacing(12)
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main.addWidget(splitter)
        
        splitter.addWidget(self._build_left_panel())
        self.drop_proxy = EditorDropProxy(self)
        try:
            if hasattr(self.drop_proxy, "editor") and hasattr(self.drop_proxy.editor, "playRequested"):
                self.drop_proxy.editor.playRequested.connect(self.play_waveform_on_device)
        except Exception:
            pass

        # Cibles / fréquence par défaut + thread holder
        self.device_targets = [0]
        self.device_freq_code = 4
        self._play_thread = None
        # Relie le signal Play de l’éditeur à la lecture hardware
        try:
            if hasattr(self.drop_proxy, "editor") and hasattr(self.drop_proxy.editor, "playRequested"):
                self.drop_proxy.editor.playRequested.connect(self.play_waveform_on_device)
        except Exception:
            pass
        # Defaults for device playback
        self.device_targets = [0]      # default targets
        self.device_freq_code = 4      # default device code (0..7)
        self._play_thread = None

        # Wire the editor's test signal if available
        try:
            if hasattr(self.drop_proxy, "editor") and hasattr(self.drop_proxy.editor, "device_test_requested"):
                self.drop_proxy.editor.device_test_requested.connect(self._on_device_test)
        except Exception:
            pass

        splitter.addWidget(self.drop_proxy)
        splitter.setSizes([320, 980])

    def _build_left_panel(self) -> QWidget:
        """Build the left panel with tabs."""
        tabs = QTabWidget()

        # Waveform Design tab (wrapped in scroll area)
        meta_tab = QWidget()
        meta_layout = QVBoxLayout(meta_tab)
        meta_layout.setSpacing(16)

        # Action buttons
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        btn_new = QPushButton("New")
        btn_new.clicked.connect(self.new_event)
        btn_save = QPushButton("Save")
        btn_save.clicked.connect(self.save_event)
        buttons.addWidget(btn_new)
        buttons.addWidget(btn_save)
        meta_layout.addLayout(buttons)

        # Waveform Information section (always expanded)
        self.metadata_widget = self._build_metadata_widget()
        info_section = CollapsibleSection(
            "Waveform Information",
            self.metadata_widget,
            collapsed=False,
            always_expanded=True
        )
        meta_layout.addWidget(info_section)

        # Haptic File group
        group_file = QGroupBox("Haptic File")
        file_layout = QVBoxLayout(group_file)
        file_layout.setSpacing(8)
        btn_import_hapt = QPushButton("Import .haptic File")
        btn_import_hapt.clicked.connect(self.import_haptic_file)
        btn_import_csv = QPushButton("Import CSV Waveform")
        btn_import_csv.clicked.connect(self.import_csv_waveform)
        btn_create = QPushButton("Create with Meta Haptics Studio")
        btn_create.clicked.connect(self.create_with_meta_studio)
        self.file_info_label = QLabel("No file loaded")
        self.file_info_label.setStyleSheet("color:#A0AEC0; font-style:italic; font-size:10.5pt;")
        self.file_info_label.setMaximumHeight(20)
        file_layout.addWidget(btn_import_csv)
        file_layout.addWidget(btn_import_hapt)
        file_layout.addWidget(btn_create)
        file_layout.addWidget(self.file_info_label)
        meta_layout.addWidget(group_file)

        # Mathematical Generator section (always expanded)
        math_content = QWidget()
        math_layout = QVBoxLayout(math_content)
        math_layout.setSpacing(10)

        eq_row = QHBoxLayout()
        eq_row.setSpacing(8)
        eq_row.addWidget(QLabel("Equation:"))
        self.math_equation = QLineEdit("np.sin(2 * np.pi * f * t)")
        eq_row.addWidget(self.math_equation, 1)
        math_layout.addLayout(eq_row)

        grid = QGridLayout()
        grid.setSpacing(8)
        grid.addWidget(QLabel("Frequency (Hz):"), 0, 0)
        self.math_freq = QDoubleSpinBox()
        self.math_freq.setRange(0.1, 5000.0)
        self.math_freq.setValue(100.0)
        self.math_freq.setSingleStep(1.0)
        grid.addWidget(self.math_freq, 0, 1)

        grid.addWidget(QLabel("Duration (s):"), 1, 0)
        self.math_dur = QDoubleSpinBox()
        self.math_dur.setRange(0.05, 30.0)
        self.math_dur.setValue(1.0)
        self.math_dur.setSingleStep(0.1)
        grid.addWidget(self.math_dur, 1, 1)

        grid.addWidget(QLabel("Sample Rate:"), 2, 0)
        self.math_sr = QDoubleSpinBox()
        self.math_sr.setRange(200.0, 50000.0)
        self.math_sr.setValue(1000.0)
        self.math_sr.setSingleStep(100.0)
        grid.addWidget(self.math_sr, 2, 1)
        math_layout.addLayout(grid)

        btn_gen = QPushButton("Generate Waveform")
        btn_gen.clicked.connect(self.generate_from_math)
        math_layout.addWidget(btn_gen)

        math_section = CollapsibleSection(
            "Mathematical Generator",
            math_content,
            collapsed=False,
            always_expanded=True
        )
        meta_layout.addWidget(math_section)

        # System logs section
        self.logs_group = QGroupBox("System Log")
        logs_layout = QVBoxLayout(self.logs_group)
        self.info_text = QTextEdit()
        self.info_text.setReadOnly(True)
        self.info_text.setMaximumHeight(70)
        self.info_text.setMinimumHeight(50)
        self.info_text.setStyleSheet(
            "QTextEdit{background:#FFFFFF;border:1px solid #E2E8F0;color:#2D3748;"
            "font-family:'SF Mono','Consolas','Monaco',monospace;font-size:10pt;border-radius:8px;padding:6px;}"
        )
        logs_layout.addWidget(self.info_text)
        clear_btn = QPushButton("Clear Log")
        clear_btn.clicked.connect(self.clear_log)
        logs_layout.addWidget(clear_btn)
        self.logs_group.setVisible(self.logs_visible)
        meta_layout.addWidget(self.logs_group)

        meta_layout.addStretch()

        # Wrap in scroll area
        scroll = QScrollArea()
        scroll.setWidget(meta_tab)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        tabs.addTab(scroll, "Waveform Design")

        # Library tab
        self.library_widget = EventLibraryWidget()
        self.library_widget.event_selected.connect(
            lambda payload: self.handle_library_payload(payload, compose=False)
        )
        tabs.addTab(self.library_widget, "Waveform Library")
        
        return tabs

    def _build_metadata_widget(self) -> QWidget:
        """Build the metadata editing widget."""
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(12)
        
        # Name field
        row = QHBoxLayout()
        row.addWidget(QLabel("Waveform Name:"))
        self.name_edit = QLineEdit()
        self.name_edit.textChanged.connect(self._on_name_changed)
        row.addWidget(self.name_edit)
        lay.addLayout(row)
        
        # Category field
        row = QHBoxLayout()
        row.addWidget(QLabel("Category:"))

        # Editable combobox
        self.category_combo = QComboBox()
        self.category_combo.setEditable(True)
        self.category_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)

        # Base categories
        self._base_categories = [c.value for c in EventCategory]
        self.category_combo.clear()
        self.category_combo.addItems(self._base_categories)

        # Placeholder text
        self.category_combo.lineEdit().setPlaceholderText(
            "crash, isolation, embodiment, alert, custom … or type your own"
        )

        # Connect signals
        self.category_combo.currentIndexChanged.connect(self._on_category_base_index_changed)
        self.category_combo.lineEdit().editingFinished.connect(self._on_category_free_text_committed)
        row.addWidget(self.category_combo)
        lay.addLayout(row)
        
        # Description field
        lay.addWidget(QLabel("Description:"))
        self.description_edit = QTextEdit()
        self.description_edit.setMaximumHeight(85)
        self.description_edit.setMinimumHeight(60)
        self.description_edit.textChanged.connect(self._on_description_changed)
        lay.addWidget(self.description_edit)
        
        return w

    # Metadata handlers
    def _on_category_base_index_changed(self, index: int):
        """Handle selection of base category from dropdown."""
        if index is None or index < 0 or not hasattr(self, "category_combo"):
            return
        text = self.category_combo.itemText(index)
        self._on_category_base_selected(text)

    def _on_category_base_selected(self, text: str):
        """Handle selection of built-in category."""
        if not self.current_event:
            return
        try:
            self.current_event.metadata.category = EventCategory(text)
        except Exception:
            self.current_event.metadata.category = EventCategory.CUSTOM

        # Remove any previous free-text tag
        tags = self.current_event.metadata.tags or []
        self.current_event.metadata.tags = [t for t in tags if not t.startswith("category_name=")]

    def _on_category_free_text_committed(self):
        """Handle commit of free-text category."""
        if not self.current_event:
            return
        text = (self.category_combo.currentText() or "").strip()
        if not text:
            self.current_event.metadata.category = EventCategory.CUSTOM
            tags = self.current_event.metadata.tags or []
            self.current_event.metadata.tags = [t for t in tags if not t.startswith("category_name=")]
            return

        # Check if it's a base category
        if text in getattr(self, "_base_categories", []):
            self._on_category_base_selected(text)
            return

        # Store as custom category with label in tags
        self.current_event.metadata.category = EventCategory.CUSTOM
        tags = self.current_event.metadata.tags or []
        tags = [t for t in tags if not t.startswith("category_name=")]
        tags.append(f"category_name={text}")
        self.current_event.metadata.tags = tags

    def _on_name_changed(self, text: str):
        """Handle name field changes."""
        if self.current_event: 
            self.current_event.metadata.name = text

    def _on_description_changed(self):
        """Handle description field changes."""
        if self.current_event: 
            self.current_event.metadata.description = self.description_edit.toPlainText()

    # Library payload handling
    def handle_library_payload(self, payload, *, compose: bool):
        """
        Double-click (compose=False) => apply defaults immediately, no dialog.
        Drag & drop (compose=True)   => open param dialog, then apply.
        """
        try:
            drop_mod = None
            if isinstance(payload, dict):
                drop_mod = payload.get("drop_mod")
                kind = payload.get("kind")
                if kind == "osc":
                    name = payload.get("name", "Sine")
                    if compose:
                        # DnD → dialog + composition mode from modifiers
                        self._handle_oscillator_with_dialog(name, compose=True, drop_mod=drop_mod)
                    else:
                        # Double-click → defaults, no dialog (previous behavior)
                        self._handle_oscillator_payload(name, compose=False)
                    return
                if kind == "file":
                    self._handle_file_payload(payload.get("path"), compose=compose)
                    return

            # Back-compat string payloads
            if isinstance(payload, str):
                if payload.startswith("oscillator::"):
                    name = payload.split("::", 1)[1]
                    if compose:
                        self._handle_oscillator_with_dialog(name, compose=True, drop_mod=drop_mod)
                    else:
                        self._handle_oscillator_payload(name, compose=False)
                else:
                    self._handle_file_payload(payload, compose=compose)
        except Exception as e:
            QMessageBox.critical(self, "Load error", str(e))

        
    
    def _apply_oscillator(self, osc_name: str, params: dict, comp_mode: str):
        t2, y2, sr2 = generate_builtin_waveform(
            osc_name,
            frequency=float(params.get("frequency", 100.0)),
            amplitude=float(params.get("amplitude", 1.0)),
            duration=float(params.get("duration", 1.0)),
            sample_rate=float(params.get("sample_rate", 1000.0)),
            f0=params.get("f0"), f1=params.get("f1"),
            fm=params.get("fm"), beta=params.get("beta"),
            duty=params.get("duty")
        )

        # Replace or no existing waveform
        if comp_mode == "replace" or not (self.current_event and self.current_event.waveform_data):
            amp_pts = [{"time": float(tt), "amplitude": float(yy)} for tt, yy in zip(t2, y2)]
            freq = float(params.get("frequency", 100.0))
            dur = float(params.get("duration", 1.0))
            sr  = float(params.get("sample_rate", 1000.0))
            freq_pts = [{"time": 0.0, "frequency": freq}, {"time": dur, "frequency": freq}]
            evt = HapticEvent(name=f"{osc_name} Oscillator")
            evt.waveform_data = WaveformData(amp_pts, freq_pts, dur, sr)
            self.current_event = evt
            self.current_file_path = None
            self.update_ui()
            self.log_info_message(f"New {osc_name} oscillator (replace)")
            return

        # Compose with existing
        wf = self.current_event.waveform_data
        y1 = np.array([p["amplitude"] for p in wf.amplitude], dtype=float)
        sr1 = float(wf.sample_rate)
        y2r = resample_to(y2, sr2, sr1)
        n = min(y1.size, y2r.size)
        if n == 0:
            return
        y1 = y1[:n]
        y2r = y2r[:n]

        if comp_mode == "add":
            y = y1 + y2r
        else:  # multiply default
            y = y1 * y2r

        peak = float(np.max(np.abs(y))) if y.size else 1.0
        if peak > 1.0:
            y = y / peak

        t = np.arange(y.size, dtype=float) / sr1
        wf.amplitude = [{"time": float(tt), "amplitude": float(yy)} for tt, yy in zip(t, y)]
        wf.duration = float(y.size / sr1)
        self.update_ui()
        self.log_info_message(f"Composed {osc_name} ({comp_mode})")


    def _handle_oscillator_payload(self, osc_name: str, *, compose: bool):
        """Handle oscillator payload from library."""
        freq, amp, dur, sr = 100.0, 1.0, 1.0, 1000.0
        
        if compose and self.current_event and self.current_event.waveform_data:
            sr = float(self.current_event.waveform_data.sample_rate)
            dur = float(self.current_event.waveform_data.duration)
        
        t2, y2, sr2 = generate_builtin_waveform(
            osc_name, frequency=freq, amplitude=amp, duration=dur, sample_rate=sr
        )
        
        if compose and self.current_event and self.current_event.waveform_data:
            # Composition mode - multiply with existing waveform
            wf = self.current_event.waveform_data
            y1 = np.array([p["amplitude"] for p in wf.amplitude], dtype=float)
            sr1 = float(wf.sample_rate)
            y2r = resample_to(y2, sr2, sr1)
            n = min(y1.size, y2r.size)
            if n == 0: 
                return
            y1[:n] *= y2r[:n]
            t1 = np.arange(y1.size) / sr1
            wf.amplitude = [{"time": float(tt), "amplitude": float(yy)} for tt, yy in zip(t1, y1)]
            wf.duration = float(y1.size / sr1)
            self.update_ui()
            self.log_info_message(f"Composed {osc_name} (multiply)")
        else:
            # Create new waveform
            amp_pts = [{"time": float(tt), "amplitude": float(yy)} for tt, yy in zip(t2, y2)]
            freq_pts = [{"time": 0.0, "frequency": freq}, {"time": float(dur), "frequency": freq}]
            evt = HapticEvent(name=f"{osc_name} Oscillator")
            evt.waveform_data = WaveformData(
                amplitude=amp_pts, frequency=freq_pts, duration=float(dur), sample_rate=float(sr)
            )
            self.current_event = evt
            self.current_file_path = None
            self.update_ui()
            self.log_info_message(f"New {osc_name} oscillator created")
            self.device_targets = [0]
            QTimer.singleShot(0, lambda: self.play_waveform_on_device(self.current_event))
        
    
    def _prefill_defaults_for_osc(self, osc_name: str, *, compose: bool) -> dict:
        k = osc_name.lower()
        d = dict(self._osc_prefs.get(k, {}))
        if compose and self.current_event and self.current_event.waveform_data:
            wf = self.current_event.waveform_data
            d.setdefault("duration", float(wf.duration))
            d.setdefault("sample_rate", float(wf.sample_rate))
        d.setdefault("amplitude", 1.0)
        d.setdefault("frequency", 100.0)
        if k == "chirp":
            d.setdefault("f0", 50.0); d.setdefault("f1", 200.0)
        elif k == "fm":
            d.setdefault("fm", 5.0); d.setdefault("beta", 1.0)
        elif k == "pwm":
            d.setdefault("duty", 0.5)
        return d
    
    def _handle_oscillator_with_dialog(self, osc_name: str, *, compose: bool, drop_mod: str | None):
        # sample rate utilisé pour générer le signal
        sr_default = 1000.0
        if compose and self.current_event and self.current_event.waveform_data:
            sr_default = float(self.current_event.waveform_data.sample_rate)

        defaults = self._prefill_defaults_for_osc(osc_name, compose=compose)
        dlg = BuiltinParamsDialog(self, osc_name, defaults=defaults, sr_default=sr_default)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        params = dlg.result_params()

        # ✅ défaut = replace ; Shift=add ; Alt=multiply (déjà mappé côté drop)
        dm = (drop_mod or "").lower()
        comp_mode = "replace" if dm == "" else ("add" if dm == "add" else "multiply" if dm == "multiply" else "replace")

        self._osc_prefs[osc_name.lower()] = dict(params)
        self._apply_oscillator(osc_name, params, comp_mode)

    def _handle_file_payload(self, path: str | None, *, compose: bool):
        """Handle file payload from library."""
        if not path or not os.path.isfile(path): 
            raise FileNotFoundError("File not found.")
        
        if path.lower().endswith(".csv"):
            t2, y2, sr2 = load_csv_waveform(path)
            if compose and self.current_event and self.current_event.waveform_data:
                # Composition mode
                wf = self.current_event.waveform_data
                y1 = np.array([p["amplitude"] for p in wf.amplitude], dtype=float)
                sr1 = float(wf.sample_rate)
                y2r = resample_to(y2, sr2, sr1)
                n = min(y1.size, y2r.size)
                if n == 0: 
                    return
                y1[:n] *= y2r[:n]
                t1 = np.arange(y1.size) / sr1
                wf.amplitude = [{"time": float(tt), "amplitude": float(yy)} for tt, yy in zip(t1, y1)]
                wf.duration = float(y1.size / sr1)
                self.update_ui()
                self.log_info_message("Composed CSV waveform (multiply)")
            else:
                # New waveform
                dur = float(t2[-1] - t2[0]) if t2.size > 1 else (y2.size / sr2)
                amp_pts = [{"time": float(tt), "amplitude": float(yy)} for tt, yy in zip(t2, y2)]
                freq_pts = [{"time": 0.0, "frequency": 0.0}, {"time": float(dur), "frequency": 0.0}]
                evt = HapticEvent(name=os.path.splitext(os.path.basename(path))[0])
                evt.waveform_data = WaveformData(
                    amplitude=amp_pts, frequency=freq_pts, duration=float(dur), sample_rate=float(sr2)
                )
                self.current_event = evt
                self.current_file_path = None
                self.update_ui()
                self.log_info_message(f"Loaded CSV: {os.path.basename(path)}")
                self.device_targets = [0]
                QTimer.singleShot(0, lambda: self.play_waveform_on_device(self.current_event))
        else:
            # Load haptic event file
            evt = HapticEvent.load_from_file(path)
            self.current_event = evt
            self.current_file_path = path
            self.update_ui()
            self.log_info_message(f"Loaded: {os.path.basename(path)}")

    # Device management
    def toggle_logs_visibility(self):
        """Toggle the visibility of the logs section."""
        self.logs_visible = not self.logs_visible
        self.logs_group.setVisible(self.logs_visible)
        self.toggle_logs_action.setText("Hide Logs" if self.logs_visible else "Show Logs")
        self.update()

    def clear_log(self):
        """Clear the log text."""
        self.info_text.clear()

    def scan_devices(self):
        """Scan for available serial devices and populate the Port submenu."""
        try:
            devices = list(self.serial_api.get_serial_devices())
        except Exception as e:
            devices = []
            self.log_info_message(f"Error scanning devices: {e}")

        # rebuild the submenu
        self._dev_ports_menu.clear()
        self._dev_ports_actions.clear()
        for p in devices:
            act = QAction(p, self, checkable=True)
            self._dev_ports_menu.addAction(act)
            self._dev_ports_group.addAction(act)
            self._dev_ports_actions[p] = act

        if devices:
            sel = self.selected_port if self.selected_port in devices else devices[0]
            self._select_port(sel)
        else:
            self.selected_port = None

        self.log_info_message(f"Found {len(devices)} device(s)")


    def toggle_connection(self):
        """Connect/Disconnect using the selected port from the Device menu."""
        if self.serial_api.connected:
            ok = self.serial_api.disconnect_serial_device()
            if ok:
                self.connect_action.setText("Connect")
                self.log_info_message("Disconnected from device")
            else:
                self.log_info_message("Failed to disconnect")
            return

        if not self.selected_port:
            QMessageBox.information(self, "Device", "Select a port first (Device → Port).")
            return

        try:
            ok = bool(self.serial_api.connect_serial_device(self.selected_port))
        except Exception as e:
            ok = False
            self.log_info_message(f"Connect error: {e}")

        if ok:
            self.connect_action.setText("Disconnect")
            self.log_info_message(f"Connected on {self.selected_port}")
        else:
            self.log_info_message("Failed to connect to device")


    def log_info_message(self, message: str):
        """Log an informational message."""
        ts = time.strftime("%H:%M:%S")
        self.info_text.append(f"<span style='color:#A0AEC0;'>[{ts}]</span> {message}")
        self.info_text.verticalScrollBar().setValue(self.info_text.verticalScrollBar().maximum())

    # Meta Haptics Studio integration
    def create_with_meta_studio(self):
        """Launch Meta Haptics Studio and watch for exported files."""
        watch_dir = QFileDialog.getExistingDirectory(
            self, "Choose the folder where you will export your .haptic file"
        )
        if not watch_dir: 
            return
        
        if self.export_watch_dir: 
            self.dir_watcher.removePath(self.export_watch_dir)
        
        self.export_watch_dir = watch_dir
        self.export_start_mtime = time.time()
        self.dir_watcher.addPath(watch_dir)
        
        # Try to launch Meta Haptics Studio
        try:
            if sys.platform.startswith("darwin"): 
                os.system("open -a 'Meta Haptics Studio'")
            elif sys.platform.startswith("win"): 
                os.startfile(r"C:\Program Files\Meta Haptic Studio\MetaHapticStudio.exe")  # type: ignore
            else: 
                os.system("/opt/meta-haptic-studio/MetaHapticStudio &")
        except Exception: 
            pass
        
        self.log_info_message(f"Meta Haptics Studio launched – waiting for .haptic in \"{watch_dir}\"…")

    def _dir_changed(self, path: str):
        """Handle directory change events from file watcher."""
        if path != self.export_watch_dir: 
            return
        
        candidates = [os.path.join(path, f) for f in os.listdir(path) if f.lower().endswith(".haptic")]
        if not candidates: 
            return
        
        latest = max(candidates, key=os.path.getmtime)
        if os.path.getmtime(latest) < self.export_start_mtime: 
            return
        
        self.dir_watcher.removePath(path)
        self.export_watch_dir = None
        
        if self.current_event and self.current_event.load_from_haptic_file(latest):
            self.update_ui()
            self.file_info_label.setText(f"Loaded: {os.path.basename(latest)}")
            self.log_info_message(f"File imported: {os.path.basename(latest)}")
        else:
            QMessageBox.critical(self, "Error", f"Could not import \"{os.path.basename(latest)}\".")

    # File operations
    def new_event(self):
        """Create a new haptic event."""
        self.current_event = HapticEvent()
        self.current_file_path = None
        self.update_ui()
        self.log_info_message("New waveform created")

    def save_event(self):
        """Save the current event."""
        if self.current_event is None: 
            return
        
        if self.current_file_path:
            if self.current_event.save_to_file(self.current_file_path):
                self.log_info_message(f"Saved: {os.path.basename(self.current_file_path)}")
                if hasattr(self, "library_widget"):
                    if hasattr(self.library_widget, "refresh"): 
                        self.library_widget.refresh()
            else: 
                QMessageBox.critical(self, "Error", "Save failed")
        else:
            self.save_event_as()

    def save_event_as(self):
        """Save the current event with a new filename."""
        if self.current_event is None: 
            return
        
        lib_dir = self.event_manager.get_events_directory("customized")
        suggested = (self.current_event.metadata.name or "untitled").replace(" ", "_")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Waveform As",
            os.path.join(lib_dir, f"{suggested}.json"),
            "Waveform Files (*.json);;All Files (*)"
        )
        if not path: 
            return
        
        if self.current_event.save_to_file(path):
            self.current_file_path = path
            self.log_info_message(f"Saved: {os.path.basename(path)}")
            
            # Copy to library if not already there
            custom_dir = os.path.abspath(lib_dir)
            if os.path.dirname(os.path.abspath(path)) != custom_dir:
                dst = os.path.join(custom_dir, os.path.basename(path))
                try: 
                    shutil.copy2(path, dst)
                    self.log_info_message(f"Copied to library/customized: {os.path.basename(dst)}")
                except Exception as e: 
                    self.log_info_message(f"Failed to copy into library/customized: {e}")
            
            if hasattr(self, "library_widget"):
                if hasattr(self.library_widget, "refresh"): 
                    self.library_widget.refresh()
        else:
            QMessageBox.critical(self, "Error", "Save failed")

    def import_haptic_file(self):
        """Import a .haptic file."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Import .haptic file", "", "Haptic Files (*.haptic);;All Files (*)"
        )
        if not path: 
            return
        
        if self.current_event and self.current_event.load_from_haptic_file(path):
            self.update_ui()
            self.file_info_label.setText(f"Loaded: {os.path.basename(path)}")
            self.log_info_message(f"File imported: {os.path.basename(path)}")
        else:
            QMessageBox.critical(self, "Error", f"Could not import \"{os.path.basename(path)}\".")

    def import_csv_waveform(self):
        """Import a CSV waveform."""
        if self.current_event is None: 
            self.current_event = HapticEvent()
        
        path, _ = QFileDialog.getOpenFileName(self, "Import CSV waveform", "", "CSV (*.csv)")
        if not path: 
            return
        
        try:
            t, y, sr = load_csv_waveform(path)
            dur = float(t[-1]) if t.size else (len(y) / sr if sr > 0 else 0.0)
            amp = [{"time": float(tt), "amplitude": float(yy)} for tt, yy in zip(t, y)]
            freq = (self.current_event.waveform_data.frequency
                    if self.current_event.waveform_data and self.current_event.waveform_data.frequency
                    else [{"time": 0.0, "frequency": 0.0}, {"time": dur, "frequency": 0.0}])
            self.current_event.waveform_data = WaveformData(amp, freq, dur, sr)
            tags = self.current_event.metadata.tags or []
            if "imported-csv" not in tags: 
                self.current_event.metadata.tags = tags + ["imported-csv"]
            self.update_ui()
            self.log_info_message(f"CSV imported: {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "Import failed", str(e))

    def generate_from_math(self):
        """Generate waveform from mathematical equation."""
        if not self.current_event: 
            return
        
        try:
            f = float(self.math_freq.value())
            dur = float(self.math_dur.value())
            sr = float(self.math_sr.value())
            
            # Clamp values
            f = max(0.01, min(f, 5000.0))
            dur = max(0.05, min(dur, 30.0))
            sr = max(200.0, min(sr, 50000.0))
            
            n = int(round(sr * dur))
            t = np.arange(n, dtype=float) / sr
            expr = self.math_equation.text().strip()
            
            if not expr: 
                raise ValueError("Equation is empty.")
            
            y = safe_eval_equation(expr, {"t": t, "f": f, "A": 1.0, "phi": 0.0})
            y = normalize_signal(y)
            
            if not np.isfinite(y).all(): 
                raise ValueError("Signal contains NaN/Inf.")
            
            amp = [{"time": float(tt), "amplitude": float(yy)} for tt, yy in zip(t, y)]
            freq = [{"time": 0.0, "frequency": f}, {"time": dur, "frequency": f}]
            self.current_event.waveform_data = WaveformData(amp, freq, dur, sr)
            
            tags = getattr(self.current_event.metadata, "tags", None) or []
            if "generated" not in tags: 
                tags.append("generated")
            self.current_event.metadata.tags = tags
            
            self.update_ui()
            self.log_info_message("Waveform generated from equation")
        except Exception as e:
            self.log_info_message(f"Equation error: {e}")

    def update_ui(self):
        """Update the UI to reflect the current event."""
        if not self.current_event:
            self.setWindowTitle("Universal Haptic Waveform Designer")
            return

        # Block signals while updating
        if hasattr(self, "name_edit"):
            self.name_edit.blockSignals(True)
        if hasattr(self, "description_edit"):
            self.description_edit.blockSignals(True)
        if hasattr(self, "category_combo"):
            self.category_combo.blockSignals(True)

        # Update name
        if hasattr(self, "name_edit"):
            self.name_edit.setText(self.current_event.metadata.name)

        # Update category
        cat_text = self.current_event.metadata.category.value
        tags = self.current_event.metadata.tags or []
        for t in tags:
            if t.startswith("category_name="):
                cat_text = t.split("=", 1)[1]
                break

        base_list = getattr(self, "_base_categories", None)
        if base_list is None:
            base_list = [c.value for c in EventCategory]
            self._base_categories = base_list

        if hasattr(self, "category_combo"):
            idx = self.category_combo.findText(cat_text)
            if cat_text in base_list and idx >= 0:
                self.category_combo.setCurrentIndex(idx)
            else:
                self.category_combo.setEditText(cat_text)

        # Update description
        if hasattr(self, "description_edit"):
            self.description_edit.setPlainText(self.current_event.metadata.description)

        # Unblock signals
        if hasattr(self, "name_edit"):
            self.name_edit.blockSignals(False)
        if hasattr(self, "description_edit"):
            self.description_edit.blockSignals(False)
        if hasattr(self, "category_combo"):
            self.category_combo.blockSignals(False)

        # Update editor
        if hasattr(self, "drop_proxy") and hasattr(self.drop_proxy, "set_event"):
            self.drop_proxy.set_event(self.current_event)

        # Update file label
        if hasattr(self, "file_info_label"):
            if self.current_event.original_haptic_file:
                self.file_info_label.setText(
                    f"Loaded: {os.path.basename(self.current_event.original_haptic_file)}"
                )
            else:
                self.file_info_label.setText("No file loaded")

        # Update window title
        title = self.current_event.metadata.name or "Untitled"
        self.setWindowTitle(f"Universal Haptic Waveform Designer – {title}")

    def closeEvent(self, e):
        try:
            if getattr(self, "_play_thread", None) and self._play_thread.isRunning():
                self._play_thread.stop()
                self._play_thread.wait(1200)
        except Exception:
            pass
        super().closeEvent(e)


def main():
    """Main application entry point."""
    app = QApplication(sys.argv)
    apply_ultra_clean_theme(app)
    load_ultra_clean_qss(app)
    
    app.setApplicationName("Universal Haptic Waveform Designer")
    app.setApplicationVersion("2.3")
    app.setOrganizationName("Haptic Systems")
    
    window = UniversalEventDesigner()
    window.show()
    window.log_info_message("Application ready - Ultra Clean Interface")
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()