"""Vega-Lite specifications for the sweep preview and angle convention."""

from math import cos, radians, sin

from ris.hfss import Sample
from ris.lookup import PhaseLookup

TEAL = "#087f73"
ORANGE = "#ad561e"
INK = "#385563"
MUTED = "#879ca7"


def sweep_chart(samples: tuple[Sample, ...], lookup: PhaseLookup) -> dict:
    points = [
        {
            "cap": sample.capacitance_pf,
            "phase": sample.phase_deg,
            "sample": index + 1,
            "status": "Excluded" if not eligible else "Preliminary" if sample.converged is False else "Eligible",
        }
        for index, (sample, eligible) in enumerate(zip(samples, lookup.eligible))
        if sample.valid
    ]
    # Each line has exactly two adjacent eligible samples so gaps remain visible.
    lines = [
        {"cap": sample.capacitance_pf, "phase": sample.phase_deg, "segment": index, "endpoint": endpoint}
        for index, first, second in lookup.segments
        for endpoint, sample in enumerate((first, second))
    ]
    return {
        "encoding": {
            "x": {"field": "cap", "type": "quantitative", "title": "Capacitance per gap (pF)", "scale": {"zero": False}},
            "y": {"field": "phase", "type": "quantitative", "title": "Unwrapped phase (°)", "scale": {"zero": False}},
        },
        "layer": [
            {
                "data": {"values": lines},
                "mark": {"type": "line", "color": TEAL, "strokeWidth": 2},
                "encoding": {
                    "detail": {"field": "segment", "type": "nominal"},
                    "order": {"field": "endpoint", "type": "ordinal"},
                },
            },
            {
                "data": {"values": points},
                "mark": {"type": "point", "filled": True, "size": 55, "opacity": 1},
                "encoding": {
                    "color": {
                        "field": "status",
                        "type": "nominal",
                        "scale": {"domain": ["Eligible", "Preliminary", "Excluded"], "range": [TEAL, ORANGE, MUTED]},
                        "legend": {"title": None, "orient": "top"},
                    },
                    "tooltip": [
                        {"field": "sample", "title": "CSV sample"},
                        {"field": "cap", "title": "Capacitance (pF)", "format": ".5g"},
                        {"field": "phase", "title": "Unwrapped phase (°)", "format": ".3f"},
                        {"field": "status", "title": "Lookup eligibility"},
                    ],
                },
            },
        ],
    }


def angle_chart() -> dict:
    """Draw a schematic with both positive angles measured from the normal."""
    origin = (0.0, 0.0)
    solid = []
    labels = []

    def vector(angle: float, length: float) -> tuple[float, float]:
        return length * sin(radians(angle)), length * cos(radians(angle))

    def segment(start: tuple[float, float], end: tuple[float, float], color: str) -> dict:
        return dict(x=start[0], z=start[1], x2=end[0], z2=end[1], color=color)

    def arrow(start: tuple[float, float], end: tuple[float, float], direction: float, color: str) -> None:
        solid.append(segment(start, end, color))
        for wing in (-25, 25):
            x, z = vector(direction + 180 + wing, 0.12)
            solid.append(segment(end, (end[0] + x, end[1] + z), color))

    def label(x: float, z: float, value: str, color: str) -> None:
        labels.append(dict(x=x, z=z, label=value, color=color))

    arrow(origin, (0.0, 1.38), 0, INK)
    arrow(origin, (1.55, 0.0), 90, INK)
    arrow(vector(57, 1.36), origin, 237, ORANGE)
    arrow(origin, vector(27, 1.34), 27, TEAL)
    for angle, radius, color in ((57, 0.43, ORANGE), (27, 0.85, TEAL)):
        arc = [vector(angle * index / 18, radius) for index in range(19)]
        solid.extend(segment(start, end, color) for start, end in zip(arc, arc[1:]))

    label(-0.06, 1.51, "+Z normal", INK)
    label(1.62, -0.13, "+X", INK)
    label(1.27, 0.85, "Transmitter", ORANGE)
    label(0.83, 1.31, "Reflected", TEAL)
    label(0.29, 0.47, "θᵢ", ORANGE)
    label(0.23, 0.94, "θᵣ", TEAL)
    label(0.03, -0.16, "C1 · x = 0", INK)
    label(1.0, -0.16, "RIS panel", INK)
    position = {
        "x": {"field": "x", "type": "quantitative", "axis": None, "scale": {"domain": [-0.40, 1.93]}},
        "y": {"field": "z", "type": "quantitative", "axis": None, "scale": {"domain": [-0.26, 1.62]}},
        "color": {"field": "color", "type": "nominal", "scale": None},
    }
    return {
        "config": {"view": {"stroke": None}},
        "layer": [
            {
                "data": {"values": solid},
                "mark": {"type": "rule", "strokeWidth": 2},
                "encoding": {**position, "x2": {"field": "x2"}, "y2": {"field": "z2"}},
            },
            {
                "data": {"values": labels},
                "mark": {"type": "text", "fontSize": 13, "fontWeight": 550},
                "encoding": {**position, "text": {"field": "label"}},
            },
        ],
    }
