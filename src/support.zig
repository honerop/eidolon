const std = @import("std");

pub const Allocator = std.mem.Allocator;
pub const Value = std.json.Value;

// Shell commands are assembled from individually single-quoted arguments.
// This preserves spaces and prevents media paths or narration becoming shell code.
extern "c" fn fopen([*:0]const u8, [*:0]const u8) ?*anyopaque;
extern "c" fn fclose(?*anyopaque) c_int;
extern "c" fn fseek(?*anyopaque, c_long, c_int) c_int;
extern "c" fn ftell(?*anyopaque) c_long;
extern "c" fn fread([*]u8, usize, usize, ?*anyopaque) usize;
extern "c" fn fwrite([*]const u8, usize, usize, ?*anyopaque) usize;
extern "c" fn popen([*:0]const u8, [*:0]const u8) ?*anyopaque;
extern "c" fn pclose(?*anyopaque) c_int;
extern "c" fn system([*:0]const u8) c_int;
extern "c" fn getenv([*:0]const u8) ?[*:0]const u8;

pub fn env(name: [*:0]const u8, default: []const u8) []const u8 {
    return if (getenv(name)) |value| std.mem.span(value) else default;
}
pub fn eq(a: []const u8, b: []const u8) bool {
    return std.mem.eql(u8, a, b);
}
pub fn fmt(a: Allocator, comptime form: []const u8, args: anytype) ![]const u8 {
    return std.fmt.allocPrint(a, form, args);
}
pub fn join(a: Allocator, parts: []const []const u8) ![]const u8 {
    return std.mem.concat(a, u8, parts);
}
pub fn field(value: Value, name: []const u8) Value {
    return if (value == .object) value.object.get(name) orelse .null else .null;
}
pub fn string(value: Value, default: []const u8) []const u8 {
    return if (value == .string) value.string else default;
}
pub fn number(value: Value, default: f64) f64 {
    return switch (value) {
        .integer => @floatFromInt(value.integer),
        .float => value.float,
        .number_string => std.fmt.parseFloat(f64, value.number_string) catch default,
        else => default,
    };
}
pub fn integer(value: Value, default: i64) i64 {
    const x = number(value, @floatFromInt(default));
    if (!std.math.isFinite(x) or x > 1000000000 or x < -1000000000) return default;
    return @intFromFloat(x);
}
pub fn boolean(value: Value, default: bool) bool {
    return if (value == .bool) value.bool else default;
}
pub fn array(value: Value) []const Value {
    return if (value == .array) value.array.items else &.{};
}
pub fn getStr(value: Value, name: []const u8, default: []const u8) []const u8 {
    return string(field(value, name), default);
}
pub fn getInt(value: Value, name: []const u8, default: i64) i64 {
    return integer(field(value, name), default);
}
pub fn getBool(value: Value, name: []const u8, default: bool) bool {
    return boolean(field(value, name), default);
}

pub fn readFile(a: Allocator, path: []const u8) ![]const u8 {
    const z = try a.dupeZ(u8, path);
    const f = fopen(z, "rb") orelse return error.OpenFailed;
    defer _ = fclose(f);
    if (fseek(f, 0, 2) != 0) return error.SeekFailed;
    const size = ftell(f);
    if (size < 0 or size > 32 * 1024 * 1024) return error.FileTooLarge;
    if (fseek(f, 0, 0) != 0) return error.SeekFailed;
    const data = try a.alloc(u8, @intCast(size));
    if (fread(data.ptr, 1, data.len, f) != data.len) return error.ReadFailed;
    return data;
}
pub fn writeFile(a: Allocator, path: []const u8, data: []const u8) !void {
    const z = try a.dupeZ(u8, path);
    const f = fopen(z, "wb") orelse return error.CreateFailed;
    defer _ = fclose(f);
    if (fwrite(data.ptr, 1, data.len, f) != data.len) return error.WriteFailed;
}
pub fn shellQuote(a: Allocator, arg: []const u8) ![]const u8 {
    var result: std.ArrayList(u8) = .empty;
    try result.append(a, '\'');
    for (arg) |byte| {
        if (byte == '\'') {
            try result.appendSlice(a, "'\\''");
        } else {
            try result.append(a, byte);
        }
    }
    try result.append(a, '\'');
    return result.toOwnedSlice(a);
}
pub fn shellCommand(a: Allocator, program: []const u8, arguments: []const []const u8) ![]const u8 {
    var result: std.ArrayList(u8) = .empty;
    try result.appendSlice(a, try shellQuote(a, program));
    for (arguments) |argument| {
        try result.append(a, ' ');
        try result.appendSlice(a, try shellQuote(a, argument));
    }
    return result.toOwnedSlice(a);
}
pub fn run(a: Allocator, program: []const u8, arguments: []const []const u8) !void {
    const command = try shellCommand(a, program, arguments);
    if (system(try a.dupeZ(u8, command)) != 0) {
        std.log.err("command failed: {s}", .{command});
        return error.ProcessFailed;
    }
}
pub fn capture(a: Allocator, program: []const u8, arguments: []const []const u8) ![]const u8 {
    const command = try shellCommand(a, program, arguments);
    const pipe = popen(try a.dupeZ(u8, command), "r") orelse return error.ProcessFailed;
    var result: std.ArrayList(u8) = .empty;
    // Read using libc to avoid unbounded pipeline buffering.
    const c = struct {
        extern "c" fn fgetc(?*anyopaque) c_int;
    };
    while (true) {
        const byte = c.fgetc(pipe);
        if (byte == -1) break;
        if (result.items.len >= 65536) {
            _ = pclose(pipe);
            return error.OutputTooLarge;
        }
        try result.append(a, @intCast(byte));
    }
    if (pclose(pipe) != 0) return error.ProcessFailed;
    return result.toOwnedSlice(a);
}
pub fn directoryOf(path: []const u8) []const u8 {
    const index = std.mem.lastIndexOfScalar(u8, path, '/') orelse return ".";
    return if (index == 0) "/" else path[0..index];
}
pub fn absoluteOrJoin(a: Allocator, root: []const u8, path: []const u8) ![]const u8 {
    if (path.len == 0 or path[0] == '/') return path;
    return fmt(a, "{s}/{s}", .{ root, path });
}
pub fn escapeXml(a: Allocator, value: []const u8) ![]const u8 {
    var result: std.ArrayList(u8) = .empty;
    for (value) |ch| {
        const replacement: []const u8 = switch (ch) {
            '&' => "&amp;",
            '<' => "&lt;",
            '>' => "&gt;",
            '"' => "&quot;",
            '\'' => "&apos;",
            else => &.{ch},
        };
        try result.appendSlice(a, replacement);
    }
    return result.toOwnedSlice(a);
}
pub fn appendFmt(out: *std.ArrayList(u8), a: Allocator, comptime form: []const u8, args: anytype) !void {
    try out.appendSlice(a, try fmt(a, form, args));
}
pub fn palette(name: []const u8) []const u8 {
    const values = [_][]const u8{
        "cyan", "ice", "white", "muted", "navy", "ink", "panel", "slate",
        "blue", "purple", "rose", "red", "orange", "yellow", "green", "black",
    };
    const colors = [_][]const u8{
        "#48dff0", "#b9f9ff", "#f1f7ff", "#8b9cb2", "#101c34", "#080d19",
        "#17253b", "#324059", "#6189ff", "#b592ff", "#ff8da9", "#ff7088",
        "#ffbd75", "#ffe18c", "#7df1bc", "#000000",
    };
    for (values, 0..) |entry, i| if (eq(name, entry)) return colors[i];
    return "#48dff0";
}

test "quotes escaped paths without injecting shell syntax" {
    const a = std.testing.allocator;
    const q = try shellQuote(a, "a'; touch /tmp/foo");
    defer a.free(q);
    try std.testing.expect(eq(q, "'a'\\''; touch /tmp/foo'"));
}
