"""
macros_plugin.py — أوامر مخصصة (شبيهة بـ Custom Slash Commands في Claude
Code): أي ملف .txt تحطه في مجلد commands/ بيبقى أمر جديد، محتواه سطور
أوامر تتنفذ بالتتابع، مع دعم {args} لتمرير مدخلات المستخدم.

مثال: commands/deploy.txt
    echo بدأ الديبلوي لـ {args}
    run git pull
"""
from __future__ import annotations

import pathlib
import sys


def _commands_dir() -> pathlib.Path:
    base = pathlib.Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) \
        else pathlib.Path(__file__).resolve().parent.parent
    return base / "commands"


def _make_macro_handler(lines: list[str]):
    def handler(ctx):
        args_text = " ".join(ctx.args)
        outputs = []
        for line in lines:
            expanded = line.replace("{args}", args_text).strip()
            if not expanded or expanded.startswith("#"):
                continue
            ctx.engine.submit(expanded)
            outputs.append(f"→ {expanded}")
        return "\n".join(outputs) if outputs else "(macro فاضي)"
    return handler


def _cmd_macros(ctx) -> str:
    directory = _commands_dir()
    directory.mkdir(parents=True, exist_ok=True)
    files = sorted(p.stem for p in directory.glob("*.txt"))
    if not files:
        return f"مفيش macros لسه — حط ملف .txt في {directory}"
    return "macros متاحة: " + ", ".join(files)


def _cmd_reload_macros(ctx) -> str:
    load_macros(ctx.engine)
    return "تم إعادة تحميل الـ macros"


def load_macros(engine):
    directory = _commands_dir()
    directory.mkdir(parents=True, exist_ok=True)
    for path in sorted(directory.glob("*.txt")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception as e:
            engine._log(f"❌ تعذرت قراءة macro {path.name}: {e}", "error")
            continue
        engine.registry.register(
            path.stem, _make_macro_handler(lines), f"macro (من {path.name})"
        )


def register(engine):
    engine.registry.register("macros", _cmd_macros, "عرض الـ macros المتاحة (أوامر مخصصة)")
    engine.registry.register("reload_macros", _cmd_reload_macros, "إعادة تحميل الـ macros من مجلد commands/")
    load_macros(engine)
