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


def _probe_fps(path: str) -> float | None:
    if not shutil.which("ffprobe"):
        return None
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True, timeout=30,
    )
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


# ═══════════════════════════════════════════════════════════════════
# قص تلقائي (auto-editor) — أداة مفتوحة المصدر منفصلة
# ═══════════════════════════════════════════════════════════════════

def _cmd_auto_trim_silence(ctx) -> str:
    if len(ctx.args) < 2:
        return "usage: auto_trim_silence <input> <output> [threshold=4%] — بيقص الصمت/اللقطات الميتة تلقائيًا"
    if not shutil.which("auto-editor"):
        return "❌ auto-editor مش متثبت — نزّله بـ: pip install auto-editor (مجاني ومفتوح المصدر، https://github.com/WyattBlue/auto-editor)"
    src, dst = ctx.args[0], ctx.args[1]
    missing = _missing_files(src)
    if missing:
        return f"❌ الملف مش موجود: {missing[0]}"
    threshold = ctx.args[2] if len(ctx.args) > 2 else "4%"
    ok, err = _run_ffmpeg(
        ["auto-editor", src, "--edit", f"audio:threshold={threshold}", "-o", dst, "--no-open", "--quiet"],
        timeout=900,  # ملفات المونتاج الطويلة بتاخد وقت أطول من فلاتر ffmpeg العادية
    )
    if not ok:
        return f"❌ فشل: {err}"
    return f"✅ اتقص الصمت/اللقطات الميتة تلقائيًا (threshold={threshold}) في {dst}"


# ═══════════════════════════════════════════════════════════════════
# كشف مشاهد (PySceneDetect) — مكتبة مفتوحة المصدر منفصلة
# ═══════════════════════════════════════════════════════════════════

def _cmd_detect_scenes(ctx) -> str:
    if not ctx.args:
        return "usage: detect_scenes <video> [threshold=27.0] — يكتشف تغييرات المشاهد (scene cuts) تلقائيًا"
    if not _HAS_SCENEDETECT:
        return "❌ PySceneDetect مش متثبت — نزّله بـ: pip install scenedetect[opencv] (مجاني ومفتوح المصدر)"
    src = ctx.args[0]
    missing = _missing_files(src)
    if missing:
        return f"❌ الملف مش موجود: {missing[0]}"
    try:
        threshold = float(ctx.args[1]) if len(ctx.args) > 1 else 27.0
    except ValueError:
        return "❌ threshold لازم يكون رقم (كل ما قل، كشف أحسّ بتغييرات أبسط)"

    try:
        scenes = _scenedetect_detect(src, ContentDetector(threshold=threshold))
    except Exception as e:
        return f"❌ فشل كشف المشاهد: {e}"

    if not scenes:
        return f"ℹ️ مفيش تغييرات مشاهد واضحة اتلقت (threshold={threshold}) — يمكن الفيديو مشهد واحد مستمر"

    lines = [f"🎬 {len(scenes)} مشهد اتلقى (threshold={threshold}):"]
    for i, (start, end) in enumerate(scenes, start=1):
        lines.append(f"  {i}. {start.get_timecode()} → {end.get_timecode()}  ({end.seconds - start.seconds:.1f}s)")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# تكبير بالذكاء الاصطناعي (Real-ESRGAN) — ملف تنفيذي خارجي اختياري
# ═══════════════════════════════════════════════════════════════════

_REALESRGAN_MODELS = ("realesr-animevideov3", "realesrgan-x4plus", "realesrgan-x4plus-anime", "realesrnet-x4plus")
_REALESRGAN_MISSING_MSG = (
    "❌ realesrgan-ncnn-vulkan مش متثبت — ملف تنفيذي جاهز (مش pip)، حمّله من:\n"
    "   https://github.com/xinntao/Real-ESRGAN/releases\n"
    "   وحطه في PATH. بيشتغل عبر Vulkan (بطيء جدًا من غير GPU حقيقي)."
)


def _validate_upscale_args(ctx) -> tuple[str, str, int, str, str | None]:
    """يرجع (src, dst, scale, model, رسالة خطأ أو None). لو فيه خطأ،
    القيم التانية بتبقى فاضية/افتراضية ومينفعش تتستخدم."""
    src, dst = ctx.args[0], ctx.args[1]
    missing = _missing_files(src)
    if missing:
        return "", "", 0, "", f"❌ الملف مش موجود: {missing[0]}"
    try:
        scale = int(ctx.args[2]) if len(ctx.args) > 2 else 4
    except ValueError:
        return "", "", 0, "", "❌ scale لازم يكون رقم صحيح (2 أو 3 أو 4)"
    if scale not in (2, 3, 4):
        return "", "", 0, "", "❌ scale لازم يكون 2 أو 3 أو 4"
    model = ctx.args[3] if len(ctx.args) > 3 else "realesrgan-x4plus"
    if model not in _REALESRGAN_MODELS:
        return "", "", 0, "", f"❌ model لازم يكون واحد من: {', '.join(_REALESRGAN_MODELS)}"
    return src, dst, scale, model, None


def _cmd_upscale_image(ctx) -> str:
    if len(ctx.args) < 2:
        return "usage: upscale_image <input> <output> [scale=4] [model=realesrgan-x4plus] — تكبير صورة بالذكاء الاصطناعي (Real-ESRGAN)"
    if not shutil.which("realesrgan-ncnn-vulkan"):
        return _REALESRGAN_MISSING_MSG
    src, dst, scale, model, err = _validate_upscale_args(ctx)
    if err:
        return err

    ok, err = _run_ffmpeg(
        ["realesrgan-ncnn-vulkan", "-i", src, "-o", dst, "-s", str(scale), "-n", model], timeout=900,
    )
    if not ok:
        return f"❌ فشل: {err}"
    # realesrgan-ncnn-vulkan بيرجع دايمًا exit code 0 حتى لو فشل فعليًا
    # (نموذج غلط، صورة تعذر فك تشفيرها، ...) — اتجرب فعليًا، مش افتراض.
    # الضمانة الحقيقية الوحيدة إن الملف طلع فعلاً وله حجم حقيقي.
    dst_path = pathlib.Path(dst)
    if not dst_path.is_file() or dst_path.stat().st_size == 0:
        return "❌ فشل التكبير — الأداة خلصت من غير خطأ ظاهر بس مفيش ملف خرج حقيقي (تأكد من اسم الموديل)"
    return f"✅ اتكبرت الصورة (x{scale}, {model}) في {dst}"


def _cmd_upscale_video(ctx) -> str:
    if len(ctx.args) < 2:
        return "usage: upscale_video <input> <output> [scale=4] [model=realesrgan-x4plus] — تكبير فيديو فريم فريم (بطيء جدًا من غير GPU)"
    if not shutil.which("realesrgan-ncnn-vulkan"):
        return _REALESRGAN_MISSING_MSG
    if not shutil.which("ffmpeg"):
        return "❌ ffmpeg غير موجود"
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
            return f"❌ فشل استخراج الفريمات: {err}"
        if not any(frames_in.iterdir()):
            return "❌ فشل استخراج الفريمات — مفيش فريمات اتولدت"

        # فريم فريم عبر Vulkan (زي upscale_image بالظبط) — بطيء جدًا من
        # غير GPU حقيقي، فمهلة أطول بكتير من باقي أوامر الملف ده.
        ok, err = _run_ffmpeg(
            ["realesrgan-ncnn-vulkan", "-i", str(frames_in), "-o", str(frames_out), "-s", str(scale), "-n", model],
            timeout=7200,
        )
        if not ok:
            return f"❌ فشل التكبير: {err}"
        if not any(frames_out.iterdir()):
            return "❌ فشل التكبير — الأداة خلصت من غير خطأ ظاهر بس مفيش فريمات خرج حقيقية"

        ok, err = _run_ffmpeg(
            ["ffmpeg", "-y", "-r", str(fps), "-i", str(frames_out / "frame_%06d.png"),
             "-i", src, "-map", "0:v", "-map", "1:a?",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "copy", "-shortest", dst],
            timeout=600,
        )
        if not ok:
            return f"❌ فشل تجميع الفيديو: {err}"

    if not pathlib.Path(dst).is_file():
        return "❌ فشل تجميع الفيديو النهائي"
    return f"✅ اتكبر الفيديو (x{scale}, {model}) في {dst}"


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
    engine.registry.register("auto_trim_silence", _cmd_auto_trim_silence, "auto_trim_silence <in> <out> [threshold=4%] — قص الصمت/اللقطات الميتة تلقائيًا (auto-editor)")
    engine.registry.register("detect_scenes", _cmd_detect_scenes, "detect_scenes <video> [threshold=27.0] — كشف تغييرات المشاهد تلقائيًا (PySceneDetect)")
    engine.registry.register("upscale_image", _cmd_upscale_image, "upscale_image <in> <out> [scale=4] [model] — تكبير صورة بالذكاء الاصطناعي (Real-ESRGAN)")
    engine.registry.register("upscale_video", _cmd_upscale_video, "upscale_video <in> <out> [scale=4] [model] — تكبير فيديو فريم فريم (Real-ESRGAN، بطيء جدًا من غير GPU)")
    engine.registry.register("title_card", _cmd_title_card, "title_card <text> <out> [duration] [size] — لوحة عنوان متحركة")
