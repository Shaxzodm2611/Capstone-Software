"""Read a numeric HFSS export and preserve row order for interpolation."""

import csv
import re
from dataclasses import dataclass
from math import degrees, isclose, isfinite

CAPACITANCE_UNITS = {"fF": 1e-3, "pF": 1.0, "nF": 1e3, "µF": 1e6, "F": 1e12}
FREQUENCY_UNITS = {"hz": 1e-9, "khz": 1e-6, "mhz": 1e-3, "ghz": 1.0}
PHASE_UNITS = ("deg", "rad")
ROLES = ("capacitance", "phase", "magnitude", "convergence")


@dataclass(frozen=True)
class RawCSV:
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    metadata: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ColumnMapping:
    capacitance: str
    phase: str
    capacitance_unit: str
    phase_unit: str
    magnitude: str | None = None
    convergence: str | None = None


@dataclass(frozen=True)
class Sample:
    capacitance_pf: float | None
    phase_deg: float | None
    magnitude_db: float | None = None
    converged: bool | None = None

    @property
    def valid(self) -> bool:
        return self.capacitance_pf is not None and self.phase_deg is not None


@dataclass(frozen=True)
class Sweep:
    samples: tuple[Sample, ...]
    has_magnitude: bool
    has_convergence: bool
    frequency_ghz: float | None
    incident_deg: float | None


def read_csv(content: bytes) -> RawCSV:
    if content.startswith((b"\xff\xfe", b"\xfe\xff")):
        source = content.decode("utf-16")
    else:
        try:
            source = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            source = content.decode("cp1252")

    metadata = []
    data_lines = []
    for line in source.splitlines():
        if line.lstrip().startswith(("#", "//")):
            entry = re.match(r"\s*(?:#|//)\s*([^:=]+)\s*[:=]\s*(.+)", line)
            if entry:
                metadata.append((entry[1].strip(), entry[2].strip()))
        elif line.strip():
            data_lines.append(line)

    if not data_lines:
        raise ValueError("The CSV is empty.")

    # The header can contain quoted HFSS expressions with embedded commas.
    delimiter = max((",", ";", "\t"), key=lambda value: len(next(csv.reader(data_lines[:1], delimiter=value))))
    try:
        records = csv.reader(data_lines, delimiter=delimiter, strict=True)
        headers = tuple(cell.strip() for cell in next(records))
        if len(headers) < 2 or not all(headers) or len(set(headers)) != len(headers):
            raise ValueError("Use a header row with unique names for the capacitance and phase columns.")
        rows = []
        for row in records:
            if len(row) > len(headers):
                raise ValueError(f"Data row {records.line_num - 1} has more fields than the header.")
            rows.append(tuple(cell.strip() for cell in row) + ("",) * (len(headers) - len(row)))
    except csv.Error as error:
        raise ValueError(f"Could not read the CSV fields ({error}).") from error
    if not rows:
        raise ValueError("The CSV has a header but no samples.")
    return RawCSV(headers, tuple(rows), tuple(metadata))


def _name(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", re.split(r"\s*\[", header.lower(), maxsplit=1)[0])


def unwrapped_header(header: str) -> bool:
    return "unwrap" in header.lower() or bool(re.match(r"\s*cang[_ (]", header, re.IGNORECASE))


def suggest_columns(headers: tuple[str, ...]) -> dict[str, str]:
    candidates = {role: [] for role in ROLES}
    for header in headers:
        name = _name(header)
        words = re.split(r"[^a-z0-9]+", header.lower())
        if "capacitance" in name or name in {"c", "cap", "cgap", "cvar", "cvaractor", "varactorc", "lumpedc"}:
            candidates["capacitance"].append(header)
        elif "phase" in name or re.match(r"\s*(?:c?ang)[_ (]", header, re.IGNORECASE):
            candidates["phase"].append(header)
        elif "converg" in name or name in {"status", "solvestatus"}:
            candidates["convergence"].append(header)
        elif "db" in words or re.match(r"\s*db\d*\s*\(", header, re.IGNORECASE):
            candidates["magnitude"].append(header)

    unwrapped = [header for header in candidates["phase"] if unwrapped_header(header)]
    if unwrapped:
        candidates["phase"] = unwrapped
    return {role: matches[0] for role, matches in candidates.items() if len(matches) == 1}


def _unit(text: str, names: tuple[str, ...]) -> str | None:
    normalized = text.lower().replace("μ", "µ")
    for name in names:
        if re.search(rf"(?<![a-zµ]){re.escape(name.lower())}(?![a-zµ])", normalized):
            return name
    return None


def capacitance_unit(header: str) -> str | None:
    # A lone variable named F should not be mistaken for an explicit unit.
    return _unit(header, tuple(CAPACITANCE_UNITS)) if len(header.strip()) > 2 else None


def phase_unit(header: str) -> str | None:
    if "°" in header or re.search(r"\bdegrees?\b", header, re.IGNORECASE):
        return "deg"
    if re.search(r"\bradians?\b", header, re.IGNORECASE):
        return "rad"
    return _unit(header, PHASE_UNITS)


def _number(text: str) -> float | None:
    try:
        value = float(text.replace("−", "-"))
    except ValueError:
        return None
    return value if isfinite(value) else None


def _convergence(text: str) -> bool | None:
    normalized = re.sub(r"[^a-z0-9]", "", text.lower())
    if normalized in {"true", "yes", "converged", "pass", "passed"} or _number(text) == 1:
        return True
    if normalized in {"false", "no", "unconverged", "notconverged", "nonconverged", "failed", "fail"} or _number(text) == 0:
        return False
    return None


def _characterization(raw: RawCSV) -> tuple[float | None, float | None]:
    frequency = []
    incidence = []
    sources = [(key, None, value) for key, value in raw.metadata]
    sources.extend((header, index, "") for index, header in enumerate(raw.headers))
    for label, index, metadata_value in sources:
        name = _name(label)
        freq = re.fullmatch(r"(?:freq(?:uency)?|sweepfreq(?:uency)?)(?:[kmg]?hz)?", name)
        angle = re.fullmatch(
            r"(?:incident(?:angle|theta)|incidence(?:angle)?|thetai|thetaincident)(?:deg(?:rees?)?|rad(?:ians?)?)?",
            name,
        )
        if not (freq or angle):
            continue
        entries = (metadata_value,) if index is None else (row[index] for row in raw.rows)
        for entry in entries:
            match = re.fullmatch(r"\s*([+−-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?)\s*(.*?)\s*", entry, re.IGNORECASE)
            if not match:
                continue
            value = _number(match[1])
            if value is None:
                continue
            if freq:
                unit = _unit(match[2], tuple(FREQUENCY_UNITS)) or _unit(label, tuple(FREQUENCY_UNITS))
                if unit:
                    frequency.append(value * FREQUENCY_UNITS[unit])
            else:
                unit = phase_unit(match[2]) or phase_unit(label)
                if unit:
                    incidence.append(degrees(value) if unit == "rad" else value)

    for values, description in ((frequency, "frequencies"), (incidence, "incident angles")):
        if values and any(not isclose(value, values[0], rel_tol=1e-9, abs_tol=1e-8) for value in values):
            raise ValueError(f"The export contains multiple characterization {description}. Export one condition per CSV.")
    return (frequency[0] if frequency else None, incidence[0] if incidence else None)


def parse_sweep(raw: RawCSV, mapping: ColumnMapping) -> Sweep:
    columns = (mapping.capacitance, mapping.phase, mapping.magnitude, mapping.convergence)
    assigned = [column for column in columns if column is not None]
    if len(assigned) != len(set(assigned)) or any(column not in raw.headers for column in assigned):
        raise ValueError("Assign a different CSV column to each field.")
    if mapping.capacitance_unit not in CAPACITANCE_UNITS or mapping.phase_unit not in PHASE_UNITS:
        raise ValueError("Confirm capacitance and phase units.")

    cap, phase = (raw.headers.index(column) for column in columns[:2])
    mag = raw.headers.index(mapping.magnitude) if mapping.magnitude else None
    conv = raw.headers.index(mapping.convergence) if mapping.convergence else None
    scale = CAPACITANCE_UNITS[mapping.capacitance_unit]
    samples = []
    for row in raw.rows:
        capacitance = _number(row[cap])
        phase_deg = _number(row[phase])
        if capacitance is not None:
            capacitance *= scale
            if not isfinite(capacitance) or capacitance < 0:
                capacitance = None
        if phase_deg is not None and mapping.phase_unit == "rad":
            phase_deg = degrees(phase_deg)
            if not isfinite(phase_deg):
                phase_deg = None
        samples.append(Sample(
            capacitance,
            phase_deg,
            _number(row[mag]) if mag is not None else None,
            _convergence(row[conv]) if conv is not None else None,
        ))
    if not any(sample.valid for sample in samples):
        raise ValueError("No row contains both a numeric, nonnegative capacitance and a numeric phase.")
    frequency, incidence = _characterization(raw)
    return Sweep(tuple(samples), mag is not None, conv is not None, frequency, incidence)
