"""Free-space steering with exp(+jωt) and signed angles from +Z."""

from dataclasses import dataclass
from decimal import Decimal
from math import degrees, pi, radians, sin

C0 = 299_792_458


@dataclass(frozen=True)
class Steering:
    reflection_deg: float
    gradient_rad_m: float
    step_deg: float


def steering(frequency_ghz: float, pitch_mm: float, incident_deg: float, reflection_deg: float) -> Steering:
    k0 = 2 * pi * frequency_ghz * 1e9 / C0
    ki_x = -k0 * sin(radians(incident_deg))
    kr_x = k0 * sin(radians(reflection_deg))
    gradient = ki_x - kr_x
    return Steering(reflection_deg, gradient, degrees(gradient * pitch_mm / 1000))


def reflection_angles(target: float, half_width: float, step: float) -> tuple[float, ...]:
    """Take whole steps from the target, staying within the sweep and visible hemisphere."""
    center, radius, spacing = (Decimal(str(value)) for value in (target, half_width, step))
    if not -90 <= center <= 90 or radius < 0 or spacing <= 0:
        raise ValueError("Use a target from −90° to +90°, a nonnegative half-width, and a positive step.")
    below = min(radius, center + 90) // spacing
    above = min(radius, 90 - center) // spacing
    return tuple(float(center + i * spacing) for i in range(-int(below), int(above) + 1))
