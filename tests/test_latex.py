"""LaTeX formula validation, scene integration, caching and rendering tests."""
from pathlib import Path
from unittest.mock import patch
import copy
import importlib.util
import json
import os
import struct
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


latex = module("latex_assets")
education = module("education")
assets = module("media_assets")
inspector = module("project_inspect")


class LatexTests(unittest.TestCase):
    def test_real_latex_expressions_are_valid(self):
        cases = [
            r"E=mc^{2}",
            r"\frac{d}{dx}x^{2}=2x",
            r"\int_{0}^{\\infty}e^{-x}\\,dx=1",
            r"\sum_{n=1}^{\\infty}\\frac{1}{n^{2}}=\\frac{\\pi^{2}}{6}",
            r"\begin{bmatrix} 1 & 2 \\\\ 3 & 4 \\end{bmatrix}",
            r"\begin{cases}x^{2}&x>0\\\\0&x\\le0\\end{cases}",
            r"\left(\\alpha+\\beta\\right)^{2}",
        ]
        for expression in cases:
            with self.subTest(expression=expression):
                self.assertEqual(latex.validate_markup(expression), expression)

    def test_blocks_tex_primitives_and_invalid_input(self):
        cases = [
            r"\input{/etc/passwd}", r"\include{secret}", r"\write18{anything}",
            r"\def\\evil{boom}", r"\csname input\\endcsname",
            r"\catcode", r"\usepackage{shellesc}",
            r"\begin{document}hello\\end{document}",
            r"\begin{bmatrix} 1",
            r"\notacommand{x}", r"E=mc^2 % hidden content",
            r"\frac{a}{b}^^5c",
            "$E=mc^2$", "", "x"*1201,
        ]
        for expression in cases:
            with self.subTest(expression=expression):
                with self.assertRaises(latex.LatexError):
                    latex.validate_markup(expression)

    def test_first_class_semantic_equation_compiles(self):
        source = {"width": 640, "height": 360, "scenes": [{
            "duration": 3, "educational": {"type": "equation",
              "title": "Euler's identity",
              "formulas": [{"latex": r"e^{i\\pi}+1=0", "position": [.5,.55],
                            "font_size": 52, "color": "cyan"}]}
        }]}
        result = education.expand_project(source)
        elements = result["scenes"][0]["elements"]
        math = next(e for e in elements if e.get("kind") == "latex")
        self.assertEqual(math["x"], 320)
        self.assertEqual(math["y"], 198)
        self.assertEqual(math["font_size"], 52)
        self.assertIn("from", math)
        self.assertNotIn("educational", result["scenes"][0])
        self.assertIn("educational", source["scenes"][0])

    def test_callouts_accept_math(self):
        project = {"width": 640, "height": 360, "scenes": [{
            "duration": 3, "educational": {
                "type": "neuron",
                "callouts": [{"latex": r"\Delta V", "position": [.5,.8]}]}
        }]}
        result = education.expand_project(project)
        self.assertTrue(any(e.get("kind") == "latex" for e in result["scenes"][0]["elements"]))

    def test_cache_hit_skips_subprocess_and_preserves_animation(self):
        # Minimal 8x4 PNG header; sufficient for dimension/read logic.
        png = latex.PNG_SIGNATURE + b"\\x00" * 8 + struct.pack(">II", 8, 4)
        calls = []
        def fake_render(source, shade, dest):
            calls.append((source, shade))
            Path(dest).write_bytes(png)
        element = {"kind": "latex", "value": r"\frac{a}{b}", "x": 300,
                   "y": 120, "font_size": 40, "fill": "cyan",
                   "from": {"opacity": 0}, "to": {"opacity": 100},
                   "start_percent": 5, "end_percent": 30}
        with tempfile.TemporaryDirectory() as td:
            cache = Path(td) / "cache"
            work = Path(td) / "working"
            with patch.object(latex, "_render_uncached", side_effect=fake_render):
                first = latex.compile_element(element, work, cache)
                second = latex.compile_element(element, work, cache)
            self.assertEqual(calls, [(r"\frac{a}{b}", "cyan")])
            self.assertEqual(first, second)
            self.assertEqual(first["kind"], "latex_image")
            self.assertEqual(first["from"], {"opacity": 0})
            self.assertTrue((work / first["src"]).is_file())
            self.assertEqual(first["width"], 8)
            self.assertEqual(first["height"], 4)

    def test_no_tex_required_for_inspect(self):
        project = {"width": 640, "height": 360, "scenes": [{
            "duration": 2, "educational": {"type": "equation",
                    "formulas": [{"latex": r"\sum_{i=1}^{n}i"}]}
        }]}
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "math.json"
            path.write_text(json.dumps(project), encoding="utf-8")
            with patch.object(latex, "_render_uncached", side_effect=AssertionError("TeX during inspect")):
                self.assertTrue(inspector.analyze(path)["ok"])

    def test_inspect_rejects_dangerous_latex(self):
        project = {"scenes": [{"duration": 2, "elements": [{
            "kind": "latex", "value": r"\input{secret.txt}", "x": 5, "y": 5
        }]}]}
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "math.json"
            path.write_text(json.dumps(project), encoding="utf-8")
            report = inspector.analyze(path)
            self.assertFalse(report["ok"])
            self.assertTrue(any("unsupported LaTeX command" in p for p in report["problems"]))

    def test_materialization_and_original_project_unchanged(self):
        project = {"width": 640, "height": 360, "scenes": [{
            "duration": 2, "elements": [{"kind": "latex",
              "value": "x^{2}+y^{2}=z^{2}", "x": 320, "y": 180}]
        }]}
        original = copy.deepcopy(project)
        png = latex.PNG_SIGNATURE + b"\\x00" * 8 + struct.pack(">II", 100, 40)
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "input.json"
            dest = Path(td) / "work" / "output.json"
            src.write_text(json.dumps(project), encoding="utf-8")
            with patch.object(latex, "_render_uncached",
                              side_effect=lambda s, c, p: Path(p).write_bytes(png)):
                data = latex.materialize_project(copy.deepcopy(project), dest.parent,
                                                 cache=Path(td) / "cache")
            self.assertEqual(data["scenes"][0]["elements"][0]["kind"], "latex_image")
            self.assertTrue((dest.parent / data["scenes"][0]["elements"][0]["src"]).exists())
        self.assertEqual(project, original)


if __name__ == "__main__":
    unittest.main()
