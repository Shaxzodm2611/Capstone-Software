import math
import unittest

from ris.hfss import ColumnMapping, Sample, capacitance_unit, parse_sweep, phase_unit, read_csv, suggest_columns
from ris.lookup import PhaseLookup, best_start, circular_error, column_profile, manual_interval
from ris.steering import reflection_angles, steering


class SteeringTests(unittest.TestCase):
    def test_default_gradient(self):
        result = steering(2.4, 20, 0, 30)
        self.assertAlmostEqual(result.gradient_rad_m, -25.15014, places=5)
        self.assertAlmostEqual(result.step_deg, -28.81994, places=5)

    def test_specular_gradient(self):
        self.assertEqual(steering(2.4, 20, 20, -20).gradient_rad_m, 0)

    def test_candidate_angles_stay_centered_and_respect_horizon(self):
        self.assertEqual(reflection_angles(30, 5, 5), (25, 30, 35))
        self.assertEqual(reflection_angles(88.1, 0.62, 0.3), (87.5, 87.8, 88.1, 88.4, 88.7))
        self.assertEqual(reflection_angles(-89, 5, 2), (-89, -87, -85))
        self.assertEqual(reflection_angles(30, 2, 5), (30,))


class CSVTests(unittest.TestCase):
    def test_hfss_header_units_metadata_and_missing_phase(self):
        raw = read_csv(
            ('# Frequency: 2400 MHz\n'
             'C_gap [nF],"cang_rad(S(1,1)) []","dB(S(1,1)) []",Converged,Theta_i [rad]\n'
             '0.001,3.141592653589793,-2,yes,0.2\n'
             '0.002,,-3,false,0.2\n'
             '0.003,2.1,-1,unknown,0.2\n').encode("utf-8-sig")
        )
        columns = suggest_columns(raw.headers)
        sweep = parse_sweep(raw, ColumnMapping(
            columns["capacitance"], columns["phase"],
            capacitance_unit(columns["capacitance"]), phase_unit(columns["phase"]),
            columns["magnitude"], columns["convergence"],
        ))
        self.assertEqual(sweep.frequency_ghz, 2.4)
        self.assertEqual(sweep.incident_deg, math.degrees(0.2))
        self.assertEqual(sweep.samples[0], Sample(1.0, 180.0, -2.0, True))
        self.assertEqual(sweep.samples[1], Sample(2.0, None, -3.0, False))
        self.assertIsNone(sweep.samples[2].converged)
        self.assertFalse(PhaseLookup(sweep.samples, include_preliminary=True).segments)

    def test_multiple_characterizations_are_rejected(self):
        raw = read_csv(b"C,Phase,Freq [GHz]\n1,0,2.4\n2,20,2.5\n")
        with self.assertRaisesRegex(ValueError, "multiple characterization frequencies"):
            parse_sweep(raw, ColumnMapping("C", "Phase", "pF", "deg"))

    def test_manual_column_mapping_without_optional_fields(self):
        raw = read_csv(b"x;y\n450;8\n800;9\n")
        sweep = parse_sweep(raw, ColumnMapping("x", "y", "fF", "deg"))
        self.assertAlmostEqual(sweep.samples[0].capacitance_pf, 0.45)
        self.assertFalse(sweep.has_magnitude)
        self.assertFalse(sweep.has_convergence)
        self.assertIsNone(sweep.samples[0].converged)


class LookupTests(unittest.TestCase):
    def test_wrapping_and_circular_error(self):
        lookup = PhaseLookup((Sample(1, 170), Sample(3, 190)))
        result = lookup.match(-179)
        self.assertAlmostEqual(result.capacitance_pf, 2.1)
        self.assertEqual(result.phase_deg, 181)
        self.assertAlmostEqual(circular_error(179.99, -179.99), -0.02)
        self.assertEqual(circular_error(result.phase_deg, -179), 0)

    def test_nonmonotone_prefers_strongest_reflection(self):
        lookup = PhaseLookup((Sample(1, 0, -6), Sample(2, 90, -4), Sample(3, 0, -1)))
        result = lookup.match(45)
        self.assertEqual(result.capacitance_pf, 2.5)
        self.assertEqual(result.magnitude_db, -2.5)
        lookup = PhaseLookup((Sample(1, 0), Sample(2, 90), Sample(3, 0)))
        self.assertEqual(lookup.match(45).capacitance_pf, 1.5)

    def test_partial_coverage_and_excluded_breaks(self):
        samples = (Sample(1, 0, converged=True), Sample(2, 45, converged=False), Sample(3, 90, converged=True))
        lookup = PhaseLookup(samples)
        profile = column_profile(lookup, 4, 20, 0, 30)
        self.assertEqual([row.position_mm for row in profile], [0, 20, 40, 60])
        self.assertEqual([row.match.capacitance_pf if row.match else None for row in profile], [1, None, None, 3])
        self.assertEqual(best_start(lookup.coverage, 4, 30).fit, 2)
        preview = PhaseLookup(samples, include_preliminary=True)
        self.assertIs(preview.match(30).converged, False)
        self.assertIs(preview.match(90).converged, True)
        self.assertEqual(best_start(preview.coverage, 4, 30).fit, 4)

    def test_best_start_uses_widest_circular_interval(self):
        lookup = PhaseLookup((Sample(1, -25), Sample(2, 35)))
        choice = best_start(lookup.coverage, 3, 10)
        self.assertEqual(choice.fit, 3)
        self.assertEqual(choice.interval, (335, 375))
        self.assertEqual(choice.phase_deg, 355)
        self.assertEqual(manual_interval(lookup.coverage, 1, 10, [0, 1, 2]), (335, 375))

    def test_equal_width_tie_uses_lowest_start(self):
        lookup = PhaseLookup((Sample(1, 10), Sample(2, 20), Sample(None, None), Sample(3, 50), Sample(4, 60)))
        choice = best_start(lookup.coverage, 1, 0)
        self.assertEqual((choice.phase_deg, choice.interval), (15, (10, 20)))

    def test_more_than_a_full_turn_checks_equivalent_branches(self):
        lookup = PhaseLookup((Sample(1, -400, -4), Sample(3, 400, -1)))
        self.assertEqual(lookup.coverage, [(0, 360)])
        self.assertEqual(lookup.match(0).phase_deg, 360)
        self.assertEqual(best_start(lookup.coverage, 7, -57).fit, 7)
