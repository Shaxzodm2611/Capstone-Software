"""Local Streamlit dashboard for the RIS Steering Calculator."""

from hashlib import sha256
from math import isclose
from pathlib import Path

import pandas as pd
import streamlit as st

from ris.charts import angle_chart, sweep_chart
from ris.hfss import (
    CAPACITANCE_UNITS,
    PHASE_UNITS,
    ColumnMapping,
    RawCSV,
    Sweep,
    capacitance_unit,
    parse_sweep,
    phase_unit,
    read_csv,
    suggest_columns,
)
from ris.lookup import (
    EPSILON,
    TURN,
    ColumnLoad,
    Interval,
    PhaseLookup,
    best_start,
    circular_regions,
    column_profile,
    manual_interval,
)
from ris.steering import Steering, reflection_angles, steering

DEMO = Path(__file__).parent / "demo" / "synthetic_hfss_sweep.csv"
ANGLE_TABLE_KEY = "reflection-table"


def interval_label(interval: Interval) -> str:
    start, end = interval
    if end - start >= TURN - EPSILON:
        return "Any phase"
    if end - start <= EPSILON:
        return f"{start:.4g}° (single phase)"
    if end > TURN:
        return f"{start:.4g}° to {end - TURN:.4g}° across 0°"
    return f"{start:.4g}° to {end:.4g}°"


def map_csv(raw: RawCSV, key: str, synthetic: bool) -> ColumnMapping | None:
    suggested = suggest_columns(raw.headers)
    options = (None, *raw.headers)
    with st.expander("CSV columns and units", expanded=not synthetic):
        selected = {
            role: st.selectbox(
                label,
                options,
                index=options.index(suggested.get(role)),
                format_func=lambda value: value if value is not None else "Choose a column",
                key=f"{key}-{role}",
            )
            for role, label in (
                ("capacitance", "Capacitance"),
                ("phase", "Unwrapped reflection phase"),
                ("magnitude", "Reflection magnitude in dB (optional)"),
                ("convergence", "Convergence (optional)"),
            )
        }
        cap, phase = selected["capacitance"], selected["phase"]
        cap_units = (None, *CAPACITANCE_UNITS)
        phase_units = (None, *PHASE_UNITS)
        cap_scale = st.selectbox(
            "Capacitance unit", cap_units,
            index=cap_units.index(capacitance_unit(cap or "")), key=f"{key}-cap-unit-{cap}",
            format_func=lambda value: value or "Choose a unit",
        )
        phase_scale = st.selectbox(
            "Phase unit", phase_units,
            index=phase_units.index(phase_unit(phase or "")), key=f"{key}-phase-unit-{phase}",
            format_func=lambda value: value or "Choose a unit",
        )
        ready = all((cap, phase, cap_scale, phase_scale))
        if not synthetic and phase is not None and "unwrap" not in phase.lower():
            ready = st.checkbox(
                "This phase column is unwrapped",
                help="Confirm the trace is continuous along the capacitance sweep, including across ±180°.",
                key=f"{key}-unwrapped-{phase}",
            ) and ready
    if not ready:
        return None
    return ColumnMapping(cap, phase, cap_scale, phase_scale, selected["magnitude"], selected["convergence"])


def load_sweep() -> tuple[Sweep | None, bool, bool]:
    st.subheader("HFSS sweep")
    uploaded = st.file_uploader("Upload an HFSS CSV", type="csv", accept_multiple_files=False)
    synthetic = uploaded is None
    if synthetic:
        st.caption("Using the synthetic demo sweep.")
    content = DEMO.read_bytes() if synthetic else uploaded.getvalue()
    key = sha256(content).hexdigest()[:16]
    try:
        raw = read_csv(content)
        mapping = map_csv(raw, key, synthetic)
        if mapping is None:
            st.info("Confirm the phase and capacitance mappings and units.")
            return None, synthetic, False
        sweep = parse_sweep(raw, mapping)
    except ValueError as error:
        st.error(str(error))
        return None, synthetic, False
    preliminary = sweep.has_convergence and st.toggle(
        "Include unconverged samples",
        help="Show a preliminary preview. Rows that rely on an unconverged sample are flagged.",
        key=f"{key}-preliminary",
    )
    return sweep, synthetic, preliminary


def characterize(sweep: Sweep, frequency: float, incidence: float) -> None:
    details, mismatches = [], []
    for label, characterized, current, unit in (
        ("frequency", sweep.frequency_ghz, frequency, "GHz"),
        ("incidence", sweep.incident_deg, incidence, "°"),
    ):
        if characterized is None:
            continue
        details.append(f"{characterized:g} {unit} {label}")
        if not isclose(characterized, current, abs_tol=1e-6):
            mismatches.append(f"{label} is {characterized:g} {unit} in the CSV and {current:g} {unit} in the calculator")
    if mismatches:
        st.warning(f"Characterization mismatch. {' · '.join(mismatches)}.")
    elif details:
        st.caption(f"Characterized at {' and '.join(details)}.")


def select_angle(choices: tuple[Steering, ...], target: float) -> Steering:
    st.subheader("Table 1 · Steering angles")
    st.caption("Select a row to recalculate the panel profile.")
    target_row = next(index for index, choice in enumerate(choices) if choice.reflection_deg == target)
    data = pd.DataFrame({
        "Angle": [choice.reflection_deg for choice in choices],
        "Gradient": [choice.gradient_rad_m for choice in choices],
        "Step": [choice.step_deg for choice in choices],
    })
    styled = data.style.apply(
        lambda row: ["background-color: #e1f5ef; font-weight: bold" if row.name == target_row else ""] * len(row),
        axis=1,
    )
    event = st.dataframe(
        styled,
        column_config={
            "Angle": st.column_config.NumberColumn("Reflection (°)", format="%+.3f"),
            "Gradient": st.column_config.NumberColumn("Gradient (rad/m)", format="%.3f"),
            "Step": st.column_config.NumberColumn("Step (°/col)", format="%.3f"),
        },
        hide_index=True,
        height=min(215, 38 + len(choices) * 36),
        row_height=36,
        on_select="rerun",
        selection_mode="single-row-required",
        selection_default={"selection": {"rows": [target_row]}},
        key=f"{ANGLE_TABLE_KEY}-{target}-{choices[0].reflection_deg}-{choices[-1].reflection_deg}-{len(choices)}",
    )
    return choices[event.selection.rows[0] if event.selection.rows else target_row]


def show_profile(profile: tuple[ColumnLoad, ...], show_magnitude: bool) -> None:
    records = []
    for column in profile:
        match = column.match
        if match is None:
            status = "Unavailable"
        elif match.converged is False:
            status = "Preliminary"
        elif match.converged is None:
            status = "Convergence unknown"
        else:
            status = "Available"
        row = {
            "Column": f"C{column.number}",
            "Position (mm)": column.position_mm,
            "Target (°)": column.target_deg,
            "Cap. per gap (pF)": match.capacitance_pf if match else None,
            "Achieved (°)": match.phase_deg if match else None,
            "Error (°)": column.error_deg,
            "Status": status,
        }
        if show_magnitude:
            row["Reflection (dB)"] = match.magnitude_db if match else None
        records.append(row)

    st.dataframe(
        pd.DataFrame(records),
        key="capacitance-profile",
        hide_index=True,
        placeholder="",
        row_height=34,
        height=min(380, 38 + len(records) * 34),
        column_config={
            "Position (mm)": st.column_config.NumberColumn(format="%.2f"),
            "Target (°)": st.column_config.NumberColumn(format="%.3f", help="Continuous target phase ramp"),
            "Cap. per gap (pF)": st.column_config.NumberColumn(format="%.5g"),
            "Achieved (°)": st.column_config.NumberColumn(format="%.3f", help="Equivalent phase in the CSV's unwrapped range"),
            "Error (°)": st.column_config.NumberColumn(format="%.3f", help="Signed circular achieved minus target phase"),
            "Reflection (dB)": st.column_config.NumberColumn(format="%.2f"),
        },
    )


def show_lookup(sweep: Sweep, lookup: PhaseLookup) -> None:
    st.subheader("Phase sweep")
    eligible = sum(lookup.eligible)
    width = sum(end - start for start, end in lookup.coverage)
    st.caption(f"{eligible}/{len(sweep.samples)} eligible samples · {width:.1f}° of 360° usable")
    st.vega_lite_chart(sweep_chart(sweep.samples, lookup), width="stretch", height=190)
    regions = circular_regions(lookup.coverage)
    labels = " · ".join(interval_label(region) for region in regions) or "No eligible phase"
    if len(regions) <= 5:
        st.caption(f"Usable phase modulo 360° · {labels}")
    else:
        with st.expander(f"{len(regions)} usable phase intervals"):
            st.write(labels)
    if not sweep.has_convergence:
        st.caption("Convergence unknown. The CSV has no mapped convergence column.")
    elif any(sample.valid and sample.converged is None for sample in sweep.samples):
        st.caption("Some samples have unknown convergence status.")


def main() -> None:
    st.set_page_config(page_title="RIS Steering Calculator", layout="wide", initial_sidebar_state="expanded")
    with st.sidebar:
        st.header("Setup")
        sweep, synthetic, preliminary = load_sweep()
        st.divider()
        st.subheader("Panel and steering")
        frequency = st.number_input("Frequency (GHz)", min_value=0.001, value=2.4, step=0.1, format="%.3f")
        pitch = st.number_input("X pitch (mm)", min_value=0.001, value=20.0, step=1.0, format="%.3f")
        count = st.number_input("Number of columns", min_value=1, value=10, step=1)
        incidence = st.number_input("Incident angle (°)", -90.0, 90.0, 0.0, step=1.0, format="%.3f")
        target = st.number_input("Desired reflection angle (°)", -90.0, 90.0, 30.0, step=1.0, format="%.3f")
        with st.expander("Reflection-angle sweep"):
            half_width = st.number_input("Half-width (°)", 0.0, 180.0, 5.0, step=1.0, format="%.3f")
            sweep_step = st.number_input("Step (°)", min_value=0.1, value=5.0, step=0.5, format="%.3f")

    st.title("RIS Steering Calculator")
    st.caption("Steering gradients and per-gap capacitances for a periodic unit-cell sweep.")
    if synthetic:
        st.info("Synthetic demo data. Upload an HFSS sweep to calculate a profile for your unit cell.")
    if sweep:
        characterize(sweep, frequency, incidence)
    lookup = PhaseLookup(sweep.samples, preliminary) if sweep else None

    choices = tuple(
        steering(frequency, pitch, incidence, angle) for angle in reflection_angles(target, half_width, sweep_step)
    )
    left, right = st.columns([1, 2], gap="medium")
    with left, st.container(border=True):
        chosen = select_angle(choices, target)
    if lookup is not None:
        with left, st.container(border=True):
            show_lookup(sweep, lookup)
    with right, st.container(border=True):
        st.subheader("Table 2 · Column capacitances")
        st.caption(f"Reflection {chosen.reflection_deg:+g}° · Incidence {incidence:+g}° · C1 at x = 0")
        if lookup is None:
            st.info("Upload and map a sweep to calculate capacitances.")
        else:
            auto = best_start(lookup.coverage, count, chosen.step_deg)
            manual = st.toggle("Manual starting phase")
            start = auto.phase_deg
            if manual:
                start = st.number_input(
                    "Starting phase (°)", value=auto.phase_deg, step=1.0, format="%.6f", key="manual-phase"
                )
            profile = column_profile(lookup, count, pitch, start, chosen.step_deg)
            matched = [column.number - 1 for column in profile if column.match is not None]
            interval = manual_interval(lookup.coverage, start, chosen.step_deg, matched) if manual else auto.interval
            phase_metric, fit_metric = st.columns(2)
            phase_metric.metric("Starting phase", f"{start:.3f}°")
            fit_metric.metric("Columns fitted", f"{len(matched)} / {count}")
            if interval is None:
                st.caption("No feasible interval for this profile.")
            elif manual:
                st.caption(f"Interval retaining these columns · {interval_label(interval)}")
            else:
                st.caption(f"Best feasible interval · {interval_label(interval)}")
            if manual:
                st.caption(f"Automatic setting fits {auto.fit}/{count} columns at {auto.phase_deg:.3f}°.")
            with st.expander("How the starting phase is chosen"):
                st.write(
                    "Each column shifts the eligible phase coverage by the negative of its ramp offset. "
                    "The automatic start maximizes the number of overlapping column intervals modulo 360°. "
                    "It takes the midpoint of the widest tied interval, then favors the lowest interval start."
                )
            show_profile(profile, sweep.has_magnitude)
            if preliminary:
                st.warning("Preliminary preview is enabled. Rows using an unconverged sample are marked Preliminary.")
            st.caption("Verify the actual reflected beam direction separately in a finite-panel HFSS simulation.")

    with left, st.container(border=True):
        st.subheader("XZ-plane angle convention")
        st.vega_lite_chart(angle_chart(), width="stretch", height=190)
        st.caption("Both angles are measured from +Z. Positive incidence puts the transmitter on +X. "
                   "Positive reflection points the outgoing beam toward +X.")
        with st.expander("Steering equations"):
            st.latex(r"\Gamma=|\Gamma|e^{j\phi},\qquad k_0=2\pi f/c")
            st.latex(r"k_{i,x}=-k_0\sin\theta_i,\qquad k_{r,x}=k_0\sin\theta_r")
            st.latex(r"g=k_{i,x}-k_{r,x},\qquad \Delta\phi=g\,p_x,\qquad \phi_n=\phi_{\mathrm{start}}+(n-1)\Delta\phi")
            st.caption("Phasor convention exp(+jωt). Column positions increase along +X.")


if __name__ == "__main__":
    main()
