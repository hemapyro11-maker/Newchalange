"""
design_plugin.py — أدوات تصميم بسيطة (لوجو، أيقونات تطبيقات) عبر
Pillow (مكتبة صور مفتوحة المصدر ومجانية بالكامل، بدون أي API مدفوع).
"""
from __future__ import annotations

import pathlib

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]

IOS_ICON_SIZES = [20, 29, 40, 58, 60, 76, 80, 87, 120, 152, 167, 180, 1024]
ANDROID_ICON_SIZES = {
    "mipmap-mdpi": 48, "mipmap-hdpi": 72, "mipmap-xhdpi": 96,
    "mipmap-xxhdpi": 144, "mipmap-xxxhdpi": 192, "playstore": 512,
}


def _find_font(size: int):
    for path in _FONT_CANDIDATES:
        if pathlib.Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _cmd_make_logo(ctx) -> str:
    if not PIL_AVAILABLE:
        return "❌ باكدج Pillow مش متثبت — ثبّته بـ: pip install Pillow"
    if len(ctx.args) < 2:
        return "usage: make_logo <text> <output.png> [size=512] [bg=#4f6ef7] [fg=#ffffff]"
    text, output = ctx.args[0], ctx.args[1]
    try:
        size = int(ctx.args[2]) if len(ctx.args) > 2 else 512
    except ValueError:
        return "❌ size لازم يكون رقم صحيح"
    if not (1 <= size <= 4096):
        return "❌ size لازم يكون بين 1 و4096"
    bg = ctx.args[3] if len(ctx.args) > 3 else "#4f6ef7"
    fg = ctx.args[4] if len(ctx.args) > 4 else "#ffffff"

    try:
        img = Image.new("RGB", (size, size), bg)
    except ValueError as e:
        return f"❌ لون الخلفية غير صالح ({bg}): {e}"
    draw = ImageDraw.Draw(img)
    font = _find_font(size // 3)
    words = text.split()
    initials = "".join(w[0] for w in words[:2]).upper() or "?"
    bbox = draw.textbbox((0, 0), initials, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    try:
        draw.text(((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1]), initials, fill=fg, font=font)
    except ValueError as e:
        return f"❌ لون الخط غير صالح ({fg}): {e}"

    out_path = pathlib.Path(output)
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(out_path)
    except OSError as e:
        return f"❌ تعذر حفظ الصورة: {e}"
    return f"✅ اتعمل اللوجو ({initials}) في {out_path}"


def _cmd_app_icons(ctx) -> str:
    if not PIL_AVAILABLE:
        return "❌ باكدج Pillow مش متثبت — ثبّته بـ: pip install Pillow"
    if len(ctx.args) < 2:
        return "usage: app_icons <source_image_square> <output_dir>"
    src = pathlib.Path(ctx.args[0])
    if not src.is_file():
        return f"❌ الملف مش موجود: {src}"
    out_dir = pathlib.Path(ctx.args[1])
    try:
        img = Image.open(src).convert("RGBA")
    except Exception as e:
        return f"❌ تعذرت قراءة الصورة: {e}"

    count = 0
    ios_dir = out_dir / "ios"
    try:
        for size in IOS_ICON_SIZES:
            ios_dir.mkdir(parents=True, exist_ok=True)
            img.resize((size, size), Image.LANCZOS).save(ios_dir / f"icon_{size}x{size}.png")
            count += 1

        for name, size in ANDROID_ICON_SIZES.items():
            target_dir = out_dir / "android" / name
            target_dir.mkdir(parents=True, exist_ok=True)
            img.resize((size, size), Image.LANCZOS).save(target_dir / "ic_launcher.png")
            count += 1
    except OSError as e:
        return f"❌ فشل الحفظ بعد {count} أيقونة: {e}"

    return f"✅ اتعمل {count} أيقونة (iOS: {len(IOS_ICON_SIZES)}, Android: {len(ANDROID_ICON_SIZES)}) في {out_dir}"


def register(engine):
    engine.registry.register("make_logo", _cmd_make_logo, "make_logo <text> <output.png> [size] [bg] [fg] — initials logo")
    engine.registry.register("app_icons", _cmd_app_icons, "app_icons <source.png> <out_dir> — generate every iOS/Android icon size")
