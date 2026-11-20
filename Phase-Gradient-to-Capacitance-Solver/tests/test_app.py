import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app.py"


class DashboardTests(unittest.TestCase):
    def test_angle_selection_recalculates_displayed_loads(self):
        app = AppTest.from_file(str(APP)).run()
        self.assertFalse(app.exception)
        key = "reflection-table-30.0-25.0-35.0-3"
        self.assertEqual(app.session_state[key]["selection"]["rows"], [1])
        original = app.dataframe[1].value
        self.assertEqual(original["Column"].tolist(), [f"C{index}" for index in range(1, 11)])

        app.session_state[key] = {"selection": {"rows": [2]}}
        app.run()
        self.assertFalse(app.exception)
        self.assertTrue(any(caption.value.startswith("Reflection +35°") for caption in app.caption))
        updated = app.dataframe[1].value
        self.assertFalse(original["Cap. per gap (pF)"].equals(updated["Cap. per gap (pF)"]))
        self.assertFalse(original["Target (°)"].equals(updated["Target (°)"]))

    def test_manual_start_and_metadata_mismatch(self):
        app = AppTest.from_file(str(APP)).run()
        manual = next(toggle for toggle in app.toggle if toggle.label == "Manual starting phase")
        manual.set_value(True).run()
        app.number_input(key="manual-phase").set_value(48.0).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.metric[0].value, "48.000°")
        data = app.dataframe[1].value
        self.assertEqual(data.loc[0, "Target (°)"], 48.0)
        self.assertEqual(data.loc[0, "Status"], "Unavailable")
        self.assertTrue(data["Cap. per gap (pF)"].isna().iloc[0])
        next(widget for widget in app.number_input if widget.label == "Frequency (GHz)").set_value(2.5).run()
        self.assertTrue(any("Characterization mismatch" in banner.value for banner in app.warning))
