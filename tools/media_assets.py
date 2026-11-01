#!/usr/bin/env python3
"""Keyless Wikimedia Commons asset adapter for Eidolon.

The video renderer remains written in Babel. This small standard-library-only
adapter handles HTTP image bytes, metadata, persistent caching, and conversion
of searched media to local paths before Babel renders the JSON timeline.
"""
from __future__ import annotations

import argparse
import hashlib
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "Eidolon/0.3 (https://github.com/honerop/eidolon) Python-urllib"
MAX_BYTES = 20 * 1024 * 1024
ALLOWED_HOSTS = {"upload.wikimedia.org"}
SUPPORTED_IMAGE_HEADERS = {
    "jpg": lambda b: b.startswith(b"\xff\xd8\xff"),
    "png": lambda b: b.startswith(b"\x89PNG\r\n\x1a\n"),
    "webp": lambda b: b.startswith(b"RIFF") and b[8:12] == b"WEBP",
    "gif": lambda b: b.startswith((b"GIF87a", b"GIF89a")),
}


class AssetError(Exception):
    pass


class TextOnly(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def text(self):
        return " ".join(" ".join(self.parts).split())


def strip_html(value):
    p = TextOnly()
    p.feed(str(value or ""))
    return html.unescape(p.text())


def cache_root():
    return Path(os.environ.get("EIDOLON_CACHE_DIR")
                or Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "eidolon" / "images")


def _urlopen(url):
    return urlopen(Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json,image/*"}), timeout=25)


def _request_json(url):
    try:
        with _urlopen(url) as r:
            if r.status != 200:
                raise AssetError("Wikimedia API returned HTTP " + str(r.status))
            return json.load(r)
    except (HTTPError, URLError, TimeoutError) as e:
        raise AssetError("Wikimedia Commons is unavailable: " + str(e)) from e
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise AssetError("Wikimedia Commons returned invalid JSON") from e


def _field(metadata, key):
    return metadata.get(key, {}).get("value", "")


def search_images(query, limit=6):
    """Return Commons results in search order with reuse metadata."""
    query = str(query).strip()
    if not query:
        raise AssetError("Image search cannot be empty")
    if len(query) > 240:
        raise AssetError("Image search is too long (240 characters max)")
    if not 1 <= limit <= 15:
        raise AssetError("Search limit must be from 1 to 15")
    params = {
        "action": "query", "generator": "search", "gsrnamespace": 6,
        "gsrsearch": query, "gsrlimit": limit,
        "prop": "imageinfo", "iiprop": "url|mime|extmetadata",
        "iiurlwidth": 1600, "format": "json", "formatversion": 2,
    }
    result = _request_json(API + "?" + urlencode(params))
    pages = sorted(result.get("query", {}).get("pages", []), key=lambda p: p.get("index", 0))
    found = []
    for page in pages:
        info = (page.get("imageinfo") or [{}])[0]
        source_url = info.get("thumburl") or info.get("url")
        if not source_url:
            continue
        host = (urlparse(source_url).hostname or "").lower()
        if host not in ALLOWED_HOSTS:
            continue
        mime = info.get("mime", "")
        # SVGs are usable when Commons provides rasterized thumbnail bytes.
        if not (mime.startswith("image/") and
                (mime in ("image/jpeg", "image/png", "image/webp", "image/gif")
                 or ("thumburl" in info))):
            continue
        m = info.get("extmetadata") or {}
        found.append({
            "title": page.get("title", ""),
            "source_page": info.get("descriptionurl") or (
                "https://commons.wikimedia.org/wiki/" + page.get("title", "").replace(" ", "_")),
            "artist": strip_html(_field(m, "Artist")),
            "license": strip_html(_field(m, "LicenseShortName")) or "Unknown",
            "license_url": strip_html(_field(m, "LicenseUrl")),
            "attribution_required": _field(m, "AttributionRequired") == "true",
            "original_url": info.get("url"),
            "download_url": source_url,
            "provider": "Wikimedia Commons",
        })
    return found


def _download_image(url, destination):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise AssetError("Refusing a non-Wikimedia image download URL")
    data = bytearray()
    try:
        with _urlopen(url) as r:
            final = urlparse(r.geturl())
            if final.scheme != "https" or final.hostname not in ALLOWED_HOSTS:
                raise AssetError("Refusing image redirected outside Wikimedia")
            while True:
                chunk = r.read(1024 * 1024)
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > MAX_BYTES:
                    raise AssetError("Image exceeds the 20 MiB limit")
    except (HTTPError, URLError, TimeoutError) as e:
        raise AssetError("Image download failed: " + str(e)) from e
    suffix = next((ext for ext, recognizer in SUPPORTED_IMAGE_HEADERS.items()
                   if recognizer(data)), None)
    if not suffix:
        raise AssetError("Download is not a supported JPEG, PNG, WebP, or GIF image")
    dest = destination.with_suffix("." + suffix)
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as tmp:
        temp = Path(tmp.name)
        try:
            tmp.write(data)
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
    os.replace(temp, dest)
    return dest


def is_public_domain(image):
    license_name = image.get("license", "").lower().strip()
    return (license_name in {"cc0", "cc0 1.0", "public domain", "public domain mark"}
            or license_name.startswith(("pd-", "public domain ")))


def fetch_image(query, cache_dir=None, offline=False, result=0, license="any"):
    if not isinstance(result, int) or isinstance(result, bool) or not 0 <= result <= 14:
        raise AssetError("Image result must be an integer from 0 to 14")
    if license not in ("any", "public-domain"):
        raise AssetError("Image license must be any or public-domain")
    cache = Path(cache_dir) if cache_dir else cache_root()
    cache.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(("commons-v2:" + query.strip() + ":" + str(result) + ":" + license).encode("utf-8")).hexdigest()[:24]
    stem = cache / ("commons-" + key)
    meta_path = stem.with_suffix(".json")
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            path = Path(meta["local_path"])
            if path.is_file() and path.stat().st_size:
                return path, meta
        except (ValueError, KeyError, OSError):
            pass
    if offline or os.environ.get("EIDOLON_OFFLINE") == "1":
        raise AssetError("Image not cached and EIDOLON_OFFLINE=1: " + query)
    images = search_images(query, limit=max(6, result + 1))
    if license == "public-domain":
        images = [i for i in images if is_public_domain(i)]
    if not images or result >= len(images):
        raise AssetError("No matching Commons image at selected result " + str(result) + " for: " + query)
    last_error = None
    for image in images[result:result + 4]:
        try:
            path = _download_image(image["download_url"], stem)
        except AssetError as e:
            last_error = e
            continue
        meta = {**image, "query": query, "result": result, "license_filter": license, "local_path": str(path)}
        temp = meta_path.with_suffix(".tmp")
        temp.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, meta_path)
        return path, meta
    raise AssetError("No compatible downloadable images for " + query + ": " + str(last_error))


def _absolute(value, root):
    if not isinstance(value, str) or not value:
        return value
    if "://" in value:
        raise AssetError("Remote src URLs are not supported; use media.search for Commons assets")
    return str((root / value).resolve())


def prepare(source, target, attribution_path=None, cache_dir=None):
    source, target = Path(source).resolve(), Path(target)
    try:
        project = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise AssetError("Cannot load video JSON: " + str(e)) from e
    if not isinstance(project, dict) or not isinstance(project.get("scenes"), list):
        raise AssetError("Video JSON must contain a scenes array")
    root = source.parent
    # Semantic scenes are expanded before resolving assets, while paths still
    # refer to the original project directory.
    import importlib.util
    edu_path = Path(os.environ.get("EIDOLON_EDUCATION_SOURCE", str(Path(__file__).with_name("education.py"))))
    edu_spec = importlib.util.spec_from_file_location("eidolon_education", edu_path)
    edu = importlib.util.module_from_spec(edu_spec)
    edu_spec.loader.exec_module(edu)
    try:
        project = edu.expand_project(project)
    except edu.EducationError as exc:
        raise AssetError(str(exc)) from exc
    # Validate math before any image downloads or LaTeX subprocesses.
    import importlib.util
    latex_path = Path(os.environ.get("EIDOLON_LATEX_SOURCE", str(Path(__file__).with_name("latex_assets.py"))))
    latex_spec = importlib.util.spec_from_file_location("eidolon_latex", latex_path)
    latex = importlib.util.module_from_spec(latex_spec)
    latex_spec.loader.exec_module(latex)
    try:
        latex.validate_project(project)
    except latex.LatexError as exc:
        raise AssetError(str(exc)) from exc
    credits = []
    if "music" in project:
        project["music"] = _absolute(project["music"], root)
    for index, scene in enumerate(project["scenes"]):
        if not isinstance(scene, dict):
            raise AssetError("Scene " + str(index) + " is not an object")
        if "audio" in scene:
            scene["audio"] = _absolute(scene["audio"], root)
        media = scene.get("media")
        if not isinstance(media, dict):
            continue
        if "search" in media:
            if media.get("provider", "commons") != "commons":
                raise AssetError("Unsupported image provider: " + str(media["provider"]))
            if media.get("kind", "image") != "image":
                raise AssetError("media.search currently supports only image scenes")
            path, meta = fetch_image(
                media["search"], cache_dir=cache_dir,
                result=media.get("result", 0), license=media.get("license", "any"))
            media["kind"] = "image"
            media["src"] = str(path)
            media.pop("search", None)
            media.pop("provider", None)
            media.pop("result", None)
            media.pop("license", None)
            credits.append({"scene": index + 1, **{k: v for k, v in meta.items()
                            if k != "local_path"}})
        elif "src" in media:
            media["src"] = _absolute(media["src"], root)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        latex.materialize_project(project, target.parent)
    except latex.LatexError as exc:
        raise AssetError(str(exc)) from exc
    target.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if attribution_path and credits:
        ap = Path(attribution_path)
        ap.parent.mkdir(parents=True, exist_ok=True)
        ap.write_text(json.dumps(credits, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return credits


def main(argv=None):
    parser = argparse.ArgumentParser(description="Keyless Wikimedia Commons media for Eidolon")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_cmd = commands.add_parser("prepare", help="Resolve image searches in a JSON video")
    prepare_cmd.add_argument("source")
    prepare_cmd.add_argument("target")
    prepare_cmd.add_argument("--attribution")
    search_cmd = commands.add_parser("search", help="Find Commons images and reuse metadata")
    search_cmd.add_argument("query")
    search_cmd.add_argument("--limit", type=int, default=6)
    fetch_cmd = commands.add_parser("fetch", help="Download and cache the best search result")
    fetch_cmd.add_argument("query")
    fetch_cmd.add_argument("--output", help="Copy the chosen image to this file or directory")
    fetch_cmd.add_argument("--result", type=int, default=0,
                           help="Zero-based result rank (0 to 14)")
    fetch_cmd.add_argument("--license", choices=("any", "public-domain"), default="any",
                           help="Optional public-domain-only filter")
    args = parser.parse_args(argv)
    try:
        if args.command == "search":
            print(json.dumps(search_images(args.query, args.limit), ensure_ascii=False, indent=2))
        elif args.command == "fetch":
            path, meta = fetch_image(args.query, result=args.result, license=args.license)
            if args.output:
                out = Path(args.output)
                if out.is_dir() or str(args.output).endswith("/"):
                    out.mkdir(parents=True, exist_ok=True)
                    out = out / path.name
                else:
                    out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, out)
                out.with_name(out.name + ".attribution.json").write_text(
                    json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                path = out
            print(str(path))
        elif args.command == "prepare":
            credits = prepare(args.source, args.target, args.attribution)
            print("eidolon: resolved " + str(len(credits)) + " Commons image(s)", file=sys.stderr)
        return 0
    except (AssetError, OSError) as e:
        print("eidolon images: " + str(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
