# Eidolon

**Eidolon is a general-purpose, JSON-driven video generator written in Babel.** Build
narrated explainers, motion graphics, image slideshows, social clips, tutorials,
montages, and diagrams from the same timeline. Mathematical plotting is only
one available drawing element. Eidolon is not a mathematics-only tool.

Nix supplies the Babel compiler, media decoders/encoders, narration engines, and a keyless Commons image adapter.
The renderer and timeline remain in `director.babel`; HTTP image downloads and license metadata are handled by `tools/media_assets.py`.

## Start

```sh
# Builds the Babel video engine and renders a general motion-graphics showcase
nix run github:honerop/eidolon

# Use your own JSON project
nix run github:honerop/eidolon -- ./project.json ./movie.mp4

# Render without neural or offline narration
EIDOLON_SKIP_TTS=1 nix run github:honerop/eidolon -- ./project.json ./movie.mp4
```

Output is H.264 MP4 plus a separate SRT subtitle file. Narration uses Edge TTS
when available and falls back to bundled offline espeak-ng if Edge fails.
Only the Edge provider needs an internet connection.

## Keyless image sourcing (Wikimedia Commons)

Eidolon can find real, freely licensed images without API keys. Add `media.search` to any scene to use Wikimedia Commons as a background:

```json
{
  "width": 640,
  "height": 360,
  "fps": 12,
  "scenes": [
    {
      "duration": 4,
      "media": {
        "kind": "image",
        "provider": "commons",
        "search": "old medieval stone fortress",
        "fit": "cover"
      },
      "narration": "An ancient fortress, built to last."
    }
  ]
}
```

The normal `nix run github:honerop/eidolon -- ./video.json ./movie.mp4` command resolves searches automatically before the Babel director renders. The built-in adapter uses the public Wikimedia Commons API, chooses a compatible image, downloads a scaled copy (up to about 1600 pixels wide) and caches it under `~/.cache/eidolon/images` (or `$XDG_CACHE_HOME/eidolon/images`). Subsequent identical queries reuse cached files. With `EIDOLON_OFFLINE=1`, only cached images may be used.

Search and fetch images independently:

```sh
# Returns JSON including file title, creator, license and source URL
nix run github:honerop/eidolon -- images search "medieval fortress" --limit 5

# Caches an image; optionally copies it and its metadata to a local directory
nix run github:honerop/eidolon -- images fetch "old castle" --output ./assets/

# Render the included keyless example (network needed on first render)
nix run github:honerop/eidolon -- ./examples/commons-image.json ./commons.mp4
```

When a project uses Commons images, Eidolon writes `movie.attribution.json` beside `movie.mp4`. This records each image's Commons file page, author, license and license URL. Check those terms and include required attribution wherever you publish the video. A free API does **not** mean every image is public domain. The adapter identifies itself to Wikimedia with a User-Agent, uses bounded downloads, and gives clear errors when search, licensing metadata or the network fails.

**Scope:** These are existing photographs/illustrations, not AI-generated images. No token or subscription is needed. It does not use third-party sites that need hidden API keys. Search results may vary until cached, and the public API can rate-limit or become unavailable. Private image generation and other providers can be separate future adapters. Babel still controls the video timeline, graphics and audio; the small Python standard-library adapter only handles HTTP image bytes and their metadata.


## Storyboard inspection and ready-made video formats

You can inspect a JSON project **without downloading anything or rendering**:

```sh
nix run github:honerop/eidolon -- inspect ./video.json
nix run github:honerop/eidolon -- inspect ./video.json --json
```

The inspector reports estimated scene start times, frame totals, size and frame rate, local file availability, and errors such as invalid image motion, missing assets and unsupported search settings. The `--json` output is designed for scripts and agents. It returns a nonzero exit code for errors, without attempting any network access. Actual duration may increase to accommodate spoken narration or audio.

Generate a starter project in one of three video layouts:

```sh
nix run github:honerop/eidolon -- init ./landscape.json --preset landscape
nix run github:honerop/eidolon -- init ./short.json --preset vertical
nix run github:honerop/eidolon -- init ./square.json --preset square
```

The presets use 1280×720, 720×1280 and 1080×1080 at 30 FPS respectively. Init does not overwrite an existing project.

## Image motion and search controls

Still images can animate with **Ken Burns** movement. The image background moves independently of animated vector overlays.

```json
{
  "duration": 5,
  "media": {
    "kind": "image",
    "search": "ancient mountains",
    "provider": "commons",
    "result": 0,
    "license": "public-domain",
    "motion": "zoom-in",
    "fit": "cover"
  }
}
```

Allowed image motions: `zoom-in`, `zoom-out`, `pan-left`, `pan-right`, `none` (default). Image motion works with local photographs and Commons searches; motion on video clips is invalid. The renderer applies the movement within each scene via FFmpeg's `zoompan` filter.

Use `result` (zero-based, 0–14) to choose a different matching image rather than always taking the first one. The `license` filter can be `any` (default) or `public-domain` (only known CC0/public-domain Commons results). This is a metadata filter, **not a legal guarantee**. Review the Commons file page before redistribution.

```sh
nix run github:honerop/eidolon -- images fetch "ancient stone fort" --result 2
nix run github:honerop/eidolon -- images fetch "ancient stone fort" --license public-domain
```

## Educational scenes (semantic JSON)

Eidolon can generate educational visuals from *concepts*, without an LLM
specifying individual frames or drawing coordinates. A deterministic compiler
(`tools/education.py`) expands each `educational` scene into ordinary
Babel-rendered shapes and animations. Existing `elements` still work.

LaTeX math is also supported: `educational.type: "equation"`,
`elements.kind: "latex"`, and mathematical callouts on diagrams and
graphs. Formulas use real TeX typesetting and cached transparent PNG assets,
while Babel renders the final SVG frames and animation.

Supported educational scene types: **diagram** (connected concepts),
**neuron** (labeled cell and traveling pulse), **signal** (moving event along
a path), **graph** (multiple data series with progressive reveal),
**timeline** (ordered events), **comparison** (animated bars), and
**simulation** (leaky integrate-and-fire neuronal model), and
**equation** (progressively appearing LaTeX formulas). Callouts and a
scene heading are available for every type. This is a semantic authoring
layer, not an AI service.

```json
{
  "width": 640, "height": 360, "fps": 12,
  "scenes": [{
    "duration": 5, "narration": "A neural signal moves along an axon.",
    "educational": {
      "type": "neuron",
      "title": "How neurons carry signals"
    }
  }]
}
```

```sh
# From a local checkout:
nix run . -- inspect examples/neuroscience-education.json
nix run . -- examples/neuroscience-education.json neuroscience.mp4
```

The full [educational scene schema](docs/education.md) documents each scene
type, units, animation behavior and limits. The
[seven-scene neuroscience example](examples/neuroscience-education.json)
is self-contained and requires no image downloads.

**Implementation detail:** semantic expansion happens during asset preparation,
while Babel still renders the timeline and frames. Directly invoking
`eidolon-director` with unexpanded semantic JSON is not supported. Use the
normal `eidolon` wrapper (or `tools/media_assets.py prepare`) instead.

## Video project format

```json
{
  "width": 1280,
  "height": 720,
  "fps": 30,
  "music": "assets/music.wav",
  "music_volume": 18,
  "scenes": [
    {
      "duration": 5,
      "media": {
        "kind": "video",
        "src": "assets/footage.mp4",
        "fit": "cover"
      },
      "audio": "assets/footage.mp4",
      "elements": [
        {
          "kind": "text", "x": 90, "y": 160, "font_size": 64,
          "fill": "white", "value": "The story starts here",
          "from": {"opacity": 0}, "start_percent": 10,
          "end_percent": 45
        }
      ]
    },
    {
      "duration": 5,
      "media": {
        "kind": "image",
        "src": "assets/photograph.png",
        "fit": "contain"
      },
      "narration": "This scene shows an image while the narrator speaks.",
      "elements": [
        {
          "kind": "rect", "x": 40, "y": 580,
          "width": 900, "height": 110,
          "fill": "panel"
        },
        {
          "kind": "text", "x": 70, "y": 648,
          "value": "Add captions, shapes and graphics",
          "font_size": 34, "fill": "white"
        }
      ]
    }
  ]
}
```

The `media` field is optional. Set it to a video clip (`kind: "video"`)
or still photograph (`kind: "image"`). Both can be resized with `fit:
"cover"` (crop to the canvas) or `fit: "contain"` (letterbox/pillarbox).
Clips loop when the scene is longer than the video. Media files are resolved
relative to the project JSON; absolute paths are also accepted.

**Sound:** `narration` creates speech for the scene. `audio` instead uses
a local audio file (or a video file containing an audio stream). The scene's
duration is extended if needed to avoid truncating audio. `music` specifies
an optional global background track, looped and mixed at `music_volume`
percent (default 15). `caption` overrides the subtitle text. Use
`EIDOLON_SKIP_TTS=1` to disable generated narration while keeping scene audio.
The engine emits a separate `.srt` file; it does not burn captions into frames.

**Graphics:** supported `elements` are `text`, `rect`, `circle`,
`line`, `arrow`, `polyline`, `axes`, and `plot`. Elements render over
the scene's background or footage. A project can use motion graphics without
any imported media. The math elements are optional, not the central schema.
Numeric properties can animate with `from`/`to` and
`start_percent`/`end_percent`.

## How it works

```text
JSON video project
        |
        v
Babel: project timeline, asset paths, graphics, scene durations, speech scheduling
        |                    |                       |
        |                    |                       +--> Edge TTS / espeak-ng
        |                    +--> SVG overlays --> librsvg rasterization
        +--> image/video backgrounds --> FFmpeg decode/scale/loop
                                       |
                                FFmpeg video composition
                                       |
                             Babel: voice / audio / music mixing
                                       |
                                   MP4 + SRT
```

The application is written in Babel. External tools (FFmpeg, librsvg,
Edge TTS and espeak-ng) are dependency executables, not application code.
The Babel compiler itself is implemented using Rust.

## Development

The Nix lock is pinned to Babel v0.3.1, rather than the old Ain compiler.
Run `nix flake update babel` when intentionally updating the compiler.


```sh
git clone https://github.com/honerop/eidolon
cd eidolon
nix develop
babelc check director.babel
nix flake check -L
```

`examples/general-showcase.json` is an asset-free general explainer.
`examples/math-explainer.json` remains as a mathematical animation example.
`examples/general-media-smoke.json` exercises actual photo, video and
audio/media mixing using assets created by GitHub Actions.

## Current boundaries

This is a basic general renderer, not a full nonlinear video editor. There
are no arbitrary multiple video layers per scene, crossfades between scenes,
timeline keyframes in seconds, image masks, video speed ramps, complete
typography controls, streaming frame output, or a visual editing UI.
Scene cuts are immediate. Media is currently a single scene-sized background,
with animated vector/text elements over it. Subtitle timing is per scene, not
per spoken word. Graph plotting currently uses integer arithmetic.

Next architectural steps: **typed tracks** (multiple video/image/audio layers,
z-order and in/out), **time-based keyframes**, **transitions/effects**,
**preview without full export**, and **frame streaming** to reduce
intermediate SVG/PNG files. Those will matter for broad video creation more
than adding more mathematical functions.
