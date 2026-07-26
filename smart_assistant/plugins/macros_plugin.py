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


_MACRO_MARKER = "macro (من "


def _macro_calls(lines: list[str], known_names: set[str]) -> set[str]:
    """أسماء الماكروهات (من ضمن known_names) اللي الماكرو ده بينادي عليها
    كأول كلمة في أي سطر."""
    calls = set()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        first = stripped.split(maxsplit=1)[0]
        if first in known_names:
            calls.add(first)
    return calls


def _detect_macro_cycles(macro_lines: dict[str, list[str]]) -> dict[str, list[str]]:
    """بيبني جراف "مين بينادي مين" بين كل الماكروهات المكتشفة، ويرجع
    dict بيربط كل اسم ماكرو مشارك في دورة (self-reference أو استدعاء
    متبادل غير مباشر عبر ماكروهات تانية) بمسار الدورة نفسها. من غير
    الكشف ده، ماكروين بينادوا بعض كانوا هيسببوا نمو لا نهائي لـ queue
    المحرك (thread واحد بينفذ الأوامر بالتتابع، فمفيش حد أقصى للعمق)."""
    names = set(macro_lines)
    graph = {name: _macro_calls(lines, names) for name, lines in macro_lines.items()}

    cycle_members: dict[str, list[str]] = {}
    for start in graph:
        path: list[str] = []

        def dfs(node: str) -> None:
            if node in path:
                cycle = [*path[path.index(node):], node]
                for n in cycle:
                    cycle_members.setdefault(n, cycle)
                return
            path.append(node)
            for nxt in graph.get(node, ()):
                dfs(nxt)
            path.pop()

        dfs(start)
    return cycle_members


def load_macros(engine):
    directory = _commands_dir()
    directory.mkdir(parents=True, exist_ok=True)
    macro_lines: dict[str, list[str]] = {}
    for path in sorted(directory.glob("*.txt")):
        try:
            macro_lines[path.stem] = path.read_text(encoding="utf-8").splitlines()
        except OSError as e:
            engine._log(f"❌ تعذرت قراءة macro {path.name}: {e}", "error")

    cycles = _detect_macro_cycles(macro_lines)

    for path in sorted(directory.glob("*.txt")):
        name = path.stem
        if name not in macro_lines:
            continue
        existing = engine.registry.get(name)
        if existing is not None and not existing.description.startswith(_MACRO_MARKER):
            engine._log(f"⚠  اتجاهل macro '{name}' لأنه بيصطدم مع أمر مدمج بنفس الاسم", "warn")
            continue
        if name in cycles:
            cycle = cycles[name]
            if len(cycle) <= 2 and cycle[0] == cycle[-1]:
                engine._log(f"⚠  اتجاهل macro '{name}' لأنه بينادي نفسه (self-reference)", "warn")
            else:
                chain = " → ".join(cycle)
                engine._log(f"⚠  اتجاهل macro '{name}' لأنه جزء من دورة استدعاء متبادلة: {chain}", "warn")
            continue
        engine.registry.register(name, _make_macro_handler(macro_lines[name]), f"{_MACRO_MARKER}{path.name})")


def register(engine):
    engine.registry.register("macros", _cmd_macros, "macros — list your custom commands")
    engine.registry.register("reload_macros", _cmd_reload_macros, "reload_macros — reload custom commands from commands/")
    load_macros(engine)
