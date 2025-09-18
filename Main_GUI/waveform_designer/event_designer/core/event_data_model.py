"""
Event Data Model for Universal Haptic Event Designer (Enhanced Parameters)

- Canonical MIME for DnD payloads
- Consistent time grid (no off-by-one)
- Polyphase resampling helper
- CSV load/save helpers
- Built-in oscillator generator (numeric, side-effect free)
- Data containers (WaveformData, ParameterModifications, ActuatorMapping, EventMetadata)
- HapticEvent with factory, effects pipeline, and persistence
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple

import numpy as np
from scipy import signal  # waveforms (square/saw/chirp, etc.)
from scipy.signal import resample_poly  # high-quality resampling


# -----------------------------------------------------------------------------
# Drag & Drop MIME
# -----------------------------------------------------------------------------
MIME_WAVEFORM = "application/x-waveform"


# -----------------------------------------------------------------------------
# Numeric utilities
# -----------------------------------------------------------------------------
def common_time_grid(duration: float, sr: float) -> np.ndarray:
    """Return a consistent sample grid using arange to avoid off-by-one."""
    n = max(1, int(round(duration * sr)))
    return np.arange(n, dtype=float) / float(sr)


def resample_to(y: np.ndarray, sr_in: float, sr_out: float) -> np.ndarray:
    """
    Resample to target sample rate using polyphase (better spectral fidelity).
    Keeps the output length proportional to duration.
    """
    y = np.asarray(y, dtype=float)
    if y.size == 0 or float(sr_in) == float(sr_out):
        return y
    up = int(round(sr_out))
    down = int(round(sr_in))
    from math import gcd
    g = gcd(up, down) or 1
    return resample_poly(y, up // g, down // g).astype(float, copy=False)


def load_csv_waveform(path: str, default_sr: float = 1_000.0) -> Tuple[np.ndarray, np.ndarray, float]:
    """
    Load CSV as (t, y, sr). Accepts one column (y) or two columns (t, y).
    If t is provided, sr is inferred from median dt; otherwise default_sr is used.
    """
    arr = np.loadtxt(path, delimiter=",")
    if arr.ndim == 1:  # one column: y
        y = np.asarray(arr, dtype=float)
        sr = float(default_sr)
        t = common_time_grid(duration=(y.size / sr), sr=sr)
        return t, y, sr

    if arr.shape[1] < 2:
        raise ValueError("CSV must have 1 (y) or 2 (t,y) columns.")

    t = np.asarray(arr[:, 0], dtype=float)
    y = np.asarray(arr[:, 1], dtype=float)
    dt = np.median(np.diff(t)) if t.size > 1 else 0.0
    sr = 1.0 / dt if dt > 0 else float(default_sr)
    return t, y, sr


def save_waveform_to_csv(path: str, t: np.ndarray, y: np.ndarray) -> None:
    """Save (t, y) as a two-column CSV with a simple header."""
    data = np.column_stack([np.asarray(t, float), np.asarray(y, float)])
    np.savetxt(path, data, delimiter=",", header="t,y", comments="")


def generate_builtin_waveform(
    kind: str,
    *,
    frequency: float,
    amplitude: float,
    duration: float,
    sample_rate: float,
    f0: float | None = None,    # Chirp start freq
    f1: float | None = None,    # Chirp end freq
    fm: float | None = None,    # FM modulating freq
    beta: float | None = None,  # FM modulation index
    duty: float | None = None   # PWM duty cycle [0..1]
) -> Tuple[np.ndarray, np.ndarray, float]:
    """
    Lightweight numeric generator used by Waveform Studio for preview and DnD.
    Returns (t, y, sr). Side-effect free, does not allocate a HapticEvent.
    """
    t = common_time_grid(duration, sample_rate)
    k = (kind or "Sine").lower()

    if k in ("sine", "sin"):
        y = amplitude * np.sin(2 * np.pi * frequency * t)
    elif k == "square":
        y = amplitude * signal.square(2 * np.pi * frequency * t, duty=(duty if duty is not None else 0.5))
    elif k == "saw":
        y = amplitude * signal.sawtooth(2 * np.pi * frequency * t, 1.0)
    elif k == "triangle":
        y = amplitude * signal.sawtooth(2 * np.pi * frequency * t, 0.5)
    elif k == "chirp":
        y = amplitude * signal.chirp(
            t,
            f0=(f0 if f0 is not None else frequency),
            f1=(f1 if f1 is not None else max(1.0, frequency * 2.0)),
            t1=duration,
            method="linear",
        )
    elif k == "fm":
        fc = float(frequency)
        fm_hz = float(fm if fm is not None else 5.0)
        beta_ = float(beta if beta is not None else 1.0)
        y = amplitude * np.sin(2 * np.pi * fc * t + beta_ * np.sin(2 * np.pi * fm_hz * t))
    elif k == "pwm":
        y = amplitude * signal.square(2 * np.pi * frequency * t, duty=(duty if duty is not None else 0.5))
    elif k == "noise":
        rng = np.random.default_rng()
        y = amplitude * rng.uniform(-1.0, 1.0, size=t.size)
    else:
        raise ValueError(f"Unknown oscillator kind: {kind}")

    return t, y.astype(float, copy=False), float(sample_rate)


# -----------------------------------------------------------------------------
# Defaults
# -----------------------------------------------------------------------------
_DEFAULT_SR   = 1000.0  # Hz
_DEFAULT_DUR  = 1.0     # s
_DEFAULT_FREQ = 100.0   # Hz
_DEFAULT_AMP  = 1.0


# -----------------------------------------------------------------------------
# Enums
# -----------------------------------------------------------------------------
class EventCategory(Enum):
    CRASH       = "crash"
    ISOLATION   = "isolation"
    EMBODIMENT  = "embodiment"
    ALERT       = "alert"
    CUSTOM      = "custom"


class ActuatorPattern(Enum):
    SIMULTANEOUS = "simultaneous"
    SEQUENTIAL   = "sequential"
    WAVE         = "wave"
    RADIAL       = "radial"
    CUSTOM       = "custom"


# -----------------------------------------------------------------------------
# Data containers
# -----------------------------------------------------------------------------
@dataclass
class WaveformData:
    """Container for haptic waveform data."""
    amplitude: List[Dict[str, float]]        # [{"time": float, "amplitude": float}, ...]
    frequency: List[Dict[str, float]]        # [{"time": float, "frequency": float}, ...]
    duration: float
    sample_rate: float = _DEFAULT_SR

    # --- small helpers for widgets ---
    def get_amplitude_array(self) -> np.ndarray:
        if not self.amplitude:
            return np.array([], dtype=float)
        return np.array([p["amplitude"] for p in self.amplitude], dtype=float)

    def get_frequency_array(self) -> np.ndarray:
        if not self.frequency:
            return np.array([], dtype=float)
        return np.array([p["frequency"] for p in self.frequency], dtype=float)

    def get_time_array(self) -> np.ndarray:
        """Time axis from duration & sample_rate (safer than linspace endpoint=True)."""
        n = max(1, int(round(self.duration * self.sample_rate)))
        return np.arange(n, dtype=float) / float(self.sample_rate)


@dataclass
class ParameterModifications:
    """Waveform parameter modifications (enhanced)."""
    # Amplitude
    intensity_multiplier: float = 1.0
    perceptual_loudness: float = 1.0  # psychoacoustic-inspired scaler
    amplitude_offset: float = 0.0     # legacy compatibility

    # Timing
    duration_scale: float = 1.0

    # Frequency (enhanced)
    frequency_shift: float = 0.0
    fm_depth: float = 0.0
    fm_rate: float = 0.0

    # ADSR
    attack_time: float = 0.0
    decay_time: float = 0.0
    sustain_level: float = 1.0
    release_time: float = 0.0

    # Shaping
    saturation_amount: float = 0.0
    compression_ratio: float = 1.0
    compression_threshold: float = 0.0

    # Modulation
    tremolo_rate: float = 0.0
    tremolo_depth: float = 0.0

    # Spatial
    phase_offset: float = 0.0  # degrees

    # Generation
    pulse_width: float = 0.5   # for square waves (if needed)

    # Custom envelope
    custom_envelope: Optional[List[float]] = None


@dataclass
class ActuatorMapping:
    """Actuator routing / pattern configuration."""
    active_actuators: List[str]
    pattern_type: ActuatorPattern = ActuatorPattern.SIMULTANEOUS
    timing_offsets: Dict[str, float] | None = None
    intensity_scaling: Dict[str, float] | None = None
    zones: List[str] | None = None

    def __post_init__(self):
        self.timing_offsets = self.timing_offsets or {}
        self.intensity_scaling = self.intensity_scaling or {}
        self.zones = self.zones or []


@dataclass
class EventMetadata:
    """Human metadata for a haptic event."""
    name:        str
    category:    EventCategory
    description: str = ""
    tags:        List[str] | None = None
    author:      str = ""
    version:     str = "1.0"
    created_date:  str = ""
    modified_date: str = ""

    def __post_init__(self):
        self.tags = self.tags or []
        ts = datetime.now().isoformat()
        if not self.created_date:
            self.created_date = ts
        if not self.modified_date:
            self.modified_date = self.created_date


# -----------------------------------------------------------------------------
# Main class
# -----------------------------------------------------------------------------
class HapticEvent:
    """Main event container."""

    def __init__(self, name: str = "New Event", category: EventCategory = EventCategory.CUSTOM) -> None:
        self.metadata = EventMetadata(name=name, category=category)
        self.waveform_data: Optional[WaveformData] = None
        self.parameter_modifications = ParameterModifications()
        self.actuator_mapping = ActuatorMapping(active_actuators=[])
        self.original_haptic_file: Optional[str] = None

    # --- factory: built-in oscillators for the Library ---
    @classmethod
    def new_basic_oscillator(
        cls,
        osc_type: str,
        *,
        frequency: float = _DEFAULT_FREQ,
        amplitude: float = _DEFAULT_AMP,
        duration: float = _DEFAULT_DUR,
        sample_rate: float = _DEFAULT_SR,
    ) -> "HapticEvent":
        """
        Build a HapticEvent containing one of the eight standard oscillators:
        Sine, Square, Saw, Triangle, Chirp, FM, PWM, Noise.
        """
        t = common_time_grid(duration, sample_rate)

        if   osc_type == "Sine":
            y = np.sin(2 * np.pi * frequency * t)
        elif osc_type == "Square":
            y = signal.square(2 * np.pi * frequency * t, duty=0.5)
        elif osc_type == "Saw":
            y = signal.sawtooth(2 * np.pi * frequency * t, 1.0)
        elif osc_type == "Triangle":
            y = signal.sawtooth(2 * np.pi * frequency * t, 0.5)
        elif osc_type == "Chirp":
            y = signal.chirp(t, f0=frequency, t1=duration, f1=frequency * 4, method="linear")
        elif osc_type == "FM":
            carr = 2 * np.pi * frequency * t
            mod  = np.sin(2 * np.pi * frequency * 0.25 * t)
            y = np.sin(carr + 2 * mod)
        elif osc_type == "PWM":
            y = signal.square(2 * np.pi * frequency * t, duty=0.5)
        elif osc_type == "Noise":
            rng = np.random.default_rng()
            y = rng.uniform(-1.0, 1.0, size=t.shape)
        else:
            raise ValueError(f"Unsupported oscillator type: {osc_type}")

        y = np.clip(amplitude * y, -1.0, 1.0)

        event = cls(name=f"{osc_type} Oscillator", category=EventCategory.CUSTOM)
        event.waveform_data = WaveformData(
            amplitude=_build_envelope_points(t, y),
            frequency=[{"time": 0.0, "frequency": frequency}, {"time": duration, "frequency": frequency}],
            duration=float(duration),
            sample_rate=float(sample_rate),
        )
        return event

    # --- effects pipeline (enhanced) ---
    def _apply_perceptual_loudness(self, sig: np.ndarray) -> np.ndarray:
        """Rough psychoacoustic scaling. Keep subtle to avoid clipping."""
        p = self.parameter_modifications
        if p.perceptual_loudness == 1.0:
            return sig
        loud = float(p.perceptual_loudness)
        if loud > 1.0:
            power = 0.6 + (loud - 1.0) * 0.4  # between 0.6 and 1.0
            enhanced = np.sign(sig) * np.power(np.abs(sig), power)
            return np.clip(enhanced * loud, -1.0, 1.0)
        return sig * loud

    def _apply_saturation(self, sig: np.ndarray) -> np.ndarray:
        """Soft clipping saturation with tanh; blend by amount."""
        amt = float(self.parameter_modifications.saturation_amount)
        if amt <= 0.0:
            return sig
        saturated = np.tanh(sig * (1 + amt * 4))
        return sig * (1 - amt) + saturated * amt

    def _apply_compression(self, sig: np.ndarray) -> np.ndarray:
        """Simple dynamics compressor above threshold."""
        p = self.parameter_modifications
        if p.compression_ratio <= 1.0:
            return sig
        thr = float(p.compression_threshold)
        ratio = float(p.compression_ratio)
        out = sig.copy()
        mask = np.abs(sig) > thr
        if np.any(mask):
            excess = np.abs(sig[mask]) - thr
            out[mask] = np.sign(sig[mask]) * (thr + excess / ratio)
        return out

    def _apply_tremolo(self, sig: np.ndarray, t: np.ndarray) -> np.ndarray:
        """Amplitude modulation with a sine LFO."""
        p = self.parameter_modifications
        if p.tremolo_rate == 0.0 or p.tremolo_depth == 0.0:
            return sig
        lfo = np.sin(2 * np.pi * float(p.tremolo_rate) * t)
        return sig * (1.0 + lfo * float(p.tremolo_depth))

    def _apply_frequency_modulation(self, sig: np.ndarray, t: np.ndarray) -> np.ndarray:
        """
        Cheap phase-based "FM-like" effect. Note: true FM requires regenerating
        the carrier; this is a light approximation for preview UX.
        """
        p = self.parameter_modifications
        if p.fm_rate == 0.0 or p.fm_depth == 0.0:
            return sig
        phase_mod = float(p.fm_depth) * np.sin(2 * np.pi * float(p.fm_rate) * t)
        out = sig.copy()
        # Sample-level shift approximation (very subtle, optional)
        n = sig.size
        for i in range(1, n):
            shift = int(phase_mod[i] * 0.1 * n)
            j = i + shift
            if 0 <= j < n:
                out[i] = sig[j]
        return out

    def _apply_phase_offset(self, sig: np.ndarray) -> np.ndarray:
        """Circular shift in samples based on degrees."""
        deg = float(self.parameter_modifications.phase_offset)
        if deg == 0.0 or sig.size == 0:
            return sig
        shift = int((deg % 360.0) / 360.0 * sig.size)
        if shift:
            return np.roll(sig, shift)
        return sig

    def _apply_adsr_envelope(self, sig: np.ndarray, t: np.ndarray) -> np.ndarray:
        """ADSR envelope; times are in seconds, mapped via sample_rate."""
        p = self.parameter_modifications
        sr = float(self.waveform_data.sample_rate)
        if (p.attack_time == 0 and p.decay_time == 0 and
            p.sustain_level == 1.0 and p.release_time == 0):
            return sig

        env = np.ones_like(t)
        atk = int(max(0, p.attack_time) * sr)
        dec = int(max(0, p.decay_time) * sr)
        rel = int(max(0, p.release_time) * sr)
        sus_level = float(p.sustain_level)

        # Attack
        if atk > 0:
            a_end = min(atk, env.size)
            env[:a_end] = np.linspace(0.0, 1.0, a_end, endpoint=True)

        # Decay
        if dec > 0:
            d_start = min(atk, env.size)
            d_end = min(d_start + dec, env.size)
            if d_end > d_start:
                env[d_start:d_end] = np.linspace(1.0, sus_level, d_end - d_start, endpoint=True)

        # Sustain
        s_start = min(atk + dec, env.size)
        s_end = max(0, env.size - rel)
        if s_end > s_start:
            env[s_start:s_end] = sus_level

        # Release
        if rel > 0 and s_end < env.size:
            env[s_end:] = np.linspace(env[s_end - 1] if s_end > 0 else sus_level, 0.0, env.size - s_end, endpoint=True)

        return sig * env

    # --- I/O from .haptic (minimal) ---
    def load_from_haptic_file(self, file_path: str) -> bool:
        """Load waveform data from a .haptic JSON file into WaveformData."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                h = json.load(f)

            signals = h.get("signals", {})
            continuous = signals.get("continuous", {})
            envelopes = continuous.get("envelopes", {})

            amp_data = envelopes.get("amplitude", []) or []
            freq_data = envelopes.get("frequency", []) or []

            duration = 0.0
            if amp_data:
                duration = max(duration, max(p["time"] for p in amp_data))
            if freq_data:
                duration = max(duration, max(p["time"] for p in freq_data))

            self.waveform_data = WaveformData(amplitude=amp_data, frequency=freq_data, duration=float(duration))
            self.original_haptic_file = file_path
            return True
        except Exception as e:
            print(f"Error loading haptic file: {e}")
            return False

    # --- Render after modifications ---
    def get_modified_waveform(self) -> Optional[np.ndarray]:
        """Amplitude after ALL user modifications (ADSR, tremolo, compression, etc.)."""
        if not self.waveform_data:
            return None
        amp = self.waveform_data.get_amplitude_array()
        if amp.size == 0:
            return None
        t = np.array([pt["time"] for pt in self.waveform_data.amplitude], dtype=float)

        p = self.parameter_modifications
        y = amp.copy()

        # Basic intensity and legacy offset
        y *= float(p.intensity_multiplier)
        y += float(p.amplitude_offset)

        # Custom envelope
        if p.custom_envelope and len(p.custom_envelope) == y.size:
            y *= np.asarray(p.custom_envelope, dtype=float)

        # ADSR
        y = self._apply_adsr_envelope(y, t)

        # FM-like + phase
        y = self._apply_frequency_modulation(y, t)
        y = self._apply_phase_offset(y)

        # Tremolo
        y = self._apply_tremolo(y, t)

        # Compression & saturation
        y = self._apply_compression(y)
        y = self._apply_saturation(y)

        # Perceptual loudness (last)
        y = self._apply_perceptual_loudness(y)

        return np.clip(y, -1.0, 1.0)

    def get_modified_frequency(self) -> Optional[np.ndarray]:
        """Frequency curve after user modifications (simple shift for now)."""
        if not self.waveform_data or not self.waveform_data.frequency:
            return None
        freq = self.waveform_data.get_frequency_array()
        if freq.size == 0:
            return None
        return freq + float(self.parameter_modifications.frequency_shift)

    # --- (de)serialisation ---
    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serialisable dict (Enum → value)."""
        md = asdict(self.metadata)
        md["category"] = self.metadata.category.value

        act = asdict(self.actuator_mapping)
        act["pattern_type"] = self.actuator_mapping.pattern_type.value

        return {
            "metadata": md,
            "waveform_data": asdict(self.waveform_data) if self.waveform_data else None,
            "parameter_modifications": asdict(self.parameter_modifications),
            "actuator_mapping": act,
            "original_haptic_file": self.original_haptic_file,
        }

    def save_to_file(self, file_path: str) -> bool:
        """Persist event as JSON; updates modified_date."""
        try:
            self.metadata.modified_date = datetime.now().isoformat()
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=2)
            return True
        except Exception as e:
            print(f"Error saving event: {e}")
            return False

    @classmethod
    def load_from_file(cls, file_path: str) -> Optional["HapticEvent"]:
        """Load event JSON from disk, rebuilding Enums and dataclasses."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            event = cls()

            # metadata
            md = data.get("metadata", {}) or {}
            if "category" in md:
                md["category"] = EventCategory(md["category"])
            event.metadata = EventMetadata(**md)

            # waveform
            wf = data.get("waveform_data")
            if wf:
                event.waveform_data = WaveformData(**wf)

            # parameter modifications
            pm = data.get("parameter_modifications", {}) or {}
            event.parameter_modifications = ParameterModifications(**pm)

            # actuators
            act = data.get("actuator_mapping", {}) or {}
            if "pattern_type" in act:
                act["pattern_type"] = ActuatorPattern(act["pattern_type"])
            event.actuator_mapping = ActuatorMapping(**act)

            event.original_haptic_file = data.get("original_haptic_file")
            return event
        except Exception as e:
            print(f"Error loading event: {e}")
            return None


# -----------------------------------------------------------------------------
# Local utility (for building WaveformData.amplitude)
# -----------------------------------------------------------------------------
def _build_envelope_points(t: np.ndarray, y: np.ndarray) -> List[Dict[str, float]]:
    """Convert two equal-length arrays into list-of-dicts for WaveformData."""
    return [{"time": float(tt), "amplitude": float(yy)} for tt, yy in zip(np.asarray(t, float), np.asarray(y, float))]