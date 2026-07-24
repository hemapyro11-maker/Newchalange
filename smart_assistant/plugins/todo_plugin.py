"""
todo_plugin.py — قائمة مهام بسيطة (شبيهة بـ Task tracking في Claude
Code)، محفوظة محلياً في todo.json. الأوامر:
  todo add <text>
  todo list
  todo done <id>
  todo clear
"""
from __future__ import annotations

import json
import pathlib
import sys


def _todo_path() -> pathlib.Path:
    base = pathlib.Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) \
        else pathlib.Path(__file__).resolve().parent.parent
    return base / "todo.json"


def _load() -> list[dict]:
    path = _todo_path()
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(items: list[dict]):
    _todo_path().write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def _format(items: list[dict]) -> str:
    if not items:
        return "القائمة فاضية 🎉"
    lines = []
    for item in items:
        mark = "✅" if item["done"] else "◻️"
        lines.append(f"{mark} #{item['id']}  {item['text']}")
    return "\n".join(lines)


def _cmd_todo(ctx) -> str:
    items = _load()
    if not ctx.args or ctx.args[0] == "list":
        return _format(items)

    action = ctx.args[0]
    if action == "add":
        text = " ".join(ctx.args[1:]).strip()
        if not text:
            return "usage: todo add <text>"
        next_id = (max((i["id"] for i in items), default=0)) + 1
        items.append({"id": next_id, "text": text, "done": False})
        _save(items)
        return f"➕ اتضافت مهمة #{next_id}"

    if action == "done":
        if len(ctx.args) < 2 or not ctx.args[1].isdigit():
            return "usage: todo done <id>"
        task_id = int(ctx.args[1])
        for item in items:
            if item["id"] == task_id:
                item["done"] = True
                _save(items)
                return f"✅ خلصت مهمة #{task_id}"
        return f"❌ مفيش مهمة رقم #{task_id}"

    if action == "clear":
        _save([])
        return "🗑 اتمسحت كل المهام"

    return "usage: todo [list|add <text>|done <id>|clear]"


def register(engine):
    engine.registry.register("todo", _cmd_todo, "todo [list|add <text>|done <id>|clear] — قائمة مهام محلية")
