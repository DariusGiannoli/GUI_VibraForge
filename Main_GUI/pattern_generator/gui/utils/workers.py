import time
import math
from typing import Optional
from PyQt6.QtCore import QThread, pyqtSignal, QObject
from ..core.data_models import TimelineClip
from ..utils.utils import _sample_event_amplitude

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

class TimelineDeviceWorker(QThread):
    """Play the timeline on hardware by streaming intensity updates."""
    finished = pyqtSignal(bool, str)
    log_message = pyqtSignal(str)
    tick = pyqtSignal(float)

    def __init__(self, api, model: TimelineModel, total_s: float, max_intensity: int,
                 freq_code: int, tick_ms: int = 50):
        super().__init__()
        self.api = api
        self.model = model
        self.total_s = max(0.0, float(total_s))
        self.maxI = int(max(0, min(15, max_intensity)))
        self.freq = int(max(0, min(7, freq_code)))
        self.dt_ms = int(max(10, tick_ms))
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            last_I: dict[int, int] = {}
            t0 = time.perf_counter()
            try:
                self.tick.emit(0.0)
            except Exception:
                pass
            while not self._stop:
                elapsed_s = time.perf_counter() - t0
                if elapsed_s > self.total_s:
                    break

                # compute target intensity for each actuator
                # (if multiple overlapping clips on same actuator: take max)
                target: dict[int, int] = {}
                for c in self.model.clips():
                    if c.start_s <= elapsed_s <= c.end_s:
                        # time inside the clip
                        local_t = elapsed_s - c.start_s
                        amp = _sample_event_amplitude(c.event, local_t)
                        Ii = int(round(amp * self.maxI))
                        if Ii <= 0:
                            continue
                        if c.actuator not in target or Ii > target[c.actuator]:
                            target[c.actuator] = Ii

                # send diffs
                # turn on/update
                for addr, inten in target.items():
                    if last_I.get(addr, 0) != inten:
                        try:
                            self.api.send_command(int(addr), int(inten), self.freq, 1)
                        except Exception as e:
                            self.log_message.emit(f"HW error @on: {e}")
                        last_I[addr] = inten
                # turn off others that were on
                for addr in list(last_I.keys()):
                    if addr not in target and last_I.get(addr, 0) > 0:
                        try:
                            self.api.send_command(int(addr), 0, 0, 0)
                        except Exception as e:
                            self.log_message.emit(f"HW error @off: {e}")
                        last_I[addr] = 0
                # heartbeat UI: prévenir la timeline de l'avancement courant
                try:
                    self.tick.emit(elapsed_s)   # elapsed_s est déjà calculé plus haut
                except Exception:
                    pass
                time.sleep(self.dt_ms / 1000.0)

            # final off for anything left
            for addr, inten in list(last_I.items()):
                if inten > 0:
                    try:
                        self.api.send_command(int(addr), 0, 0, 0)
                    except Exception as e:
                        self.log_message.emit(f"HW error @off: {e}")
            
            # dernier tick pour caler le curseur à la fin
            try:
                end_t = self.total_s if not self._stop else max(0.0, time.perf_counter() - t0)
                self.tick.emit(end_t)
            except Exception:
                pass
            self.finished.emit(not self._stop, "Timeline done" if not self._stop else "Timeline stopped")

        except Exception as e:
            self.finished.emit(False, f"Timeline worker error: {e}")

class StrokePlaybackWorker(QThread):
    """Schedule and play a stroke schedule on hardware with explicit offs."""
    finished = pyqtSignal(bool, str)
    log_message = pyqtSignal(str)
    step_started = pyqtSignal(int, list, tuple)

    def __init__(self, api, schedule, freq_code:int):
        super().__init__()
        self.api = api
        self.schedule = list(sorted(schedule, key=lambda s: s["t_on"]))
        self.freq_code = int(max(0, min(7, freq_code)))
        self._stop_flag = False

    def stop(self):
        self._stop_flag = True

    def run(self):
        """Play the precomputed schedule on the device and emit UI updates.

        Emits:
            - step_started(int index, list bursts, tuple pt): just before sending ON commands
            - log_message(str): on hardware errors
            - finished(bool ok, str message): at end or on error
        """
        try:
            t0 = time.perf_counter()
            off_events = []  # list of {"t_off": ms_from_start, "addr": int}
            active_addrs = set()

            for i, step in enumerate(self.schedule):
                if self._stop_flag:
                    break

                # Wait until the absolute onset time (in ms from t0)
                while not self._stop_flag and (time.perf_counter() - t0) * 1000.0 < step["t_on"]:
                    time.sleep(0.0005)

                # Notify UI about the step that is starting
                try:
                    self.step_started.emit(i, step["bursts"], step.get("pt", (0.5, 0.5)))
                except Exception:
                    pass  # never break playback because of UI issues

                # Send ON commands for this step
                for addr, inten in step["bursts"]:
                    try:
                        self.api.send_command(int(addr), int(inten), self.freq_code, 1)
                        active_addrs.add(int(addr))
                    except Exception as e:
                        self.log_message.emit(f"HW error @on: {e}")

                # Schedule OFF commands for this step
                for addr, _ in step["bursts"]:
                    off_events.append({
                        "t_off": step["t_on"] + step["dur_ms"],
                        "addr": int(addr)
                    })

                # Send any OFFs that are due by now
                now_ms = (time.perf_counter() - t0) * 1000.0
                due = [o for o in off_events if o["t_off"] <= now_ms]
                for off in due:
                    try:
                        self.api.send_command(off["addr"], 0, 0, 0)
                        active_addrs.discard(off["addr"])
                    except Exception as e:
                        self.log_message.emit(f"HW error @off: {e}")
                    off_events.remove(off)

            # Drain remaining OFFs
            if self._stop_flag:
                # On stop, turn everything off immediately (no more waiting)
                for off in off_events:
                    try:
                        self.api.send_command(off["addr"], 0, 0, 0)
                    except Exception as e:
                        self.log_message.emit(f"HW error @off: {e}")
            else:
                # Normal end: wait until each OFF time then send it
                for off in off_events:
                    while (time.perf_counter() - t0) * 1000.0 < off["t_off"]:
                        time.sleep(0.0005)
                    try:
                        self.api.send_command(off["addr"], 0, 0, 0)
                    except Exception as e:
                        self.log_message.emit(f"HW error @off: {e}")

            self.finished.emit(not self._stop_flag,
                            "Stroke playback done" if not self._stop_flag else "Stopped")

        except Exception as e:
            self.finished.emit(False, f"Stroke worker error: {e}")

    @staticmethod
    def _resample_polyline(points_xy: list[tuple[float,float]], n_samples: int) -> list[tuple[float,float]]:

        """Arc-length resample of a polyline in [0..1]×[0..1]."""
        if n_samples <= 1 or len(points_xy) < 2:
            return points_xy[:1] * max(1, n_samples)
        # cumulative distances
        d = [0.0]
        for a,b in zip(points_xy, points_xy[1:]):
            dx, dy = b[0]-a[0], b[1]-a[1]
            d.append(d[-1] + math.hypot(dx, dy))
        length = d[-1] if d[-1] > 0 else 1e-9
        targets = [i*length/(n_samples-1) for i in range(n_samples)]
        out = []
        j = 0
        for t in targets:
            while j+1 < len(d) and d[j+1] < t:
                j += 1
            if j+1 >= len(d):
                out.append(points_xy[-1]); continue
            # local interpolation between j and j+1
            seg = d[j+1] - d[j]
            alpha = 0.0 if seg <= 0 else (t - d[j]) / seg
            x = points_xy[j][0] + alpha * (points_xy[j+1][0]-points_xy[j][0])
            y = points_xy[j][1] + alpha * (points_xy[j+1][1]-points_xy[j][1])
            out.append((x,y))
        return out

    @staticmethod
    def _nearest_n(point_xy: tuple[float,float], id_to_xy: dict[int,tuple[float,float]], n:int) -> list[tuple[int,float]]:
        """Return list of (id, distance) for n nearest nodes to the point."""
        items = []
        for aid, (x,y) in id_to_xy.items():
            items.append((aid, math.hypot(point_xy[0]-x, point_xy[1]-y)))
        items.sort(key=lambda t: t[1])
        return items[:max(1,n)]

    @staticmethod
    def _phantom_intensities_2act(d1: float, d2: float, Av: int) -> tuple[int,int]:
        """Eq. (2) from Park et al. (Av in device units 1..15)."""
        d1 = max(d1, 1e-6); d2 = max(d2, 1e-6)
        A1 = math.sqrt(d2/(d1+d2)) * Av
        A2 = math.sqrt(d1/(d1+d2)) * Av
        return (max(1, min(15, round(A1))), max(1, min(15, round(A2))))

    @staticmethod
    def _phantom_intensities_3act(d1: float, d2: float, d3: float, Av: int) -> tuple[int,int,int]:
        """Eq. (10) from Park et al. — energy-based 3‑actuator phantom."""
        d1 = max(d1, 1e-6); d2 = max(d2, 1e-6); d3 = max(d3, 1e-6)
        inv = [1.0/d1, 1.0/d2, 1.0/d3]
        s = sum(inv)
        # Ai = sqrt((1/di)/sum(1/dj)) * Av
        A = [math.sqrt(v/s) * Av for v in inv]
        A = [max(1, min(15, round(a))) for a in A]
        return (A[0], A[1], A[2])


import inspect

class PatternWorker(QThread):
    finished = pyqtSignal(bool, str)
    log_message = pyqtSignal(str)

    def __init__(self, pattern, params: dict):
        super().__init__()
        self.pattern = pattern
        self.params = dict(params or {})
        self._stop = False

    def stop(self):
        self._stop = True
        try:
            if hasattr(self.pattern, "stop"):
                self.pattern.stop()
        except Exception:
            pass

    def run(self):
        try:
            exec_fn = getattr(self.pattern, "execute", None)
            if not callable(exec_fn):
                raise RuntimeError("Pattern has no execute() method")

            sig = inspect.signature(exec_fn)
            expected = [p.name for p in sig.parameters.values()
                        if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)]

            p = self.params
            safe = {}

            # ---- map actuators
            val_act = p.get("actuators") or p.get("targets") or p.get("addresses") or p.get("ids")
            for k in ("actuators", "targets", "addresses", "ids"):
                if k in expected and val_act is not None:
                    safe[k] = val_act
                    break

            # ---- map intensity (aka amplitude/gain)
            val_int = p.get("intensity", p.get("amplitude", p.get("gain")))
            for k in ("intensity", "amplitude", "gain"):
                if k in expected and val_int is not None:
                    safe[k] = int(val_int)
                    break

            # ---- map device frequency code
            val_freq = (p.get("device_freq_code", None) or
                        p.get("freq_code", None) or
                        p.get("frequency", None) or
                        p.get("freq", 0))
            for k in ("device_freq_code", "freq_code", "frequency", "freq"):
                if k in expected and val_freq is not None:
                    safe[k] = int(val_freq)
                    break

            # ---- map duration (seconds → ms if pattern expects *_ms)
            dur_s = float(p.get("duration", p.get("duration_s", 0.0)))
            if "duration_ms" in expected:
                safe["duration_ms"] = int(round(dur_s * 1000.0))
            elif "duration_s" in expected:
                safe["duration_s"] = dur_s
            elif "duration" in expected:
                safe["duration"] = dur_s

            # ---- pass any other expected keys present in params
            passthrough = set(expected) - {
                "actuators","targets","addresses","ids",
                "intensity","amplitude","gain",
                "device_freq_code","freq_code","frequency","freq",
                "duration","duration_s","duration_ms"
            }
            for k in passthrough:
                if k in p:
                    safe[k] = p[k]

            self.log_message.emit(
                f"Executing {self.pattern.__class__.__name__} with args: {safe}"
            )
            exec_fn(**safe)
            self.finished.emit(True, "done")

        except Exception as e:
            try:
                self.log_message.emit(f"Pattern execution error: {e}")
            finally:
                self.finished.emit(False, f"{e}")
