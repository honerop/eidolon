"""Render a safe, bounded subset of LaTeX math into cached transparent PNGs.

The resulting images are referenced by relative paths from Babel-generated SVG.
No TeX process is launched for a cache hit. Requires pdflatex and pdftocairo
only for videos containing LaTeX. This is not a sandbox for arbitrary TeX.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile

COLORS = {
    "cyan": "48DFF0", "ice": "B9F9FF", "white": "F1F7FF",
    "muted": "8B9CB2", "navy": "101C34", "ink": "080D19",
    "panel": "17253B", "slate": "324059", "blue": "6189FF",
    "purple": "B592FF", "rose": "FF8DA9", "red": "FF7088",
    "orange": "FFBD75", "yellow": "FFE18C", "green": "7DF1BC",
    "black": "000000",
}
# This is deliberately an allowlist. User-supplied TeX is NOT executable code.
# In particular no file I/O, macros, special primitives, packages or catcodes.
COMMANDS = set("""
frac dfrac tfrac binom dbinom tbinom sqrt
sum prod coprod int iint iiint oint lim limsup liminf max min sup inf
sin cos tan cot sec csc arcsin arccos arctan log ln exp
det dim gcd hom ker Pr mod bmod pmod
alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta
iota kappa lambda mu nu xi pi varpi rho varrho sigma varsigma tau
upsilon phi varphi chi psi omega
Gamma Delta Theta Lambda Xi Pi Sigma Upsilon Phi Psi Omega
partial nabla infty forall exists nexists neg top bot
in notin ni subset subseteq supset supseteq cup cap setminus
land lor wedge vee bigcup bigcap bigvee bigwedge
le leq ge geq neq ne approx equiv sim simeq cong propto
to rightarrow leftarrow leftrightarrow mapsto Rightarrow Leftarrow
Leftrightarrow longrightarrow Longrightarrow implies iff
uparrow downarrow parallel perp pm mp times div cdot ast star circ
oplus otimes odot bullet
overline underline hat widehat bar vec tilde widetilde dot ddot
underbrace overbrace overset underset
mathrm mathbf mathit mathsf mathtt mathcal mathbb mathfrak
text operatorname left right middle big Big bigg Bigg
qquad quad hspace phantom vphantom hphantom
ldots cdots vdots ddots dots
langle rangle lceil rceil lfloor rfloor
lvert rvert lVert rVert
begin end
""".split())
SPECIAL_COMMANDS = set(r"\\,;! {}|%:><_")
ENVIRONMENTS = {
    "matrix", "pmatrix", "bmatrix", "Bmatrix", "vmatrix", "Vmatrix",
    "smallmatrix", "cases", "aligned", "gathered", "split"
}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
DPI = 240
CACHE_VERSION = "tex-png-v1"


class LatexError(ValueError):
    """Invalid math markup, rendering failure or missing LaTeX tools."""


def validate_markup(value):
    if not isinstance(value, str) or not value.strip():
        raise LatexError("latex value must be a nonempty string")
    if len(value) > 1200:
        raise LatexError("latex value exceeds 1200 characters")
    if any(ord(char) < 32 and char not in "\t\n" for char in value):
        raise LatexError("latex contains invalid control characters")
    if "#" in value or "%" in value.replace(r"\%", "") or "^^" in value:
        raise LatexError("latex contains disallowed TeX syntax")
    if "$" in value:
        raise LatexError("latex must omit math-mode delimiters ($)")
    for match in re.finditer(r"\\([a-zA-Z@]+|.)", value, flags=re.DOTALL):
        cmd = match.group(1)
        if cmd not in COMMANDS and cmd not in SPECIAL_COMMANDS:
            raise LatexError("unsupported LaTeX command: \\" + cmd)
    env_matches = re.findall(r"\\(begin|end)\{([^{}]+)\}", value)
    if len(env_matches) > 24:
        raise LatexError("too many LaTeX environments")
    stack = []
    for action, name in env_matches:
        if name not in ENVIRONMENTS:
            raise LatexError("unsupported LaTeX environment: " + name)
        if action == "begin":
            stack.append(name)
        elif not stack or stack.pop() != name:
            raise LatexError("unbalanced LaTeX environments")
    if stack:
        raise LatexError("unbalanced LaTeX environments")
    # Reject \begin or \end without the exact validated environment syntax.
    if len(re.findall(r"\\(?:begin|end)(?![A-Za-z@])", value)) != len(env_matches):
        raise LatexError("invalid LaTeX environment syntax")
    if value.count("{") != value.count("}"):
        raise LatexError("unbalanced braces")
    return value


def validate_element(element):
    if not isinstance(element, dict):
        raise LatexError("LaTeX element must be an object")
    validate_markup(element.get("value"))
    shade = element.get("fill", "white")
    if shade not in COLORS:
        raise LatexError("LaTeX fill must use an Eidolon palette color")
    for key, default, low, high in (
        ("x", 0, -8192, 16384), ("y", 0, -8192, 16384),
        ("font_size", 44, 12, 128), ("max_width", 8192, 1, 8192),
    ):
        number = element.get(key, default)
        if isinstance(number, bool) or not isinstance(number, int) or not low <= number <= high:
            raise LatexError(f"LaTeX {key} must be an integer in {low}..{high}")
    if element.get("anchor", "center") not in ("left", "center", "right"):
        raise LatexError("LaTeX anchor must be left, center or right")
    return element


def validate_project(project):
    if not isinstance(project, dict):
        raise LatexError("project must be an object")
    for scene_index, scene in enumerate(project.get("scenes", []), 1):
        if not isinstance(scene, dict):
            continue
        for element_index, element in enumerate(scene.get("elements", []), 1):
            if isinstance(element, dict) and element.get("kind") == "latex":
                try:
                    validate_element(element)
                except LatexError as exc:
                    raise LatexError(f"scene {scene_index}, element {element_index}: {exc}") from exc


def cache_root():
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "eidolon" / "latex"


def _png_size(path):
    data = path.read_bytes()[:24]
    if len(data) != 24 or not data.startswith(PNG_SIGNATURE):
        raise LatexError("LaTeX renderer did not produce a valid PNG")
    width, height = struct.unpack(">II", data[16:24])
    if not 0 < width <= 16000 or not 0 < height <= 16000:
        raise LatexError("LaTeX PNG dimensions are invalid")
    return width, height


def _run(program, args, cwd):
    env = dict(os.environ, openin_any="p", openout_any="p", shell_escape="f")
    try:
        process = subprocess.run([program, *args], cwd=cwd, env=env,
                                 text=True, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, timeout=25,
                                 check=False)
    except FileNotFoundError as exc:
        raise LatexError(f"missing LaTeX tool: {program}; use the Nix wrapper") from exc
    except subprocess.TimeoutExpired as exc:
        raise LatexError(f"LaTeX tool timed out: {program}") from exc
    if process.returncode:
        tail = (process.stdout or "")[-1000:]
        raise LatexError(f"LaTeX render failed ({program}): {tail.strip()}")
    return process


def _render_uncached(source, shade, dest):
    document = ("\\documentclass[border=2pt]{standalone}\n"
                "\\usepackage{amsmath,amssymb,xcolor}\n"
                "\\begin{document}\n"
                "\\color[HTML]{" + COLORS[shade] + "}$\\displaystyle "
                + source + "$\n"
                "\\end{document}\n")
    with tempfile.TemporaryDirectory(prefix="eidolon-tex-") as tmp:
        directory = Path(tmp)
        (directory / "formula.tex").write_text(document, encoding="utf-8")
        _run(os.environ.get("EIDOLON_PDFLATEX", "pdflatex"), [
            "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape",
            "-output-directory=" + tmp, "formula.tex"], cwd=tmp)
        _run(os.environ.get("EIDOLON_PDFTOCAIRO", "pdftocairo"), [
            "-f", "1", "-l", "1", "-singlefile", "-transp",
            "-png", "-r", str(DPI), "formula.pdf", "formula"], cwd=tmp)
        image = directory / "formula.png"
        _png_size(image)
        if image.stat().st_size > 8 * 1024 * 1024:
            raise LatexError("LaTeX PNG is too large")
        shutil.copyfile(image, dest)


def compile_element(element, output_dir, cache=None):
    """Return an SVG-compatible latex_image element, materializing its PNG."""
    validate_element(element)
    shade = element.get("fill", "white")
    source = element["value"]
    key = hashlib.sha256(json.dumps([CACHE_VERSION, source, shade, DPI],
                                    ensure_ascii=False).encode("utf-8")).hexdigest()[:32]
    explicit_cache = cache is not None
    cache = Path(cache) if explicit_cache else cache_root()
    try:
        cache.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        if explicit_cache:
            raise LatexError(f"cannot create LaTeX cache: {cache}: {exc}") from exc
        # Nix sandbox builds commonly set HOME=/homeless-shelter, which is
        # intentionally not writable. Keep their cache in the render workspace.
        cache = Path(output_dir) / ".latex-cache"
        cache.mkdir(parents=True, exist_ok=True)
    cached = cache / ("latex-" + key + ".png")
    if not cached.exists():
        temporary = cache / ("latex-" + key + ".tmp.png")
        try:
            _render_uncached(source, shade, temporary)
            os.replace(temporary, cached)
        finally:
            temporary.unlink(missing_ok=True)
    original_width, original_height = _png_size(cached)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / cached.name
    if target.resolve() != cached.resolve():
        shutil.copyfile(cached, target)
    # 12pt design size rendered at 240dpi. Preserve actual TeX box dimensions.
    scale = element.get("font_size", 44) / (12 * DPI / 72)
    scale = min(scale, element.get("max_width", 8192) / original_width)
    width = max(1, round(original_width * scale))
    height = max(1, round(original_height * scale))
    x, y = element.get("x", 0), element.get("y", 0)
    anchor = element.get("anchor", "center")
    if anchor == "center":
        x -= round(width / 2)
    elif anchor == "right":
        x -= width
    y -= round(height / 2)
    result = {key: value for key, value in element.items() if key not in
              ("kind", "value", "fill", "font_size", "max_width", "anchor")}
    result.update(kind="latex_image", src=target.name,
                  x=x, y=y, width=width, height=height)
    return result


def materialize_project(project, output_dir, cache=None):
    """Materialize every math element in place; idempotent on prepared JSON."""
    validate_project(project)
    for scene in project.get("scenes", []):
        if not isinstance(scene, dict) or not isinstance(scene.get("elements"), list):
            continue
        scene["elements"] = [
            compile_element(element, output_dir, cache=cache)
            if isinstance(element, dict) and element.get("kind") == "latex"
            else element
            for element in scene["elements"]
        ]
    return project
