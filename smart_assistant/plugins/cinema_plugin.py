"""
cinema_plugin.py — أدوات مونتاج وتصحيح ألوان بمستوى احترافي، مبنية على
تقنيات حقيقية بيستخدمها مونتيرة ومصححو ألوان فعلياً (transitions حركية،
color grading، stabilization، loudness mastering زي معايير البث)، كل ده
عبر فلاتر FFmpeg القياسية (مجانية ومفتوحة المصدر بالكامل).

ملحوظة صادقة: الأدوات دي بتديك نفس التقنيات اللي أدوات المونتاج
الاحترافية (Premiere/DaVinci Resolve/Avid) بتستخدمها تحت الغطاء — لكن
"جودة هوليوود" في النهاية شغل فني بيعمله مونتير/مصحح ألوان بشري بيقرر
التوقيت والذوق والقصة. السوفت وير بيوفر الأدوات مش الفن.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import tempfile


def _run_ffmpeg(args: list[str], timeout: int) -> tuple[bool, str]:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"⏱ انتهت المهلة ({timeout}s)"
    except OSError as e:
        return False, f"❌ تعذر تشغيل {args[0]}: {e}"
    if result.returncode != 0:
        return False, result.stderr.strip()[-600:]
    return True, result.stdout


def _missing_files(*paths: str) -> list[str]:
    return [p for p in paths if not pathlib.Path(p).is_file()]


def _probe_dimensions(path: str) -> tuple[int, int] | None:
    if not shutil.which("ffprobe"):
        return None
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", path],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    for s in data.get("streams", []):
        if s.get("codec_type") == "video":
            w, h = s.get("width"), s.get("height")
            if w and h:
                return int(w), int(h)
    return None


def _probe_duration(path: str) -> float | None:
    if not shutil.which("ffprobe"):
        return None
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True, timeout=30,
    )
    try:
        return float(result.stdout.strip())
    except (ValueError, AttributeError):
        return None


def _atempo_chain(factor: float) -> str:
    """atempo بيقبل بس 0.5-2.0 لكل مرحلة، فلو الفاكتور خارج النطاق ده
    بنسلسل أكتر من مرحلة (نفس اللي أدوات المونتاج الاحترافية بتعمله
    داخلياً لـ speed ramping خارج النطاق العادي)."""
    stages = []
    remaining = factor
    while remaining > 2.0:
        stages.append(2.0)
        remaining /= 2.0
    while remaining < 0.5:
        stages.append(0.5)
        remaining /= 0.5
    stages.append(remaining)
    return ",".join(f"atempo={s:.6f}" for s in stages)


# ═══════════════════════════════════════════════════════════════════
# Color grading
# ═══════════════════════════════════════════════════════════════════

_COLOR_PRESETS = {
    "cinematic": "curves=preset=medium_contrast,eq=saturation=1.15:contrast=1.05",
    "teal_orange": (
        "colorbalance=rs=-0.10:gs=0.05:bs=0.15:rm=0.10:gm=0.0:bm=-0.05:rh=0.15:gh=0.05:bh=-0.10,"
        "eq=saturation=1.2"
    ),
    "noir": "curves=preset=strong_contrast,hue=s=0",
    "vintage": "curves=preset=vintage",
    "warm": "colorbalance=rm=0.15:bm=-0.10",
    "cool": "colorbalance=bm=0.15:rm=-0.10",
    "bw": "hue=s=0",
}


def _cmd_color_grade(ctx) -> str:
    if len(ctx.args) < 2:
        presets = ", ".join(_COLOR_PRESETS)
        return f"usage: color_grade <input> <output> [preset=cinematic]\npresets: {presets}"
    if not shutil.which("ffmpeg"):
        return "❌ ffmpeg غير موجود"
    src, dst = ctx.args[0], ctx.args[1]
    preset = ctx.args[2] if len(ctx.args) > 2 else "cinematic"
    missing = _missing_files(src)
    if missing:
        return f"❌ الملف مش موجود: {missing[0]}"
    if preset not in _COLOR_PRESETS:
        return f"❌ preset غير معروف: {preset} (المتاح: {', '.join(_COLOR_PRESETS)})"
    ok, err = _run_ffmpeg(
        ["ffmpeg", "-y", "-i", src, "-vf", _COLOR_PRESETS[preset], "-c:a", "copy", dst], timeout=300,
    )
    if not ok:
        return f"❌ فشل التصحيح اللوني:\n{err}"
    return f"✅ اتعمل color grading ({preset}) في {dst}"


# ═══════════════════════════════════════════════════════════════════
# Transitions (crossfade)
# ═══════════════════════════════════════════════════════════════════

_TRANSITIONS = {
    "fade", "wipeleft", "wiperight", "wipeup", "wipedown", "slideleft", "slideright",
    "slideup", "slidedown", "circlecrop", "rectcrop", "dissolve", "radial", "pixelize",
    "smoothleft", "smoothright", "circleopen", "circleclose", "hblur", "zoomin",
}


def _cmd_transition(ctx) -> str:
    if len(ctx.args) < 3:
        return f"usage: transition <clip1> <clip2> <output> [style=fade] [duration=1]\nstyles: {', '.join(sorted(_TRANSITIONS))}"
    if not shutil.which("ffmpeg"):
        return "❌ ffmpeg غير موجود"
    clip1, clip2, dst = ctx.args[0], ctx.args[1], ctx.args[2]
    style = ctx.args[3] if len(ctx.args) > 3 else "fade"
    try:
        duration = float(ctx.args[4]) if len(ctx.args) > 4 else 1.0
    except ValueError:
        return "❌ duration لازم يكون رقم"
    missing = _missing_files(clip1, clip2)
    if missing:
        return f"❌ الملف مش موجود: {missing[0]}"
    if style not in _TRANSITIONS:
        return f"❌ style غير معروف: {style} (المتاح: {', '.join(sorted(_TRANSITIONS))})"

    clip1_duration = _probe_duration(clip1)
    if clip1_duration is None:
        return f"❌ تعذر معرفة مدة {clip1}"
    if duration >= clip1_duration:
        return f"❌ duration ({duration}s) لازم يكون أقل من مدة الكليب الأول ({clip1_duration:.2f}s)"
    offset = clip1_duration - duration

    filter_complex = (
        f"[0:v][1:v]xfade=transition={style}:duration={duration}:offset={offset}[v];"
        f"[0:a][1:a]acrossfade=d={duration}[a]"
    )
    ok, err = _run_ffmpeg(
        ["ffmpeg", "-y", "-i", clip1, "-i", clip2, "-filter_complex", filter_complex,
         "-map", "[v]", "-map", "[a]", dst],
        timeout=300,
    )
    if not ok:
        # لو مفيش صوت في أحد الكليبين، acrossfade هتفشل — نجرب فيديو بس
        filter_video_only = f"[0:v][1:v]xfade=transition={style}:duration={duration}:offset={offset}[v]"
        ok, err = _run_ffmpeg(
            ["ffmpeg", "-y", "-i", clip1, "-i", clip2, "-filter_complex", filter_video_only,
             "-map", "[v]", dst],
            timeout=300,
        )
        if not ok:
            return f"❌ فشل الانتقال:\n{err}"
        return f"✅ اتعمل انتقال ({style}) في {dst} (بدون صوت — أحد الكليبين مالوش مسار صوت)"
    return f"✅ اتعمل انتقال ({style}) في {dst}"


# ═══════════════════════════════════════════════════════════════════
# Letterbox (cinematic aspect ratio bars)
# ═══════════════════════════════════════════════════════════════════

def _cmd_letterbox(ctx) -> str:
    if len(ctx.args) < 2:
        return "usage: letterbox <input> <output> [ratio=2.39]"
    if not shutil.which("ffmpeg"):
        return "❌ ffmpeg غير موجود"
    src, dst = ctx.args[0], ctx.args[1]
    missing = _missing_files(src)
    if missing:
        return f"❌ الملف مش موجود: {missing[0]}"
    try:
        ratio = float(ctx.args[2]) if len(ctx.args) > 2 else 2.39
    except ValueError:
        return "❌ ratio لازم يكون رقم"
    if ratio <= 0:
        return "❌ ratio لازم يكون أكبر من صفر"

    dims = _probe_dimensions(src)
    if dims is None:
        return f"❌ تعذر معرفة أبعاد {src}"
    width, height = dims
    bar_height = max(0, round((height - width / ratio) / 2))
    if bar_height == 0:
        return f"⚠  الفيديو أعرض من {ratio}:1 بالفعل — مفيش شريط يتضاف"

    vf = f"drawbox=x=0:y=0:w=iw:h={bar_height}:color=black:t=fill,drawbox=x=0:y=ih-{bar_height}:w=iw:h={bar_height}:color=black:t=fill"
    ok, err = _run_ffmpeg(["ffmpeg", "-y", "-i", src, "-vf", vf, "-c:a", "copy", dst], timeout=300)
    if not ok:
        return f"❌ فشل: {err}"
    return f"✅ اتعمل letterbox ({ratio}:1) في {dst}"


# ═══════════════════════════════════════════════════════════════════
# Stabilization (two-pass vidstab)
# ═══════════════════════════════════════════════════════════════════

def _cmd_stabilize(ctx) -> str:
    if len(ctx.args) < 2:
        return "usage: stabilize <input> <output>"
    if not shutil.which("ffmpeg"):
        return "❌ ffmpeg غير موجود"
    src, dst = ctx.args[0], ctx.args[1]
    missing = _missing_files(src)
    if missing:
        return f"❌ الملف مش موجود: {missing[0]}"

    with tempfile.TemporaryDirectory() as tmp:
        transforms = str(pathlib.Path(tmp) / "transforms.trf")
        ok, err = _run_ffmpeg(
            ["ffmpeg", "-y", "-i", src, "-vf", f"vidstabdetect=shakiness=5:accuracy=15:result={transforms}",
             "-f", "null", "-"],
            timeout=300,
        )
        if not ok:
            return f"❌ فشلت مرحلة تحليل الاهتزاز (pass 1):\n{err}"
        ok, err = _run_ffmpeg(
            ["ffmpeg", "-y", "-i", src, "-vf", f"vidstabtransform=smoothing=30:input={transforms}",
             "-c:a", "copy", dst],
            timeout=300,
        )
    if not ok:
        return f"❌ فشلت مرحلة التثبيت (pass 2):\n{err}"
    return f"✅ اتعمل تثبيت الفيديو (stabilization) في {dst}"


# ═══════════════════════════════════════════════════════════════════
# Speed ramping
# ═══════════════════════════════════════════════════════════════════

def _cmd_speed_ramp(ctx) -> str:
    if len(ctx.args) < 3:
        return "usage: speed_ramp <input> <output> <factor>  (0.5=نص سرعة/بطيء، 2=ضعف السرعة)"
    if not shutil.which("ffmpeg"):
        return "❌ ffmpeg غير موجود"
    src, dst, factor_arg = ctx.args[0], ctx.args[1], ctx.args[2]
    missing = _missing_files(src)
    if missing:
        return f"❌ الملف مش موجود: {missing[0]}"
    try:
        factor = float(factor_arg)
    except ValueError:
        return "❌ factor لازم يكون رقم"
    if factor <= 0:
        return "❌ factor لازم يكون أكبر من صفر"

    vf = f"setpts={1 / factor:.6f}*PTS"
    af = _atempo_chain(factor)
    ok, err = _run_ffmpeg(["ffmpeg", "-y", "-i", src, "-vf", vf, "-af", af, dst], timeout=300)
    if not ok:
        # ملفات من غير صوت — نجرب فيديو بس
        ok, err = _run_ffmpeg(["ffmpeg", "-y", "-i", src, "-vf", vf, "-an", dst], timeout=300)
        if not ok:
            return f"❌ فشل: {err}"
        return f"✅ اتغيرت السرعة (×{factor}) في {dst} (بدون صوت)"
    return f"✅ اتغيرت السرعة (×{factor}) في {dst}"


# ═══════════════════════════════════════════════════════════════════
# Picture-in-picture
# ═══════════════════════════════════════════════════════════════════

_PIP_POSITIONS = {
    "bottom-right": "main_w-overlay_w-20:main_h-overlay_h-20",
    "bottom-left": "20:main_h-overlay_h-20",
    "top-right": "main_w-overlay_w-20:20",
    "top-left": "20:20",
    "center": "(main_w-overlay_w)/2:(main_h-overlay_h)/2",
}


def _cmd_pip(ctx) -> str:
    if len(ctx.args) < 3:
        return f"usage: pip <background> <overlay> <output> [position=bottom-right] [scale=0.3]\npositions: {', '.join(_PIP_POSITIONS)}"
    if not shutil.which("ffmpeg"):
        return "❌ ffmpeg غير موجود"
    bg, overlay, dst = ctx.args[0], ctx.args[1], ctx.args[2]
    position = ctx.args[3] if len(ctx.args) > 3 else "bottom-right"
    missing = _missing_files(bg, overlay)
    if missing:
        return f"❌ الملف مش موجود: {missing[0]}"
    try:
        scale = float(ctx.args[4]) if len(ctx.args) > 4 else 0.3
    except ValueError:
        return "❌ scale لازم يكون رقم"
    if not (0 < scale <= 1):
        return "❌ scale لازم يكون بين 0 و1"
    if position not in _PIP_POSITIONS:
        return f"❌ position غير معروف: {position} (المتاح: {', '.join(_PIP_POSITIONS)})"

    filter_complex = f"[1:v]scale=iw*{scale}:ih*{scale}[ov];[0:v][ov]overlay={_PIP_POSITIONS[position]}"
    ok, err = _run_ffmpeg(
        ["ffmpeg", "-y", "-i", bg, "-i", overlay, "-filter_complex", filter_complex,
         "-map", "0:a?", dst],
        timeout=300,
    )
    if not ok:
        return f"❌ فشل: {err}"
    return f"✅ اتعمل Picture-in-Picture ({position}) في {dst}"


# ═══════════════════════════════════════════════════════════════════
# Chroma key (green screen compositing)
# ═══════════════════════════════════════════════════════════════════

def _cmd_chroma_key(ctx) -> str:
    if len(ctx.args) < 3:
        return "usage: chroma_key <foreground> <background> <output> [color=0x00FF00] [similarity=0.3]"
    if not shutil.which("ffmpeg"):
        return "❌ ffmpeg غير موجود"
    fg, bg, dst = ctx.args[0], ctx.args[1], ctx.args[2]
    color = ctx.args[3] if len(ctx.args) > 3 else "0x00FF00"
    missing = _missing_files(fg, bg)
    if missing:
        return f"❌ الملف مش موجود: {missing[0]}"
    try:
        similarity = float(ctx.args[4]) if len(ctx.args) > 4 else 0.3
    except ValueError:
        return "❌ similarity لازم يكون رقم"
    if not (0 < similarity <= 1):
        return "❌ similarity لازم يكون بين 0 و1"

    filter_complex = f"[0:v]colorkey=color={color}:similarity={similarity}:blend=0.1[fg];[1:v][fg]overlay"
    ok, err = _run_ffmpeg(
        ["ffmpeg", "-y", "-i", fg, "-i", bg, "-filter_complex", filter_complex, "-map", "0:a?", dst],
        timeout=300,
    )
    if not ok:
        return f"❌ فشل: {err}"
    return f"✅ اتعمل دمج الخلفية (chroma key) في {dst}"


# ═══════════════════════════════════════════════════════════════════
# Audio mastering
# ═══════════════════════════════════════════════════════════════════

def _cmd_master_audio(ctx) -> str:
    if len(ctx.args) < 2:
        return "usage: master_audio <input> <output> [target_lufs=-16]  (-16 ستريمنج، -23 بث EBU R128)"
    if not shutil.which("ffmpeg"):
        return "❌ ffmpeg غير موجود"
    src, dst = ctx.args[0], ctx.args[1]
    missing = _missing_files(src)
    if missing:
        return f"❌ الملف مش موجود: {missing[0]}"
    try:
        target = float(ctx.args[2]) if len(ctx.args) > 2 else -16.0
    except ValueError:
        return "❌ target_lufs لازم يكون رقم"
    if not (-40 <= target <= 0):
        return "❌ target_lufs لازم يكون بين -40 و0"

    ok, err = _run_ffmpeg(
        ["ffmpeg", "-y", "-i", src, "-af", f"loudnorm=I={target}:TP=-1.5:LRA=11", dst], timeout=300,
    )
    if not ok:
        return f"❌ فشل: {err}"
    return f"✅ اتعمل audio mastering (target: {target} LUFS) في {dst}"


def _cmd_denoise_audio(ctx) -> str:
    if len(ctx.args) < 2:
        return "usage: denoise_audio <input> <output>"
    if not shutil.which("ffmpeg"):
        return "❌ ffmpeg غير موجود"
    src, dst = ctx.args[0], ctx.args[1]
    missing = _missing_files(src)
    if missing:
        return f"❌ الملف مش موجود: {missing[0]}"
    ok, err = _run_ffmpeg(["ffmpeg", "-y", "-i", src, "-af", "afftdn", dst], timeout=300)
    if not ok:
        return f"❌ فشل: {err}"
    return f"✅ اتشال الضوضاء من الصوت في {dst}"


# ═══════════════════════════════════════════════════════════════════
# Title cards / motion graphics
# ═══════════════════════════════════════════════════════════════════

def _cmd_title_card(ctx) -> str:
    if len(ctx.args) < 2:
        return "usage: title_card <text> <output> [duration=3] [size=1920x1080]"
    if not shutil.which("ffmpeg"):
        return "❌ ffmpeg غير موجود"
    text, dst = ctx.args[0], ctx.args[1]
    try:
        duration = float(ctx.args[2]) if len(ctx.args) > 2 else 3.0
    except ValueError:
        return "❌ duration لازم يكون رقم"
    if duration <= 1.0:
        return "❌ duration لازم يكون أكبر من 1 ثانية (نصف ثانية fade in + نصف fade out)"
    size = ctx.args[3] if len(ctx.args) > 3 else "1920x1080"

    escaped = text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    fade = 0.5
    alpha_expr = f"if(lt(t\\,{fade})\\,t/{fade}\\,if(gt(t\\,{duration - fade})\\,({duration}-t)/{fade}\\,1))"
    vf = (
        f"drawtext=text='{escaped}':fontsize=80:fontcolor=white:"
        f"x=(w-text_w)/2:y=(h-text_h)/2:alpha='{alpha_expr}'"
    )
    ok, err = _run_ffmpeg(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=black:s={size}:d={duration}",
         "-vf", vf, dst],
        timeout=120,
    )
    if not ok:
        return f"❌ فشل: {err}"
    return f"✅ اتعمل title card في {dst}"


def register(engine):
    engine.registry.register("color_grade", _cmd_color_grade, "color_grade <in> <out> [preset] — تصحيح ألوان سينمائي")
    engine.registry.register("transition", _cmd_transition, "transition <c1> <c2> <out> [style] [dur] — انتقال احترافي بين كليبين")
    engine.registry.register("letterbox", _cmd_letterbox, "letterbox <in> <out> [ratio=2.39] — شرايط سوداء سينمائية")
    engine.registry.register("stabilize", _cmd_stabilize, "stabilize <in> <out> — تثبيت اهتزاز الفيديو (two-pass)")
    engine.registry.register("speed_ramp", _cmd_speed_ramp, "speed_ramp <in> <out> <factor> — تغيير سرعة الفيديو/الصوت")
    engine.registry.register("pip", _cmd_pip, "pip <bg> <overlay> <out> [position] [scale] — صورة داخل صورة")
    engine.registry.register("chroma_key", _cmd_chroma_key, "chroma_key <fg> <bg> <out> [color] [similarity] — دمج خلفية خضراء")
    engine.registry.register("master_audio", _cmd_master_audio, "master_audio <in> <out> [lufs] — توحيد جهارة الصوت لمعيار بث")
    engine.registry.register("denoise_audio", _cmd_denoise_audio, "denoise_audio <in> <out> — إزالة ضوضاء الصوت")
    engine.registry.register("title_card", _cmd_title_card, "title_card <text> <out> [duration] [size] — لوحة عنوان متحركة")
