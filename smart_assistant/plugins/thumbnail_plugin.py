"""
thumbnail_plugin.py — مصمم المصغرات (thumbnails): تحليل صورة حقيقي عبر
Pillow (سطوع، تباين، تشبع لون، الدقة/النسبة، حجم الملف مقابل حدود يوتيوب
الفعلية)، توليد مصغرة بنص فوق خلفية مع اختيار لون نص تلقائي حسب سطوع
المكان اللي هيتحط فيه النص، ومقارنة A/B بين مصغرتين على نفس المقاييس.

الأوامر: thumbnail_analyze, thumbnail_generate, thumbnail_ab_compare
"""
from __future__ import annotations

import pathlib

try:
    from PIL import Image, ImageDraw, ImageFont, ImageStat
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

TARGET_SIZE = (1280, 720)          # مقاس يوتيوب الموصى بيه رسميًا
TARGET_ASPECT = 16 / 9
MAX_FILE_SIZE = 2 * 1024 * 1024    # حد يوتيوب الفعلي: 2MB

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]


def _find_font(size: int):
    for path in _FONT_CANDIDATES:
        if pathlib.Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                pass
    return ImageFont.load_default()


def _require_pil() -> str | None:
    if not PIL_AVAILABLE:
        return "❌ Pillow is not installed — pip install Pillow"
    return None


def _analyze_image(path: pathlib.Path) -> dict:
    """بيرجع dict فيه كل مقاييس التحليل — مستخدم في thumbnail_analyze
    وthumbnail_ab_compare عشان نفس المنطق يتحسب مرة واحدة."""
    file_size = path.stat().st_size
    img = Image.open(path)
    width, height = img.size
    aspect = width / height if height else 0

    # الإحصائيات (سطوع/تباين/تشبع) مجاميع إحصائية مش محتاجة كل بيكسل —
    # عينة مصغّرة بتدي نفس النتيجة عمليًا بسرعة أكبر بكتير. اختبار حمل
    # حقيقي على صورة 24 ميجابكسل أظهر إن حساب الإحصائيات على الدقة
    # الكاملة كان بياخد أكتر من ثانيتين؛ نفس الحساب على عينة 800px بقى
    # أجزاء من الثانية من غير أي فرق ملحوظ في النتيجة.
    sample_max_dim = 800
    if max(width, height) > sample_max_dim:
        scale = sample_max_dim / max(width, height)
        sample = img.convert("RGB").resize((max(1, round(width * scale)), max(1, round(height * scale))))
    else:
        sample = img.convert("RGB")

    gray = sample.convert("L")
    stat_gray = ImageStat.Stat(gray)
    brightness = stat_gray.mean[0]
    contrast = stat_gray.stddev[0]

    hsv = sample.convert("HSV")
    saturation = ImageStat.Stat(hsv).mean[1]

    small = sample.resize((50, 50))
    colors = small.getcolors(50 * 50) or []
    dominant = max(colors, key=lambda c: c[0])[1] if colors else (0, 0, 0)
    dominant_hex = "#{:02x}{:02x}{:02x}".format(*dominant)

    score = 50
    notes = []

    aspect_diff = abs(aspect - TARGET_ASPECT) / TARGET_ASPECT if aspect else 1
    if width == TARGET_SIZE[0] and height == TARGET_SIZE[1]:
        score += 20
        notes.append(f"✅ resolution matches the recommended {TARGET_SIZE[0]}x{TARGET_SIZE[1]}")
    elif aspect_diff < 0.03:
        score += 12
        notes.append(f"✅ aspect ratio is right (16:9), though {width}x{height} is not the ideal resolution")
    else:
        score -= 10
        notes.append(f"⚠️ aspect ratio {aspect:.2f} is far from 16:9 — it may get cropped in previews")

    if file_size > MAX_FILE_SIZE:
        score -= 20
        notes.append(f"❌ file size {file_size / 1024:.0f}KB is over YouTube's 2MB limit")
    else:
        notes.append(f"✅ file size {file_size / 1024:.0f}KB — within YouTube's limit")

    if brightness < 60:
        score -= 5
        notes.append(f"⚠️ the image is dark (brightness {brightness:.0f}/255) — it may disappear in a feed")
    elif brightness > 210:
        score -= 5
        notes.append(f"⚠️ the image is very light (brightness {brightness:.0f}/255) — it may look washed out")
    else:
        score += 10
        notes.append(f"✅ balanced brightness ({brightness:.0f}/255)")

    if contrast < 30:
        score -= 10
        notes.append(f"⚠️ low contrast ({contrast:.0f}) — it may look flat next to other thumbnails")
    elif contrast > 55:
        score += 15
        notes.append(f"✅ strong contrast ({contrast:.0f}) — it catches the eye in a results list")
    else:
        score += 5
        notes.append(f"🙂 moderate contrast ({contrast:.0f})")

    if saturation > 100:
        score += 10
        notes.append(f"✅ vivid colours (saturation {saturation:.0f}/255) — these usually get more clicks")
    else:
        notes.append(f"ℹ️ muted colours (saturation {saturation:.0f}/255)")

    return {
        "width": width, "height": height, "file_size": file_size,
        "brightness": brightness, "contrast": contrast, "saturation": saturation,
        "dominant_hex": dominant_hex, "score": max(0, min(100, score)), "notes": notes,
    }


def _cmd_thumbnail_analyze(ctx) -> str:
    err = _require_pil()
    if err:
        return err
    if not ctx.args:
        return "usage: thumbnail_analyze <image_path>"
    path = pathlib.Path(ctx.args[0])
    if not path.is_file():
        return f"❌ file not found: {path}"
    try:
        result = _analyze_image(path)
    except Exception as e:
        return f"❌ could not analyse the image: {e}"

    lines = [
        f"🖼 Thumbnail analysis: {path.name}",
        f"   📐 {result['width']}x{result['height']}  |  🎨 dominant colour: {result['dominant_hex']}",
        f"\nScore: {result['score']}/100\n",
    ]
    lines += [f"  {n}" for n in result["notes"]]
    return "\n".join(lines)


def _fit_text_size(draw, text: str, max_width: int, max_height: int, start_size: int = 120) -> tuple:
    """بيصغّر حجم الخط تدريجيًا لحد ما النص يتظبط في المساحة المتاحة —
    بدل حجم ثابت ممكن يطلع برّه الصورة أو يبقى صغير جدًا من غير داعي."""
    size = start_size
    while size > 10:
        font = _find_font(size)
        bbox = draw.textbbox((0, 0), text, font=font)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        if w <= max_width and h <= max_height:
            return font, w, h
        size -= 4
    font = _find_font(10)
    bbox = draw.textbbox((0, 0), text, font=font)
    return font, bbox[2] - bbox[0], bbox[3] - bbox[1]


def _cmd_thumbnail_generate(ctx) -> str:
    err = _require_pil()
    if err:
        return err
    if len(ctx.args) < 3:
        return "usage: thumbnail_generate <bg_image> <title_text> <out.jpg>"
    bg_path = pathlib.Path(ctx.args[0])
    title = ctx.args[1]
    out_path = pathlib.Path(ctx.args[2])
    if not bg_path.is_file():
        return f"❌ file not found: {bg_path}"
    if not title.strip():
        return "❌ the text is empty"

    try:
        img = Image.open(bg_path).convert("RGB")
    except Exception as e:
        return f"❌ could not read the image: {e}"

    # cover-fit: نكبّر لحد ما أصغر بعد يغطي المساحة المطلوبة، وبعدين نقص
    # الزيادة من النص عشان الصورة تملى 1280x720 بالظبط من غير تشويه.
    tw, th = TARGET_SIZE
    scale = max(tw / img.width, th / img.height)
    new_size = (round(img.width * scale), round(img.height * scale))
    img = img.resize(new_size, Image.LANCZOS)
    left = (img.width - tw) // 2
    top = (img.height - th) // 2
    img = img.crop((left, top, left + tw, top + th))

    draw = ImageDraw.Draw(img)
    max_text_width = int(tw * 0.9)
    banner_height = int(th * 0.32)
    max_text_height = int(banner_height * 0.8)
    font, text_w, text_h = _fit_text_size(draw, title, max_text_width, max_text_height)

    text_x = (tw - text_w) // 2
    text_y = th - banner_height + (banner_height - text_h) // 2

    # لون النص التلقائي: بنقيس متوسط سطوع المنطقة اللي النص هيتحط فيها
    # فعليًا، مش الصورة كلها — عشان القرار يبقى دقيق حتى لو نص الصورة
    # غامق ونصها فاتح.
    region = img.crop((0, th - banner_height, tw, th)).convert("L")
    region_brightness = ImageStat.Stat(region).mean[0]
    if region_brightness < 128:
        fill, stroke = "#ffffff", "#000000"
    else:
        fill, stroke = "#000000", "#ffffff"

    stroke_width = max(2, font.size // 20 if hasattr(font, "size") else 3)
    draw.text((text_x, text_y), title, fill=fill, font=font,
              stroke_width=stroke_width, stroke_fill=stroke)

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(out_path, quality=90)
    except OSError as e:
        return f"❌ could not save the image: {e}"

    size_kb = out_path.stat().st_size / 1024
    warn = f" ⚠️ {size_kb:.0f}KB is over YouTube's 2MB limit" if size_kb * 1024 > MAX_FILE_SIZE else ""
    return f"✅ thumbnail created ({tw}x{th}, {size_kb:.0f}KB) at {out_path}{warn}"


def _cmd_thumbnail_ab_compare(ctx) -> str:
    err = _require_pil()
    if err:
        return err
    if len(ctx.args) < 2:
        return "usage: thumbnail_ab_compare <image_a> <image_b>"
    path_a, path_b = pathlib.Path(ctx.args[0]), pathlib.Path(ctx.args[1])
    if not path_a.is_file():
        return f"❌ file not found: {path_a}"
    if not path_b.is_file():
        return f"❌ file not found: {path_b}"

    try:
        a = _analyze_image(path_a)
        b = _analyze_image(path_b)
    except Exception as e:
        return f"❌ could not analyse: {e}"

    lines = [
        f"⚖️ A/B comparison: {path_a.name}  vs  {path_b.name}",
        f"\n  A) {path_a.name} — {a['score']}/100  (contrast {a['contrast']:.0f}, saturation {a['saturation']:.0f})",
        f"  B) {path_b.name} — {b['score']}/100  (contrast {b['contrast']:.0f}, saturation {b['saturation']:.0f})",
    ]
    if a["score"] == b["score"]:
        lines.append("\n🤝 effectively tied — pick whichever represents the video more honestly")
    else:
        winner, wscore = ("A", a["score"]) if a["score"] > b["score"] else ("B", b["score"])
        lines.append(f"\n🏆 {winner} scores higher on the measurable properties ({wscore}/100) — an indicator, not a guarantee of real click-through")
    return "\n".join(lines)


def register(engine):
    engine.registry.register("thumbnail_analyze", _cmd_thumbnail_analyze,
                              "thumbnail_analyze <image_path> — analyse a thumbnail (brightness, contrast, resolution, size)")
    engine.registry.register("thumbnail_generate", _cmd_thumbnail_generate,
                              "thumbnail_generate <bg_image> <title> <out.jpg> — build a 1280x720 thumbnail with auto-coloured text")
    engine.registry.register("thumbnail_ab_compare", _cmd_thumbnail_ab_compare,
                              "thumbnail_ab_compare <image_a> <image_b> — compare two thumbnails on the same measures")
