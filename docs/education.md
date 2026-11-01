# Educational scene authoring

Educational scenes let scripts and LLMs describe **what to explain**, rather
than calculate every SVG coordinate or every frame. The compiler is offline,
deterministic, and part of Eidolon's JSON preparation stage. The final timeline,
frames, narration, audio mixing, and MP4 export run through the Zig renderer.

## Quick start

```sh
nix run github:honerop/eidolon -- init ./video.json --preset landscape
# Edit scenes in video.json; replace some manually specified elements with educational.
nix run github:honerop/eidolon -- inspect ./video.json
nix run github:honerop/eidolon -- ./video.json ./video.mp4
```

For a complete example, see `examples/neuroscience-education.json`. The
example has seven scenes, covering neurons, electric pulses, synaptic flow,
a data graph, comparisons, a time sequence, and a simple simulation.

Every educational scene is a normal Eidolon scene with an additional
`educational` object. Use standard `duration`, `narration`, `media`,
`background`, `audio`, and `caption` keys. You can include additional
ordinary `elements` alongside the generated visuals.

A common set of optional keys applies to every educational object:

- `title`: heading at the top.
- `callouts`: a list of `{"text":"Note","position":[0.15,0.92],"color":"ice"}`;
  coordinates are fractions of the video width and height.
- `type`: required; choose one of the types below.

Colors are currently restricted to the renderer's named palette:
`cyan`, `ice`, `white`, `muted`, `navy`, `ink`, `panel`,
`slate`, `blue`, `purple`, `rose`, `red`, `orange`, `yellow`,
`green`, `black`.

## 1. Concept diagrams

```json
{
  "type": "diagram",
  "title": "Synaptic transmission",
  "layout": "horizontal",
  "nodes": [
    {"id": "signal", "label": "Action potential"},
    {"id": "release", "label": "Vesicle release"},
    {"id": "receptor", "label": "Receptor activation"}
  ],
  "edges": [
    {"from": "signal", "to": "release"},
    {"from": "release", "to": "receptor"}
  ]
}
```

Nodes have unique `id` values and optional `label`, `color`,
or `position` as normalized coordinates. The default layout places nodes
horizontally; `layout: "vertical"` is also available. Edges refer to node
ids and support optional `color` and `arrow` (default true).

## 2. Moving signals

```json
{
  "type": "signal", "title": "An impulse travels",
  "path": [[0.1, 0.55], [0.35, 0.55], [0.60, 0.55], [0.9, 0.35]],
  "start_percent": 10, "end_percent": 90, "color": "orange"
}
```

The first percentage is when the marker starts moving in the scene, and the
last is when it arrives at the end of the path. Movement across each segment
is linear. Coordinates use **fractions** in the range 0 to 1. The marker is
only visible on its active segment, rather than leaving a trail of ghost dots.

The `neuron` preset builds a labeled schematic cell with dendrites, cell
body, axon, terminals, and an animated pulse. No assets or node definitions
are needed:

```json
{"type": "neuron", "title": "A neuron", "color": "cyan"}
```

These are schematic visuals, not anatomically precise 3D models.

## 3. Data graphs

```json
{
  "type": "graph",
  "title": "Activity over observations",
  "min": 0, "max": 12,
  "reveal": true,
  "series": [
    {"name": "Group A", "values": [1, 2, 4, 9, 5], "color": "cyan"},
    {"name": "Group B", "values": [3, 4, 6, 5, 8], "color": "purple"}
  ]
}
```

Values are evenly spaced observations on the x-axis. The y-axis uses the
explicit `min`/`max` range or automatically derives a range from the data.
`reveal` animates the plotted lines from left to right over the scene. It
defaults to true. This is a graph of supplied samples, not evaluation of
arbitrary mathematical expressions. Use `elements.kind: "plot"` for
Eidolon's existing function plots.

## 4. Timelines

```json
{
  "type": "timeline",
  "title": "Action potential",
  "events": [
    {"at": 0, "label": "Rest"},
    {"at": 1.5, "label": "Depolarization"},
    {"at": 3, "label": "Repolarization"},
    {"at": 5, "label": "Recovery"}
  ]
}
```

Time values are numeric **relative positions**, not automatically mapped to
scene seconds. The compiler sorts the events and spaces them according to
their `at` values. Event labels appear progressively.

## 5. Comparisons

```json
{
  "type": "comparison", "title": "Relative stimulus intensity",
  "max": 100,
  "items": [
    {"name": "Weak", "value": 25, "color": "blue"},
    {"name": "Strong", "value": 80, "color": "orange"}
  ]
}
```

Each value is between zero and `max`. Bars grow as the scene plays.
Numerical values are supplied by the author; Eidolon does not invent
scientific measurements.

## 6. Deterministic neuron simulations

```json
{
  "type": "simulation",
  "title": "Integrate and fire",
  "model": "integrate-and-fire",
  "input": [0.2, 0.3, 0.4, 0.5, 0.2, 0.6, 0.3],
  "decay": 0.85,
  "threshold": 1,
  "reset": 0
}
```

This is a deliberately simplified discrete leaky integrate-and-fire model.
At each step, it applies:

```text
potential = max(0, potential * decay + current)
if potential >= threshold:
    mark spike
    potential = reset
```

The graph shows the potential **before reset** for that step, a horizontal
threshold guide, and spike markers along the top edge. The input represents
an arbitrary current per discrete step; it is not calibrated to physical
amperes, membrane voltages, or biological time. It is for conceptual
education, not neuroscience research or clinical interpretation.

## 7. LaTeX equations and mathematical annotations

Math uses a real LaTeX engine, not Unicode approximations. Equations can
show fractions, radicals, integrals, sums, Greek letters, matrices, and AMS
math layouts, with optional animated appearances.

A full semantic equation scene:

```json
{
  "duration": 5,
  "narration": "This equation describes energy in terms of mass.",
  "educational": {
    "type": "equation",
    "title": "Mass-energy equivalence",
    "formulas": [
      {
        "latex": "E=mc^{2}",
        "position": [0.5, 0.5],
        "font_size": 72,
        "color": "cyan"
      }
    ]
  }
}
```

`position` is a normalized canvas coordinate between 0 and 1;
`font_size` is the nominal 12–128 pixel-scale text size. Multiple formulas
appear progressively. Unicode can be used in surrounding captions; TeX
operators should use the standard backslash commands in the formula itself.

Any existing scene can also contain a **first-class formula element**:

```json
{
  "kind": "latex",
  "value": "\\frac{d}{dt}V_m",
  "x": 650,
  "y": 400,
  "font_size": 56,
  "fill": "white",
  "anchor": "center",
  "from": {"opacity": 0},
  "to": {"opacity": 100},
  "start_percent": 20,
  "end_percent": 50
}
```

Note: the JSON source above escapes a LaTeX backslash as `\\`.
For example, `"value": "\\frac{a}{b}"` in a JSON file becomes the
LaTeX string `\frac{a}{b}`.

You can put mathematical callouts on diagrams or graphs:

```json
"callouts": [
  {
    "latex": "f(t)=\\sin(\\omega t)",
    "position": [0.5, 0.9],
    "color": "ice"
  }
]
```

For direct elements, `x`/`y` are integer canvas pixels at the formula's
vertical center; `anchor` controls horizontal alignment (`left`,
`center` or `right`). `max_width` optionally caps displayed width
while retaining the mathematical aspect ratio.

**Rendering:** During project preparation, Eidolon validates markup,
runs `pdflatex` with shell escape disabled, converts the cropped result
into a transparent PNG using `pdftocairo`, and caches the PNG under
`$XDG_CACHE_HOME/eidolon/latex` (default `~/.cache/eidolon/latex`).
Only new or changed formulas need TeX compilation. Zig embeds references
to these images in its per-frame SVG, so graphics, appearance animation,
narration, and FFmpeg export remain part of the existing pipeline.
`inspect` validates formula syntax without launching TeX.

For deterministic builds, use the Nix wrapper. It supplies the LaTeX,
AMS packages, xcolor, and Poppler tools automatically.
`examples/latex-smoke.json` demonstrates formulas, a definite integral,
a matrix, and a graph with a mathematical callout:

```sh
nix run . -- inspect examples/latex-smoke.json
nix run . -- examples/latex-smoke.json latex.mp4
```

**Security and scope:** This supports a *restricted math subset*, not arbitrary
TeX documents. Allowed math commands and math environments are whitelisted;
file access, macro definitions, shell escape, packages, and special primitives
are excluded. LaTeX itself is complex and should not be treated as a secure
sandbox for untrusted projects. Render unknown input in a separately restricted
process or container. There is no TikZ, PStricks, general document compilation,
or complete custom macro support.

## Design boundaries

The educational compiler produces ordinary scene `elements`; it is not a
second renderer. The Zig output path creates the final MP4. Its
implementation uses Python from the standard library as an authoring adapter,
like the existing Commons asset adapter. No network or LLM calls are needed.

Limits are intentionally bounded: 1–200 scenes, 600 combined elements per
scene, up to 24 diagram nodes, 120 values per graph series, 100 simulation
samples, 10 timeline events, 6 comparison items, and 24 signal points.
The renderer's existing 18,000-frame ceiling still applies.

Current output remains SVG-based, with integer pixel coordinates. Polylines
reveal by adding samples, not continuous stroke interpolation. There is no
unrestricted TeX, physical simulation engine, automatic word wrapping,
or arbitrary 2D/3D coordinate transform yet. These can be added as
separate semantic scene types without changing the JSON-to-Zig boundary.

## Integration and testing

The normal `eidolon` wrapper calls `tools/media_assets.py prepare`, which
expands `educational` objects **before** resolving local asset paths and
Commons searches. Offline `eidolon inspect` validates them with the same
compiler. Raw `eidolon-director` requires pre-expanded JSON.

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
nix flake check -L
```
