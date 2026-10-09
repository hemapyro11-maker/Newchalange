"""Modern, calm colours and fonts for Nezuko's chat workspace."""
from __future__ import annotations

DARK = {
    "bg":       "#0b111a",
    "panel":    "#111c29",
    "panel_hi": "#1b2d40",
    "text":     "#f4f4f4",
    "dim":      "#b4b4b4",
    "faint":    "#777777",
    "border":   "#24364a",
    "accent":   "#51d8ef",
    "green":    "#52c79a",
    "red":      "#ef6b73",
    "yellow":   "#e5b567",
    "blue":     "#7ab7ff",
}

LIGHT = {
    "bg":       "#faf9f5",
    "panel":    "#ffffff",
    "panel_hi": "#f0eee6",
    "text":     "#1f1e1d",
    "dim":      "#6b665c",
    "faint":    "#9a9488",
    "border":   "#ddd8ca",
    "accent":   "#0d8f70",
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

UI_CANDIDATES = (
    "Segoe UI Variable", "Segoe UI", "Inter", "Noto Sans Arabic",
    "Tahoma", "Arial", "sans-serif",
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


def pick_ui(root) -> str:
    """Pick a readable interface font with strong Arabic shaping on Windows."""
    try:
        from tkinter import font as tkfont
        available = {f.lower() for f in tkfont.families(root)}
    except Exception:  # noqa: BLE001
        return "Segoe UI"
    for name in UI_CANDIDATES:
        if name.lower() in available:
            return name
    return "Arial"


def palette(mode: str) -> dict:
    return DARK if mode == "dark" else LIGHT
