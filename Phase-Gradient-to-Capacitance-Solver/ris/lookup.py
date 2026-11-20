"""Piecewise-linear phase inversion and circular coverage optimization."""

from collections import defaultdict
from dataclasses import dataclass
from math import ceil, floor

from ris.hfss import Sample

TURN = 360.0
EPSILON = 1e-9
Interval = tuple[float, float]


def wrap(phase: float) -> float:
    value = phase % TURN
    return 0.0 if value <= EPSILON or TURN - value <= EPSILON else value


def circular_error(achieved_deg: float, target_deg: float) -> float:
    return (wrap(achieved_deg) - wrap(target_deg) + 180) % TURN - 180


def merge_intervals(intervals: list[Interval]) -> list[Interval]:
    merged: list[Interval] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1] + EPSILON:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _split_circle(start: float, width: float) -> list[Interval]:
    if width >= TURN - EPSILON:
        return [(0.0, TURN)]
    start = wrap(start)
    end = start + width
    if end < TURN - EPSILON:
        return [(start, end)]
    # Preserve phase 0 as an eligible endpoint even when an interval ends at 360.
    return [(start, TURN), (0.0, max(0.0, end - TURN))]


def circular_regions(intervals: list[Interval]) -> list[Interval]:
    """Represent a component crossing 0° by an end greater than 360°."""
    if len(intervals) > 1 and intervals[0][0] <= EPSILON and intervals[-1][1] >= TURN - EPSILON:
        return intervals[1:-1] + [(intervals[-1][0], TURN + intervals[0][1])]
    return intervals


@dataclass(frozen=True)
class Match:
    capacitance_pf: float
    phase_deg: float
    magnitude_db: float | None
    converged: bool | None


def _interpolate(first: Sample, second: Sample, phase: float) -> Match:
    weight = (phase - first.phase_deg) / (second.phase_deg - first.phase_deg)
    capacitance = first.capacitance_pf + weight * (second.capacitance_pf - first.capacitance_pf)
    magnitude = None
    if first.magnitude_db is not None and second.magnitude_db is not None:
        magnitude = first.magnitude_db + weight * (second.magnitude_db - first.magnitude_db)
    flags = (first.converged, second.converged)
    convergence = False if False in flags else True if all(flags) else None
    return Match(capacitance, phase, magnitude, convergence)


class PhaseLookup:
    def __init__(self, samples: tuple[Sample, ...], include_preliminary: bool = False):
        self.eligible = tuple(
            sample.valid and (include_preliminary or sample.converged is not False) for sample in samples
        )
        self.points = tuple(sample for sample, eligible in zip(samples, self.eligible) if eligible)
        self.segments = tuple(
            (index, first, second)
            for index, (first, second) in enumerate(zip(samples, samples[1:]))
            if self.eligible[index] and self.eligible[index + 1] and first.capacitance_pf != second.capacitance_pf
        )
        intervals = [(wrap(sample.phase_deg), wrap(sample.phase_deg)) for sample in self.points]
        for _, first, second in self.segments:
            low, high = sorted((first.phase_deg, second.phase_deg))
            intervals.extend(_split_circle(low, high - low))
        self.coverage = merge_intervals(intervals)

    def match(self, target_deg: float) -> Match | None:
        target = wrap(target_deg)
        solutions = [
            Match(sample.capacitance_pf, sample.phase_deg, sample.magnitude_db, sample.converged)
            for sample in self.points
            if abs(circular_error(sample.phase_deg, target)) <= EPSILON
        ]
        for _, first, second in self.segments:
            low, high = sorted((first.phase_deg, second.phase_deg))
            if high - low <= 2 * EPSILON:
                continue
            # Interior matches on a segment are ordered by both capacitance and
            # any interpolated dB value, so only the two extreme turns can win.
            first_turn = floor((low + EPSILON - target) / TURN) + 1
            last_turn = ceil((high - EPSILON - target) / TURN) - 1
            if first_turn <= last_turn:
                for turn in sorted({first_turn, last_turn}):
                    solutions.append(_interpolate(first, second, target + turn * TURN))

        def priority(solution: Match) -> tuple[float, bool, float]:
            loss = -solution.magnitude_db if solution.magnitude_db is not None else float("inf")
            return loss, solution.converged is False, solution.capacitance_pf

        return min(solutions, key=priority, default=None)


@dataclass(frozen=True)
class StartChoice:
    phase_deg: float
    fit: int
    interval: Interval | None


@dataclass(frozen=True)
class ColumnLoad:
    number: int
    position_mm: float
    target_deg: float
    match: Match | None

    @property
    def error_deg(self) -> float | None:
        return circular_error(self.match.phase_deg, self.target_deg) if self.match else None


def column_profile(
    lookup: PhaseLookup, count: int, pitch_mm: float, start_deg: float, step_deg: float
) -> tuple[ColumnLoad, ...]:
    profile = []
    for index in range(count):
        target = start_deg + index * step_deg
        profile.append(ColumnLoad(index + 1, index * pitch_mm, target, lookup.match(target)))
    return tuple(profile)


def _shift_coverage(coverage: list[Interval], offset: float) -> list[Interval]:
    return merge_intervals([
        part
        for start, end in coverage
        for part in _split_circle(start - offset, end - start)
    ])


def best_start(coverage: list[Interval], count: int, step_deg: float) -> StartChoice:
    if not coverage or count <= 0:
        return StartChoice(0.0, 0, None)
    events = defaultdict(lambda: [0, 0])
    events[0.0]
    events[TURN]
    for column in range(count):
        for start, end in _shift_coverage(coverage, column * step_deg):
            events[start][0] += 1
            events[end][1] += 1

    grouped: list[tuple[float, int, int]] = []
    for position, (begins, ends) in sorted(events.items()):
        if grouped and position - grouped[-1][0] <= EPSILON and position != TURN:
            anchor, previous_begins, previous_ends = grouped[-1]
            grouped[-1] = (anchor, previous_begins + begins, previous_ends + ends)
        else:
            grouped.append((position, begins, ends))

    # Closed endpoints count even when several columns meet only at one phase.
    scores: list[tuple[int, Interval]] = []
    active = 0
    previous = 0.0
    for position, begins, ends in grouped:
        if position > previous:
            scores.append((active, (previous, position)))
        if position < TURN:  # The 360° endpoint is already scored at 0°.
            scores.append((active + begins, (position, position)))
        active += begins - ends
        previous = position

    fit = max(score for score, _ in scores)
    regions = circular_regions(merge_intervals([interval for score, interval in scores if score == fit]))
    widest = max(end - start for start, end in regions)
    start, end = min(interval for interval in regions if widest - (interval[1] - interval[0]) <= EPSILON)
    return StartChoice(wrap((start + end) / 2), fit, (start, end))


def manual_interval(
    coverage: list[Interval], start_deg: float, step_deg: float, matched_columns: list[int]
) -> Interval | None:
    """Find the connected interval retaining all columns fitted at a manual start."""
    if not matched_columns:
        return None
    phase = wrap(start_deg)
    if coverage == [(0.0, TURN)]:
        return (0.0, TURN)

    lower, upper = phase - TURN, phase + TURN
    for column in matched_columns:
        regions = circular_regions(_shift_coverage(coverage, column * step_deg))
        for start, end in regions:
            for equivalent in (phase, phase + TURN):
                if start - EPSILON <= equivalent <= end + EPSILON:
                    offset = phase - equivalent
                    lower = max(lower, start + offset)
                    upper = min(upper, end + offset)
    left = wrap(lower)
    return left, left + max(0.0, upper - lower)
