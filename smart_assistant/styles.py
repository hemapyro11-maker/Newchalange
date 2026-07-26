"""
styles.py — أنماط الرد (output styles): بتغيّر أسلوب نيزوكو في الكلام
من غير ما تغيّر قدراتها.

نفس فكرة output styles في Claude Code: النمط بيتحقن في تعليمات النظام،
فبيأثر على **الشكل والنبرة** بس — مش على الأدوات ولا الصلاحيات ولا
مبدأ التأكيد قبل التنفيذ.

الأنماط المدمجة:
    default    ردود قصيرة عملية بالعامية
    concise    أقصر ما يمكن — سطر أو اتنين
    detailed   شرح كامل مع السبب والخطوات
    teacher    بيشرح الفكرة ورا كل حاجة عشان تتعلم
    formal     عربي فصيح رسمي

وتقدر تضيف بتاعك في `styles/<name>.md` — أي ملف markdown محتواه
بيتحقن كما هو.
"""
from __future__ import annotations

import pathlib
import re
import sys

import brain

BUILTIN: dict[str, dict[str, str]] = {
    "default": {
        "label": "Default",
        "desc": "short, practical answers",
        "prompt": (
            "Keep replies short and practical. Lead with the answer, then only "
            "the detail that changes what the user does next."
        ),
    },
    "concise": {
        "label": "Concise",
        "desc": "one or two lines, nothing more",
        "prompt": (
            "Answer in one or two lines. No preamble, no restating the "
            "question, no closing offers of further help. If a single word "
            "answers it, use a single word."
        ),
    },
    "detailed": {
        "label": "Detailed",
        "desc": "full explanation with reasoning and steps",
        "prompt": (
            "Explain fully: what you are doing, why that approach, and what "
            "each step accomplishes. Surface trade-offs and anything that "
            "could go wrong. Structure longer answers with short headings."
        ),
    },
    "teacher": {
        "label": "Teacher",
        "desc": "explains the idea behind every step",
        "prompt": (
            "Teach as you answer. Explain the concept behind each step so the "
            "user could do it themselves next time. Define jargon the first "
            "time it appears. Prefer a worked example over an abstract rule."
        ),
    },
    "formal": {
        "label": "Formal",
        "desc": "formal standard Arabic",
        "prompt": (
            "اكتب بالعربية الفصحى الرسمية، بجُمَل كاملة ومصطلحات دقيقة. "
            "تجنّب العامية والاختصارات."
        ),
    },
}

DEFAULT = "default"


def _base_dir() -> pathlib.Path:
    if getattr(sys, "frozen", False):
        return pathlib.Path(sys.executable).resolve().parent
    return pathlib.Path(__file__).resolve().parent


def styles_dir() -> pathlib.Path:
    d = _base_dir() / "styles"
    d.mkdir(parents=True, exist_ok=True)
    return d


def custom() -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for path in sorted(styles_dir().glob("*.md")):
        try:
            body = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if body:
            out[path.stem] = {
                "label": path.stem,
                "desc": "custom",
                "prompt": body,
            }
    return out


def all_styles() -> dict[str, dict[str, str]]:
    """المدمجة + المخصصة. المخصصة بتغلب لو الاسم واحد، فتقدر تستبدل
    نمط مدمج من غير ما تلمس الكود."""
    merged = dict(BUILTIN)
    merged.update(custom())
    return merged


def current() -> str:
    name = brain.load_config().get("output_style", DEFAULT)
    return name if name in all_styles() else DEFAULT


def set_current(name: str) -> tuple[bool, str]:
    if name not in all_styles():
        return False, f"❌ unknown style: {name} ({', '.join(sorted(all_styles()))})"
    cfg = brain.load_config()
    cfg["output_style"] = name
    brain.save_config(cfg)
    return True, f"✅ output style: {name}"


def prompt_for(name: str | None = None) -> str:
    """نص النمط اللي بيتحقن في تعليمات النظام."""
    style = all_styles().get(name or current())
    return style["prompt"] if style else ""


def save_custom(name: str, body: str) -> pathlib.Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "-", name)[:40] or "style"
    path = styles_dir() / f"{safe}.md"
    path.write_text(body.strip() + "\n", encoding="utf-8")
    return path


def delete_custom(name: str) -> bool:
    path = styles_dir() / f"{name}.md"
    try:
        path.unlink()
        return True
    except OSError:
        return False
