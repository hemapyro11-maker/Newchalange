"""
media_plugin.py — تحليل ومعالجة الفيديو/الصوت عبر FFmpeg (أداة خارجية
مجانية ومفتوحة المصدر، Zero-Cost حسب معايير المشروع). يتحمّل تلقائياً
لأنه موجود جوه مجلد plugins/ ومعرّف فيه register(engine).

الأوامر: probe, convert, trim, merge_av, concat
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile


def _cmd_probe(ctx) -> str:
    if not ctx.args:
        return "usage: probe <file>"
    if not shutil.which("ffprobe"):
        return "❌ ffprobe غير موجود — ثبّت FFmpeg وضيفه للـ PATH (ffmpeg.org/download.html)"
    path = ctx.args[0]
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", path],
            capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        return "⏱ انتهت المهلة أثناء تحليل الملف"

    if result.returncode != 0:
        return f"❌ الملف مش قابل للقراءة أو مساره غلط:\n{result.stderr.strip()[:300]}"
    try:
        data = json.loads(result.stdout)
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
        return "❌ ffmpeg غير موجود — ثبّته من ffmpeg.org"
    src, dst = ctx.args[0], ctx.args[1]
    result = subprocess.run(["ffmpeg", "-y", "-i", src, dst], capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        return f"❌ فشل التحويل:\n{result.stderr.strip()[-500:]}"
    return f"✅ تم التحويل إلى {dst}"


def _cmd_trim(ctx) -> str:
    if len(ctx.args) < 4:
        return "usage: trim <input> <start_sec> <duration_sec> <output>"
    if not shutil.which("ffmpeg"):
        return "❌ ffmpeg غير موجود"
    src, start, duration, dst = ctx.args[0], ctx.args[1], ctx.args[2], ctx.args[3]
    result = subprocess.run(
        ["ffmpeg", "-y", "-ss", start, "-i", src, "-t", duration, "-c", "copy", dst],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        return f"❌ فشل القص:\n{result.stderr.strip()[-500:]}"
    return f"✅ تم القص إلى {dst}"


def _cmd_merge_av(ctx) -> str:
    if len(ctx.args) < 3:
        return "usage: merge_av <video> <audio> <output>"
    if not shutil.which("ffmpeg"):
        return "❌ ffmpeg غير موجود"
    video, audio, dst = ctx.args[0], ctx.args[1], ctx.args[2]
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", video, "-i", audio,
         "-c:v", "copy", "-c:a", "aac", "-shortest", dst],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        return f"❌ فشل الدمج:\n{result.stderr.strip()[-500:]}"
    return f"✅ تم دمج الصوت مع الفيديو في {dst}"


def _cmd_concat(ctx) -> str:
    if len(ctx.args) < 3:
        return "usage: concat <output> <file1> <file2> [file3 ...]"
    if not shutil.which("ffmpeg"):
        return "❌ ffmpeg غير موجود"
    dst, *files = ctx.args
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        for path in files:
            f.write(f"file '{os.path.abspath(path)}'\n")
        list_path = f.name
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", dst],
            capture_output=True, text=True, timeout=300,
        )
    finally:
        os.unlink(list_path)
    if result.returncode != 0:
        return f"❌ فشل الدمج:\n{result.stderr.strip()[-500:]}"
    return f"✅ تم دمج {len(files)} ملفات في {dst}"


def register(engine):
    engine.registry.register("probe", _cmd_probe, "تحليل ملف فيديو/صوت (ffprobe) واكتشاف المشاكل")
    engine.registry.register("convert", _cmd_convert, "تحويل صيغة ملف ميديا (ffmpeg)")
    engine.registry.register("trim", _cmd_trim, "قص جزء من فيديو أو صوت")
    engine.registry.register("merge_av", _cmd_merge_av, "دمج فيديو مع مسار صوت خارجي")
    engine.registry.register("concat", _cmd_concat, "دمج/لصق عدة ملفات فيديو أو صوت في ملف واحد")
