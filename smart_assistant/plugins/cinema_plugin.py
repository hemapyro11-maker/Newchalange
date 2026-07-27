"""
cinema_plugin.py — أدوات مونتاج وتصحيح ألوان بمستوى احترافي، مبنية على
تقنيات حقيقية بيستخدمها مونتيرة ومصححو ألوان فعلياً (transitions حركية،
color grading، stabilization، loudness mastering زي معايير البث)، كل ده
عبر فلاتر FFmpeg القياسية (مجانية ومفتوحة المصدر بالكامل).

ملحوظة صادقة: الأدوات دي بتديك نفس التقنيات اللي أدوات المونتاج
الاحترافية (Premiere/DaVinci Resolve/Avid) بتستخدمها تحت الغطاء — لكن
"جودة هوليوود" في النهاية شغل فني بيعمله مونتير/مصحح ألوان بشري بيقرر
التوقيت والذوق والقصة. السوفت وير بيوفر الأدوات مش الفن.

كمان فيه `auto_trim_silence` — أداة خارجية اختيارية (auto-editor،
https://github.com/WyattBlue/auto-editor، `pip install auto-editor`)
بتقص الصمت/اللقطات الميتة من فيديو أو بودكاست تلقائيًا، بنفس أسلوب
subprocess اللي ffmpeg نفسه بيتنادى بيه هنا — من غيرها الأمر بيرجع
رسالة واضحة تقول تتثبت إزاي.

و`detect_scenes` — كشف تلقائي لتغييرات المشاهد (scene cuts) عبر مكتبة
PySceneDetect (اختيارية، `pip install scenedetect[opencv]`) — مفيد
لتوليد فصول/timestamps تلقائيًا لفيديو طويل. مكتبة Python حقيقية
(import مباشر، مش subprocess) فبتتبع نفس نمط الـ import الاختياري
اللي faster-whisper بيستخدمه في voice_plugin.py.

و`upscale_image`/`upscale_video` — تكبير بالذكاء الاصطناعي عبر
Real-ESRGAN (ملف تنفيذي جاهز اسمه `realesrgan-ncnn-vulkan`، **مش**
حزمة pip — بيتحمّل من https://github.com/xinntao/Real-ESRGAN/releases
ويتحط في PATH). بيشتغل عبر Vulkan، يعني ممكن يشتغل حتى من غير NVIDIA/CUDA
(أي GPU بيدعم Vulkan)، لكن **بطيء جدًا من غير GPU حقيقي** (اتجرب فعليًا
على Vulkan software rendering: حوالي دقيقتين لصورة صغيرة واحدة).
`upscale_video` بيشتغل فريم فريم: استخراج فريمات بـ ffmpeg، تكبير كل
فريم، وتجميعهم تاني مع الصوت الأصلي — عملية تقيلة جدًا لفيديو طويل.
ملحوظة اتجربت فعليًا وليها أهمية: الأداة دي بترجع exit code صفر **حتى
لو فشلت فعليًا** (موديل غلط، صورة تعذر فك تشفيرها)، فـ upscale_image/
upscale_video بيتأكدوا من وجود ملف الخرج فعليًا بدل ما يثقوا في exit
code بس.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import tempfile

try:
    from scenedetect import ContentDetector
    from scenedetect import detect as _scenedetect_detect
    _HAS_SCENEDETECT = True
except ImportError:
    _HAS_SCENEDETECT = False


def _run_ffmpeg(args: list[str], timeout: int) -> tuple[bool, str]:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"⏱ timed out after ({timeout}s)"
    except OSError as e:
        return False, f"❌ could not run {args[0]}: {e}"
    if result.returncode != 0:
        return False, result.stderr.strip()[-600:]
    return True, result.stdout


def _missing_files(*paths: str) -> list[str]:
    return [p for p in paths if not pathlib.Path(p).is_file()]


def _run_ffprobe(args: list[str]) -> subprocess.CompletedProcess | None:
    """نداء ffprobe آمن — بيرجع None لو انتهت المهلة أو الأمر مش موجود
    فعليًا (TOCTOU بين shutil.which وقت التشغيل)، بدل ما نسيب الاستثناء
    يهرب من الدالة اللي بتنادينا ويكسر الـ traceback في وش المستخدم من
    غير رسالة ❌ زي أي فشل تاني في الملف ده."""
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=30)
    except (subprocess.TimeoutExpired, OSError):
        return None


def _probe_dimensions(path: str) -> tuple[int, int] | None:
    if not shutil.which("ffprobe"):
        return None
    result = _run_ffprobe(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", path])
    if result is None or result.returncode != 0:
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
    result = _run_ffprobe(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path])
    if result is None:
        return None
    try:
        return float(result.stdout.strip())
    except (ValueError, AttributeError):
        return None


def _probe_fps(path: str) -> float | None:
    if not shutil.which("ffprobe"):
        return None
    result = _run_ffprobe(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate",
         "-of", "default=nw=1:nk=1", path],
    )
    if result is None:
        return None
    try:
        num, den = result.stdout.strip().split("/")
        return float(num) / float(den)
    except (ValueError, ZeroDivisionError):
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
        return "❌ ffmpeg not found"
    src, dst = ctx.args[0], ctx.args[1]
    preset = ctx.args[2] if len(ctx.args) > 2 else "cinematic"
    missing = _missing_files(src)
    if missing:
        return f"❌ file not found: {missing[0]}"
    if preset not in _COLOR_PRESETS:
        return f"❌ unknown preset: {preset} (available: {', '.join(_COLOR_PRESETS)})"
    ok, err = _run_ffmpeg(
        ["ffmpeg", "-y", "-i", src, "-vf", _COLOR_PRESETS[preset], "-c:a", "copy", dst], timeout=300,
    )
    if not ok:
        return f"❌ colour grading failed:\n{err}"
    return f"✅ colour grading ({preset}) written to {dst}"


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
        return "❌ ffmpeg not found"
    clip1, clip2, dst = ctx.args[0], ctx.args[1], ctx.args[2]
    style = ctx.args[3] if len(ctx.args) > 3 else "fade"
    try:
        duration = float(ctx.args[4]) if len(ctx.args) > 4 else 1.0
    except ValueError:
        return "❌ duration must be a number"
    missing = _missing_files(clip1, clip2)
    if missing:
        return f"❌ file not found: {missing[0]}"
    if style not in _TRANSITIONS:
        return f"❌ unknown style: {style} (available: {', '.join(sorted(_TRANSITIONS))})"

    clip1_duration = _probe_duration(clip1)
    if clip1_duration is None:
        return f"❌ could not determine the duration of {clip1}"
    if duration >= clip1_duration:
        return f"❌ duration ({duration}s) must be shorter than the first clip ({clip1_duration:.2f}s)"
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
            return f"❌ transition failed:\n{err}"
        return f"✅ transition ({style}) written to {dst} (silent — one of the clips has no audio track)"
    return f"✅ transition ({style}) written to {dst}"


# ═══════════════════════════════════════════════════════════════════
# Letterbox (cinematic aspect ratio bars)
# ═══════════════════════════════════════════════════════════════════

def _cmd_letterbox(ctx) -> str:
    if len(ctx.args) < 2:
        return "usage: letterbox <input> <output> [ratio=2.39]"
    if not shutil.which("ffmpeg"):
        return "❌ ffmpeg not found"
    src, dst = ctx.args[0], ctx.args[1]
    missing = _missing_files(src)
    if missing:
        return f"❌ file not found: {missing[0]}"
    try:
        ratio = float(ctx.args[2]) if len(ctx.args) > 2 else 2.39
    except ValueError:
        return "❌ ratio must be a number"
    if ratio <= 0:
        return "❌ ratio must be greater than zero"

    dims = _probe_dimensions(src)
    if dims is None:
        return f"❌ could not determine the dimensions of {src}"
    width, height = dims
    bar_height = max(0, round((height - width / ratio) / 2))
    if bar_height == 0:
        return f"⚠  the video is already wider than {ratio}:1 — no bars to add"

    vf = f"drawbox=x=0:y=0:w=iw:h={bar_height}:color=black:t=fill,drawbox=x=0:y=ih-{bar_height}:w=iw:h={bar_height}:color=black:t=fill"
    ok, err = _run_ffmpeg(["ffmpeg", "-y", "-i", src, "-vf", vf, "-c:a", "copy", dst], timeout=300)
    if not ok:
        return f"❌ failed: {err}"
    return f"✅ letterboxed ({ratio}:1) to {dst}"


# ═══════════════════════════════════════════════════════════════════
# Stabilization (two-pass vidstab)
# ═══════════════════════════════════════════════════════════════════

def _cmd_stabilize(ctx) -> str:
    if len(ctx.args) < 2:
        return "usage: stabilize <input> <output>"
    if not shutil.which("ffmpeg"):
        return "❌ ffmpeg not found"
    src, dst = ctx.args[0], ctx.args[1]
    missing = _missing_files(src)
    if missing:
        return f"❌ file not found: {missing[0]}"

    with tempfile.TemporaryDirectory() as tmp:
        transforms = str(pathlib.Path(tmp) / "transforms.trf")
        ok, err = _run_ffmpeg(
            ["ffmpeg", "-y", "-i", src, "-vf", f"vidstabdetect=shakiness=5:accuracy=15:result={transforms}",
             "-f", "null", "-"],
            timeout=300,
        )
        if not ok:
            return f"❌ the shake-analysis pass failed (pass 1):\n{err}"
        ok, err = _run_ffmpeg(
            ["ffmpeg", "-y", "-i", src, "-vf", f"vidstabtransform=smoothing=30:input={transforms}",
             "-c:a", "copy", dst],
            timeout=300,
        )
    if not ok:
        return f"❌ the stabilisation pass failed (pass 2):\n{err}"
    return f"✅ video stabilised at {dst}"


# ═══════════════════════════════════════════════════════════════════
# Speed ramping
# ═══════════════════════════════════════════════════════════════════

def _cmd_speed_ramp(ctx) -> str:
    if len(ctx.args) < 3:
        return "usage: speed_ramp <input> <output> <factor>  (0.5 = half speed, 2 = double speed)"
    if not shutil.which("ffmpeg"):
        return "❌ ffmpeg not found"
    src, dst, factor_arg = ctx.args[0], ctx.args[1], ctx.args[2]
    missing = _missing_files(src)
    if missing:
        return f"❌ file not found: {missing[0]}"
    try:
        factor = float(factor_arg)
    except ValueError:
        return "❌ factor must be a number"
    if factor <= 0:
        return "❌ factor must be greater than zero"

    vf = f"setpts={1 / factor:.6f}*PTS"
    af = _atempo_chain(factor)
    ok, err = _run_ffmpeg(["ffmpeg", "-y", "-i", src, "-vf", vf, "-af", af, dst], timeout=300)
    if not ok:
        # ملفات من غير صوت — نجرب فيديو بس
        ok, err = _run_ffmpeg(["ffmpeg", "-y", "-i", src, "-vf", vf, "-an", dst], timeout=300)
        if not ok:
            return f"❌ failed: {err}"
        return f"✅ speed changed (×{factor}) at {dst} (silent)"
    return f"✅ speed changed (×{factor}) at {dst}"


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
        return "❌ ffmpeg not found"
    bg, overlay, dst = ctx.args[0], ctx.args[1], ctx.args[2]
    position = ctx.args[3] if len(ctx.args) > 3 else "bottom-right"
    missing = _missing_files(bg, overlay)
    if missing:
        return f"❌ file not found: {missing[0]}"
    try:
        scale = float(ctx.args[4]) if len(ctx.args) > 4 else 0.3
    except ValueError:
        return "❌ scale must be a number"
    if not (0 < scale <= 1):
        return "❌ scale must be between 0 and 1"
    if position not in _PIP_POSITIONS:
        return f"❌ unknown position: {position} (available: {', '.join(_PIP_POSITIONS)})"

    filter_complex = f"[1:v]scale=iw*{scale}:ih*{scale}[ov];[0:v][ov]overlay={_PIP_POSITIONS[position]}"
    ok, err = _run_ffmpeg(
        ["ffmpeg", "-y", "-i", bg, "-i", overlay, "-filter_complex", filter_complex,
         "-map", "0:a?", dst],
        timeout=300,
    )
    if not ok:
        return f"❌ failed: {err}"
    return f"✅ picture-in-picture ({position}) written to {dst}"


# ═══════════════════════════════════════════════════════════════════
# Chroma key (green screen compositing)
# ═══════════════════════════════════════════════════════════════════

def _cmd_chroma_key(ctx) -> str:
    if len(ctx.args) < 3:
        return "usage: chroma_key <foreground> <background> <output> [color=0x00FF00] [similarity=0.3]"
    if not shutil.which("ffmpeg"):
        return "❌ ffmpeg not found"
    fg, bg, dst = ctx.args[0], ctx.args[1], ctx.args[2]
    color = ctx.args[3] if len(ctx.args) > 3 else "0x00FF00"
    missing = _missing_files(fg, bg)
    if missing:
        return f"❌ file not found: {missing[0]}"
    try:
        similarity = float(ctx.args[4]) if len(ctx.args) > 4 else 0.3
    except ValueError:
        return "❌ similarity must be a number"
    if not (0 < similarity <= 1):
        return "❌ similarity must be between 0 and 1"

    filter_complex = f"[0:v]colorkey=color={color}:similarity={similarity}:blend=0.1[fg];[1:v][fg]overlay"
    ok, err = _run_ffmpeg(
        ["ffmpeg", "-y", "-i", fg, "-i", bg, "-filter_complex", filter_complex, "-map", "0:a?", dst],
        timeout=300,
    )
    if not ok:
        return f"❌ failed: {err}"
    return f"✅ chroma key composite written to {dst}"


# ═══════════════════════════════════════════════════════════════════
# Audio mastering
# ═══════════════════════════════════════════════════════════════════

def _cmd_master_audio(ctx) -> str:
    if len(ctx.args) < 2:
        return "usage: master_audio <input> <output> [target_lufs=-16]  (-16 streaming, -23 broadcast EBU R128)"
    if not shutil.which("ffmpeg"):
        return "❌ ffmpeg not found"
    src, dst = ctx.args[0], ctx.args[1]
    missing = _missing_files(src)
    if missing:
        return f"❌ file not found: {missing[0]}"
    try:
        target = float(ctx.args[2]) if len(ctx.args) > 2 else -16.0
    except ValueError:
        return "❌ target_lufs must be a number"
    if not (-40 <= target <= 0):
        return "❌ target_lufs must be between -40 and 0"

    ok, err = _run_ffmpeg(
        ["ffmpeg", "-y", "-i", src, "-af", f"loudnorm=I={target}:TP=-1.5:LRA=11", dst], timeout=300,
    )
    if not ok:
        return f"❌ failed: {err}"
    return f"✅ audio mastered (target: {target} LUFS) at {dst}"


def _cmd_denoise_audio(ctx) -> str:
    if len(ctx.args) < 2:
        return "usage: denoise_audio <input> <output>"
    if not shutil.which("ffmpeg"):
        return "❌ ffmpeg not found"
    src, dst = ctx.args[0], ctx.args[1]
    missing = _missing_files(src)
    if missing:
        return f"❌ file not found: {missing[0]}"
    ok, err = _run_ffmpeg(["ffmpeg", "-y", "-i", src, "-af", "afftdn", dst], timeout=300)
    if not ok:
        return f"❌ failed: {err}"
    return f"✅ noise removed from the audio at {dst}"


# ═══════════════════════════════════════════════════════════════════
# Title cards / motion graphics
# ═══════════════════════════════════════════════════════════════════

def _cmd_title_card(ctx) -> str:
    if len(ctx.args) < 2:
        return "usage: title_card <text> <output> [duration=3] [size=1920x1080]"
    if not shutil.which("ffmpeg"):
        return "❌ ffmpeg not found"
    text, dst = ctx.args[0], ctx.args[1]
    try:
        duration = float(ctx.args[2]) if len(ctx.args) > 2 else 3.0
    except ValueError:
        return "❌ duration must be a number"
    if duration <= 1.0:
        return "❌ duration must be over 1 second (half a second fade in, half fade out)"
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
        return f"❌ failed: {err}"
    return f"✅ title card written to {dst}"


# ═══════════════════════════════════════════════════════════════════
# قص تلقائي (auto-editor) — أداة مفتوحة المصدر منفصلة
# ═══════════════════════════════════════════════════════════════════

def _cmd_auto_trim_silence(ctx) -> str:
    if len(ctx.args) < 2:
        return "usage: auto_trim_silence <input> <output> [threshold=4%] — cuts silence and dead air automatically"
    if not shutil.which("auto-editor"):
        return "❌ auto-editor is not installed — pip install auto-editor (free and open source, https://github.com/WyattBlue/auto-editor)"
    src, dst = ctx.args[0], ctx.args[1]
    missing = _missing_files(src)
    if missing:
        return f"❌ file not found: {missing[0]}"
    threshold = ctx.args[2] if len(ctx.args) > 2 else "4%"
    ok, err = _run_ffmpeg(
        ["auto-editor", src, "--edit", f"audio:threshold={threshold}", "-o", dst, "--no-open", "--quiet"],
        timeout=900,  # ملفات المونتاج الطويلة بتاخد وقت أطول من فلاتر ffmpeg العادية
    )
    if not ok:
        return f"❌ failed: {err}"
    dst_path = pathlib.Path(dst)
    if not dst_path.is_file() or dst_path.stat().st_size == 0:
        return "❌ trimming failed — auto-editor exited without an error but produced no real output file"
    return f"✅ silence and dead air trimmed automatically (threshold={threshold}) at {dst}"


# ═══════════════════════════════════════════════════════════════════
# كشف مشاهد (PySceneDetect) — مكتبة مفتوحة المصدر منفصلة
# ═══════════════════════════════════════════════════════════════════

def _cmd_detect_scenes(ctx) -> str:
    if not ctx.args:
        return "usage: detect_scenes <video> [threshold=27.0] — finds scene cuts automatically"
    if not _HAS_SCENEDETECT:
        return "❌ PySceneDetect is not installed — pip install scenedetect[opencv] (free and open source)"
    src = ctx.args[0]
    missing = _missing_files(src)
    if missing:
        return f"❌ file not found: {missing[0]}"
    try:
        threshold = float(ctx.args[1]) if len(ctx.args) > 1 else 27.0
    except ValueError:
        return "❌ threshold must be a number (lower is more sensitive to subtle cuts)"

    try:
        scenes = _scenedetect_detect(src, ContentDetector(threshold=threshold))
    except Exception as e:
        return f"❌ scene detection failed: {e}"

    if not scenes:
        return f"ℹ️ no clear scene changes found (threshold={threshold}) — the video may be one continuous shot"

    lines = [f"🎬 {len(scenes)} scenes found (threshold={threshold}):"]
    for i, (start, end) in enumerate(scenes, start=1):
        lines.append(f"  {i}. {start.get_timecode()} → {end.get_timecode()}  ({end.seconds - start.seconds:.1f}s)")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# تكبير بالذكاء الاصطناعي (Real-ESRGAN) — ملف تنفيذي خارجي اختياري
# ═══════════════════════════════════════════════════════════════════

_REALESRGAN_MODELS = ("realesr-animevideov3", "realesrgan-x4plus", "realesrgan-x4plus-anime", "realesrnet-x4plus")
_REALESRGAN_MISSING_MSG = (
    "❌ realesrgan-ncnn-vulkan is not installed — it is a prebuilt binary, not a pip package. Download it from:\n"
    "   https://github.com/xinntao/Real-ESRGAN/releases\n"
    "   and put it on your PATH. It runs on Vulkan (very slow without a real GPU)."
)


def _validate_upscale_args(ctx) -> tuple[str, str, int, str, str | None]:
    """يرجع (src, dst, scale, model, رسالة خطأ أو None). لو فيه خطأ،
    القيم التانية بتبقى فاضية/افتراضية ومينفعش تتستخدم."""
    src, dst = ctx.args[0], ctx.args[1]
    missing = _missing_files(src)
    if missing:
        return "", "", 0, "", f"❌ file not found: {missing[0]}"
    try:
        scale = int(ctx.args[2]) if len(ctx.args) > 2 else 4
    except ValueError:
        return "", "", 0, "", "❌ scale must be a whole number (2, 3 or 4)"
    if scale not in (2, 3, 4):
        return "", "", 0, "", "❌ scale must be 2, 3 or 4"
    model = ctx.args[3] if len(ctx.args) > 3 else "realesrgan-x4plus"
    if model not in _REALESRGAN_MODELS:
        return "", "", 0, "", f"❌ model must be one of: {', '.join(_REALESRGAN_MODELS)}"
    return src, dst, scale, model, None


def _cmd_upscale_image(ctx) -> str:
    if len(ctx.args) < 2:
        return "usage: upscale_image <input> <output> [scale=4] [model=realesrgan-x4plus] — AI image upscaling (Real-ESRGAN)"
    if not shutil.which("realesrgan-ncnn-vulkan"):
        return _REALESRGAN_MISSING_MSG
    src, dst, scale, model, err = _validate_upscale_args(ctx)
    if err:
        return err

    ok, err = _run_ffmpeg(
        ["realesrgan-ncnn-vulkan", "-i", src, "-o", dst, "-s", str(scale), "-n", model], timeout=900,
    )
    if not ok:
        return f"❌ failed: {err}"
    # realesrgan-ncnn-vulkan بيرجع دايمًا exit code 0 حتى لو فشل فعليًا
    # (نموذج غلط، صورة تعذر فك تشفيرها، ...) — اتجرب فعليًا، مش افتراض.
    # الضمانة الحقيقية الوحيدة إن الملف طلع فعلاً وله حجم حقيقي.
    dst_path = pathlib.Path(dst)
    if not dst_path.is_file() or dst_path.stat().st_size == 0:
        return "❌ upscaling failed — the tool exited without an error but produced no real output file (check the model name)"
    return f"✅ image upscaled (x{scale}, {model}) at {dst}"


def _cmd_upscale_video(ctx) -> str:
    if len(ctx.args) < 2:
        return "usage: upscale_video <input> <output> [scale=4] [model=realesrgan-x4plus] — upscale video frame by frame (very slow without a GPU)"
    if not shutil.which("realesrgan-ncnn-vulkan"):
        return _REALESRGAN_MISSING_MSG
    if not shutil.which("ffmpeg"):
        return "❌ ffmpeg not found"
    src, dst, scale, model, err = _validate_upscale_args(ctx)
    if err:
        return err
    fps = _probe_fps(src) or 25.0

    with tempfile.TemporaryDirectory(prefix="nezuko_upscale_") as tmp:
        frames_in = pathlib.Path(tmp) / "in"
        frames_out = pathlib.Path(tmp) / "out"
        frames_in.mkdir()
        frames_out.mkdir()

        ok, err = _run_ffmpeg(["ffmpeg", "-y", "-i", src, str(frames_in / "frame_%06d.png")], timeout=600)
        if not ok:
            return f"❌ frame extraction failed: {err}"
        frames_in_count = sum(1 for _ in frames_in.iterdir())
        if frames_in_count == 0:
            return "❌ frame extraction failed — no frames were produced"

        # فريم فريم عبر Vulkan (زي upscale_image بالظبط) — بطيء جدًا من
        # غير GPU حقيقي، فمهلة أطول بكتير من باقي أوامر الملف ده.
        ok, err = _run_ffmpeg(
            ["realesrgan-ncnn-vulkan", "-i", str(frames_in), "-o", str(frames_out), "-s", str(scale), "-n", model],
            timeout=7200,
        )
        if not ok:
            return f"❌ upscaling failed: {err}"
        # مش كفاية نتأكد إن فيه فريم واحد على الأقل — realesrgan-ncnn-vulkan
        # ممكن يعلّق/يفشل نص الطريق (اتجرب فعليًا إنه غير مستقر تحت
        # Vulkan software rendering) وبرضو يرجع exit code صفر، فلو عدد
        # فريمات الخرج أقل من الدخل، ffmpeg هيجمّع فيديو مقصوص بصمت (image2
        # demuxer بيوقف عند أول اسم فريم ناقص بالترتيب) من غير أي تحذير.
        frames_out_count = sum(1 for _ in frames_out.iterdir())
        if frames_out_count == 0:
            return "❌ upscaling failed — the tool exited without an error but produced no real output frames"
        if frames_out_count < frames_in_count:
            return (
                f"❌ upscaling only partly finished — {frames_out_count} of {frames_in_count} frames "
                "(the tool stopped halfway with no visible error). Try again, or on a shorter clip."
            )

        ok, err = _run_ffmpeg(
            ["ffmpeg", "-y", "-r", str(fps), "-i", str(frames_out / "frame_%06d.png"),
             "-i", src, "-map", "0:v", "-map", "1:a?",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "copy", "-shortest", dst],
            timeout=600,
        )
        if not ok:
            return f"❌ reassembling the video failed: {err}"

    if not pathlib.Path(dst).is_file():
        return "❌ could not reassemble the final video"
    return f"✅ video upscaled (x{scale}, {model}) at {dst}"


# ── ترجمات (subtitles): توليد وحرق ──────────────────────────────────
# faster-whisper بيدّي توقيت (start/end) لكل جملة، مش النص المجمّع بس
# اللي voice_plugin.py بيستخدمه لـ listen — فده لازم مسار منفصل مش
# إعادة استخدام لدالة listen. الكاش هنا محلي للملف ده عن قصد (مش نفس
# كاش voice_plugin.py) عشان كل إضافة تفضل مستقلة بنفسها.
_faster_whisper_models: dict[str, object] = {}
_SUBTITLE_TIMEOUT = 1800  # الترجمة بطيئة على CPU لفيديو طويل


def _load_whisper_model(size: str):
    model = _faster_whisper_models.get(size)
    if model is None:
        from faster_whisper import WhisperModel  # noqa: PLC0415
        model = WhisperModel(size, device="cpu", compute_type="int8")
        _faster_whisper_models[size] = model
    return model


def _srt_timestamp(seconds: float) -> str:
    total_ms = round(max(0.0, seconds) * 1000)
    h, rem = divmod(total_ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _vtt_timestamp(seconds: float) -> str:
    return _srt_timestamp(seconds).replace(",", ".")


def _cmd_generate_subtitles(ctx) -> str:
    if len(ctx.args) < 2:
        return (
            "usage: generate_subtitles <video_or_audio> <out.srt|out.vtt> "
            "[model=tiny|base|small|medium] [lang=auto|en|ar|...]"
        )
    src, dst = ctx.args[0], ctx.args[1]
    model_size, lang = "base", None
    for arg in ctx.args[2:]:
        if arg.startswith("model="):
            model_size = arg.split("=", 1)[1]
        elif arg.startswith("lang="):
            value = arg.split("=", 1)[1]
            lang = None if value == "auto" else value

    missing = _missing_files(src)
    if missing:
        return f"❌ file not found: {missing[0]}"
    fmt = pathlib.Path(dst).suffix.lower()
    if fmt not in (".srt", ".vtt"):
        return "❌ output must end in .srt or .vtt"

    try:
        model = _load_whisper_model(model_size)
    except ImportError:
        return "❌ faster-whisper is not installed — pip install faster-whisper"
    except Exception as e:  # noqa: BLE001 - اسم موديل غلط أو تعذر التحميل
        return f"❌ could not load the '{model_size}' model: {e}"

    try:
        raw_segments, info = model.transcribe(src, language=lang, vad_filter=True)
        segments = [s for s in raw_segments if s.text.strip()]
    except Exception as e:  # noqa: BLE001 - ملف صوت تالف أو صيغة مش مدعومة
        return f"❌ transcription failed: {e}"
    if not segments:
        return "🔇 no speech detected — nothing to write"

    if fmt == ".vtt":
        blocks = ["WEBVTT\n"] + [
            f"{_vtt_timestamp(s.start)} --> {_vtt_timestamp(s.end)}\n{s.text.strip()}"
            for s in segments
        ]
    else:
        blocks = [
            f"{i}\n{_srt_timestamp(s.start)} --> {_srt_timestamp(s.end)}\n{s.text.strip()}"
            for i, s in enumerate(segments, 1)
        ]
    try:
        pathlib.Path(dst).write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    except OSError as e:
        return f"❌ could not save the subtitles: {e}"

    detected = f" (detected language: {info.language})" if lang is None else ""
    return f"✅ {len(segments)} subtitle lines written to {dst}{detected}"


def _cmd_burn_subtitles(ctx) -> str:
    if len(ctx.args) < 3:
        return "usage: burn_subtitles <video> <subtitles.srt|.vtt|.ass> <out.mp4>"
    if not shutil.which("ffmpeg"):
        return "❌ ffmpeg not found"
    src, subs, dst = ctx.args[0], ctx.args[1], ctx.args[2]
    missing = _missing_files(src, subs)
    if missing:
        return f"❌ file not found: {missing[0]}"

    # المسار بيتحط جوه واصف فلتر ffmpeg نصي، فأي `:` أو `'` أو `\` فيه
    # بتتفسر غلط (خصوصًا مسار ويندوز زي C:\...) — لازم تتهرّب صراحة
    # قبل ما تتحط جوه الفلتر، وإلا الأمر بيفشل أو بيقرا مسار غلط.
    escaped = subs.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    ok, err = _run_ffmpeg(
        ["ffmpeg", "-y", "-i", src, "-vf", f"subtitles='{escaped}'",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "copy", dst],
        timeout=_SUBTITLE_TIMEOUT,
    )
    if not ok:
        return f"❌ burning subtitles failed:\n{err}"
    if not pathlib.Path(dst).is_file():
        return "❌ ffmpeg finished but produced no real output file"
    return f"✅ subtitles burned into {dst}"


def register(engine):
    engine.registry.register("color_grade", _cmd_color_grade, "color_grade <in> <out> [preset] — cinematic colour grading")
    engine.registry.register("transition", _cmd_transition, "transition <c1> <c2> <out> [style] [dur] — professional transition between two clips")
    engine.registry.register("letterbox", _cmd_letterbox, "letterbox <in> <out> [ratio=2.39] — cinematic black bars")
    engine.registry.register("stabilize", _cmd_stabilize, "stabilize <in> <out> — remove camera shake (two-pass)")
    engine.registry.register("speed_ramp", _cmd_speed_ramp, "speed_ramp <in> <out> <factor> — change video/audio speed")
    engine.registry.register("pip", _cmd_pip, "pip <bg> <overlay> <out> [position] [scale] — picture in picture")
    engine.registry.register("chroma_key", _cmd_chroma_key, "chroma_key <fg> <bg> <out> [color] [similarity] — green-screen compositing")
    engine.registry.register("master_audio", _cmd_master_audio, "master_audio <in> <out> [lufs] — normalise loudness to a broadcast standard")
    engine.registry.register("denoise_audio", _cmd_denoise_audio, "denoise_audio <in> <out> — remove background noise from audio")
    engine.registry.register("auto_trim_silence", _cmd_auto_trim_silence, "auto_trim_silence <in> <out> [threshold=4%] — cut silence and dead air automatically (auto-editor)")
    engine.registry.register("detect_scenes", _cmd_detect_scenes, "detect_scenes <video> [threshold=27.0] — find scene changes automatically (PySceneDetect)")
    engine.registry.register("upscale_image", _cmd_upscale_image, "upscale_image <in> <out> [scale=4] [model] — AI image upscaling (Real-ESRGAN)")
    engine.registry.register("upscale_video", _cmd_upscale_video, "upscale_video <in> <out> [scale=4] [model] — upscale video frame by frame (Real-ESRGAN; very slow without a GPU)")
    engine.registry.register("title_card", _cmd_title_card, "title_card <text> <out> [duration] [size] — animated title card")
    engine.registry.register("generate_subtitles", _cmd_generate_subtitles, "generate_subtitles <video> <out.srt|out.vtt> [model=base] [lang=auto] — real speech-to-text subtitles with timestamps (faster-whisper)")
    engine.registry.register("burn_subtitles", _cmd_burn_subtitles, "burn_subtitles <video> <subs.srt> <out.mp4> — hardcode subtitles onto the video (ffmpeg/libass)")
