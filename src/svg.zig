const std = @import("std");
const s = @import("support.zig");
const A = s.Allocator;
const V = s.Value;
const F = s.appendFmt;

fn prop(v: V, key: []const u8, fallback: f64) f64 {
    return s.number(s.field(v, key), fallback);
}
fn val(element: V, key: []const u8, default: f64, frame: usize, frames: usize) f64 {
    const base = prop(element, key, default);
    const from = prop(s.field(element, "from"), key, base);
    const to = prop(s.field(element, "to"), key, base);
    const total = if (frames <= 1) 1 else frames - 1;
    const frame_pct: f64 = @as(f64, @floatFromInt(frame)) * 100 / @as(f64, @floatFromInt(total));
    const start = prop(element, "start_percent", 0);
    const end = prop(element, "end_percent", 100);
    var pct: f64 = if (end <= start)
        (if (frame_pct >= end) 1 else 0)
    else
        @max(0, @min(1, (frame_pct - start) / (end - start)));
    if (s.eq(s.getStr(element, "ease", ""), "smooth")) pct = pct * pct * (3 - 2 * pct);
    return from + (to - from) * pct;
}
fn n(v: V, name: []const u8, d: f64) f64 {
    return prop(v, name, d);
}
fn palette(v: V, name: []const u8, fallback: []const u8) []const u8 {
    return s.palette(s.getStr(v, name, fallback));
}
fn visible(el: V, frame: usize, total: usize) bool {
    const pct: f64 = @as(f64, @floatFromInt(frame)) * 100 / @as(f64, @floatFromInt(if (total > 1) total - 1 else 1));
    return pct >= prop(el, "visible_start_percent", 0) and pct <= prop(el, "visible_end_percent", 100);
}
fn opacity(el: V, frame: usize, count: usize) f64 {
    return @max(0, @min(1, val(el, "opacity", 100, frame, count) / 100));
}
fn drawLine(out: *std.ArrayList(u8), a: A, e: V, frame: usize, total: usize, arrow: bool) !void {
    try F(out, a,
        "<line x1=\"{d:.2}\" y1=\"{d:.2}\" x2=\"{d:.2}\" y2=\"{d:.2}\" stroke=\"{s}\" stroke-width=\"{d:.2}\" stroke-linecap=\"round\" opacity=\"{d:.3}\" {s}/>",
        .{
            val(e, "x1", 0, frame, total), val(e, "y1", 0, frame, total),
            val(e, "x2", 0, frame, total), val(e, "y2", 0, frame, total),
            palette(e, "stroke", "cyan"), n(e, "stroke_width", 3), opacity(e, frame, total),
            if (arrow) "marker-end=\"url(#eidolon-arrow)\"" else "",
        });
}
fn drawText(out: *std.ArrayList(u8), a: A, e: V, frame: usize, total: usize) !void {
    const txt = try s.escapeXml(a, s.getStr(e, "value", ""));
    try F(out, a,
        "<text x=\"{d:.2}\" y=\"{d:.2}\" font-size=\"{d:.2}\" font-family=\"DejaVu Sans, sans-serif\" font-weight=\"{s}\" fill=\"{s}\" opacity=\"{d:.3}\">{s}</text>",
        .{
            val(e, "x", 0, frame, total), val(e, "y", 0, frame, total),
            n(e, "font_size", 42),
            if (s.eq(s.getStr(e, "weight", ""), "bold")) "700" else "500",
            palette(e, "fill", "white"), opacity(e, frame, total), txt,
        });
}
fn drawRect(out: *std.ArrayList(u8), a: A, e: V, frame: usize, total: usize) !void {
    try F(out, a, "<rect x=\"{d:.2}\" y=\"{d:.2}\" width=\"{d:.2}\" height=\"{d:.2}\" rx=\"{d:.2}\" fill=\"{s}\" opacity=\"{d:.3}\"/>",
        .{ val(e, "x", 0, frame, total), val(e, "y", 0, frame, total),
            @max(0, val(e, "width", 0, frame, total)), @max(0, val(e, "height", 0, frame, total)),
            n(e, "radius", 0), palette(e, "fill", "cyan"), opacity(e, frame, total) });
}
fn drawCircle(out: *std.ArrayList(u8), a: A, e: V, frame: usize, total: usize) !void {
    try F(out, a, "<circle cx=\"{d:.2}\" cy=\"{d:.2}\" r=\"{d:.2}\" fill=\"{s}\" opacity=\"{d:.3}\"/>",
        .{ val(e, "cx", 0, frame, total), val(e, "cy", 0, frame, total),
            @max(0, val(e, "r", 0, frame, total)), palette(e, "fill", "cyan"), opacity(e, frame, total) });
}
fn drawPoly(out: *std.ArrayList(u8), a: A, e: V, frame: usize, total: usize) !void {
    const points = s.array(s.field(e, "points"));
    var last = points.len;
    if (s.getBool(e, "reveal", false)) {
        const start = n(e, "start_percent", 0);
        const end = n(e, "end_percent", 100);
        const pct = @as(f64, @floatFromInt(frame)) * 100 / @as(f64, @floatFromInt(if (total > 1) total - 1 else 1));
        const u = if (end <= start) @as(f64, if (pct >= end) 1 else 0) else @max(0, @min(1, (pct - start) / (end - start)));
        last = @intFromFloat(@floor(@as(f64, @floatFromInt(points.len)) * u));
    }
    try out.appendSlice(a, "<polyline fill=\"none\" points=\"");
    for (points[0..last]) |p| {
        try F(out, a, "{d:.2},{d:.2} ", .{ n(p, "x", 0), n(p, "y", 0) });
    }
    try F(out, a, "\" stroke=\"{s}\" stroke-width=\"{d:.2}\" stroke-linejoin=\"round\" stroke-linecap=\"round\" opacity=\"{d:.3}\"/>",
        .{ palette(e, "stroke", "cyan"), n(e, "stroke_width", 3), opacity(e, frame, total) });
}
fn drawImage(out: *std.ArrayList(u8), a: A, e: V, frame: usize, total: usize) !void {
    const href = try s.escapeXml(a, s.getStr(e, "src", ""));
    try F(out, a, "<image href=\"{s}\" x=\"{d:.2}\" y=\"{d:.2}\" width=\"{d:.2}\" height=\"{d:.2}\" opacity=\"{d:.3}\"/>",
        .{ href, val(e, "x", 0, frame, total), val(e, "y", 0, frame, total),
            @max(1, val(e, "width", 1, frame, total)), @max(1, val(e, "height", 1, frame, total)),
            opacity(e, frame, total) });
}
fn drawAxes(out: *std.ArrayList(u8), a: A, e: V) !void {
    const x = n(e, "x", 0);
    const y = n(e, "y", 0);
    const width = n(e, "width", 1);
    const height = n(e, "height", 1);
    const xmin = n(e, "x_min", -5);
    const xmax = n(e, "x_max", 5);
    const ymin = n(e, "y_min", -3);
    const ymax = n(e, "y_max", 3);
    const origin_x = x + width * (0 - xmin) / @max(0.001, xmax - xmin);
    const origin_y = y + height * (ymax - 0) / @max(0.001, ymax - ymin);
    try F(out, a, "<line x1=\"{d:.2}\" y1=\"{d:.2}\" x2=\"{d:.2}\" y2=\"{d:.2}\" stroke=\"{s}\" stroke-width=\"2\" opacity=\"0.7\"/>",
        .{ origin_x, y, origin_x, y + height, palette(e, "stroke", "slate") });
    try F(out, a, "<line x1=\"{d:.2}\" y1=\"{d:.2}\" x2=\"{d:.2}\" y2=\"{d:.2}\" stroke=\"{s}\" stroke-width=\"2\" opacity=\"0.7\"/>",
        .{ x, origin_y, x + width, origin_y, palette(e, "stroke", "slate") });
}
fn drawPlot(out: *std.ArrayList(u8), a: A, e: V, frame: usize, total: usize) !void {
    const x0 = n(e, "x_min", -5);
    const x1 = n(e, "x_max", 5);
    const y0 = n(e, "y_min", -3);
    const y1 = n(e, "y_max", 3);
    const start = n(e, "start_percent", 0);
    const end = n(e, "end_percent", 100);
    const pct = @as(f64, @floatFromInt(frame)) * 100 / @as(f64, @floatFromInt(if (total > 1) total - 1 else 1));
    const u = if (end <= start) @as(f64, if (pct >= end) 1 else 0) else @max(0, @min(1, (pct - start) / (end - start)));
    const last: usize = @intFromFloat(@floor(180 * u));
    const function = s.getStr(e, "function", "quadratic");
    const param_a = n(e, "a", 1);
    const param_b = n(e, "b", 0);
    const param_c = n(e, "c", 0);
    try out.appendSlice(a, "<polyline fill=\"none\" points=\"");
    for (0..last + 1) |i| {
        const x = x0 + (x1 - x0) * @as(f64, @floatFromInt(i)) / 180;
        const y = if (s.eq(function, "sin")) param_a * @sin(x + param_b) + param_c
             else if (s.eq(function, "cos")) param_a * @cos(x + param_b) + param_c
             else if (s.eq(function, "linear")) param_a * x + param_c
             else if (s.eq(function, "cubic")) param_a * x * x * x + param_b * x + param_c
             else param_a * x * x + param_b * x + param_c;
        const screen_x = n(e, "x", 0) + n(e, "width", 1) * (x - x0) / @max(0.001, x1 - x0);
        const screen_y = n(e, "y", 0) + n(e, "height", 1) * (y1 - y) / @max(0.001, y1 - y0);
        if (std.math.isFinite(screen_y) and @abs(screen_y) < 1000000) {
            try F(out, a, "{d:.2},{d:.2} ", .{ screen_x, screen_y });
        }
    }
    try F(out, a, "\" stroke=\"{s}\" stroke-width=\"{d:.2}\" opacity=\"{d:.3}\"/>",
        .{ palette(e, "stroke", "cyan"), n(e, "stroke_width", 3), opacity(e, frame, total) });
}
pub fn document(a: A, scene: V, frame: usize, total: usize, width: usize, height: usize) ![]const u8 {
    var out: std.ArrayList(u8) = .empty;
    try F(&out, a,
        "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"{d}\" height=\"{d}\"><defs><marker id=\"eidolon-arrow\" markerWidth=\"10\" markerHeight=\"10\" refX=\"9\" refY=\"3\" orient=\"auto\"><path d=\"M0,0 L0,6 L9,3 Z\" fill=\"#48dff0\"/></marker></defs>",
        .{ width, height });
    if (s.field(scene, "media") == .null) {
        try F(&out, a, "<rect width=\"100%\" height=\"100%\" fill=\"{s}\"/>",
            .{palette(scene, "background", "ink")});
    }
    for (s.array(s.field(scene, "elements"))) |element| {
        if (!visible(element, frame, total)) continue;
        const kind = s.getStr(element, "kind", "");
        if (s.eq(kind, "text")) {
            try drawText(&out, a, element, frame, total);
        } else if (s.eq(kind, "rect")) {
            try drawRect(&out, a, element, frame, total);
        } else if (s.eq(kind, "circle")) {
            try drawCircle(&out, a, element, frame, total);
        } else if (s.eq(kind, "line") or s.eq(kind, "arrow")) {
            try drawLine(&out, a, element, frame, total, s.eq(kind, "arrow"));
        } else if (s.eq(kind, "polyline")) {
            try drawPoly(&out, a, element, frame, total);
        } else if (s.eq(kind, "plot")) {
            try drawPlot(&out, a, element, frame, total);
        } else if (s.eq(kind, "axes")) {
            try drawAxes(&out, a, element);
        } else if (s.eq(kind, "latex_image")) {
            try drawImage(&out, a, element, frame, total);
        }
    }
    try out.appendSlice(a, "</svg>");
    return out.toOwnedSlice(a);
}
test "svg preserves escaped caption text" {
    const a = std.testing.allocator;
    const source =
        \\{"elements":[{"kind":"text","x":20,"y":30,"value":"A & B"}]}
    ;
    const parsed = try std.json.parseFromSlice(V, a, source, .{});
    defer parsed.deinit();
    const result = try document(a, parsed.value, 0, 2, 160, 96);
    defer a.free(result);
    try std.testing.expect(std.mem.indexOf(u8, result, "A &amp; B") != null);
}
