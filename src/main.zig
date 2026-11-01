const std = @import("std");
const s = @import("support.zig");
const svg = @import("svg.zig");
const A = s.Allocator;
const V = s.Value;

const Scene = struct {
    data: V,
    start: usize,
    frames: usize,
    audio: []const u8,
};

const Renderer = struct {
    a: A,
    work: []const u8,
    root: []const u8,
    ffmpeg: []const u8,
    ffprobe: []const u8,
    rsvg: []const u8,
    tts: []const u8,
    espeak: []const u8,
    fps: usize,
    width: usize,
    height: usize,

    fn file(self: Renderer, name: []const u8) ![]const u8 {
        return s.fmt(self.a, "{s}/{s}", .{ self.work, name });
    }
    fn indexed(self: Renderer, prefix: []const u8, frame: usize, ext: []const u8) ![]const u8 {
        return self.file(try s.fmt(self.a, "{s}-{d:0>6}.{s}", .{ prefix, frame, ext }));
    }
    fn fpsString(self: Renderer) ![]const u8 {
        return s.fmt(self.a, "{d}", .{self.fps});
    }
    fn totalMillis(self: Renderer, frames: usize) usize {
        return @divTrunc(frames * 1000, self.fps);
    }
    fn resolution(self: Renderer) ![]const u8 {
        return s.fmt(self.a, "{d}x{d}", .{ self.width, self.height });
    }
    fn videoLen(self: Renderer, audio_path: []const u8) !usize {
        const output = try s.capture(self.a, self.ffprobe, &.{
            "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", audio_path,
        });
        const seconds = std.fmt.parseFloat(f64, std.mem.trim(u8, output, " \n\r\t")) catch return error.InvalidMediaDuration;
        if (!std.math.isFinite(seconds) or seconds <= 0 or seconds > 36000) return error.InvalidMediaDuration;
        return @intFromFloat(@ceil(seconds * 1000));
    }
    fn synthesize(self: Renderer, scene: V, index: usize) ![]const u8 {
        const source = s.getStr(scene, "audio", "");
        if (source.len != 0) return s.absoluteOrJoin(self.a, self.root, source);
        const text = s.getStr(scene, "narration", "");
        if (text.len == 0 or s.eq(s.env("EIDOLON_SKIP_TTS", ""), "1")) return "";
        const mp3 = try self.indexed("voice", index, "mp3");
        const rate = try s.fmt(self.a, "--rate={s}", .{s.getStr(scene, "voice_rate", "-5%")});
        const command = try s.shellCommand(self.a, self.tts, &.{
            "--voice", s.getStr(scene, "voice", "en-US-AndrewNeural"),
            rate, "--text", text, "--write-media", mp3,
        });
        const fallback = s.env("EIDOLON_ESPEAK", "espeak-ng");
        // Edge is online. A failed request must not prevent offline exports.
        const c = struct {
            extern "c" fn system([*:0]const u8) c_int;
        };
        if (c.system(try self.a.dupeZ(u8, command)) == 0) return mp3;
        const wav = try self.indexed("voice", index, "wav");
        try s.run(self.a, fallback, &.{ "-v", "en-us", "-s", "155", "-w", wav, text });
        return wav;
    }
    fn createSvgFrames(self: Renderer, scenes: []const Scene, total: usize) !void {
        std.log.info("rendering {d} SVG frames in Zig", .{total});
        var index: usize = 0;
        for (scenes) |scene| {
            for (0..scene.frames) |local_frame| {
                const content = try svg.document(self.a, scene.data, local_frame, scene.frames,
                    self.width, self.height);
                const svg_file = try self.indexed("frame", index, "svg");
                const png_file = try self.indexed("frame", index, "png");
                try s.writeFile(self.a, svg_file, content);
                try s.run(self.a, self.rsvg, &.{ "--output", png_file, svg_file });
                index += 1;
            }
        }
    }
    fn renderMedia(self: Renderer, scenes: []const Scene, total: usize) !bool {
        var any_media = false;
        for (scenes) |scene| {
            if (s.field(scene.data, "media") != .null) any_media = true;
        }
        if (!any_media) return false;
        const color = try s.fmt(self.a, "color=c=black:s={d}x{d}:r={d}", .{
            self.width, self.height, self.fps,
        });
        const target = try self.file("media-%06d.png");
        try s.run(self.a, self.ffmpeg, &.{ "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", color, "-frames:v",
            try s.fmt(self.a, "{d}", .{total}), "-start_number", "0", target,
        });
        for (scenes) |scene| {
            const media = s.field(scene.data, "media");
            if (media == .null) continue;
            const source = try s.absoluteOrJoin(self.a, self.root, s.getStr(media, "src", ""));
            if (source.len == 0) return error.MediaSourceMissing;
            const is_image = s.eq(s.getStr(media, "kind", "image"), "image");
            const fit = s.getStr(media, "fit", "cover");
            const base = try s.fmt(self.a,
                "scale={d}:{d}:force_original_aspect_ratio={s}",
                .{ self.width, self.height, if (s.eq(fit, "contain")) "decrease" else "increase" });
            const geometry = if (s.eq(fit, "contain"))
                try s.fmt(self.a, "{s},pad={d}:{d}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1",
                    .{ base, self.width, self.height })
            else
                try s.fmt(self.a, "{s},crop={d}:{d},setsar=1", .{ base, self.width, self.height });
            const motion = s.getStr(media, "motion", "none");
            const vf = if (is_image and !s.eq(motion, "none")) blk: {
                const n = @max(1, scene.frames - 1);
                const zoom = if (s.eq(motion, "zoom-in")) "min(pzoom+0.002,1.18)"
                             else if (s.eq(motion, "zoom-out")) "max(1.18-on*0.002,1)"
                             else "1.12";
                const xpos = if (s.eq(motion, "pan-left"))
                    try s.fmt(self.a, "(iw-iw/zoom)*(1-on/{d})", .{n})
                else if (s.eq(motion, "pan-right"))
                    try s.fmt(self.a, "(iw-iw/zoom)*on/{d}", .{n})
                else "iw/2-(iw/zoom/2)";
                break :blk try s.fmt(self.a,
                    "{s},zoompan=z='{s}':x='{s}':y='ih/2-(ih/zoom/2)':d=1:s={d}x{d}:fps={d}",
                    .{ geometry, zoom, xpos, self.width, self.height, self.fps });
            } else if (!is_image)
                try s.fmt(self.a, "fps={d},{s}", .{ self.fps, geometry })
            else geometry;

            const frames = try s.fmt(self.a, "{d}", .{scene.frames});
            const start = try s.fmt(self.a, "{d}", .{scene.start});
            if (is_image) {
                try s.run(self.a, self.ffmpeg, &.{ "-y", "-hide_banner", "-loglevel", "error",
                    "-loop", "1", "-framerate", try self.fpsString(),
                    "-i", source, "-vf", vf, "-frames:v", frames, "-start_number", start, target });
            } else {
                try s.run(self.a, self.ffmpeg, &.{ "-y", "-hide_banner", "-loglevel", "error",
                    "-stream_loop", "-1", "-i", source, "-vf", vf,
                    "-frames:v", frames, "-start_number", start, target });
            }
        }
        return true;
    }
    fn silentVideo(self: Renderer, with_media: bool) ![]const u8 {
        const output = try self.file("silent.mp4");
        const frames = try self.file("frame-%06d.png");
        const fps_str = try self.fpsString();
        if (!with_media) {
            try s.run(self.a, self.ffmpeg, &.{ "-y", "-hide_banner", "-loglevel", "error",
                "-framerate", fps_str, "-i", frames, "-c:v", "libx264",
                "-pix_fmt", "yuv420p", "-crf", "17",
                "-movflags", "+faststart", output });
        } else {
            const media = try self.file("media-%06d.png");
            try s.run(self.a, self.ffmpeg, &.{ "-y", "-hide_banner", "-loglevel", "error",
                "-framerate", fps_str, "-i", media, "-framerate", fps_str, "-i", frames,
                "-filter_complex", "[0:v][1:v]overlay=shortest=1:format=auto,format=yuv420p[v]",
                "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-crf", "17", "-movflags", "+faststart", output });
        }
        return output;
    }
    fn mixAudio(self: Renderer, scenes: []const Scene, silent: []const u8, output: []const u8,
                project: V, total: usize) !void {
        var inputs: std.ArrayList([]const u8) = .empty;
        const append = struct {
            fn arg(list: *std.ArrayList([]const u8), a: A, v: []const u8) !void {
                try list.append(a, v);
            }
        }.arg;
        try append(&inputs, self.a, "-y");
        try append(&inputs, self.a, "-hide_banner");
        try append(&inputs, self.a, "-loglevel");
        try append(&inputs, self.a, "error");
        try append(&inputs, self.a, "-i");
        try append(&inputs, self.a, silent);
        try append(&inputs, self.a, "-f");
        try append(&inputs, self.a, "lavfi");
        try append(&inputs, self.a, "-t");
        try append(&inputs, self.a, try s.fmt(self.a, "{d:.3}", .{
            @as(f64, @floatFromInt(self.totalMillis(total))) / 1000 }));
        try append(&inputs, self.a, "-i");
        try append(&inputs, self.a, "anullsrc=r=48000:cl=stereo");
        var filters: std.ArrayList(u8) = .empty;
        var refs: std.ArrayList(u8) = .empty;
        try refs.appendSlice(self.a, "[1:a]");
        var count: usize = 1;
        var index: usize = 2;
        for (scenes) |scene| {
            if (scene.audio.len == 0) continue;
            try append(&inputs, self.a, "-i");
            try append(&inputs, self.a, scene.audio);
            try s.appendFmt(&filters, self.a,
                "[{d}:a]aresample=48000,adelay={d}:all=1[a{d}];",
                .{ index, self.totalMillis(scene.start), index });
            try s.appendFmt(&refs, self.a, "[a{d}]", .{index});
            index += 1;
            count += 1;
        }
        const music = s.getStr(project, "music", "");
        if (music.len != 0) {
            try append(&inputs, self.a, "-stream_loop");
            try append(&inputs, self.a, "-1");
            try append(&inputs, self.a, "-i");
            try append(&inputs, self.a, try s.absoluteOrJoin(self.a, self.root, music));
            const vol = @max(0, @min(100, s.getInt(project, "music_volume", 15)));
            try s.appendFmt(&filters, self.a, "[{d}:a]volume={d:.2}[music];",
                .{ index, @as(f64, @floatFromInt(vol)) / 100 });
            try refs.appendSlice(self.a, "[music]");
            count += 1;
        }
        if (count == 1) {
            try s.run(self.a, self.ffmpeg, &.{ "-y", "-hide_banner", "-loglevel", "error",
                "-i", silent, "-c", "copy", output });
            return;
        }
        try s.appendFmt(&filters, self.a, "{s}amix=inputs={d}:normalize=0:duration=longest[a]",
            .{ refs.items, count });
        try append(&inputs, self.a, "-filter_complex");
        try append(&inputs, self.a, filters.items);
        try append(&inputs, self.a, "-map");
        try append(&inputs, self.a, "0:v");
        try append(&inputs, self.a, "-map");
        try append(&inputs, self.a, "[a]");
        try append(&inputs, self.a, "-c:v");
        try append(&inputs, self.a, "copy");
        try append(&inputs, self.a, "-c:a");
        try append(&inputs, self.a, "aac");
        try append(&inputs, self.a, "-b:a");
        try append(&inputs, self.a, "192k");
        try append(&inputs, self.a, "-t");
        try append(&inputs, self.a, try s.fmt(self.a, "{d:.3}", .{
            @as(f64, @floatFromInt(self.totalMillis(total))) / 1000 }));
        try append(&inputs, self.a, output);
        try s.run(self.a, self.ffmpeg, inputs.items);
    }
    fn srtTime(self: Renderer, frames: usize) ![]const u8 {
        const ms = self.totalMillis(frames);
        const hours = @divTrunc(ms, 3600000);
        const minutes = @mod(@divTrunc(ms, 60000), 60);
        const seconds = @mod(@divTrunc(ms, 1000), 60);
        const millis = @mod(ms, 1000);
        return s.fmt(self.a, "{d:0>2}:{d:0>2}:{d:0>2},{d:0>3}",
            .{ hours, minutes, seconds, millis });
    }
    fn subtitles(self: Renderer, scenes: []const Scene, output: []const u8) !void {
        var captions: std.ArrayList(u8) = .empty;
        for (scenes, 0..) |scene, i| {
            const text = s.getStr(scene.data, "caption", s.getStr(scene.data, "narration", ""));
            if (text.len == 0) continue;
            try s.appendFmt(&captions, self.a, "{d}\n{s} --> {s}\n{s}\n\n",
                .{ i + 1, try self.srtTime(scene.start),
                    try self.srtTime(scene.start + scene.frames), text });
        }
        const path = if (std.mem.endsWith(u8, output, ".mp4"))
            try s.fmt(self.a, "{s}.srt", .{output[0 .. output.len - 4]})
        else try s.fmt(self.a, "{s}.srt", .{output});
        try s.writeFile(self.a, path, captions.items);
    }
};

pub fn main(init: std.process.Init) !void {
    const a = init.arena.allocator();
    const args = try init.minimal.args.toSlice(a);
    if (args.len < 3) {
        try std.Io.File.stderr().writeStreamingAll(init.io,
            "usage: eidolon-director prepared-project.json output.mp4\n");
        return error.InvalidArguments;
    }
    const project_path = args[1];
    const output = args[2];
    const text = try s.readFile(a, project_path);
    const parsed = try std.json.parseFromSlice(V, a, text, .{
        .allocate = .alloc_always,
    });
    const project = parsed.value;
    const fps_num = s.getInt(project, "fps", 30);
    const width_num = s.getInt(project, "width", 1280);
    const height_num = s.getInt(project, "height", 720);
    if (fps_num < 1 or fps_num > 120 or width_num < 16 or width_num > 8192 or
        height_num < 16 or height_num > 8192 or @mod(width_num, 2) != 0 or @mod(height_num, 2) != 0)
        return error.InvalidVideoDimensions;
    const work = s.env("EIDOLON_WORK", ".");
    const renderer = Renderer{
        .a = a, .work = work, .root = s.directoryOf(project_path),
        .ffmpeg = s.env("EIDOLON_FFMPEG", "ffmpeg"),
        .ffprobe = s.env("EIDOLON_FFPROBE", "ffprobe"),
        .rsvg = s.env("EIDOLON_RSVG", "rsvg-convert"),
        .tts = s.env("EIDOLON_EDGE_TTS", "edge-tts"),
        .espeak = s.env("EIDOLON_ESPEAK", "espeak-ng"),
        .fps = @intCast(fps_num), .width = @intCast(width_num), .height = @intCast(height_num),
    };
    _ = renderer.espeak;
    var scenes: std.ArrayList(Scene) = .empty;
    var cursor: usize = 0;
    const source_scenes = s.array(s.field(project, "scenes"));
    if (source_scenes.len == 0 or source_scenes.len > 200) return error.InvalidScenes;
    for (source_scenes, 0..) |scene, i| {
        const sound = try renderer.synthesize(scene, i);
        const duration = if (s.field(scene, "frames") != .null)
            s.getInt(scene, "frames", 1)
        else
            @as(i64, @intFromFloat(@ceil(s.number(s.field(scene, "duration"), 4) *
                  @as(f64, @floatFromInt(renderer.fps)))));
        if (duration <= 0 or duration > 18000) return error.InvalidSceneDuration;
        var frames: usize = @intCast(duration);
        if (sound.len != 0) {
            const sound_ms = try renderer.videoLen(sound);
            const needed = @divTrunc((sound_ms + 350) * renderer.fps + 999, 1000);
            frames = @max(frames, needed);
        }
        if (cursor + frames > 18000) return error.TooManyFrames;
        try scenes.append(a, .{ .data = scene, .start = cursor, .frames = frames, .audio = sound });
        cursor += frames;
    }
    try renderer.createSvgFrames(scenes.items, cursor);
    const has_media = try renderer.renderMedia(scenes.items, cursor);
    const silent = try renderer.silentVideo(has_media);
    try renderer.mixAudio(scenes.items, silent, output, project, cursor);
    try renderer.subtitles(scenes.items, output);
    std.log.info("eidolon: created {s} (Zig engine, {d} frames)", .{ output, cursor });
}

test "source example renders with Zig JSON value" {
    const a = std.testing.allocator;
    const data = "{\"fps\":12,\"scenes\":[{\"frames\":4,\"elements\":[]}]}";
    const parsed = try std.json.parseFromSlice(V, a, data, .{});
    defer parsed.deinit();
    try std.testing.expectEqual(@as(i64, 12), s.getInt(parsed.value, "fps", 30));
}
