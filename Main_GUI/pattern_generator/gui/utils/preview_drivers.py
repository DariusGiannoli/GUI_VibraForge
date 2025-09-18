import random
from PyQt6.QtCore import QObject, QTimer

class PatternPreviewDriver(QObject):
    """
    Lightweight UI-only animator that highlights which actuators are 'active'
    at each instant. It does NOT talk to hardware.
    """
    def __init__(self, canvas_selector: 'MultiCanvasSelector', parent=None):
        super().__init__(parent)
        self.canvas_selector = canvas_selector
        self.timer = QTimer(self)
        self.timer.setInterval(50)  # 20 FPS
        self.timer.timeout.connect(self._on_tick)
        self.running = False

        self._elapsed = 0.0
        self._total = 0.0
        self._cycle = 1.0
        self._pattern_name = ""
        self._params = {}

    def start(self, pattern_name: str, params: dict):
        """params must contain: actuators (list[int]), duration, repeat,
           playback_rate, and any pattern-specific fields (e.g., wave_speed…)."""
        self._pattern_name = pattern_name
        self._params = dict(params)
        duration = float(params.get("duration", 1.0))
        rate = max(0.001, float(params.get("playback_rate", 1.0)))
        self._cycle = max(0.05, duration / rate)      # effective duration of 1 run
        self._total = self._cycle * max(1, int(params.get("repeat", 1)))
        self._elapsed = 0.0
        self.running = True
        self.timer.start()
        # draw first frame immediately
        self._apply_active(self._active_at_time(0.0))

    def stop(self):
        self.timer.stop()
        self.running = False
        try:
            self.canvas_selector.clear_preview()
        except Exception:
            pass

    # ---- internals
    def _on_tick(self):
        if not self.running:
            return
        self._elapsed += self.timer.interval() / 1000.0
        if self._elapsed > self._total:
            self.stop()
            return
        t_cycle = self._elapsed % self._cycle
        self._apply_active(self._active_at_time(t_cycle))

    def _apply_active(self, ids):
        try:
            self.canvas_selector.set_preview_active(ids)
        except Exception:
            pass

    def _active_at_time(self, t: float) -> list[int]:
        name = self._pattern_name
        a = list(self._params.get("actuators", []))
        if not a:
            return []

        sp = self._params

        if name == "Wave":
            n = len(a)
            sweep = max(0.05, float(sp.get("wave_speed", 0.5)))
            progress = (t % sweep) / sweep
            idx = int(progress * n) % n
            return [a[idx]]

        if name == "Circular":
            n = len(a)
            sweep = max(0.05, float(sp.get("rotation_speed", 1.0)))
            progress = (t % sweep) / sweep
            idx = int(progress * n) % n
            return [a[idx]]

        if name == "Random":
            interval = float(sp.get("change_interval", 0.3))
            k = int(t / max(0.05, interval))
            rng = random.Random(k)
            return [rng.choice(a)]

        if name == "Pulse Train":
            on_t  = float(sp.get("pulse_on", 0.2))
            off_t = float(sp.get("pulse_off", 0.3))
            cyc = max(0.05, on_t + off_t)
            return a if (t % cyc) < on_t else []

        return a  # Single Pulse / Fade / Sine Wave