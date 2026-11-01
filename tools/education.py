"""Deterministic compiler for high-level educational video scenes.

Expands scene.educational to regular Eidolon SVG elements. No network, AI,
external packages, or renderer dependency. All coordinates become pixels;
the Babel director continues to render and schedule the resulting scene.
"""
from __future__ import annotations

import copy
import math


class EducationError(ValueError):
    """Invalid semantic scene specification."""


COLORS = ("cyan", "ice", "white", "muted", "navy", "ink", "panel", "slate",
          "blue", "purple", "rose", "red", "orange", "yellow", "green", "black")
SERIES_COLORS = ("cyan", "purple", "green", "orange", "rose", "blue")
MAX_ELEMENTS = 600


def fail(message):
    raise EducationError(message)


def number(value, name, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        fail(f"{name} must be a finite number")
    value = float(value)
    if minimum is not None and value < minimum:
        fail(f"{name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        fail(f"{name} must be <= {maximum}")
    return value


def text(value, name, limit=200):
    if not isinstance(value, str) or not value or len(value) > limit:
        fail(f"{name} must be nonempty text (max {limit} characters)")
    return value


def bounded_list(value, name, minimum=1, maximum=60):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        fail(f"{name} must contain {minimum} to {maximum} items")
    return value


def color(value, name="color"):
    if not isinstance(value, str) or value not in COLORS:
        fail(f"{name} must be a supported palette color")
    return value


def point(value, name, width, height):
    bounded_list(value, name, 2, 2)
    return (round(number(value[0], name + "[0]", 0, 1) * width),
            round(number(value[1], name + "[1]", 0, 1) * height))


def line(x1, y1, x2, y2, stroke="cyan", thickness=3, arrow=False, **extra):
    return dict(kind="arrow" if arrow else "line",
                x1=int(x1), y1=int(y1), x2=int(x2), y2=int(y2),
                stroke=stroke, stroke_width=thickness, **extra)


def label(value, x, y, size=28, fill="white", **extra):
    return dict(kind="text", value=str(value), x=int(x), y=int(y),
                font_size=int(size), fill=fill, **extra)


def circle(x, y, radius=12, fill="cyan", **extra):
    return dict(kind="circle", cx=int(x), cy=int(y), r=int(radius),
                fill=fill, **extra)


def rect(x, y, width, height, fill="panel", radius=12, **extra):
    return dict(kind="rect", x=int(x), y=int(y), width=int(width),
                height=int(height), radius=int(radius), fill=fill, **extra)


def header(spec, width, height):
    title = spec.get("title")
    if title is None:
        return []
    title = text(title, "educational.title", 120)
    return [label(title, width * .07, height * .14,
                  size=max(18, min(56, height // 14)), weight="bold")]


def _caption_size(height):
    return max(15, min(28, height // 25))


def _fade(element, start, end):
    element["from"] = {"opacity": 0}
    element["to"] = {"opacity": 100}
    element["start_percent"] = int(start)
    element["end_percent"] = int(end)
    return element


def diagram(spec, width, height):
    nodes = bounded_list(spec.get("nodes"), "diagram.nodes", 2, 24)
    edges = spec.get("edges", [])
    bounded_list(edges, "diagram.edges", 0, 60)
    layout = spec.get("layout", "horizontal")
    if layout not in ("horizontal", "vertical"):
        fail("diagram.layout must be horizontal or vertical")
    positions, out = {}, []
    for i, node in enumerate(nodes):
        if not isinstance(node, dict):
            fail("diagram nodes must be objects")
        node_id = text(node.get("id"), "node.id", 50)
        if node_id in positions:
            fail("duplicate diagram node id: " + node_id)
        if "position" in node:
            x, y = point(node["position"], "node.position", width, height)
        elif layout == "horizontal":
            x, y = round(width * (.15 + .70 * i / max(1, len(nodes) - 1))), round(height * .53)
        else:
            x, y = round(width * .5), round(height * (.27 + .57 * i / max(1, len(nodes) - 1)))
        positions[node_id] = (x, y, node)
    for edge in edges:
        if not isinstance(edge, dict):
            fail("diagram edges must be objects")
        source, target = edge.get("from"), edge.get("to")
        if source not in positions or target not in positions:
            fail("diagram edge references an unknown node")
        x1, y1, _ = positions[source]
        x2, y2, _ = positions[target]
        out.append(line(x1, y1, x2, y2, color(edge.get("color", "muted")),
                        thickness=4, arrow=edge.get("arrow", True) is True))
    for i, (node_id, (x, y, node)) in enumerate(positions.items()):
        fill = color(node.get("color", SERIES_COLORS[i % len(SERIES_COLORS)]))
        out.append(circle(x, y, min(width, height) * .040, fill))
        caption = text(node.get("label", node_id), "node.label", 80)
        out.append(_fade(label(caption, x - min(120, len(caption) * 7), y + height * .083,
                               _caption_size(height)), 5, 38))
    return out


def graph(spec, width, height):
    series = bounded_list(spec.get("series"), "graph.series", 1, 6)
    left, right = round(width * .12), round(width * .88)
    top, bottom = round(height * .28), round(height * .77)
    sets = []
    for i, item in enumerate(series):
        if not isinstance(item, dict):
            fail("graph.series entries must be objects")
        values = bounded_list(item.get("values"), "series.values", 2, 120)
        values = [number(v, "series.values") for v in values]
        sets.append((text(item.get("name", f"Series {i+1}"), "series.name", 40), values,
                     color(item.get("color", SERIES_COLORS[i % len(SERIES_COLORS)]))))
    low = number(spec.get("min", min(min(values) for _, values, _ in sets)), "graph.min")
    high = number(spec.get("max", max(max(values) for _, values, _ in sets)), "graph.max")
    if high <= low:
        # Flat data remains useful. Give it an explicit visible range.
        if "min" in spec or "max" in spec:
            fail("graph.max must be larger than graph.min")
        low -= 1
        high += 1
    out = [line(left, top, left, bottom, "muted", 2),
           line(left, bottom, right, bottom, "muted", 2)]
    for i in range(5):
        y = round(bottom - (bottom - top) * i / 4)
        out.append(line(left, y, right, y, "slate", 1))
        out.append(label(f"{low + (high-low)*i/4:.2g}", width * .025,
                         y + 8, max(12, height // 34), "muted"))
    for i, (name, values, shade) in enumerate(sets):
        coords = [
            {"x": round(left + (right-left)*j/(len(values)-1)),
             "y": round(bottom - (bottom-top)*(value-low)/(high-low))}
            for j, value in enumerate(values)
        ]
        curve = {"kind": "polyline", "points": coords, "stroke": shade,
                 "stroke_width": max(2, width // 320)}
        if spec.get("reveal", True) is True:
            curve["reveal"] = True
            curve["start_percent"] = 8
            curve["end_percent"] = 95
        out.append(curve)
        legend_x = left + (right-left)*i/max(1, len(sets))
        legend_y = round(height * .86)
        out.append(circle(legend_x, legend_y-7, 6, shade))
        out.append(label(name, legend_x+12, legend_y, max(12, height//34), "white"))
    return out


def timeline(spec, width, height):
    events = bounded_list(spec.get("events"), "timeline.events", 2, 10)
    parsed = []
    for event in events:
        if not isinstance(event, dict):
            fail("timeline events must be objects")
        parsed.append((number(event.get("at"), "event.at"),
                       text(event.get("label"), "event.label", 55)))
    parsed.sort(key=lambda pair: pair[0])
    lo, hi = parsed[0][0], parsed[-1][0]
    if hi <= lo:
        fail("timeline events must have distinct start and end times")
    left, right = round(width * .12), round(width * .88)
    mid = round(height * .55)
    out = [line(left, mid, right, mid, "muted", 4, arrow=True)]
    for i, (at, name) in enumerate(parsed):
        x = round(left + (right-left)*(at-lo)/(hi-lo))
        above = i % 2 == 0
        y2 = mid + (-height * .13 if above else height * .13)
        out.extend([circle(x, mid, 10, SERIES_COLORS[i % len(SERIES_COLORS)]),
                    line(x, mid, x, round(y2), "slate", 2),
                    _fade(label(name, min(x, right-100), y2 + (-12 if above else 30),
                                _caption_size(height)), 5 + i*7, min(100, 30+i*7))])
    return out


def comparison(spec, width, height):
    items = bounded_list(spec.get("items"), "comparison.items", 2, 6)
    max_value = number(spec.get("max", 100), "comparison.max", .000001)
    out = []
    x, bar_x = round(width * .08), round(width * .36)
    bar_width, bar_height = round(width * .52), max(10, round(height * .046))
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            fail("comparison items must be objects")
        name = text(item.get("name"), "comparison.item.name", 50)
        value = number(item.get("value"), "comparison.item.value", 0, max_value)
        shade = color(item.get("color", SERIES_COLORS[i % len(SERIES_COLORS)]))
        y = round(height * (.29 + .58 * i / max(1, len(items)-1)))
        out.extend([label(name, x, y + bar_height, _caption_size(height)),
                    rect(bar_x, y, bar_width, bar_height, "slate", 7)])
        final_width = round(bar_width * value / max_value)
        out.append(dict(kind="rect", x=bar_x, y=y, width=final_width,
                        height=bar_height, radius=7, fill=shade,
                        **{"from": {"width": 0}, "to": {"width": final_width},
                           "start_percent": 5+i*6, "end_percent": min(96, 65+i*6)}))
        out.append(label(f"{value:g}", bar_x+bar_width+12, y+bar_height,
                         _caption_size(height), "ice"))
    return out


def signal(spec, width, height):
    points = bounded_list(spec.get("path"), "signal.path", 2, 24)
    coords = [point(p, "signal.path point", width, height) for p in points]
    start = int(number(spec.get("start_percent", 8), "signal.start_percent", 0, 100))
    end = int(number(spec.get("end_percent", 90), "signal.end_percent", start+1, 100))
    shade = color(spec.get("color", "cyan"))
    out = [line(*a, *b, "muted", max(3, width//250))
           for a, b in zip(coords, coords[1:])]
    segments = len(coords) - 1
    for i, ((x1, y1), (x2, y2)) in enumerate(zip(coords, coords[1:])):
        a = round(start + (end-start)*i/segments)
        b = round(start + (end-start)*(i+1)/segments)
        out.append(dict(kind="circle", cx=x2, cy=y2,
                        r=max(6, min(width, height)//45), fill=shade,
                        **{"from": {"cx": x1, "cy": y1},
                           "to": {"cx": x2, "cy": y2},
                           "start_percent": a, "end_percent": max(a+1, b),
                           "visible_start_percent": a,
                           "visible_end_percent": max(a+1, b)}))
    return out


def neuron(spec, width, height):
    y = round(height*.53)
    soma_x = round(width*.30)
    axon_end = round(width*.82)
    shade = color(spec.get("color", "cyan"))
    out = []
    for dy in (-.17, -.085, .085, .17):
        px, py = round(width*.14), round(y + height*dy)
        out.extend([line(px, py, soma_x, y, "blue", 4),
                    circle(px, py, 6, "blue")])
    out.append(circle(soma_x, y, min(width, height)//12, shade))
    out.append(circle(soma_x, y, min(width, height)//30, "navy"))
    out.extend([line(soma_x + min(width,height)//12, y, axon_end, y, shade, 6),
                line(axon_end, y, round(width*.90), round(y-height*.09), "purple", 4),
                line(axon_end, y, round(width*.90), round(y+height*.09), "purple", 4)])
    for i, (caption, x, label_y) in enumerate((
        ("Dendrites", width*.11, height*.29),
        ("Cell body", width*.26, height*.76),
        ("Axon", width*.59, height*.38),
        ("Terminals", width*.78, height*.76),
    )):
        out.append(_fade(label(caption, x, label_y, _caption_size(height)),
                         6+i*8, 36+i*8))
    pulse = {"path": [[(soma_x+min(width,height)//12)/width, y/height],
                       [axon_end/width, y/height],
                       [.90, (y-height*.09)/height]],
             "start_percent": 25, "end_percent": 90, "color": "orange"}
    out.extend(signal(pulse, width, height))
    return out


def simulation(spec, width, height):
    if spec.get("model", "integrate-and-fire") != "integrate-and-fire":
        fail("simulation.model must be integrate-and-fire")
    values = bounded_list(spec.get("input"), "simulation.input", 2, 100)
    values = [number(v, "simulation.input") for v in values]
    decay = number(spec.get("decay", .85), "simulation.decay", 0, 1)
    threshold = number(spec.get("threshold", 1), "simulation.threshold", .000001)
    reset = number(spec.get("reset", 0), "simulation.reset", 0, threshold)
    membrane, readings, spikes = 0.0, [], []
    for i, current in enumerate(values):
        membrane = max(0.0, membrane*decay + current)
        readings.append(membrane)
        if membrane >= threshold:
            spikes.append(i)
            membrane = reset
    visual = graph({"series": [{"name": "Membrane potential", "values": readings,
                                "color": "cyan"}],
                    "min": 0, "max": max(threshold*1.15, max(readings)*1.05),
                    "reveal": True}, width, height)
    left, right = round(width*.12), round(width*.88)
    top, bottom = round(height*.28), round(height*.77)
    high = max(threshold*1.15, max(readings)*1.05)
    y = round(bottom - (bottom-top)*threshold/high)
    visual.append(line(left, y, right, y, "orange", 2))
    visual.append(label("Threshold", left+12, y-10, _caption_size(height), "orange"))
    for i in spikes:
        x = round(left+(right-left)*i/(len(readings)-1))
        visual.append(circle(x, top+8, 7, "rose"))
    visual.append(label(f"Spikes: {len(spikes)}", width*.72, height*.2,
                        _caption_size(height), "rose"))
    return visual


RENDERERS = {
    "diagram": diagram,
    "graph": graph,
    "timeline": timeline,
    "comparison": comparison,
    "signal": signal,
    "neuron": neuron,
    "simulation": simulation,
}


def callouts(spec, width, height):
    out = []
    for i, item in enumerate(bounded_list(spec, "educational.callouts", 0, 20)):
        if not isinstance(item, dict):
            fail("callout must be an object")
        x, y = point(item.get("position"), "callout.position", width, height)
        out.append(_fade(label(text(item.get("text"), "callout.text", 100),
                               x, y, _caption_size(height),
                               color(item.get("color", "ice"))),
                         min(90, 6+i*9), min(100, 37+i*9)))
    return out


def expand_project(project):
    """Return a new project with high-level scenes compiled to ordinary elements."""
    if not isinstance(project, dict):
        fail("project must be an object")
    output = copy.deepcopy(project)
    width = int(number(output.get("width", 1280), "width", 64, 8192))
    height = int(number(output.get("height", 720), "height", 64, 8192))
    if width != output.get("width", 1280) or height != output.get("height", 720):
        fail("width and height must be integers")
    scenes = bounded_list(output.get("scenes"), "scenes", 1, 200)
    for index, scene in enumerate(scenes, 1):
        if not isinstance(scene, dict):
            fail(f"scene {index} must be an object")
        spec = scene.get("educational")
        if spec is None:
            continue
        if not isinstance(spec, dict):
            fail(f"scene {index}: educational must be an object")
        kind = spec.get("type")
        if kind not in RENDERERS:
            fail(f"scene {index}: unsupported educational type {kind!r}")
        existing = scene.get("elements", [])
        if not isinstance(existing, list):
            fail(f"scene {index}: elements must be an array")
        try:
            new_elements = header(spec, width, height)
            new_elements.extend(RENDERERS[kind](spec, width, height))
            if "callouts" in spec:
                new_elements.extend(callouts(spec["callouts"], width, height))
        except EducationError as exc:
            fail(f"scene {index}: {exc}")
        if len(new_elements) + len(existing) > MAX_ELEMENTS:
            fail(f"scene {index}: too many rendered elements (max {MAX_ELEMENTS})")
        scene["elements"] = new_elements + existing
        scene.pop("educational")
    return output
