import sys
import os
import time
from datetime import datetime

# Configuration du PYTHONPATH pour les imports externes
current_dir = os.path.dirname(os.path.abspath(__file__))  # gui/
pattern_generator = os.path.dirname(current_dir)          # pattern_generator/
main_gui = os.path.dirname(pattern_generator)             # Main_GUI/
if main_gui not in sys.path:
    sys.path.insert(0, main_gui)

from PyQt6.QtCore import (
    Qt, QTimer, QProcess, QProcessEnvironment, QSize
)
from PyQt6.QtGui import (
    QAction, QActionGroup, QKeySequence, QShortcut,
    QPalette, QColor, QTextCursor
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout,
    QTabWidget, QScrollArea, QFrame,
    QGroupBox, QLabel, QPushButton, QComboBox, QSlider,
    QSpinBox, QDoubleSpinBox, QTextEdit, QLineEdit,
    QMessageBox, QStyleFactory, QStatusBar,
    QSizePolicy, QMenu, QDialog, QDialogButtonBox
)


try:
    # Relative imports for when used as module
    from ..core.constants import PATTERN_PARAMETERS, PREMADE_PATTERNS
    from ..utils.managers import (WaveformLibraryManager, EventLibraryManager, 
                                PatternLibraryManager, DrawingLibraryManager)
    from ..widgets.actuator_widgets import MultiCanvasSelector
    from ..widgets.timeline_widgets import TimelinePanel
    from ..widgets.drawing_widgets import DrawingStudioTab
    from ..widgets.pattern_widgets import UnifiedPatternLibraryWidget
    from ..utils.preview_drivers import PatternPreviewDriver
    from ..utils.workers import PatternWorker, StrokePlaybackWorker
    from ..dialogs.dialogs import SavePatternDialog
    from ..utils.utils import centralize_drawn_stroke_playback_in_drawing
except ImportError:
    # Absolute imports for when executed directly
    from core.constants import PATTERN_PARAMETERS, PREMADE_PATTERNS
    from utils.managers import (WaveformLibraryManager, EventLibraryManager, 
                               PatternLibraryManager, DrawingLibraryManager)
    from widgets.actuator_widgets import MultiCanvasSelector
    from widgets.timeline_widgets import TimelinePanel
    from widgets.drawing_widgets import DrawingStudioTab
    from widgets.pattern_widgets import UnifiedPatternLibraryWidget
    from utils.preview_drivers import PatternPreviewDriver
    from utils.workers import PatternWorker, StrokePlaybackWorker
    from dialogs.dialogs import SavePatternDialog
    from utils.utils import centralize_drawn_stroke_playback_in_drawing

# Imports externes
try:
    from core import PhantomEngine, PreviewBundle
    from core.storage import save_bundle, load_bundle, list_bundles
    from communication import python_serial_api
    from core.vibration_patterns import *
    from gui.widgets.flexible_actuator_selector import FlexibleActuatorSelector
    from gui.widgets.phantom_preview_canvas import PhantomPreviewCanvas
except ImportError as e:
    print(f"Warning: Some external modules not found: {e}")


class HapticPatternGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # Initialize API and patterns
        self.api = python_serial_api()
        self.current_pattern = None
        self.pattern_worker = None
        self.is_running = False
        self._last_loaded_acts = []
        
        # Initialize library managers
        self.pattern_manager = PatternLibraryManager()
        self.event_manager = EventLibraryManager()
        self.wf_manager = WaveformLibraryManager()
        
        # Current waveform tracking
        self.current_waveform_source = "Built-in Oscillators"
        self.current_waveform_name = "Sine"
        self.current_event = None

        # --- [PHANTOMS] state holders ---
        self.phantom_engine: Optional[PhantomEngine] = None
        self.preview_bundle: Optional[PreviewBundle] = None
        self.preview_timer = QTimer(self)
        self.preview_timer.setInterval(25)  # used only for device playback timing if needed
        self._device_queue = []  # (at, actuator_id, intensity, duration_ms)
        self._device_start_ms = None
        # Available patterns
        self.patterns = {
            "Single Pulse": SinglePulsePattern(),
            "Wave": WavePattern(),
            "Pulse Train": PulseTrainPattern(),
            "Fade": FadePattern(),
            "Circular": CircularPattern(),
            "Random": RandomPattern(),
            "Sine Wave": SineWavePattern()
        }
        
        # Set API for all patterns
        for pattern in self.patterns.values():
            if hasattr(pattern, "set_api"):
                pattern.set_api(self.api)
        
        self._create_ui()
        self._name_widgets_for_qss()
        self.setup_connection_menu()     # build the Connection menu
        self.setup_waveform_menu()
        self._scan_ports_menu()          # preload menu with ports
        if hasattr(self, "connectionGroup"):
            self.connectionGroup.hide()  # keep widgets for signals, but hide the top bar
        self._connect_signals()
        self.scan_ports()
        self.preview_driver = PatternPreviewDriver(self.canvas_selector, self)
        self._stroke_worker = None
        self._stroke_preview_timer = QTimer(self)
        self._stroke_preview_timer.setInterval(30)  # ~33 FPS
        self._stroke_preview_timer.timeout.connect(self._on_stroke_preview_tick)
        self._stroke_preview_state = None  # dict with schedule, t0, id_to_xy, idx
        self._stroke_playing = False
    
    def _clear_canvas_selection(self):
        """Remove any blue selection ring in the Designer canvas."""
        try:
            cs = getattr(self, "canvas_selector", None)
            if not cs:
                return
            # Prefer dedicated API if present
            if hasattr(cs, "clear_selection"):
                cs.clear_selection()
            elif hasattr(cs, "set_selected_actuators"):
                cs.set_selected_actuators([])
            elif hasattr(cs, "select_actuators"):
                cs.select_actuators([])
        except Exception:
            pass
    
    def _preview_drawn_stroke(self):
        """Construit le même schedule que pour le hardware, mais l'anime en UI uniquement."""
        if self._stroke_preview_timer.isActive():
            self._stroke_preview_timer.stop()
            self.canvas_selector.clear_preview()
            try:
                ov = getattr(self.drawing_tab, "_overlay", None)
                if ov and hasattr(ov, "clear_preview_marker"):
                    ov.clear_preview_marker()
            except Exception:
                pass
            self._log_info("Drawing preview: stopped")
            return

        data = self._get_overlay_json()
        if not data:
            QMessageBox.information(self, "Drawing", "No drawing found. Use the Drawing Studio overlay.")
            return
        poly = self._extract_last_polyline(data)
        if len(poly) < 2:
            QMessageBox.information(self, "Drawing", "Need at least 2 points. Draw a stroke on the overlay.")
            return
        id_to_xy = self._get_actuator_positions_for_overlay(data)
        if not id_to_xy:
            QMessageBox.warning(self, "Nodes", "No actuator anchors available. Use 3×3 Grid or Back Layout.")
            return

        mode = self.strokeModeCombo.currentText()
        step_ms = int(self.strokeStepMs.value())
        Av = int(max(1, min(15, self.intensitySlider.value())))
        total_time_s = float(self.durationSpinBox.value())
        schedule = self._build_stroke_schedule(poly, id_to_xy, step_ms, total_time_s, mode, Av)
        if not schedule:
            QMessageBox.information(self, "Preview", "Failed to build a schedule from the drawing.")
            return

        # Hide any lingering selection ring during preview
        self._clear_canvas_selection()

        self._stroke_preview_state = {
            "schedule": schedule,
            "t0": time.perf_counter(),
            "id_to_xy": id_to_xy,
            "idx": -1
        }
        ov = getattr(self.drawing_tab, "_overlay", None)
        if ov:
            ov.setVisible(True)
            ov.raise_()
        self._stroke_preview_timer.start()
        self._log_info(f"Drawing preview: {len(schedule)} steps")
    
    def load_premade_template(self, preset: dict):
        """
        Apply a premade pattern to the Waveform Lab so the existing
        Control section (Preview/Start/Stop/Emergency) can be used.
        """
        try:
            cfg = dict(preset.get("config", {}))

            # 1) Go to Waveform Lab (tab index 0 in this app)
            QTimer.singleShot(0, lambda: self.tab_widget.setCurrentIndex(0))

            # 2) Pattern type first → rebuild specific params UI
            pt = cfg.get("pattern_type", "Single Pulse")
            self.patternComboBox.setCurrentText(pt)
            QApplication.processEvents()
            self._create_pattern_specific_params()

            # 3) Global parameters (these drive both Preview & device playback)
            self.intensitySlider.setValue(int(cfg.get("intensity", self.intensitySlider.value())))
            # Device frequency code lives in Global Parameters in this app
            try:
                self.strokeFreqCode.setValue(int(cfg.get("frequency", self.strokeFreqCode.value())))
            except Exception:
                pass  # in case strokeFreqCode isn't available in your build

            # 4) Waveform suggestion (optional). If the waveform isn't present,
            #    we keep the current selection and just log a note.
            wf = cfg.get("waveform", {})
            if isinstance(wf, dict) and wf.get("name"):
                before = self.waveformComboBox.currentText()
                self._apply_loaded_waveform(wf)
                after = self.waveformComboBox.currentText()
                if before == after and (before or after):
                    self._log_info(f"Premade '{preset['name']}': waveform '{wf.get('name')}' not found, keeping '{after}'")

            # 5) Pattern-specific fields
            sp = cfg.get("specific_parameters", {})
            for key, widget in getattr(self, "pattern_specific_widgets", {}).items():
                if key in sp:
                    try:
                        widget.setValue(sp[key])
                    except Exception:
                        pass

            # 6) Actuators → the MultiCanvasSelector helper auto-creates chains if needed
            acts = list(cfg.get("actuators", []))
            if acts and hasattr(self, "canvas_selector"):
                self.canvas_selector.load_actuator_configuration(acts)
            
                # Remember + auto-select the loaded actuators so Start works immediately
            self._last_loaded_acts = list(acts)
            try:
                if hasattr(self.canvas_selector, "select_actuators"):
                    self.canvas_selector.select_actuators(acts)
                elif hasattr(self.canvas_selector, "set_selected_actuators"):
                    self.canvas_selector.set_selected_actuators(acts)
                else:
                    # best-effort fallback API
                    if hasattr(self.canvas_selector, "clear_selection"):
                        self.canvas_selector.clear_selection()
                    for aid in acts:
                        try:
                            self.canvas_selector.set_selected(aid, True)
                        except Exception:
                            pass
            except Exception:
                pass


            self._log_info(f"Premade pattern loaded: {preset.get('name', 'Unnamed')}")
            QMessageBox.information(self, "Premade Pattern",
                                    f"Loaded '{preset.get('name','Preset')}'.\n"
                                    f"Use Preview/Start in the Waveform Lab → Control section.")
        except Exception as e:
            self._log_info(f"Error applying premade: {e}")
            QMessageBox.critical(self, "Error", f"Failed to apply premade pattern:\n{e}")
    
    def _create_global_parameters_section(self, layout: QVBoxLayout):
        """
        Global Parameters shared by both Timeline playback and Drawn-stroke phantoms:
        - Intensity (gain)        → self.intensitySlider (+ self.intensityValueLabel)
        - Device freq code (0..7) → self.strokeFreqCode (QSlider) + self.freqCodeValueLabel
        """
        group = QGroupBox("Global Parameters")
        form = QFormLayout(group)
        form.setContentsMargins(8, 6, 8, 6)
        form.setSpacing(6)

        # ── Intensity (gain) [0..15]
        self.intensitySlider = QSlider(Qt.Orientation.Horizontal)
        self.intensitySlider.setRange(0, 15)
        self.intensitySlider.setValue(7)

        self.intensityValueLabel = QLabel(str(self.intensitySlider.value()))
        intensityWrap = QWidget()
        iw = QHBoxLayout(intensityWrap)
        iw.setContentsMargins(0, 0, 0, 0)
        iw.addWidget(self.intensitySlider)
        iw.addWidget(self.intensityValueLabel)
        form.addRow("Intensity (gain):", intensityWrap)

        # ── Device frequency code [0..7] — now a slider for consistency
        self.strokeFreqCode = QSlider(Qt.Orientation.Horizontal)
        self.strokeFreqCode.setRange(0, 7)
        self.strokeFreqCode.setSingleStep(1)
        self.strokeFreqCode.setPageStep(1)
        self.strokeFreqCode.setValue(4)
        self.strokeFreqCode.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.strokeFreqCode.setTickInterval(1)
        self.strokeFreqCode.setToolTip(
            "Hardware 'device frequency' index (0..7). Used by Timeline playback and drawn-stroke phantoms."
        )

        self.freqCodeValueLabel = QLabel(str(self.strokeFreqCode.value()))
        self.strokeFreqCode.valueChanged.connect(
            lambda v: self.freqCodeValueLabel.setText(str(v))
        )

        freqWrap = QWidget()
        fw = QHBoxLayout(freqWrap)
        fw.setContentsMargins(0, 0, 0, 0)
        fw.addWidget(self.strokeFreqCode)
        fw.addWidget(self.freqCodeValueLabel)
        form.addRow("Device freq code:", freqWrap)

        layout.addWidget(group)
    
    def _create_timeline_panel(self, parent_layout: QVBoxLayout):
        """Create the timeline panel as a full-width horizontal section."""
        self.timeline_panel = TimelinePanel(self)
        # Reduce minimum height and set fixed height for more compact timeline
        self.timeline_panel.setMinimumHeight(200)
        self.timeline_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)  # Change to Fixed
        
        if hasattr(self, 'canvas_selector'):
            self.timeline_panel.attach_canvas_selector(self.canvas_selector)
        
        parent_layout.addWidget(self.timeline_panel)

    def _on_stroke_preview_tick(self):
        st = self._stroke_preview_state
        if not st:
            self._stroke_preview_timer.stop(); return
        elapsed_ms = (time.perf_counter() - st["t0"]) * 1000.0
        # avancer tant que des steps sont dus
        advanced = False
        while st["idx"] + 1 < len(st["schedule"]) and st["schedule"][st["idx"] + 1]["t_on"] <= elapsed_ms:
            st["idx"] += 1
            advanced = True
        if not advanced:
            return
        # afficher l'état courant
        step = st["schedule"][st["idx"]]
        active_ids = [aid for (aid, _inten) in step["bursts"]]
        try:
            self.canvas_selector.set_preview_active(active_ids)
        except Exception:
            pass
        try:
            ov = getattr(self.drawing_tab, "_overlay", None)
            if ov and hasattr(ov, "show_preview_marker"):
                ov.show_preview_marker(step.get("pt", (0.5,0.5)), st["id_to_xy"], step["bursts"])
        except Exception:
            pass
        # arrêt si fini
        if st["idx"] >= len(st["schedule"]) - 1:
            self._stroke_preview_timer.stop()
            # Remove any highlight/marker at the end of the preview
            try:
                if self.canvas_selector:
                    self.canvas_selector.clear_preview()
            except Exception:
                pass
            try:
                ov = getattr(self.drawing_tab, "_overlay", None)
                if ov and hasattr(ov, "clear_preview_marker"):
                    ov.clear_preview_marker()
            except Exception:
                pass
            self._log_info("Drawing preview: done")
    
    def _get_overlay_json(self) -> dict | None:
        """Grab the current overlay JSON from the Drawing Studio tab."""
        try:
            ov = getattr(self.drawing_tab, "_overlay", None)
            if ov and hasattr(ov, "to_json"):
                return ov.to_json()
        except Exception as e:
            self._log_info(f"Overlay read error: {e}")
        return None


    def _extract_last_polyline(self, data: dict) -> list[tuple[float,float]]:
        """
        Return a list of normalized (x,y) in [0..1] from the most recent stroke.
        Fallback: concatenate all strokes.
        """
        strokes = data.get("strokes", [])
        if not strokes:
            return []
        # pick the last stroke with points
        for s in reversed(strokes):
            pts = s.get("points") or []
            if len(pts) >= 2:
                return [(float(x), float(y)) for (x,y) in pts]
        # fallback: concat everything
        pts_all = []
        for s in strokes:
            pts = s.get("points") or []
            pts_all.extend([(float(x), float(y)) for (x,y) in pts])
        return pts_all


    def _get_actuator_positions_for_overlay(self, overlay_json: dict) -> dict[int, tuple[float,float]]:
        """
        Build id->(x,y) normalized map. Prefer nodes stored with the drawing;
        else use current fixed canvas nodes.
        """
        # 1) nodes serialized by overlay (best)
        nodes = overlay_json.get("nodes") or []
        m = {}
        for n in nodes:
            try:
                m[int(n["id"])] = (float(n["x"]), float(n["y"]))
            except Exception:
                pass
        if m:
            return m

        # 2) current fixed canvas nodes
        try:
            cur = self.canvas_selector.current_nodes() or []
            for (aid, xn, yn) in cur:
                m[int(aid)] = (float(xn), float(yn))
        except Exception:
            pass
        return m


    def _build_stroke_schedule(self, poly_xy: list[tuple[float,float]], id_to_xy: dict[int,tuple[float,float]],
                            duration_ms: int, total_time_s: float, mode: str, Av: int) -> list[dict]:
        """
        Return a list of steps: [{t_on, dur_ms, bursts=[(addr,intensity), ...]}].
        SOA is computed from Eq.(1): SOA_ms = 0.32*duration + 47.3.
        No overlap guaranteed if duration ≤ 69 ms (Eq.(11)).
        """
        if len(poly_xy) < 2 or not id_to_xy:
            return []

        duration_ms = int(max(20, min(69, duration_ms)))
        soa_ms = 0.32 * duration_ms + 47.3  # Eq. (1), ms domain
        n_samples = max(2, int((total_time_s * 1000.0) / soa_ms))
        samples = StrokePlaybackWorker._resample_polyline(poly_xy, n_samples)

        schedule = []
        t = 0.0
        for p in samples:
            neigh   = StrokePlaybackWorker._nearest_n(p, id_to_xy, 3)
            if mode.startswith("Physical"):
                # nearest 1
                addr = neigh[0][0]
                bursts = [(addr, Av)]
            elif "2-Act" in mode:
                (a1,d1),(a2,d2) = neigh[:2]
                A1,A2   = StrokePlaybackWorker._phantom_intensities_2act(d1,d2,Av)
                bursts = [(a1,A1),(a2,A2)]
            else:
                (a1,d1),(a2,d2),(a3,d3) = neigh[:3]
                A1,A2,A3= StrokePlaybackWorker._phantom_intensities_3act(d1,d2,d3,Av)
                bursts = [(a1,A1),(a2,A2),(a3,A3)]

            schedule.append({
                "t_on": t,
                "dur_ms": duration_ms,
                "bursts": bursts,
                "pt": p
            })
            t += soa_ms

        return schedule


    def _play_drawn_stroke(self):
        """Entry point when user clicks 'Play Drawing'."""
        # DEBUG : Vérifications d'état
        self._log_info(f"DEBUG: _play_drawn_stroke called")
        self._log_info(f"DEBUG: is_running = {self.is_running}")
        self._log_info(f"DEBUG: _stroke_worker = {self._stroke_worker}")
        self._log_info(f"DEBUG: API connected = {self.api.connected if self.api else 'No API'}")
        if hasattr(self, '_stroke_playing'):
            self._log_info(f"DEBUG: _stroke_playing = {self._stroke_playing}")
        
        # Nettoyer l'état précédent si nécessaire
        if self._stroke_worker and self._stroke_worker.isRunning():
            self._log_info("Stopping previous stroke worker...")
            self._stop_drawn_stroke()
        
        # Vérifier les conditions de blocage
        if self.is_running or (self._stroke_worker and self._stroke_worker.isRunning()):
            QMessageBox.warning(self, "Busy", "A pattern is currently running. Stop it first.")
            return
            
        if not self.api or not self.api.connected:
            QMessageBox.warning(self, "Hardware", "Please connect to a device first.")
            return

        # Test simple de l'API avant de commencer
        try:
            # Test très bref sur un actuateur
            self.api.send_command(0, 1, 4, 1)  
            time.sleep(0.005)  # 5ms seulement
            self.api.send_command(0, 0, 0, 0)  
            self._log_info("DEBUG: API test command successful")
        except Exception as e:
            self._log_info(f"DEBUG: API test failed: {e}")
            QMessageBox.warning(self, "API Test", f"API communication test failed: {e}")
            return

        data = self._get_overlay_json()
        if not data:
            QMessageBox.information(self, "Drawing", "No drawing found. Use the Drawing Studio overlay.")
            return

        poly = self._extract_last_polyline(data)
        if len(poly) < 2:
            QMessageBox.information(self, "Drawing", "Need at least 2 points. Draw a stroke on the overlay.")
            return

        id_to_xy = self._get_actuator_positions_for_overlay(data)
        if not id_to_xy:
            QMessageBox.warning(self, "Nodes", "No actuator anchors available. Use 3×3 Grid or Back Layout.")
            return

        mode = self.strokeModeCombo.currentText()
        step_ms = int(self.strokeStepMs.value())
        Av = int(max(1, min(15, self.intensitySlider.value())))
        total_time_s = float(self.durationSpinBox.value())
        schedule = self._build_stroke_schedule(poly, id_to_xy, step_ms, total_time_s, mode, Av)
        if not schedule:
            QMessageBox.information(self, "Schedule", "Failed to build a schedule from the drawing.")
            return
        # remember which actuators this stroke will touch (for reliable STOP)
        self._last_stroke_actuators = {aid for step in schedule for (aid, _i) in step["bursts"]}
        self._log_info(f"DEBUG: last stroke will touch actuators: {sorted(self._last_stroke_actuators)}")

        # stop any preview and start worker
        # stop any preview and start worker
        try:
            self.preview_driver.stop()
        except Exception:
            pass

        # Marquer qu'on est en train de jouer un stroke
        self._clear_canvas_selection()
        self._stroke_playing = True
        
        self._log_info(f"Playing drawn stroke → mode='{mode}', steps={len(schedule)}, step={step_ms}ms, total≈{total_time_s:.2f}s")
        self._stroke_worker = StrokePlaybackWorker(self.api, schedule, self.strokeFreqCode.value())
        self._stroke_worker.log_message.connect(self._log_info)
        self._stroke_worker.finished.connect(self._on_stroke_finished)
        self._stroke_worker.step_started.connect(self._on_stroke_step_started)
        self._stroke_worker.start()
    
    def _test_single_actuator(self):
        """Test un seul actuateur pour vérifier que l'API fonctionne"""
        if not self.api or not self.api.connected:
            QMessageBox.warning(self, "Test", "Please connect first")
            return
            
        selected = self._get_selected_actuators()
        if not selected:
            QMessageBox.information(self, "Test", "Please select at least one actuator")
            return
            
        try:
            actuator_id = selected[0]
            intensity = self.intensitySlider.value()
            freq = self.strokeFreqCode.value() if hasattr(self, 'strokeFreqCode') else 4
            
            self._log_info(f"Testing actuator {actuator_id} with intensity {intensity}, freq {freq}")
            
            # Allumer
            self.api.send_command(actuator_id, intensity, freq, 1)
            time.sleep(0.5)  # 500ms
            # Éteindre
            self.api.send_command(actuator_id, 0, 0, 0)
            
            self._log_info("Single actuator test completed")
            
        except Exception as e:
            self._log_info(f"Single actuator test failed: {e}")
            QMessageBox.critical(self, "Test Failed", f"Error: {e}")
    
    def _all_off(self, addrs=None):
        """Turn OFF the provided actuators immediately; safe even if repeated."""
        try:
            if addrs is None:
                addrs = range(128)
            for a in addrs:
                try:
                    self.api.send_command(int(a), 0, 0, 0)
                except Exception:
                    pass
        except Exception as e:
            self._log_info(f"all_off error: {e}")

    def _stop_drawn_stroke(self):
        """Hard-stop drawn stroke and guarantee hardware OFF immediately."""
        self._stroke_playing = False

        # 1) Kill hardware first (even if the worker is still running)
        targets = sorted(self._last_stroke_actuators) if getattr(self, "_last_stroke_actuators", None) else list(range(32))
        self._log_info(f"DEBUG: HARD-OFF {targets}")
        self._all_off(targets)

        # 2) Ask the worker to stop, then wait; if it hangs, terminate.
        w = self._stroke_worker
        if w and w.isRunning():
            # polite stop if available
            for meth in ("requestInterruption", "stop"):
                try:
                    fn = getattr(w, meth, None)
                    if callable(fn):
                        fn()
                except Exception:
                    pass

            if not w.wait(700):  # short wait; HW is already OFF
                self._log_info("Warning: Stroke worker unresponsive → terminate()")
                try:
                    w.terminate()
                    w.wait(700)
                except Exception:
                    pass

            # delayed cleanup, like in _on_stroke_finished
            def _finalize():
                nonlocal w
                if w and w.isRunning():
                    QTimer.singleShot(50, _finalize)
                    return
                try:
                    if w:
                        w.deleteLater()
                except Exception:
                    pass
                self._stroke_worker = None
            QTimer.singleShot(0, _finalize)

        # 3) UI cleanup
        try:
            self._stroke_preview_timer.stop()
            if self.canvas_selector:
                self.canvas_selector.clear_preview()
                self._clear_canvas_selection()
            ov = getattr(self.drawing_tab, "_overlay", None)
            if ov and hasattr(ov, "clear_preview_marker"):
                ov.clear_preview_marker()
        except Exception:
            pass

        self._log_info("Drawn stroke: hard-stopped and cleaned")
    
    def _on_stroke_step_started(self, idx: int, bursts: list, pt: tuple):
        ov = getattr(self.drawing_tab, "_overlay", None)
        if ov:
            ov.setVisible(True)
            ov.raise_()
        active = [aid for (aid, _i) in bursts]
        try:
            self.canvas_selector.set_preview_active(active)
        except Exception:
            pass
        try:
            ov = getattr(self.drawing_tab, "_overlay", None)
            if ov and hasattr(ov, "show_preview_marker"):
                # id_to_xy vient du dernier build; si besoin, recalculer depuis overlay
                data = self._get_overlay_json() or {}
                id_to_xy = self._get_actuator_positions_for_overlay(data)
                ov.show_preview_marker(pt, id_to_xy, bursts)
        except Exception:
            pass


    def _on_stroke_finished(self, ok: bool, msg: str):
        """Callback quand le stroke worker termine — cleanup différé + OFF garanti."""
        self._stroke_playing = False

        # OFF garanti pour les actuateurs utilisés par ce stroke (pas seulement la sélection UI)
        targets = sorted(self._last_stroke_actuators) if getattr(self, "_last_stroke_actuators", None) else list(range(32))
        self._log_info(f"DEBUG: FINISH → OFF {targets}")
        self._all_off(targets)

        self._log_info(f"Drawn stroke finished → {msg}")
        try:
            if self.canvas_selector:
                self.canvas_selector.clear_preview()
                self._clear_canvas_selection()
        except Exception:
            pass

        # Finalisation différée de l'objet thread
        def _finalize_when_stopped():
            w = getattr(self, "_stroke_worker", None)
            if w is None:
                return
            if w.isRunning():
                QTimer.singleShot(50, _finalize_when_stopped)
                return
            try:
                w.deleteLater()
            except Exception:
                pass
            self._stroke_worker = None

        QTimer.singleShot(0, _finalize_when_stopped)

    def _name_widgets_for_qss(self):
        # buttons
        self.startButton.setObjectName("startButton")
        self.stopButton.setObjectName("stopButton")
        #self.saveButton.setObjectName("saveButton")
        # info boxes
        self.waveformInfoLabel.setObjectName("waveformInfoLabel")
        self.patternDescLabel.setObjectName("patternDescLabel")

    def setup_waveform_menu(self):
        mb = self.menuBar()
        self.menu_waveform = mb.addMenu("&Waveform")

        self.act_open_designer = QAction("Open Waveform Designer…", self)
        self.act_open_designer.triggered.connect(self._open_waveform_designer)
        self.menu_waveform.addAction(self.act_open_designer)

        self.menu_waveform.addSeparator()

        self.act_refresh_library = QAction("Refresh Library", self)
        self.act_refresh_library.setShortcut("Ctrl+Shift+R")
        self.act_refresh_library.triggered.connect(self.refresh_waveforms)
        self.menu_waveform.addAction(self.act_refresh_library)

    def _open_waveform_designer(self):
        here = os.path.dirname(os.path.abspath(__file__))       # gui/core/
        gui_dir = os.path.dirname(here)                         # gui/
        pattern_generator = os.path.dirname(gui_dir)            # pattern_generator/
        main_gui = os.path.dirname(pattern_generator)           # Main_GUI/

        # We will launch the designer as a MODULE so that relative imports work
        module_path = ["-m", "waveform_designer.event_designer.main"]

        # Prepare process
        self._designer_proc = QProcess(self)
        self._designer_proc.finished.connect(lambda *_: self.refresh_waveforms())

        # 1) Ensure the working directory is Main_GUI so resources/paths resolve
        self._designer_proc.setWorkingDirectory(main_gui)

        # 2) Ensure PYTHONPATH contains Main_GUI (so absolute imports work even from IDE)
        env = self._designer_proc.processEnvironment()
        if env is None:
            from PyQt6.QtCore import QProcessEnvironment
            env = QProcessEnvironment.systemEnvironment()
        existing = env.value("PYTHONPATH", "")
        if existing:
            env.insert("PYTHONPATH", f"{main_gui}{os.pathsep}{existing}")
        else:
            env.insert("PYTHONPATH", main_gui)
        self._designer_proc.setProcessEnvironment(env)

        # Optional: capture logs to your info panel
        try:
            self._designer_proc.readyReadStandardError.connect(
                lambda: self._log_info(self._designer_proc.readAllStandardError().data().decode(errors='ignore'))
            )
            self._designer_proc.readyReadStandardOutput.connect(
                lambda: self._log_info(self._designer_proc.readAllStandardOutput().data().decode(errors='ignore'))
            )
        except Exception:
            pass

        # Start using current Python interpreter and run as module
        self._designer_proc.start(sys.executable, module_path)
        if not self._designer_proc.waitForStarted(3000):
            QMessageBox.critical(self, "Waveform Designer", "Failed to start Universal Event Designer.")
            return

    def setup_connection_menu(self):
        """Build 'Connection' menu and move controls from the top bar into it."""
        self.is_connected = False
        self.selected_port = None
        self._ports_actions = {}
        self.ports_group = QActionGroup(self)
        self.ports_group.setExclusive(True)

        mb = self.menuBar()
        self.menu_connection = mb.addMenu("&Connection")

        # Scan
        self.act_scan = QAction("Scan Ports", self)
        self.act_scan.setShortcut("Ctrl+R")
        self.act_scan.triggered.connect(self._scan_ports_menu)
        self.menu_connection.addAction(self.act_scan)

        # Dynamic Ports submenu
        self.menu_ports = QMenu("Ports", self)
        self.menu_connection.addMenu(self.menu_ports)
        self._refresh_ports_menu([])

        self.menu_connection.addSeparator()

        # Connect / Disconnect
        self.act_connect = QAction("Connect", self)
        self.act_connect.setShortcut("Ctrl+Shift+C")
        self.act_connect.triggered.connect(self._do_connect)
        self.menu_connection.addAction(self.act_connect)

        self.act_disconnect = QAction("Disconnect", self)
        self.act_disconnect.setShortcut("Ctrl+Shift+D")
        self.act_disconnect.triggered.connect(self._do_disconnect)
        self.menu_connection.addAction(self.act_disconnect)

        # Initial state
        self._update_connection_actions()
        # Optional: show status in the status bar (bottom)
        if not self.statusBar():
            self.setStatusBar(QStatusBar(self))
        self.statusBar().showMessage("Status: Disconnected")

    def _scan_ports_menu(self):
        ports = self._scan_available_ports()
        self._refresh_ports_menu(ports)
        # keep legacy combo in sync (even if hidden)
        if hasattr(self, "portComboBox"):
            self.portComboBox.clear()
            self.portComboBox.addItems(ports)
        self.statusBar().showMessage(f"Found {len(ports)} port(s)")
        self._log_info(f"Found {len(ports)} port(s)" if ports else "No ports found")
    
    def setup_view_menu(self):
        mb = self.menuBar()
        self.menu_view = mb.addMenu("&View")

        # Checkable action to show/hide the bottom log
        self.act_show_log = QAction("Show Log", self, checkable=True)
        self.act_show_log.setShortcut("Ctrl+L")
        self.act_show_log.setChecked(True)
        self.act_show_log.toggled.connect(self._set_log_visible)
        self.menu_view.addAction(self.act_show_log)

    def _set_log_visible(self, visible: bool):
        if hasattr(self, "infoGroup"):
            self.infoGroup.setVisible(visible)
        if visible and hasattr(self, "infoTextEdit"):
            from PyQt6.QtGui import QTextCursor
            # Qt6: enums are namespaced
            self.infoTextEdit.moveCursor(QTextCursor.MoveOperation.End)
            self.infoTextEdit.ensureCursorVisible()

    def _refresh_ports_menu(self, ports: list[str]):
        self.menu_ports.clear()
        self._ports_actions.clear()
        for p in ports:
            act = QAction(p, self, checkable=True)
            self.ports_group.addAction(act)
            self.menu_ports.addAction(act)
            act.triggered.connect(lambda checked, port=p: self._select_port(port))
            self._ports_actions[p] = act

        # Keep previous selection if still available; else preselect first
        if ports:
            sel = self.selected_port if self.selected_port in ports else ports[0]
            self._ports_actions[sel].setChecked(True)
            self._select_port(sel)

    def _select_port(self, port: str):
        self.selected_port = port
        self.statusBar().showMessage(f"Port selected: {port}")

    def _do_connect(self):
        # fallback to legacy combo if no menu selection yet
        if not self.selected_port and hasattr(self, "portComboBox"):
            self._select_port(self.portComboBox.currentText() or None)
        if not self.selected_port:
            QMessageBox.information(self, "Connect", "Select a port first.")
            return
        try:
            ok = bool(self.api.connect_serial_device(self.selected_port))
            self.is_connected = ok
        except Exception as e:
            self.is_connected = False
            QMessageBox.warning(self, "Connect", str(e))
        self._update_connection_actions()
        self.statusBar().showMessage(
            f"Status: Connected ({self.selected_port})" if self.is_connected else "Status: Disconnected"
        )
        if hasattr(self, "statusLabel"):
            self.statusLabel.setText("Status: Connected" if self.is_connected else "Status: Disconnected")
        

    def _do_disconnect(self):
        try:
            self.api.disconnect_serial_device()
        except Exception as e:
            QMessageBox.warning(self, "Disconnect", str(e))
        self.is_connected = False
        self._update_connection_actions()
        self.statusBar().showMessage("Status: Disconnected")
        if hasattr(self, "statusLabel"):
            self.statusLabel.setText("Status: Disconnected")

    def _update_connection_actions(self):
        self.act_connect.setEnabled(not self.is_connected)
        self.act_disconnect.setEnabled(self.is_connected)
        self.menu_ports.setEnabled(not self.is_connected)
        self.act_scan.setEnabled(not self.is_connected)

    def _scan_available_ports(self) -> list[str]:
        """Use existing serial API to enumerate ports."""
        try:
            return list(self.api.get_serial_devices())
        except Exception:
            return []
    
    def _create_ui(self):
        """Create the complete UI programmatically"""
        self.setWindowTitle("Haptic Vibration Pattern Controller")
        
        # Rendre la fenêtre redimensionnable et commencer plus petit
        self.setGeometry(100, 100, 1200, 900)
        self.setMinimumSize(1000, 700)  # Taille minimum
        
        # Create central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setSpacing(6)  # Plus d'espace entre sections
        
        # Connection group
        self._create_connection_group(layout)
        
        # Main layout with two columns
        main_layout = QHBoxLayout()
        
        # Left column - Tabbed interface
        self._create_left_column(main_layout)
        
        # Right column - Actuator selection  
        self._create_right_column(main_layout)
        
        # AFTER
        layout.addLayout(main_layout)
        self._create_timeline_panel(layout)

        # No bottom "Information" panel anymore (frees ~80px)

        # Give timeline 1/3 of vertical space: workspace ≈ 66%, timeline ≈ 33%
        layout.setStretch(0, 0)  # connection bar
        layout.setStretch(1, 2)  # main workspace (left + right) - 2/3
        layout.setStretch(2, 1)  # timeline - 1/3

        self.showMaximized()
    
    def _create_connection_group(self, layout):
        """Legacy top bar (now hidden)."""
        self.connectionGroup = QGroupBox("Connection")
        connectionLayout = QHBoxLayout(self.connectionGroup)

        self.scanPortsButton = QPushButton("Scan Ports")
        self.portComboBox = QComboBox()
        self.connectButton = QPushButton("Connect")
        self.disconnectButton = QPushButton("Disconnect")
        self.statusLabel = QLabel("Status: Disconnected")

        connectionLayout.addWidget(self.scanPortsButton)
        connectionLayout.addWidget(self.portComboBox)
        connectionLayout.addWidget(self.connectButton)
        connectionLayout.addWidget(self.disconnectButton)
        connectionLayout.addStretch()
        connectionLayout.addWidget(self.statusLabel)

        layout.addWidget(self.connectionGroup)
    
    def _create_left_column(self, main_layout):
        """Create left column with tabbed interface"""
        leftColumn = QWidget()
        leftColumn.setMaximumWidth(520)
        leftColumnLayout = QVBoxLayout(leftColumn)
        
        # Create tab widget for Waveform Lab and Pattern Library
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #ccc;
            }
            QTabBar::tab {
                padding: 8px 16px;
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                border: 1px solid #ccc;
                background-color: #f5f5f5;
            }
            QTabBar::tab:selected {
                background-color: white;
                border-bottom: 1px solid white;
                font-weight: bold;
            }
            QTabBar::tab:hover {
                background-color: #eeeeee;
            }
        """)
        
        # Create Waveform Lab tab
        waveform_scroll = QScrollArea()
        waveform_scroll.setWidgetResizable(True)
        waveform_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        waveform_scroll.setFrameShape(QFrame.Shape.NoFrame)

        waveform_page = QWidget()
        waveform_page_layout = QVBoxLayout(waveform_page)
        waveform_page_layout.setContentsMargins(8, 8, 8, 8)
        waveform_page_layout.setSpacing(8)

        self._create_waveform_lab_content(waveform_page_layout)
        waveform_page_layout.addStretch()

        waveform_scroll.setWidget(waveform_page)
        
        # Create Pattern Library tab
        pattern_library_tab = QWidget()
        pattern_library_tab_layout = QVBoxLayout(pattern_library_tab)
        self._create_pattern_library_content(pattern_library_tab_layout)
        
        # Add tabs
        self.tab_widget.addTab(waveform_scroll, "Waveform Lab")
        self.tab_widget.addTab(pattern_library_tab, "Pattern Library")

        self.drawing_tab = DrawingStudioTab()
        self.tab_widget.addTab(self.drawing_tab, "Drawing Studio")

        if hasattr(self, "drawnStrokeGroup") and self.drawnStrokeGroup:
            gb = self.drawnStrokeGroup
            # detach from its old parent/layout
            old_parent = gb.parentWidget()
            if old_parent and old_parent.layout():
                old_parent.layout().removeWidget(gb)
            gb.setParent(self.drawing_tab)
            # append at the bottom of Drawing Studio content
            self.drawing_tab.layout().addWidget(gb)
        centralize_drawn_stroke_playback_in_drawing(self)
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        self.drawing_tab.bind_controls(self)
        
        leftColumnLayout.addWidget(self.tab_widget)
        main_layout.addWidget(leftColumn)


    def _on_tab_changed(self, idx: int):
        try:
            is_drawing = (idx == self.tab_widget.indexOf(self.drawing_tab))
            if hasattr(self.drawing_tab, "set_overlay_active"):
                self.drawing_tab.set_overlay_active(is_drawing)
        except Exception:
            pass

    def _create_headless_frequency_controls(self):
        """Create hidden frequency widgets so existing signal hookups don't break."""
        self.lblFrequency = QLabel("Frequency:")
        self.frequencySlider = QSlider(Qt.Orientation.Horizontal)
        self.frequencySlider.setRange(0, 7)
        self.frequencySlider.setValue(2)
        self.frequencyValueLabel = QLabel("2")
        # keep them hidden; patterns that use waveform data will ignore frequency
        self.lblFrequency.setVisible(False)
        self.frequencySlider.setVisible(False)
        self.frequencyValueLabel.setVisible(False)

    def _create_waveform_lab_content(self, layout):
        # Waveform Selection — keep
        self._create_waveform_selection_section(layout)

        # NEW: Global Parameters shared by Timeline & Phantoms
        self._create_global_parameters_section(layout)

        # These 3 sections exist but are hidden:
        self._create_pattern_selection_section(layout)
        self._create_basic_parameters_section(layout)
        self._create_specific_parameters_section(layout)

        # Drawn stroke, Save, Control — keep
        self._create_drawn_stroke_section(layout)
        #self._create_save_pattern_section(layout)
        self._create_control_section(layout)

        # <<< keep these hidden >>>
        if hasattr(self, "grpPatternSelection"):
            self.grpPatternSelection.setVisible(False)
        if hasattr(self, "grpBasicParameters"):
            self.grpBasicParameters.setVisible(False)
        if hasattr(self, "specificParamsGroup"):
            self.specificParamsGroup.setVisible(False)

        layout.addStretch()

    
    def _create_drawn_stroke_section(self, layout):
        group = QGroupBox("Drawn Stroke Playback")
        group.setObjectName("DrawnStrokePlaybackGroup")
        self.drawnStrokeGroup = group  
        v = QVBoxLayout(group)
        v.setContentsMargins(8, 6, 8, 6)
        v.setSpacing(6)

        # Row 1: renderer
        top = QHBoxLayout()
        top.addWidget(QLabel("Renderer:"))
        self.strokeModeCombo = QComboBox()
        self.strokeModeCombo.addItems([
            "Physical (nearest 1)",
            "Phantom (3-Act)"
        ])
        self.strokeModeCombo.setCurrentIndex(0)  # Commencer par Physical pour debug
        self.strokeModeCombo.setMaximumWidth(200)
        top.addWidget(self.strokeModeCombo)
        top.addStretch()
        v.addLayout(top)

        # Row 2: controls 
        controls_layout = QGridLayout()
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setHorizontalSpacing(8)
        controls_layout.setVerticalSpacing(6)

        self.durationSpinBox = QDoubleSpinBox()
        self.durationSpinBox.setRange(0.1, 600.0)
        self.durationSpinBox.setValue(1.0)  # Plus court pour debug
        self.durationSpinBox.setDecimals(2)
        self.durationSpinBox.setSuffix(" s")
        self.durationSpinBox.setMaximumWidth(100)
        self.durationSpinBox.setMinimumWidth(80)
            
        controls_layout.addWidget(QLabel("Total time (drawn stroke):"), 0, 0)
        controls_layout.addWidget(self.durationSpinBox, 0, 1)

        self.strokeStepMs = QSpinBox()
        self.strokeStepMs.setRange(20, 69)
        self.strokeStepMs.setValue(60)
        self.strokeStepMs.setSuffix(" ms")
        self.strokeStepMs.setMaximumWidth(100)
        self.strokeStepMs.setMinimumWidth(80)
            
        controls_layout.addWidget(QLabel("Step duration (≤69 ms):"), 1, 0)
        controls_layout.addWidget(self.strokeStepMs, 1, 1)

        controls_layout.setColumnStretch(2, 1)
        v.addLayout(controls_layout)

        # Buttons avec test
        btns = QHBoxLayout()
        #self.testActuatorBtn = QPushButton("Test Selected") (decomment if you want to test on a particular actuator)
        #self.testActuatorBtn.setStyleSheet("background-color: #FFA500; font-weight: bold;")
        #btns.addWidget(self.testActuatorBtn)
        
        self.previewDrawingBtn = QPushButton("Preview")
        btns.addWidget(self.previewDrawingBtn)
        self.playDrawingBtn = QPushButton("Play Drawing")
        self.stopDrawingBtn = QPushButton("Stop")
        btns.addWidget(self.playDrawingBtn)
        btns.addWidget(self.stopDrawingBtn)
        btns.addStretch()
        v.addLayout(btns)

        layout.addWidget(group)

    def _create_pattern_library_content(self, layout):
        """Single Pattern Library with two categories (Pre-made / Custom)."""
        self.pattern_visualization = UnifiedPatternLibraryWidget(self.pattern_manager, PREMADE_PATTERNS)
        # Wire like before (no behavior change)
        self.pattern_visualization.template_selected.connect(self.load_premade_template)
        self.pattern_visualization.pattern_selected.connect(self.load_pattern_from_library)
        self.pattern_visualization.pattern_deleted.connect(self.on_pattern_deleted)
        layout.addWidget(self.pattern_visualization)
    
    def _create_waveform_selection_section(self, layout):
        group = QGroupBox("Waveform Selection")
        v = QVBoxLayout(group); v.setSpacing(5); v.setContentsMargins(8, 5, 8, 5)

        # Top row: Refresh / New…
        row = QHBoxLayout(); row.setSpacing(6)
        title = QLabel("Waveform Library"); title.setStyleSheet("font-weight:600;")
        row.addWidget(title); row.addStretch()
        self.refreshWaveformsButton = QPushButton("Refresh"); self.refreshWaveformsButton.setMaximumWidth(70)
        row.addWidget(self.refreshWaveformsButton)
        self.newWaveformButton = QPushButton("New…"); self.newWaveformButton.setMaximumWidth(70)
        self.newWaveformButton.clicked.connect(self._open_waveform_designer)
        row.addWidget(self.newWaveformButton)
        v.addLayout(row)

        # Waveform picker
        pick = QHBoxLayout(); pick.setSpacing(6)
        pick.addWidget(QLabel("Waveform:"))
        self.waveformComboBox = QComboBox()
        pick.addWidget(self.waveformComboBox)
        v.addLayout(pick)

        # Info
        self.waveformInfoLabel = QLabel("Select a waveform from the library")
        self.waveformInfoLabel.setWordWrap(True)
        self.waveformInfoLabel.setStyleSheet(
            "padding:4px;border:1px solid #ddd;border-radius:3px;"
            "background:#f9f9f9;font-style:italic;font-size:10px;"
        )
        self.waveformInfoLabel.setMaximumHeight(40)
        v.addWidget(self.waveformInfoLabel)

        layout.addWidget(group)
    
    def _create_pattern_selection_section(self, layout):
        """Create pattern selection - COMPACT"""
        patternGroup = QGroupBox("Pattern Selection")
        self.grpPatternSelection = patternGroup
        patternLayout = QVBoxLayout(patternGroup)
        patternLayout.setSpacing(3)
        patternLayout.setContentsMargins(8, 5, 8, 5)
        
        self.patternComboBox = QComboBox()
        self.patternComboBox.addItems([
            "Single Pulse", "Wave", "Pulse Train", "Fade", 
            "Circular", "Random", "Sine Wave"
        ])
        patternLayout.addWidget(self.patternComboBox)
        
        self.patternDescLabel = QLabel("Single vibration pulse on selected actuators")
        self.patternDescLabel.setWordWrap(True)
        self.patternDescLabel.setStyleSheet("font-style: italic; padding: 2px; color: #666; font-size: 10px;")
        self.patternDescLabel.setMaximumHeight(25)  # Plus petit
        patternLayout.addWidget(self.patternDescLabel)
        
        layout.addWidget(patternGroup)
    
    def _create_basic_parameters_section(self, layout):
        """
        Minimal 'Basic Parameters' (kept hidden). We NO LONGER create intensity here.
        We keep Duration here for legacy patterns, and create headless frequency
        widgets to satisfy existing signal hookups without showing them.
        """
        group = QGroupBox("Basic Parameters")
        self.grpBasicParameters = group
        g = QGridLayout(group)
        g.setSpacing(4)
        g.setContentsMargins(8, 5, 8, 5)

        # Duration (legacy/placeholder; waveform-driven patterns may ignore it)
        g.addWidget(QLabel("Duration:"), 0, 0)
        self.durationSpinBox = QDoubleSpinBox()
        self.durationSpinBox.setRange(0.1, 600.0)
        self.durationSpinBox.setValue(2.0)
        self.durationSpinBox.setDecimals(2)
        self.durationSpinBox.setSuffix(" s")
        g.addWidget(self.durationSpinBox, 0, 1, 1, 2)

        layout.addWidget(group)

        # Create hidden 'legacy' frequency widgets so existing code paths stay safe.
        self._create_headless_frequency_controls()
    
    def _create_specific_parameters_section(self, layout):
        """Create the Pattern-Specific Parameters section (auto-size)."""
        self.specificParamsGroup = QGroupBox("Pattern-Specific Parameters")

        # Let the group grow/shrink as needed (no fixed max height)
        self.specificParamsGroup.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding
        )

        # Prepare an inner container layout once; we'll repopulate its contents later
        container = QVBoxLayout(self.specificParamsGroup)
        container.setContentsMargins(8, 6, 8, 6)
        container.setSpacing(6)

        # Keep handle to the container so we can clear & refill it
        self._specific_params_container = container
        self.pattern_specific_widgets = {}

        # First build based on the current pattern
        self._create_pattern_specific_params()

        layout.addWidget(self.specificParamsGroup)
    
    # def _create_save_pattern_section(self, layout):
    #     """Create save pattern section - COMPACT"""
    #     saveGroup = QGroupBox("Save Pattern")
    #     saveLayout = QVBoxLayout(saveGroup)
    #     saveLayout.setContentsMargins(8, 5, 8, 5)
        
    #     self.saveButton = QPushButton("Save Current Pattern")
    #     saveLayout.addWidget(self.saveButton)
        
    #     layout.addWidget(saveGroup)
    
    def _create_control_section(self, layout):
        """Create control section - COMPACT"""
        controlGroup = QGroupBox("Control")
        controlLayout = QVBoxLayout(controlGroup)
        controlLayout.setSpacing(5)
        controlLayout.setContentsMargins(8, 5, 8, 5)
        
        # Start/Stop buttons - ligne compacte
        buttonLayout = QHBoxLayout()
        buttonLayout.setSpacing(5)
        
        self.startButton = QPushButton("Start")
        self.stopButton = QPushButton("Pause")
        self.previewButton = QPushButton("Preview")
        self.previewButton.setCheckable(True)
        buttonLayout.addWidget(self.previewButton)
        
        buttonLayout.addWidget(self.startButton)
        buttonLayout.addWidget(self.stopButton)
        controlLayout.addLayout(buttonLayout)
        
        layout.addWidget(controlGroup)
    
    def _create_pattern_library_section(self, layout):
        """Create pattern library section"""
        # No group box here since it's already in a tab
        self.pattern_visualization = PatternVisualizationWidget(self.pattern_manager)
        self.pattern_visualization.pattern_selected.connect(self.load_pattern_from_library)
        self.pattern_visualization.pattern_deleted.connect(self.on_pattern_deleted)
        layout.addWidget(self.pattern_visualization)
    
    def _create_right_column(self, main_layout):
        """Create right column with actuator selection"""
        rightColumn = QWidget()
        rightColumnLayout = QVBoxLayout(rightColumn)
        rightColumnLayout.setContentsMargins(0, 0, 0, 0)
        rightColumnLayout.setSpacing(6)

        actuatorGroup = QGroupBox("Actuator Selection & Design")
        actuatorGroup.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        actuatorLayout = QVBoxLayout(actuatorGroup)
        actuatorLayout.setContentsMargins(6, 0, 6, 6)   # was default (bigger on some styles)
        actuatorLayout.setSpacing(6)

        self.canvas_selector = MultiCanvasSelector()
        self.canvas_selector.selection_changed.connect(self.on_actuator_selection_changed)
        self.canvas_selector.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        actuatorLayout.addWidget(self.canvas_selector, 1)

        try:
            if hasattr(self, "drawing_tab") and self.drawing_tab is not None:
                self.drawing_tab.attach_canvas_selector(self.canvas_selector)
        except Exception:
            pass

        rightColumnLayout.addWidget(actuatorGroup, 1)
        main_layout.addWidget(rightColumn, 1)
    
    def _create_info_section(self, layout):
        """Create info section - ALWAYS VISIBLE but compact"""
        self.infoGroup = QGroupBox("Information")        
        self.infoGroup.setFixedHeight(80)
        infoLayout = QVBoxLayout(self.infoGroup)
        infoLayout.setContentsMargins(5, 5, 5, 5)

        self.infoTextEdit = QTextEdit()
        self.infoTextEdit.setReadOnly(True)
        self.infoTextEdit.setStyleSheet(
            "QTextEdit { "
            "font-family: 'Consolas', 'Monaco', monospace; "
            "font-size: 10px; "
            "padding: 5px; "
            "border: 1px solid #999; "
            "background-color: #f8f8f8; "
            "line-height: 1.2; "
            "}"
        )
        infoLayout.addWidget(self.infoTextEdit)

        layout.addWidget(self.infoGroup)
    
    def _connect_signals(self):
        """Connect signals to slots"""
        # Connection buttons
        self.scanPortsButton.clicked.connect(self._scan_ports_menu)
        self.connectButton.clicked.connect(self._do_connect)
        self.disconnectButton.clicked.connect(self._do_disconnect)
        self.previewButton.toggled.connect(self._on_preview_toggled)
        self.previewDrawingBtn.clicked.connect(self._preview_drawn_stroke)

        
        # Waveform controls
        self.waveformComboBox.currentTextChanged.connect(self.on_waveform_changed)
        self.refreshWaveformsButton.clicked.connect(self.refresh_waveforms)
        
        # Pattern controls
        self.patternComboBox.currentTextChanged.connect(self._on_pattern_change)
        
        # Basic parameter sliders
        self.intensitySlider.valueChanged.connect(
            lambda v: self.intensityValueLabel.setText(str(v))
        )
        self.frequencySlider.valueChanged.connect(
            lambda v: self.frequencyValueLabel.setText(str(v))
        )
        
        # Control buttons
        self.startButton.clicked.connect(self.start_pattern)
        self.stopButton.clicked.connect(self.stop_pattern)
        #self.saveButton.clicked.connect(self.save_pattern)
        
        # Initialize waveform controls
        self.refresh_waveforms()
        self.update_waveform_info()

        self.playDrawingBtn.clicked.connect(self._play_drawn_stroke)
        self.stopDrawingBtn.clicked.connect(self._stop_drawn_stroke)
        if hasattr(self, 'testActuatorBtn'):
            self.testActuatorBtn.clicked.connect(self._test_single_actuator)
    
    def refresh_waveforms(self):
        self.waveformComboBox.clear()
        self._wf_entries = self.wf_manager.list_entries()
        self._wf_by_display = {e["display"]: e for e in self._wf_entries}
        if self._wf_entries:
            self.waveformComboBox.addItems([e["display"] for e in self._wf_entries])
            self._log_info(f"Waveform Library → {self.wf_manager.lib_root}/customized "
                        f"→ {len(self._wf_entries)} file(s)")
        else:
            self.waveformComboBox.addItem("No waveforms found")
            self._log_info(f"Waveform Library → {self.wf_manager.lib_root}/customized → 0 file")
        if self.waveformComboBox.count() > 0:
            self.update_waveform_info()
        
    def _on_preview_toggled(self, checked: bool):
        if checked:
            actuators = self._get_selected_actuators()
            if not actuators:
                QMessageBox.warning(self, "Preview", "Please select at least one actuator")
                self.previewButton.setChecked(False)
                return
            
            wf = self.current_event
            wf_duration = 0.0
            try:
                wf_duration = float(wf.waveform_data.duration or 0.0) if (wf and wf.waveform_data) else 0.0
            except Exception:
                wf_duration = 0.0

            params = {
                'actuators': actuators,
                'intensity': self.intensitySlider.value(),
                'frequency': self.frequencySlider.value(),  # ignored by waveform-driven patterns
                'duration': wf_duration if wf_duration > 0 else 2.0,  # fall back just in case
                'playback_rate': 1.0,
                'repeat': 1,
                'start_offset': 0.0,
            }

            for name, w in self.pattern_specific_widgets.items():
                params[name] = w.value()
            self.preview_driver.stop()
            self.preview_driver.start(self.patternComboBox.currentText(), params)
            self._log_info("Preview started (UI-only)")
            self.previewButton.setText("Stop Preview")
        else:
            self.preview_driver.stop()
            self._log_info("Preview stopped")
            self.previewButton.setText("Preview")
    
    def on_waveform_source_changed(self):
        self.current_waveform_source = self.waveformSourceComboBox.currentText()
        self.refresh_waveforms()
        self._log_info(f"Waveform source: {self.current_waveform_source}")

    def on_waveform_changed(self):
        self.current_waveform_name = self.waveformComboBox.currentText()
        self.update_waveform_info()
        self._log_info(f"Waveform: {self.current_waveform_name}")
        
    def update_waveform_info(self):
        name = self.waveformComboBox.currentText()
        if not self._wf_entries or name == "No waveforms found":
            self.waveformInfoLabel.setText("No waveforms available.")
            self.current_event = None
            return
        entry = self._wf_by_display.get(name)
        ev = self.wf_manager.load_event(entry) if entry else None
        self.current_event = ev
        if ev and ev.waveform_data:
            dur = ev.waveform_data.duration or 0.0
            sr  = ev.waveform_data.sample_rate or 0.0
            md  = ev.metadata.name if ev.metadata else entry["name"]
            self.waveformInfoLabel.setText(f"<b>{md}</b><br>Duration: {dur:.2f}s • Sample Rate: {sr:g}Hz")
            # (removed) offsetSpinBox.setMaximum(...)
        else:
            self.waveformInfoLabel.setText("Failed to load waveform.")
    
    def get_current_waveform_info(self):
        return {"source": "Waveform Library", "name": self.waveformComboBox.currentText(), "event": self.current_event}
    
    def _create_pattern_specific_params(self):
        """(Re)build the content of the Pattern-Specific Parameters panel."""
        # Clear previous widgets from the container
        container = getattr(self, "_specific_params_container", None)
        if container is None:
            return
        self._clear_layout(container)

        pattern_name = self.patternComboBox.currentText()
        self.pattern_specific_widgets = {}

        pattern_config = PATTERN_PARAMETERS.get(pattern_name, {})
        parameters = pattern_config.get("parameters", [])

        if not parameters:
            # Show a small hint instead of an empty box
            hint = QLabel("No additional parameters for this pattern.")
            hint.setStyleSheet("font-style: italic; color: #666;")
            container.addWidget(hint)
        else:
            form = QFormLayout()
            form.setContentsMargins(0, 0, 0, 0)
            form.setSpacing(8)

            for param in parameters:
                label = QLabel(param["label"])
                label.setToolTip(param.get("description", ""))

                if param["type"] == "float":
                    editor = QDoubleSpinBox()
                    editor.setRange(*param["range"])
                    editor.setSingleStep(param["step"])
                    editor.setValue(param["default"])
                    if param.get("suffix"):
                        editor.setSuffix(param["suffix"])
                else:  # "int"
                    editor = QSpinBox()
                    editor.setRange(*param["range"])
                    editor.setSingleStep(param["step"])
                    editor.setValue(param["default"])
                    if param.get("suffix"):
                        editor.setSuffix(param["suffix"])

                editor.setToolTip(param.get("description", ""))
                form.addRow(label, editor)
                self.pattern_specific_widgets[param["name"]] = editor

            container.addLayout(form)

        # Make sure geometry updates immediately
        self.specificParamsGroup.adjustSize()
        self.specificParamsGroup.updateGeometry()
    
    def _clear_layout(self, layout):
        """Clear all widgets from layout"""
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                widget = item.widget()
                widget.setParent(None)
                widget.deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())
    
    def _on_pattern_change(self):
        """Handle pattern selection change"""
        pattern_name = self.patternComboBox.currentText()
        if pattern_name in self.patterns:
            self.patternDescLabel.setText(self.patterns[pattern_name].description)
        self._create_pattern_specific_params()
    
    def scan_ports(self):
        """Scan for available serial ports"""
        try:
            ports = self.api.get_serial_devices()
            self.portComboBox.clear()
            self.portComboBox.addItems(ports)
            self._log_info(f"Found {len(ports)} ports" if ports else "No ports found")
        except Exception as e:
            self._log_info(f"Error scanning ports: {e}")
    
    def connect(self):
        """Connect to selected serial port"""
        port = self.portComboBox.currentText()
        if not port:
            QMessageBox.warning(self, "Error", "Please select a port")
            return
        
        try:
            success = self.api.connect_serial_device(port)
            status = "Connected" if success else "Connection Failed"
            self.statusLabel.setText(f"Status: {status}")
            self._log_info(f"{'Connected to' if success else 'Failed to connect to'} {port}")
        except Exception as e:
            self.statusLabel.setText("Status: Connection Error")
            self._log_info(f"Connection error: {e}")
    
    def disconnect(self):
        """Disconnect from serial port"""
        try:
            if self.api.disconnect_serial_device():
                self.statusLabel.setText("Status: Disconnected")
                self._log_info("Disconnected")
        except Exception as e:
            self._log_info(f"Disconnect error: {e}")
    
    def save_pattern(self):
        """Save current configuration into the pattern library"""
        actuators = self._get_selected_actuators()
        if not actuators:
            QMessageBox.warning(self, "Warning", "Please select at least one actuator before saving.")
            return

        waveform_info = self.get_current_waveform_info()

        current_config = {
            'pattern_type': self.patternComboBox.currentText(),
            'actuators': actuators,
            'intensity': self.intensitySlider.value(),
            'frequency': self.frequencySlider.value(),
            # no 'duration' — waveform is the source of truth
            'waveform': {
                'source': wf_info['source'],
                'name': wf_info['name']
            },
            'waveform_duration': wf_dur if wf_dur > 0 else None,
            'specific_parameters': {}
        }

        for param_name, widget in self.pattern_specific_widgets.items():
            current_config['specific_parameters'][param_name] = widget.value()

        dialog = SavePatternDialog(current_config, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            save_data = dialog.get_save_data()
            pattern_name = save_data['name']
            existing = self.pattern_manager.get_all_patterns()
            if pattern_name in existing:
                reply = QMessageBox.question(
                    self, "Overwrite Pattern",
                    f"Pattern '{pattern_name}' already exists in the library. Overwrite?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return

            if self.pattern_manager.save_pattern(pattern_name, save_data):
                self.pattern_visualization.refresh_patterns()
                self._log_info(f"Pattern '{pattern_name}' saved to pattern library")
                QMessageBox.information(self, "Success", f"Pattern '{pattern_name}' saved to pattern library!")
            else:
                QMessageBox.critical(self, "Error", "Failed to save pattern to library.")

    def _apply_loaded_waveform(self, waveform_info: dict | None):
        """Select a waveform from the library; robust if file naming differs."""
        if not waveform_info:
            return
        name = str(waveform_info.get("name", "")).strip()
        # We only have Waveform Library now.
        self.refresh_waveforms()  # repopulates self.waveformComboBox & self._wf_by_display

        # Try exact display text first
        idx = self.waveformComboBox.findText(name)
        # If saved name was a base name (without bucket suffix), try to match by base
        if idx < 0 and hasattr(self, "_wf_by_display"):
            base = name.split(" [", 1)[0]
            for display in self._wf_by_display.keys():
                if display.split(" [", 1)[0] == base:
                    idx = self.waveformComboBox.findText(display)
                    if idx >= 0:
                        break

        if idx >= 0:
            self.waveformComboBox.setCurrentIndex(idx)
            self.update_waveform_info()
        else:
            self._log_info(f"Waveform '{name}' not found in library.")


    def _set_rate_combo(self, rate_value: float):
        """Helper to restore playback rate on a QComboBox if you have one."""
        try:
            # try by userData first
            for i in range(self.rateCombo.count()):
                data = self.rateCombo.itemData(i)
                if isinstance(data, (int, float)) and abs(float(data) - float(rate_value)) < 1e-6:
                    self.rateCombo.setCurrentIndex(i)
                    return
            # fallback: match by text like "1.00x"
            txt = f"{float(rate_value):.2f}x"
            ix = self.rateCombo.findText(txt)
            if ix >= 0:
                self.rateCombo.setCurrentIndex(ix)
        except Exception:
            pass


    def load_pattern_from_library(self, pattern_info):
        try:
            config = pattern_info["config"]
            if config.get("pattern_type") == "Timeline":
                try:
                    # switch left column visible and ensure Designer page
                    if hasattr(self, "timeline_panel") and self.timeline_panel:
                        self.timeline_panel.load_from_config(config)
                    if hasattr(self, "canvas_selector"):
                        self.canvas_selector.canvasCombo.setCurrentIndex(0)  # Designer
                    self._log_info(f"Timeline '{pattern_info['name']}' loaded")
                    QMessageBox.information(self, "Timeline", f"Timeline '{pattern_info['name']}' loaded.")
                    return
                except Exception as e:
                    self._log_info(f"Timeline load error: {e}")
                    QMessageBox.critical(self, "Error", f"Failed to load timeline: {e}")
                    return
            QTimer.singleShot(0, lambda: self.tab_widget.setCurrentIndex(0))

            # 1) Pattern type first
            self.patternComboBox.setCurrentText(config.get("pattern_type", "Single Pulse"))
            QApplication.processEvents()
            self._create_pattern_specific_params()

            # 2) Basic parameters
            self.intensitySlider.setValue(int(config.get("intensity", 7)))
            self.durationSpinBox.setValue(float(config.get("duration", 2.0)))
            if hasattr(self, "frequencySlider"):
                self.frequencySlider.setValue(int(config.get("frequency", 0)))

            # 3) Waveform from library
            self._apply_loaded_waveform(config.get("waveform", {}))

            # 4) Pattern-specific params
            sp = config.get("specific_parameters", {})
            for key, widget in getattr(self, "pattern_specific_widgets", {}).items():
                if key in sp:
                    try:
                        widget.setValue(sp[key])
                    except Exception:
                        pass

            # (removed) restore playbackRateSpinBox/repeatSpinBox/offsetSpinBox — section deleted

            # 6) Actuators
            if "actuators" in config and hasattr(self, "canvas_selector"):
                acts = list(config.get("actuators", []))
                self.canvas_selector.load_actuator_configuration(acts)
                self._last_loaded_acts = list(acts)
                try:
                    if hasattr(self.canvas_selector, "select_actuators"):
                        self.canvas_selector.select_actuators(acts)
                    elif hasattr(self.canvas_selector, "set_selected_actuators"):
                        self.canvas_selector.set_selected_actuators(acts)
                    else:
                        if hasattr(self.canvas_selector, "clear_selection"):
                            self.canvas_selector.clear_selection()
                        for aid in acts:
                            try:
                                self.canvas_selector.set_selected(aid, True)
                            except Exception:
                                pass
                except Exception:
                    pass

            self._log_info(f"Pattern '{pattern_info['name']}' loaded from library")
            QMessageBox.information(self, "Success",
                                    f"Pattern '{pattern_info['name']}' loaded successfully!")
        except Exception as e:
            self._log_info(f"Error loading pattern: {e}")
            QMessageBox.critical(self, "Error", f"Failed to load pattern: {e}")
    
    def on_pattern_deleted(self, pattern_name):
        """Appelé quand un pattern est supprimé de la bibliothèque"""
        self._log_info(f"Pattern '{pattern_name}' deleted from library")
    
    def on_actuator_selection_changed(self, selected_ids):
        """Appelé quand la sélection d'actuateurs change"""
        if selected_ids:
            self._log_info(f"Selected actuators: {selected_ids}")
        else:
            self._log_info("No actuators selected")
    
    def _get_selected_actuators(self):
        """Return selected actuators; if none, fall back to last loaded set."""
        try:
            ids = self.canvas_selector.get_selected_actuators()
        except Exception:
            ids = []
        if not ids and getattr(self, "_last_loaded_acts", None):
            return list(self._last_loaded_acts)
        return ids

    
    def start_pattern(self):
        """Start the selected pattern"""
        if self.is_running:
            QMessageBox.warning(self, "Warning", "Pattern is already running")
            return
        if not (getattr(self.api, "connected", False) or getattr(self, "is_connected", False)):
            QMessageBox.warning(self, "Error", "Please connect to a device first")
            return

        actuators = self._get_selected_actuators()
        if not actuators and getattr(self, "_last_loaded_acts", None):
            actuators = list(self._last_loaded_acts)
        if not actuators:
            QMessageBox.warning(self, "Error", "Please select at least one actuator")
            return

        pattern_name = self.patternComboBox.currentText()
        if pattern_name not in self.patterns:
            QMessageBox.warning(self, "Error", "Invalid pattern selected")
            return

        waveform_info = self.get_current_waveform_info()
        if waveform_info['source'] == 'Waveform Library' and not waveform_info['event']:
            QMessageBox.warning(self, "Waveform", "Please select a waveform from the library.")
            return


        base_intensity = self.intensitySlider.value()
        base_frequency = (
            self.strokeFreqCode.value()
            if hasattr(self, "strokeFreqCode") else
            (self.frequencySlider.value() if hasattr(self, "frequencySlider") else 0)
        )


        if waveform_info['source'] == 'Built-in Oscillators':
            intensity, frequency = self._apply_builtin_waveform_modulation(
                waveform_info['name'], base_intensity, base_frequency
            )
        else:
            intensity, frequency = base_intensity, base_frequency

        # Duration comes from the selected waveform if available
        wf_duration = 0.0
        if waveform_info['source'] == 'Waveform Library' and waveform_info['event'] and getattr(waveform_info['event'], 'waveform_data', None):
            try:
                wf_duration = float(waveform_info['event'].waveform_data.duration or 0.0)
            except Exception:
                wf_duration = 0.0

        # Use device frequency code for hardware (falls back if slider not present)
        freq_code = (self.strokeFreqCode.value()
                    if hasattr(self, "strokeFreqCode")
                    else (self.frequencySlider.value() if hasattr(self, "frequencySlider") else 0))

        params = {
            'actuators': actuators,
            'intensity': int(intensity),
            # pass both names for broad pattern compatibility
            'frequency': int(freq_code),
            'freq_code': int(freq_code),
            'duration': float(wf_duration if wf_duration > 0 else 2.0),
        }
        # Add pattern-specific fields only (no playback_rate/repeat/start_offset here)
        for name, w in getattr(self, "pattern_specific_widgets", {}).items():
            try:
                params[name] = w.value()
            except Exception:
                pass

        self.current_pattern = self.patterns[pattern_name]
        # Attach waveform data for library events if supported by the pattern
        if waveform_info['source'] == 'Waveform Library' and waveform_info['event']:
            if hasattr(self.current_pattern, 'set_waveform_data'):
                self.current_pattern.set_waveform_data(waveform_info['event'])
        else:
            if hasattr(self.current_pattern, 'set_waveform_data'):
                self.current_pattern.set_waveform_data(None)

        self.current_pattern.stop_flag = False
        self.is_running = True

        self.pattern_worker = PatternWorker(self.current_pattern, params)
        self.pattern_worker.finished.connect(self._on_pattern_finished)
        self.pattern_worker.log_message.connect(self._log_info)
        self.pattern_worker.start()

        # Do NOT auto-start UI preview here; it confused Start vs Preview.
        # If you want UI feedback while playing, toggle Preview explicitly.
        try:
            self.preview_driver.stop()
        except Exception:
            pass

        self._log_info(f"DEVICE START → {pattern_name} on {actuators} (I:{params['intensity']}, freq_code:{int(freq_code)})")


        waveform_desc = f" with {waveform_info['name']} waveform" if waveform_info['name'] else ""
        self._log_info(f"Started {pattern_name} pattern{waveform_desc} on actuators {actuators} (I:{intensity}, F:{frequency})")
    
    def _apply_builtin_waveform_modulation(self, waveform_name, base_intensity, base_frequency):
        """Apply waveform-specific modifications to basic parameters"""
        
        # Different waveforms can modify intensity and frequency differently
        waveform_modifications = {
            "Sine": (base_intensity, base_frequency),
            "Square": (min(15, base_intensity + 2), base_frequency),
            "Saw": (base_intensity, min(7, base_frequency + 1)),
            "Triangle": (max(1, base_intensity - 1), base_frequency),
            "Chirp": (base_intensity, min(7, base_frequency + 2)),
            "FM": (base_intensity, max(0, base_frequency - 1)),
            "PWM": (min(15, base_intensity + 1), base_frequency),
            "Noise": (max(1, min(15, base_intensity + random.randint(-2, 2))), 
                     max(0, min(7, base_frequency + random.randint(-1, 1))))
        }
        
        intensity, frequency = waveform_modifications.get(waveform_name, (base_intensity, base_frequency))
        
        self._log_info(f"Waveform '{waveform_name}' modified parameters: {base_intensity}->{intensity}, {base_frequency}->{frequency}")
        
        return intensity, frequency
    
    def stop_pattern(self):
        """Stop the current pattern"""
        self._stop_drawn_stroke()
        if self.current_pattern:
            self.current_pattern.stop()
            self._log_info("Pattern stop requested")
        
        if self.pattern_worker and self.pattern_worker.isRunning():
            # Attendre que le pattern worker s'arrête proprement
            if not self.pattern_worker.wait(2000):
                self._log_info("Warning: Pattern worker thread did not stop gracefully")
                self.pattern_worker.terminate()
                self.pattern_worker.wait(1000)
            self.pattern_worker = None
            
        try:
            self.preview_driver.stop()
        except Exception:
            pass
        self._force_stop_selected_actuators()
        self.is_running = False
        self._log_info("Pattern stopped")
        
    
    def _force_stop_selected_actuators(self):
        """Force stop all selected actuators"""
        try:
            actuators = self._get_selected_actuators()
            if actuators:
                for addr in actuators:
                    self.api.send_command(addr, 0, 0, 0)
                self._log_info(f"Force stopped actuators: {actuators}")
        except Exception as e:
            self._log_info(f"Error force stopping actuators: {e}")
    
    def emergency_stop(self):
        """Emergency stop - stops pattern and all actuators"""
        self._stop_drawn_stroke()
        self.stop_pattern()
        try:
            for i in range(128):
                self.api.send_command(i, 0, 0, 0)
            self._log_info("Emergency stop executed - all actuators (0-127) stopped")
        except Exception as e:
            self._log_info(f"Emergency stop error: {e}")
    
    def _on_pattern_finished(self, success, message):
        """Handle pattern completion"""
        self._force_stop_selected_actuators()
        self.is_running = False
        self._log_info("Pattern completed")
    
    def closeEvent(self, event):
        """Handle window closing - amélioration du nettoyage des threads"""
        self._log_info("Application closing - cleaning up threads...")
        
        # Arrêter tous les workers en cours
        self.emergency_stop()
        
        # Arrêter le stroke worker avec timeout plus long
        if hasattr(self, '_stroke_worker') and self._stroke_worker and self._stroke_worker.isRunning():
            self._stroke_worker.stop()
            if not self._stroke_worker.wait(3000):
                self._log_info("Force terminating stroke worker")
                self._stroke_worker.terminate()
                self._stroke_worker.wait(1000)
            self._stroke_worker = None
        
        # Arrêter le pattern worker
        if hasattr(self, 'pattern_worker') and self.pattern_worker and self.pattern_worker.isRunning():
            if not self.pattern_worker.wait(2000):
                self._log_info("Force terminating pattern worker")
                self.pattern_worker.terminate()
                self.pattern_worker.wait(1000)
            self.pattern_worker = None
        
        # Arrêter tous les timers
        if hasattr(self, '_stroke_preview_timer'):
            self._stroke_preview_timer.stop()
        if hasattr(self, 'preview_timer'):
            self.preview_timer.stop()
        
        # Arrêter le timeline panel
        try:
            if hasattr(self, "timeline_panel") and self.timeline_panel:
                self.timeline_panel.stop_all()
        except Exception as e:
            self._log_info(f"Error stopping timeline: {e}")
        
        self._all_off(range(128))
        
        # Déconnecter l'API
        if hasattr(self, 'api') and self.api and self.api.connected:
            try:
                self.api.disconnect_serial_device()
            except Exception as e:
                self._log_info(f"Error disconnecting API: {e}")
        
        self._log_info("Cleanup completed")
        event.accept()
    
    def _log_info(self, message):
        """Lightweight logger: status bar + stdout (text panel may not exist)."""
        timestamp = time.strftime('%H:%M:%S')
        log_message = f"{timestamp} - {message}"

        # Show brief status
        try:
            if not self.statusBar():
                self.setStatusBar(QStatusBar(self))
            self.statusBar().showMessage(message, 4000)
        except Exception:
            pass

        # Only append if the panel exists
        if hasattr(self, "infoTextEdit") and self.infoTextEdit is not None:
            self.infoTextEdit.append(log_message)

        print(log_message)

def main():
    app = QApplication(sys.argv)
    app.setStyle(QStyleFactory.create("Fusion"))

    # High DPI scaling policy (PyQt6 handles scaling automatically)
    app.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    # Palette claire pour éviter les champs foncés qui mangent le texte
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window,       QColor("#F6F7F9"))
    pal.setColor(QPalette.ColorRole.Base,         QColor("#FFFFFF"))
    pal.setColor(QPalette.ColorRole.AlternateBase,QColor("#F3F4F6"))
    pal.setColor(QPalette.ColorRole.Text,         QColor("#111827"))
    pal.setColor(QPalette.ColorRole.WindowText,   QColor("#111827"))
    pal.setColor(QPalette.ColorRole.Button,       QColor("#FFFFFF"))
    pal.setColor(QPalette.ColorRole.ButtonText,   QColor("#111827"))
    pal.setColor(QPalette.ColorRole.ToolTipBase,  QColor("#111827"))
    pal.setColor(QPalette.ColorRole.ToolTipText,  QColor("#F9FAFB"))
    pal.setColor(QPalette.ColorRole.Highlight,    QColor("#3B82F6"))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    app.setPalette(pal)

    # Charger la feuille de style
    qss_path = os.path.join(os.path.dirname(__file__), "..", "resources", "haptic_pro.qss")
    if os.path.exists(qss_path):
        with open(qss_path, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())

    window = HapticPatternGUI()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()