# RIS Steering Calculator

## AI disclosure

OpenAI Codex generated the initial application, synthetic data, verification tests, and documentation from the prompt reproduced verbatim below. Codex also ran the automated checks described in this README. The synthetic CSV is for demonstration and contains no HFSS simulation results.

## Run locally on Windows

```powershell
uv sync
uv run streamlit run app.py
```

The app opens with a clearly labelled synthetic demo. Upload an HFSS CSV to replace it. Confirm the column mappings and units, enter the steering inputs, and select a reflection angle in Table 1 to view its per-gap capacitances in Table 2.

## HFSS export

Export one frequency and incidence condition per CSV, with capacitance and a continuous, unwrapped phase trace along the capacitance sweep. The lookup preserves CSV row order. Include optional reflection magnitude in dB and convergence status to rank competing matches and identify preliminary values. The calculator recognizes characterization metadata in columns such as `Freq [GHz]` and `Theta_i [deg]` or comment lines such as `# Frequency [GHz]: 2.4` and `# Incident angle [deg]: 0`.

The calculator produces candidate per-gap loads from periodic unit-cell data. Verify the actual reflected beam direction in a separate finite-panel HFSS simulation.

## Verification

Run the verification suite with `uv run python -m unittest discover -s tests`.

## Prompt used to generate the app

````text
Build a modern local Streamlit app in Python called RIS Steering Calculator. Use uv for dependency and environment management. Include a pyproject.toml, uv.lock, and a short README. The app should run on Windows with `uv sync` followed by `uv run streamlit run app.py`.

The app takes an HFSS CSV of unwrapped reflection phase versus capacitance and calculates the phase gradient and per-column capacitances for a desired reflected beam direction. The workflow is upload the sweep, enter the steering angles, select a reflection angle in Table 1, then read the C1–C10 values in Table 2.

## Inputs and layout

- Upload the numeric HFSS CSV. Require capacitance and unwrapped phase. Accept optional reflection magnitude in dB and convergence status. Recognize HFSS-style headers and let the user map columns and confirm units when needed. Show a compact preview of the imported phase curve and its usable coverage.
- Provide editable inputs for frequency (2.4 GHz), X pitch (20 mm), number of columns (10), signed incident angle (0°), and desired signed reflection angle (+30°).
- Make the reflection-angle sweep half-width and step editable. Default both to 5°, so a +30° target shows +25°, +30°, and +35°. Always include the exact target angle and select it initially.
- Use a clean dashboard layout with inputs grouped together and both tables visible in the main area. Keep units visible and use clear status labels for unavailable capacitances and preliminary results.

## Angle convention and steering math

Show a small XZ-plane diagram with the surface normal along +Z. Both angles are measured from +Z. The incident angle is positive when the transmitter is on the +X side. The reflected angle is positive when the outgoing beam points toward +X. C1 starts at x = 0 and column positions increase along +X.

Use the exp(+jωt) phasor convention and define the reflection coefficient as Γ = |Γ| exp(jφ). For free-space steering, use k0 = 2πf/c, k_i,x = −k0 sin(θ_i), and k_r,x = +k0 sin(θ_r). The required gradient is g = k_i,x − k_r,x in rad/m. The adjacent-column phase step is Δφ = g × pitch, displayed in degrees.

## Table 1 — Reflection angle and phase gradient

Hold the entered incident angle fixed. Show one row per candidate reflection angle, with the signed reflection angle, required gradient in rad/m, and phase step in degrees per column. Highlight the desired angle. Selecting another row updates Table 2 for that angle.

## Table 2 — Capacitance by HFSS column

Show C1 through CN down the page. Include column position, target reflection phase, capacitance per gap in pF, achieved phase from the lookup, circular phase error, and lookup status. Include reflection magnitude when the CSV supplies it. Capacitance is the value for each gap load in that column.

- Generate the phase ramp as φ_n = φ_start + (n − 1)Δφ. Keep the ramp continuous and use 360° equivalence when matching it to the CSV.
- Use piecewise linear interpolation between adjacent eligible CSV samples. Handle nonmonotonic curves by checking each segment for valid solutions. If several capacitances match, prefer the strongest reflection when magnitude is available and use a deterministic tie-break otherwise.
- Leave capacitance blank and mark the row unavailable when its phase lies outside eligible coverage. Treat excluded data points as breaks in the curve so interpolation cannot bridge them.
- Exclude points explicitly marked unconverged by default. Provide an opt-in preliminary preview that includes them and flags rows that rely on them. If the export has no convergence column, display that convergence is unknown.

## Automatic starting phase

Choose one shared starting phase for the entire panel. Maximize the number of columns whose target phases can be realized. Make the reasoning visible in the app.

A concrete approach is to convert the eligible phase segments into circular coverage intervals, shift them by each column's required phase step to obtain feasible starting-phase intervals, and find where the most columns overlap. For tied intervals, choose the midpoint of the widest interval and use a deterministic tie-break if needed. Show the chosen starting phase, how many columns it fits, and the feasible interval that led to the choice. Provide a manual starting-phase override and recalculate the same profile and coverage summary.

## Verification and delivery

Keep the steering math, CSV parsing, and capacitance lookup separate from the Streamlit UI so they can be verified independently. Include a clearly labelled synthetic demo CSV and check these cases:

- At 2.4 GHz and 20 mm pitch, 0° incidence and +30° reflection gives about −25.15 rad/m and −28.82° per column.
- A source at +20° and specular reflection at −20° gives zero gradient.
- Matching across ±180° gives a small circular phase error for equivalent phases.
- Partial phase coverage leaves unsupported columns blank, and excluded samples break interpolation.
- Clicking a different angle in Table 1 changes the C1–CN profile in Table 2.

The app calculates a candidate profile using periodic unit-cell data. Show that the actual reflected beam direction is verified separately in a finite-panel HFSS simulation. If the CSV was characterized at a different frequency or incidence angle, clearly identify that mismatch when the metadata is available., before you start however - in the README.md, be very explicit regarding AI usage, include the prompt used to generate this app. Furthermore, a UV project has already been set-up.
````
