#!/usr/bin/env python3
"""Offline project validation, timelines, and starter templates for Eidolon."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

PRESETS = {
    "landscape": (1280, 720),
    "vertical": (720, 1280),
    "square": (1080, 1080),
}
MOTIONS = {"none", "zoom-in", "zoom-out", "pan-left", "pan-right"}
FITS = {"cover", "contain"}
MAX_FRAMES = 18000


def _positive_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _file_status(root, name, problems, kind, label):
    if not isinstance(name, str) or not name.strip():
        problems.append(f"{label}: {kind} path is empty")
        return "missing"
    if "://" in name:
        problems.append(f"{label}: {kind} must be a local file, not a URL")
        return "invalid"
    p = (root / name).resolve()
    if not p.is_file():
        problems.append(f"{label}: missing {kind} file: {p}")
        return "missing"
    return "found"


def analyze(path):
    """Create a deterministic, entirely offline diagnostic report.

    Duration excludes increases caused by synthesized narration or audio. Actual
    audio length is probed later by the Babel renderer through ffprobe.
    """
    source = Path(path).resolve()
    problems, warnings, timeline = [], [], []
    try:
        project = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {"ok": False, "source": str(source), "problems": [str(e)],
                "warnings": [], "scenes": [], "frames_estimate": 0}
    if not isinstance(project, dict):
        return {"ok": False, "source": str(source),
                "problems": ["JSON root must be an object"], "warnings": [],
                "scenes": [], "frames_estimate": 0}
    import importlib.util
    edu_path = Path(os.environ.get("EIDOLON_EDUCATION_SOURCE", str(Path(__file__).with_name("education.py"))))
    edu_spec = importlib.util.spec_from_file_location("eidolon_education", edu_path)
    edu = importlib.util.module_from_spec(edu_spec)
    edu_spec.loader.exec_module(edu)
    try:
        project = edu.expand_project(project)
    except edu.EducationError as exc:
        return {"ok": False, "source": str(source), "problems": [str(exc)],
                "warnings": [], "scenes": [], "frames_estimate": 0}

    width, height, fps = (project.get(k, d) for k, d in
                          (("width", 1280), ("height", 720), ("fps", 30)))
    for name, value in (("width", width), ("height", height), ("fps", fps)):
        if not _positive_int(value):
            problems.append(f"{name} must be a positive integer")
    if _positive_int(width) and _positive_int(height) and (width % 2 or height % 2):
        warnings.append("H.264 yuv420p requires even dimensions: use even width and height")
    scenes = project.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        problems.append("scenes must be a nonempty array")
        scenes = []
    if "music" in project:
        _file_status(source.parent, project["music"], problems, "music", "project")
    total = 0
    for i, scene in enumerate(scenes, 1):
        label = f"scene {i}"
        if not isinstance(scene, dict):
            problems.append(f"{label} must be an object")
            continue
        raw_frames = scene.get("frames")
        if raw_frames is not None:
            frames = raw_frames if _positive_int(raw_frames) else 0
            if not frames:
                problems.append(f"{label}: frames must be a positive integer")
        else:
            seconds = scene.get("duration", 4)
            frames = seconds * fps if isinstance(seconds, int) and not isinstance(seconds, bool) and seconds > 0 and _positive_int(fps) else 0
            if not frames:
                problems.append(f"{label}: duration must be a positive integer")
        media = scene.get("media")
        media_kind, media_status, source_name, motion = "none", "none", "", "none"
        if media is not None:
            if not isinstance(media, dict):
                problems.append(f"{label}: media must be an object")
            else:
                media_kind = media.get("kind", "image")
                if media_kind not in ("image", "video"):
                    problems.append(f"{label}: unsupported media kind {media_kind!r}")
                fit = media.get("fit", "cover")
                if fit not in FITS:
                    problems.append(f"{label}: fit must be cover or contain")
                motion = media.get("motion", "none")
                if motion not in MOTIONS:
                    problems.append(f"{label}: invalid motion {motion!r}")
                if motion != "none" and media_kind != "image":
                    problems.append(f"{label}: motion is supported only for images")
                if "search" in media:
                    source_name = media["search"]
                    media_status = "remote-commons"
                    if media_kind != "image" or not isinstance(source_name, str) or not source_name.strip():
                        problems.append(f"{label}: image search requires a nonempty string and kind=image")
                    if media.get("provider", "commons") != "commons":
                        problems.append(f"{label}: unsupported search provider")
                    chosen = media.get("result", 0)
                    if not isinstance(chosen, int) or isinstance(chosen, bool) or not 0 <= chosen <= 14:
                        problems.append(f"{label}: media.result must be from 0 to 14")
                    if media.get("license", "any") not in ("any", "public-domain"):
                        problems.append(f"{label}: media.license must be any or public-domain")
                elif "src" in media:
                    source_name = media["src"]
                    media_status = _file_status(source.parent, source_name, problems, "media", label)
                else:
                    problems.append(f"{label}: media requires search or src")
        if "audio" in scene:
            _file_status(source.parent, scene["audio"], problems, "audio", label)
        elements = scene.get("elements", [])
        if not isinstance(elements, list):
            problems.append(f"{label}: elements must be an array")
        row = {
            "number": i, "start_second_estimate": round(total / fps, 3) if _positive_int(fps) else 0,
            "frames": frames, "media_kind": media_kind, "media_status": media_status,
            "media_source": source_name, "motion": motion,
            "has_narration": bool(scene.get("narration")),
        }
        timeline.append(row)
        total += frames
    if total > MAX_FRAMES:
        problems.append(f"project has {total} estimated frames, exceeding the {MAX_FRAMES} frame limit")
    if any(s["has_narration"] for s in timeline) or any(isinstance(s, dict) and s.get("audio") for s in scenes):
        warnings.append("Actual duration can increase to fit speech/audio; listed timing is an estimate")
    return {
        "ok": not problems, "source": str(source),
        "width": width, "height": height, "fps": fps,
        "scene_count": len(scenes), "frames_estimate": total,
        "duration_seconds_estimate": round(total / fps, 3) if _positive_int(fps) else 0,
        "scenes": timeline, "problems": problems, "warnings": warnings,
    }


def initial_project(preset):
    if preset not in PRESETS:
        raise ValueError("Unknown preset")
    w, h = PRESETS[preset]
    return {
        "width": w, "height": h, "fps": 30, "scenes": [
            {
                "duration": 3, "background": "ink",
                "elements": [
                    {"kind": "text", "x": max(32, w // 18), "y": h // 2,
                     "value": "YOUR VIDEO", "font_size": min(64, w // 12), "fill": "white",
                     "from": {"opacity": 0}, "start_percent": 0, "end_percent": 40},
                    {"kind": "line", "x1": max(32, w // 18), "y1": h // 2 + 24,
                     "x2": w - max(32, w // 18), "y2": h // 2 + 24, "stroke": "cyan"}
                ],
                "caption": "Replace this scene with your story."
            },
            {
                "duration": 3, "background": "navy",
                "elements": [
                    {"kind": "text", "x": max(32, w // 18), "y": h // 2,
                     "value": "MADE WITH EIDOLON", "font_size": min(40, w // 19),
                     "fill": "ice"}
                ],
                "caption": "Edit the scenes, then render this JSON."
            }
        ]
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Inspect or create Eidolon video projects offline")
    commands = parser.add_subparsers(dest="command", required=True)
    ins = commands.add_parser("inspect", help="Validate and show a no-network storyboard timeline")
    ins.add_argument("project")
    ins.add_argument("--json", action="store_true", help="Machine-readable report")
    init = commands.add_parser("init", help="Create a JSON starter project")
    init.add_argument("output")
    init.add_argument("--preset", choices=sorted(PRESETS), default="landscape")
    args = parser.parse_args(argv)
    if args.command == "init":
        target = Path(args.output)
        try:
            with target.open("x", encoding="utf-8") as f:
                json.dump(initial_project(args.preset), f, indent=2, ensure_ascii=False)
                f.write("\n")
        except OSError as e:
            parser.error(str(e))
        print(f"Created {target} ({args.preset})")
        return 0
    result = analyze(args.project)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Eidolon storyboard:", result["source"])
        if "fps" in result:
            print(f"  Canvas: {result['width']} x {result['height']} @ {result['fps']} fps")
            print(f"  Estimated: {result['duration_seconds_estimate']} seconds, {result['frames_estimate']} frames")
        for scene in result["scenes"]:
            print(f"  [{scene['number']}] {scene['start_second_estimate']}s + {scene['frames']} frames | "
                  f"{scene['media_kind']} ({scene['media_status']}) | {scene['motion']}")
        for w in result["warnings"]:
            print("  WARNING:", w)
        for p in result["problems"]:
            print("  ERROR:", p)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
