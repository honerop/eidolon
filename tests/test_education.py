"""Offline tests for the high-level educational scene compiler."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


edu = load("education")
assets = load("media_assets")
inspect = load("project_inspect")


def project(kind, **args):
    return {"width": 640, "height": 360, "fps": 8,
            "scenes": [{"duration": 2, "educational": {"type": kind, **args}}]}


class EducationTests(unittest.TestCase):
    def render(self, kind, **kwargs):
        return edu.expand_project(project(kind, **kwargs))["scenes"][0]["elements"]

    def test_diagram_compiles_edges_and_nodes(self):
        elems = self.render("diagram",
                            nodes=[{"id": "a", "label": "Input"},
                                   {"id": "b", "label": "Output"}],
                            edges=[{"from": "a", "to": "b"}])
        self.assertEqual(sum(e["kind"] == "circle" for e in elems), 2)
        self.assertEqual(sum(e["kind"] == "arrow" for e in elems), 1)
        self.assertIn("Input", [e.get("value") for e in elems])

    def test_graph_reveal_and_y_mapping(self):
        elems = self.render("graph",
                            series=[{"name": "Activity", "values": [0, 1, 0, 2]}])
        curve = next(e for e in elems if e["kind"] == "polyline")
        self.assertTrue(curve["reveal"])
        self.assertEqual(len(curve["points"]), 4)
        self.assertEqual(curve["points"][0]["x"], round(640*.12))
        self.assertLess(curve["points"][-1]["y"], curve["points"][0]["y"])

    def test_flat_graph_does_not_divide_by_zero(self):
        elems = self.render("graph", series=[{"values": [0, 0, 0]}])
        self.assertTrue(any(e["kind"] == "polyline" for e in elems))

    def test_timeline_is_sorted(self):
        elems = self.render("timeline",
                            events=[{"at": 4, "label": "After"},
                                    {"at": 1, "label": "Before"}])
        self.assertEqual(sum(e["kind"] == "circle" for e in elems), 2)
        self.assertLess(next(e["x"] for e in elems if e.get("value") == "Before"),
                        next(e["x"] for e in elems if e.get("value") == "After"))

    def test_comparison_animates_bar_widths(self):
        elems = self.render("comparison",
                            items=[{"name": "A", "value": 35},
                                   {"name": "B", "value": 80}])
        bars = [e for e in elems if e["kind"] == "rect" and "from" in e]
        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[0]["from"]["width"], 0)
        self.assertGreater(bars[1]["to"]["width"], bars[0]["to"]["width"])

    def test_signal_has_bounded_visibility_windows(self):
        elems = self.render("signal",
                            path=[[.1, .5], [.5, .5], [.9, .2]])
        pulses = [e for e in elems if e["kind"] == "circle"]
        self.assertEqual(len(pulses), 2)
        self.assertEqual(pulses[0]["visible_end_percent"],
                         pulses[1]["visible_start_percent"])
        self.assertEqual(pulses[0]["from"]["cx"], round(640*.1))

    def test_neuron_is_reusable_without_assets(self):
        elems = self.render("neuron", title="Action potential")
        self.assertTrue(len(elems) > 10)
        self.assertIn("Axon", [e.get("value") for e in elems])

    def test_simulation_is_deterministic(self):
        params = {"input": [.3, .3, .3, .3, .3, .3], "decay": .9, "threshold": 1}
        a = self.render("simulation", **params)
        b = self.render("simulation", **params)
        self.assertEqual(a, b)
        self.assertTrue(any(str(e.get("value", "")).startswith("Spikes: ") for e in a))
        self.assertTrue(any(e.get("value") == "Threshold" for e in a))

    def test_callouts_animate_and_existing_elements_are_preserved(self):
        src = project("neuron", callouts=[
            {"text": "Travels forward", "position": [.5, .9]}])
        src["scenes"][0]["elements"] = [{"kind": "text", "value": "Own label"}]
        out = edu.expand_project(src)
        self.assertIn("Own label", [e.get("value") for e in out["scenes"][0]["elements"]])
        self.assertIn("educational", src["scenes"][0])
        self.assertNotIn("educational", out["scenes"][0])

    def test_invalid_references_and_inputs(self):
        tests = [
            project("diagram", nodes=[{"id": "a"}, {"id": "b"}],
                    edges=[{"from": "a", "to": "missing"}]),
            project("signal", path=[[0, 0], [2, .4]]),
            project("comparison", items=[{"name": "A", "value": 20},
                                         {"name": "B", "value": 120}]),
            project("simulation", input=[.1, float("nan")]),
            project("timeline", events=[{"at": 1, "label": "A"},
                                         {"at": 1, "label": "B"}]),
            project("unknown"),
        ]
        for bad in tests:
            with self.subTest(bad=bad["scenes"][0]["educational"]["type"]):
                with self.assertRaises(edu.EducationError):
                    edu.expand_project(bad)

    def test_media_preparation_and_offline_inspection(self):
        source = project("diagram", nodes=[{"id": "a"}, {"id": "b"}],
                         edges=[{"from": "a", "to": "b"}])
        with tempfile.TemporaryDirectory() as td:
            original = Path(td) / "scene.json"
            target = Path(td) / "prepared.json"
            original.write_text(json.dumps(source))
            self.assertTrue(inspect.analyze(original)["ok"])
            self.assertEqual(assets.prepare(original, target), [])
            parsed = json.loads(target.read_text())
            self.assertNotIn("educational", parsed["scenes"][0])
            self.assertTrue(parsed["scenes"][0]["elements"])

    def test_bad_semantics_are_errors_during_inspection(self):
        with tempfile.TemporaryDirectory() as td:
            original = Path(td) / "scene.json"
            original.write_text(json.dumps(project("signal", path=[[.1,.5]])))
            self.assertFalse(inspect.analyze(original)["ok"])
            with self.assertRaises(assets.AssetError):
                assets.prepare(original, Path(td) / "out.json")


if __name__ == "__main__":
    unittest.main()
