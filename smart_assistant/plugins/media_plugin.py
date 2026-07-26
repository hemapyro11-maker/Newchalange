"""
media_plugin.py — تحليل ومعالجة الفيديو/الصوت عبر FFmpeg (أداة خارجية
مجانية ومفتوحة المصدر، Zero-Cost حسب معايير المشروع). يتحمّل تلقائياً
لأنه موجود جوه مجلد plugins/ ومعرّف فيه register(engine).

الأوامر: probe, convert, trim, merge_av, concat, extract_audio,
thumbnail, overlay_text
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import tempfile


def _missing_files(*paths: str) -> list[str]:
    return [p for p in paths if not pathlib.Path(p).is_file()]


def _run_ffmpeg(args: list[str], timeout: int) -> tuple[bool, str]:
    """بيشغّل ffmpeg/ffprobe ويرجع (نجح, رسالة الخطأ لو فشل). بيمسك كل
    حالات الفشل الممكنة (timeout, binary اتشال أثناء التشغيل, ...) بدل
    ما يسيب استثناء خام يوصل للمستخدم."""
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"⏱ timed out after ({timeout}s) — الملف كبير أوي أو ffmpeg علّق"
    except OSError as e:
        return False, f"❌ تعذر تشغيل {args[0]}: {e}"
    if result.returncode != 0:
        return False, result.stderr.strip()[-500:]
    return True, result.stdout


def _cmd_probe(ctx) -> str:
    if not ctx.args:
        return "usage: probe <file>"
    if not shutil.which("ffprobe"):
        return "❌ ffprobe غير موجود — ثبّت FFmpeg وضيفه للـ PATH (ffmpeg.org/download.html)"
    path = ctx.args[0]
    if not pathlib.Path(path).is_file():
        return f"❌ file not found: {path}"
    ok, output = _run_ffmpeg(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", path],
        timeout=30,
    )
    if not ok:
        return f"❌ الملف مش قابل للقراءة:\n{output}"
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return "❌ تعذر تحليل مخرجات ffprobe"

    fmt = data.get("format", {})
    streams = data.get("streams", [])
    lines = [
        f"📄 {path}",
        f"⏱  duration: {fmt.get('duration', '?')}s   size: {fmt.get('size', '?')} bytes",
    ]
    issues = []
    if not streams:
        issues.append("مفيش أي stream — الملف ممكن يكون تالف")
    for s in streams:
        kind = s.get("codec_type")
        codec = s.get("codec_name")
        if kind == "video":
            lines.append(f"🎬 video: {codec}  {s.get('width')}x{s.get('height')}  fps={s.get('r_frame_rate')}")
        elif kind == "audio":
            lines.append(f"🔊 audio: {codec}  {s.get('sample_rate')}Hz  ch={s.get('channels')}")
            if s.get("channels") in (0, "0"):
                issues.append("مسار الصوت بلا قنوات (channels=0)")
    try:
        if float(fmt.get("duration", 0)) <= 0:
            issues.append("مدة الملف صفر — الملف على الأغلب تالف")
    except (TypeError, ValueError):
        pass

    lines.append("⚠  مشاكل محتملة: " + " | ".join(issues) if issues else "✅ الملف سليم وقابل للقراءة")
    return "\n".join(lines)


def _cmd_convert(ctx) -> str:
    if len(ctx.args) < 2:
        return "usage: convert <input> <output>"
    if not shutil.which("ffmpeg"):
        return "❌ ffmpeg not found — ثبّته من ffmpeg.org"
    src, dst = ctx.args[0], ctx.args[1]
    missing = _missing_files(src)
    if missing:
        return f"❌ file not found: {missing[0]}"
    ok, err = _run_ffmpeg(["ffmpeg", "-y", "-i", src, dst], timeout=300)
    if not ok:
        return f"❌ فشل التحويل:\n{err}"
    return f"✅ تم التحويل إلى {dst}"


def _cmd_trim(ctx) -> str:
    if len(ctx.args) < 4:
        return "usage: trim <input> <start_sec> <duration_sec> <output>"
    if not shutil.which("ffmpeg"):
        return "❌ ffmpeg not found"
    src, start, duration, dst = ctx.args[0], ctx.args[1], ctx.args[2], ctx.args[3]
    missing = _missing_files(src)
    if missing:
        return f"❌ file not found: {missing[0]}"
    ok, err = _run_ffmpeg(
        ["ffmpeg", "-y", "-ss", start, "-i", src, "-t", duration, "-c", "copy", dst], timeout=120,
    )
    if not ok:
        return f"❌ فشل القص:\n{err}"
    return f"✅ تم القص إلى {dst}"


def _cmd_merge_av(ctx) -> str:
    if len(ctx.args) < 3:
        return "usage: merge_av <video> <audio> <output>"
    if not shutil.which("ffmpeg"):
        return "❌ ffmpeg not found"
    video, audio, dst = ctx.args[0], ctx.args[1], ctx.args[2]
    missing = _missing_files(video, audio)
    if missing:
        return f"❌ file not found: {missing[0]}"
    ok, err = _run_ffmpeg(
        ["ffmpeg", "-y", "-i", video, "-i", audio, "-c:v", "copy", "-c:a", "aac", "-shortest", dst],
        timeout=300,
    )
    if not ok:
        return f"❌ فشل الدمج:\n{err}"
    return f"✅ تم دمج الصوت مع الفيديو في {dst}"


def _cmd_concat(ctx) -> str:
    if len(ctx.args) < 3:
        return "usage: concat <output> <file1> <file2> [file3 ...]"
    if not shutil.which("ffmpeg"):
        return "❌ ffmpeg not found"
    dst, *files = ctx.args
    missing = _missing_files(*files)
    if missing:
        return f"❌ file not found: {missing[0]}"
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        for path in files:
            # ffmpeg concat demuxer syntax: quote paths with ' and escape
            # any literal ' inside them as '\'' — بدون كده أسماء ملفات
            # فيها quote بتكسر الأمر.
            escaped = os.path.abspath(path).replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")
        list_path = f.name
    try:
        ok, err = _run_ffmpeg(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", dst],
            timeout=300,
        )
    finally:
        os.unlink(list_path)
    if not ok:
        return f"❌ فشل الدمج:\n{err}"
    return f"✅ تم دمج {len(files)} ملفات في {dst}"


def _cmd_extract_audio(ctx) -> str:
    if len(ctx.args) < 2:
        return "usage: extract_audio <video> <output.mp3>"
    if not shutil.which("ffmpeg"):
        return "❌ ffmpeg not found"
    src, dst = ctx.args[0], ctx.args[1]
    missing = _missing_files(src)
    if missing:
        return f"❌ file not found: {missing[0]}"
    ok, err = _run_ffmpeg(
        ["ffmpeg", "-y", "-i", src, "-vn", "-acodec", "libmp3lame", dst], timeout=180,
    )
    if not ok:
        return f"❌ فشل الاستخراج:\n{err}"
    return f"✅ اتحفظ الصوت في {dst}"


def _cmd_thumbnail(ctx) -> str:
    if len(ctx.args) < 3:
        return "usage: thumbnail <video> <timestamp_sec> <output.jpg>"
    if not shutil.which("ffmpeg"):
        return "❌ ffmpeg not found"
    src, ts, dst = ctx.args[0], ctx.args[1], ctx.args[2]
    missing = _missing_files(src)
    if missing:
        return f"❌ file not found: {missing[0]}"
    ok, err = _run_ffmpeg(["ffmpeg", "-y", "-ss", ts, "-i", src, "-frames:v", "1", dst], timeout=60)
    if not ok:
        return f"❌ failed: {err}"
    return f"✅ اتحفظت الصورة في {dst}"


def _cmd_overlay_text(ctx) -> str:
    if len(ctx.args) < 3:
        return "usage: overlay_text <video> <text> <output>"
    if not shutil.which("ffmpeg"):
        return "❌ ffmpeg not found"
    src, text, dst = ctx.args[0], ctx.args[1], ctx.args[2]
    missing = _missing_files(src)
    if missing:
        return f"❌ file not found: {missing[0]}"
    escaped = text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    vf = (
        f"drawtext=text='{escaped}':fontcolor=white:fontsize=32:"
        "x=(w-text_w)/2:y=h-text_h-20:box=1:boxcolor=black@0.5"
    )
    ok, err = _run_ffmpeg(["ffmpeg", "-y", "-i", src, "-vf", vf, "-codec:a", "copy", dst], timeout=300)
    if not ok:
        return f"❌ فشل إضافة النص:\n{err}"
    return f"✅ اتحفظ الفيديو مع النص في {dst}"


def register(engine):
    engine.registry.register("probe", _cmd_probe, "probe <file> — inspect a video/audio file (ffprobe) and flag problems")
    engine.registry.register("convert", _cmd_convert, "convert <in> <out> — convert a media file to another format (ffmpeg)")
    engine.registry.register("trim", _cmd_trim, "trim <in> <start> <duration> <out> — cut a section out of video or audio")
    engine.registry.register("merge_av", _cmd_merge_av, "merge_av <video> <audio> <out> — attach an external audio track to a video")
    engine.registry.register("concat", _cmd_concat, "concat <out> <files...> — join several video or audio files into one")
    engine.registry.register("extract_audio", _cmd_extract_audio, "extract_audio <video> <out.mp3> — pull the audio out of a video")
    engine.registry.register("thumbnail", _cmd_thumbnail, "thumbnail <video> <sec> <out.jpg> — grab a still frame from a video")
    engine.registry.register("overlay_text", _cmd_overlay_text, "overlay_text <video> <text> <out> — burn text or a watermark onto a video")
