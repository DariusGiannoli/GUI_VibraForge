from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Dict, List, Tuple, Optional
import math
import json
import itertools
import time

# Paper constants (Park et al. 2016)
SOA_SLOPE = 0.32              # s/s
SOA_INTERCEPT_S = 0.0473      # s
MAX_DURATION_MS = 70          # ensure duration < SOA (no overlap)
DEFAULT_DURATION_MS = 60
DEFAULT_FREQ_HZ = 250

@dataclass
class PhantomPoint:
    x: float
    y: float
    t_ms: int

@dataclass
class PhantomStep:
    phantom_index: int
    phantom_pos: Tuple[float, float]
    onset_ms: int
    duration_ms: int
    waveform: str
    # three physical actuators + their intensities (1..15)
    a1: int; a2: int; a3: int
    i1: int; i2: int; i3: int

@dataclass
class PreviewBundle:
    name: str
    layout_positions: Dict[int, Tuple[float, float]]
    path_points: List[Tuple[float, float]]
    samples: List[PhantomPoint]
    steps: List[PhantomStep]
    created_ts: float

    def to_json(self) -> str:
        return json.dumps({
            "name": self.name,
            "layout_positions": self.layout_positions,
            "path_points": self.path_points,
            "samples": [asdict(s) for s in self.samples],
            "steps": [asdict(s) for s in self.steps],
            "created_ts": self.created_ts
        }, indent=2)

    @staticmethod
    def from_json(s: str) -> "PreviewBundle":
        data = json.loads(s)
        samples = [PhantomPoint(**pp) for pp in data["samples"]]
        steps = [PhantomStep(**ps) for ps in data["steps"]]
        return PreviewBundle(
            name=data["name"],
            layout_positions={int(k): tuple(v) for k, v in data["layout_positions"].items()},
            path_points=[tuple(p) for p in data["path_points"]],
            samples=samples,
            steps=steps,
            created_ts=data["created_ts"],
        )

class PhantomEngine:
    """
    Computes triangle set, picks best triangle per sample, computes 3-actuator
    phantom intensities, produces a timed step list for preview & playback.
    Coordinates are in millimeters in the same space as your layout.
    """

    def __init__(self, layout_positions: Dict[int, Tuple[float, float]]):
        self.set_layout(layout_positions)
        self.waveform: str = "Sine"
        self.duration_ms: int = DEFAULT_DURATION_MS
        self.freq_hz: int = DEFAULT_FREQ_HZ

    def set_layout(self, positions: Dict[int, Tuple[float, float]]):
        self.positions = dict(positions)
        self._triangles = self._compute_triangles()

    def set_waveform(self, name: str):
        self.waveform = name

    def set_duration_intensity(self, duration_ms: int):
        self.duration_ms = max(30, min(MAX_DURATION_MS, int(duration_ms)))

    def set_frequency(self, hz: int):
        self.freq_hz = max(50, min(1000, int(hz)))

    # ---------- core math ----------
    @staticmethod
    def _triangle_area(a, b, c) -> float:
        return abs((a[0]*(b[1]-c[1]) + b[0]*(c[1]-a[1]) + c[0]*(a[1]-b[1]))/2.0)

    def _compute_triangles(self):
        ids = list(self.positions.keys())
        tris = []
        for i, j, k in itertools.combinations(ids, 3):
            p1, p2, p3 = self.positions[i], self.positions[j], self.positions[k]
            area = self._triangle_area(p1, p2, p3)
            if 25 <= area <= 8000:  # generous bounds for coverage
                perim = (math.dist(p1, p2) + math.dist(p2, p3) + math.dist(p3, p1))
                smoothness = perim * 0.1 + (perim**2)/(12*math.sqrt(3)*area)
                tris.append({
                    "ids": (i, j, k),
                    "pos": (p1, p2, p3),
                    "area": area,
                    "center": ((p1[0]+p2[0]+p3[0])/3.0, (p1[1]+p2[1]+p3[1])/3.0),
                    "smooth": smoothness
                })
        # prioritize smoother & mid-sized triangles
        tris.sort(key=lambda t: (t["smooth"], t["area"]))
        return tris[:75]

    @staticmethod
    def _point_in_triangle(p, a, b, c) -> bool:
        def sign(p1, p2, p3):
            return (p1[0] - p3[0])*(p2[1] - p3[1]) - (p2[0] - p3[0])*(p1[1] - p2[1])
        d1 = sign(p, a, b); d2 = sign(p, b, c); d3 = sign(p, c, a)
        has_neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
        has_pos = (d1 > 0) or (d2 > 0) or (d3 > 0)
        return not (has_neg and has_pos)

    def _best_triangle(self, p: Tuple[float, float]) -> Optional[dict]:
        candidates = [t for t in self._triangles if self._point_in_triangle(p, *t["pos"])]
        if candidates:
            return min(candidates, key=lambda t: t["smooth"])
        # fallback: closest center
        if not self._triangles:
            return None
        return min(self._triangles, key=lambda t: math.dist(p, t["center"]) + 10*t["smooth"])

    @staticmethod
    def _three_actuator_intensities(p, tri_pos, desired_1_15: int) -> Tuple[int, int, int]:
        # Park et al. 3-actuator energy model: Ai ∝ sqrt((1/di) / Σ(1/dj)), clamped to 1..15
        dists = [max(1.0, math.dist(p, q)) for q in tri_pos]
        denom = sum(1.0/d for d in dists)
        norm = [math.sqrt((1.0/d) / denom) for d in dists]
        scale = max(1, min(15, desired_1_15))
        vals = [max(1, min(15, round(n * scale))) for n in norm]
        return tuple(vals)  # i1, i2, i3

    @staticmethod
    def soa_ms_for_duration(duration_ms: int) -> int:
        # SOA(s) = 0.32*dur(s) + 0.0473  -> ms
        soa_s = SOA_SLOPE * (duration_ms / 1000.0) + SOA_INTERCEPT_S
        return max(duration_ms + 1, int(round(soa_s * 1000.0)))

    # ---------- public API ----------
    def sample_path(self, path_points: List[Tuple[float, float]], sampling_ms: int, max_samples: int) -> List[PhantomPoint]:
        if len(path_points) < 2:
            return []
        # even sampling along polyline length
        # compute total length
        segs = list(zip(path_points[:-1], path_points[1:]))
        lengths = [math.dist(a, b) for a, b in segs]
        total = sum(lengths) or 1.0
        n = max(3, min(max_samples, total and int(total/100.0*max_samples) or max_samples))
        pts: List[PhantomPoint] = []
        t_acc = 0
        target_d = [i/(n-1)*total for i in range(n)]
        # walk segments
        si = 0
        acc = 0.0
        for idx, td in enumerate(target_d):
            while si < len(segs) and acc + lengths[si] < td:
                acc += lengths[si]; si += 1
            if si >= len(segs):
                a, b, seglen = segs[-1][0], segs[-1][1], lengths[-1]
            else:
                a, b, seglen = segs[si][0], segs[si][1], lengths[si]
            remain = td - acc
            u = 0 if seglen == 0 else remain/seglen
            x = a[0] + u*(b[0]-a[0]); y = a[1] + u*(b[1]-a[1])
            pts.append(PhantomPoint(x=x, y=y, t_ms=t_acc))
            t_acc += max(20, sampling_ms // 3)  # faster motion while obeying non-overlap
        return pts

    def build_preview(self,
                      name: str,
                      path_points: List[Tuple[float, float]],
                      sampling_ms: int,
                      max_samples: int,
                      desired_intensity_1_15: int) -> PreviewBundle:
        samples = self.sample_path(path_points, sampling_ms, max_samples)
        steps: List[PhantomStep] = []
        for idx, s in enumerate(samples):
            tri = self._best_triangle((s.x, s.y))
            if not tri:
                continue
            i1, i2, i3 = self._three_actuator_intensities((s.x, s.y), tri["pos"], desired_intensity_1_15)
            a1, a2, a3 = tri["ids"]
            steps.append(PhantomStep(
                phantom_index=idx,
                phantom_pos=(s.x, s.y),
                onset_ms=s.t_ms,
                duration_ms=self.duration_ms,
                waveform=self.waveform,
                a1=a1, a2=a2, a3=a3,
                i1=i1, i2=i2, i3=i3
            ))
        return PreviewBundle(
            name=name,
            layout_positions=self.positions,
            path_points=path_points,
            samples=samples,
            steps=steps,
            created_ts=time.time()
        )