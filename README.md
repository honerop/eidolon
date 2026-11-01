# Eidolon

**Programmable educational video generator powered by Zig 0.16.**

Eidolon turns structured JSON into animated H.264 MP4 videos, with diagrams,
graphs, interactive-style explanations, mathematical formulas, narration,
media, and subtitles. You describe what a scene teaches, not every frame.

The timeline, frame generation, SVG scene composition, media scheduling, audio
mixing, and subtitle export are now **Zig**, not Babel. The existing Python
authoring adapters still expand semantic educational descriptions, fetch
Wikimedia Commons images, and typeset restricted LaTeX formulas. FFmpeg,
librsvg, Edge TTS/espeak-ng, and a small TeX installation perform the
heavy media work. There is no runtime or build dependency on Babel.

## Run

```sh
nix run github:honerop/eidolon -- ./project.json ./movie.mp4

# Generate the bundled explanation example, including LaTeX
nix run github:honerop/eidolon -- ./examples/neuroscience-education.json ./neuroscience.mp4

# No generated narration and no network
EIDOLON_SKIP_TTS=1 nix run github:honerop/eidolon -- ./project.json ./movie.mp4

# Create and validate a new project
nix run github:honerop/eidolon -- init video.json --preset landscape
nix run github:honerop/eidolon -- inspect video.json --json
```

The executable writes `movie.mp4` and `movie.srt`. Audio is extended to
fit narration, and subtitle timestamps follow the actual expanded timeline.
Edge TTS is attempted first; espeak-ng is an offline fallback.

## High-level educational scenes

```json
{
  "width": 1280,
  "height": 720,
  "fps": 30,
  "scenes": [
    {
      "duration": 5,
      "narration": "Signals are transmitted between neurons.",
      "educational": {
        "type": "diagram",
        "title": "Synaptic transmission",
        "nodes": [
          {"id": "a", "label": "First neuron"},
          {"id": "b", "label": "Chemical signal"},
          {"id": "c", "label": "Second neuron"}
        ],
        "edges": [
          {"from": "a", "to": "b"},
          {"from": "b", "to": "c"}
        ]
      }
    },
    {
      "duration": 5,
      "educational": {
        "type": "equation",
        "title": "Euler's identity",
        "formulas": [
          {
            "latex": "e^{i\\pi}+1=0",
            "position": [0.5, 0.5],
            "font_size": 72,
            "color": "cyan"
          }
        ]
      }
    }
  ]
}
```

See [the education schema](docs/education.md) for the seven original scene
types (diagram, graph, neuron, signal, timeline, comparison, simulation),
plus LaTeX equations and mathematical callouts. Source project JSON remains
compatible with the previous Babel-based renderer.

## Standard vector elements

Scenes can also contain `elements` with kinds `text`, `rect`, `circle`,
`line`, `arrow`, `polyline`, `axes`, `plot`, and `latex`. Geometry
properties support `from`, `to`, `start_percent`, `end_percent`, and
optional `ease: "smooth"`. `latex` elements become cached transparent PNGs
that the Zig SVG renderer embeds. `polyline` supports progressive reveal.

A scene may include `media` for local image/video backgrounds with contain
or cover fit and simple Ken Burns motion. A scene can also have explicit
`audio`; the project can have `music` and `music_volume`. Image searches
through Wikimedia Commons are optional, cached, and produce attribution
metadata. The `images search` and `images fetch` subcommands are preserved.

## Development

```sh
git clone https://github.com/honerop/eidolon
cd eidolon
nix develop
zig version                 # 0.16.x
zig build-exe src/main.zig -O ReleaseFast -lc -femit-bin=eidolon-director
zig test src/support.zig -lc
zig test src/svg.zig -lc
zig test src/main.zig -lc
nix flake check -L
```

The Nix flake installs Zig 0.16 and the external tools automatically.
`packages.director` is the standalone native binary. The regular
`nix run` command wraps this binary with preflight validation and asset
preparation.

### Architecture

```text
JSON project
    |
    +--> Python authoring adapters: education, Commons, LaTeX
    |
    v
Normalized JSON
    |
    v
Zig: timeline, animation, SVG and SVG/image composition
    |
    +--> librsvg / FFmpeg for graphics and media
    +--> Edge TTS / espeak-ng for narration
    |
    v
H.264 MP4 + SRT
```

The former `director.babel`, `preview.babel` and `render.babel` programs are
historical sources, not executed by the current Nix package. Zig source lives
in `src/`. No Babel compiler is downloaded by the new build.

The renderer still uses frame-by-frame SVG/PNG intermediates and has the old
18,000-frame ceiling. A streaming pipeline is the next performance step.
LaTeX is a restricted math subset, not an unrestricted TeX engine.
