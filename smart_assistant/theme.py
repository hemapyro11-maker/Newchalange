"""
theme.py — لوحة ألوان وخطوط نيزوكو على طراز الطرفية (terminal).

الفلسفة: شاشة طرفية، مش تطبيق كروت. يعني خط مونوسبيس في كل حتة،
خلفية داكنة، حدود رفيعة جدًا، ولون تمييز واحد بس بيتصرف بحساب.
كل حاجة تانية رمادي بدرجات.

الوضع الداكن هو الافتراضي؛ الفاتح موجود لمن يحتاجه.
"""
from __future__ import annotations

DARK = {
    "bg":       "#1a1917",   # خلفية الشاشة
    "panel":    "#232220",   # صندوق الإدخال والقوايم
    "panel_hi": "#2d2b28",   # السطر المختار في القوايم
    "text":     "#e8e5df",
    "dim":      "#8a857c",   # نص ثانوي
    "faint":    "#5c5850",   # نص باهت جدًا (تلميحات)
    "border":   "#3a3833",
    "accent":   "#d97757",   # اللون الوحيد المميز
    "green":    "#6cae6c",
    "red":      "#e0776a",
    "yellow":   "#d4a35a",
    "blue":     "#7aa2c2",
}

LIGHT = {
    "bg":       "#faf9f5",
    "panel":    "#ffffff",
    "panel_hi": "#f0eee6",
    "text":     "#1f1e1d",
    "dim":      "#6b665c",
    "faint":    "#9a9488",
    "border":   "#ddd8ca",
    "accent":   "#c1633f",
    "green":    "#4b8b6b",
    "red":      "#c1483d",
    "yellow":   "#b8863a",
    "blue":     "#4a7a9e",
}

# خطوط مونوسبيس بترتيب الأفضلية. Cascadia بتيجي مع ويندوز تيرمينال،
# وConsolas موجودة على أي ويندوز. الباقي للينكس/ماك.
MONO_CANDIDATES = (
    "Cascadia Mono", "Cascadia Code", "Consolas", "JetBrains Mono",
    "DejaVu Sans Mono", "Menlo", "Monaco", "Courier New", "monospace",
)


def pick_mono(root) -> str:
    """بيختار أول خط مونوسبيس متاح فعليًا على الجهاز.

    من غير الفحص ده، تحديد خط مش موجود بيخلي Tk يرجع للخط الافتراضي
    (غير مونوسبيس) بصمت — فالشكل بيتكسر من غير أي رسالة خطأ.
    """
    try:
        from tkinter import font as tkfont
        available = {f.lower() for f in tkfont.families(root)}
    except Exception:  # noqa: BLE001
        return "Courier New"
    for name in MONO_CANDIDATES:
        if name.lower() in available:
            return name
    return "Courier New"


def palette(mode: str) -> dict:
    return DARK if mode == "dark" else LIGHT
