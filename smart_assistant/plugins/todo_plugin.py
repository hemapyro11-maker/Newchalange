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
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _save(items: list[dict]) -> str | None:
    """يحفظ ويرجع None لو نجح، أو رسالة خطأ لو فشل."""
    try:
        _todo_path().write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        return f"❌ تعذر حفظ القائمة: {e}"
    return None


def _format(items: list[dict]) -> str:
    if not items:
        return "القائمة فاضية 🎉"
    lines = []
    for item in items:
        if not isinstance(item, dict) or "id" not in item:
            continue
        mark = "✅" if item.get("done") else "◻️"
        lines.append(f"{mark} #{item['id']}  {item.get('text', '')}")
    return "\n".join(lines) if lines else "القائمة فاضية 🎉"


def _cmd_todo(ctx) -> str:
    items = _load()
    if not ctx.args or ctx.args[0] == "list":
        return _format(items)

    action = ctx.args[0]
    if action == "add":
        text = " ".join(ctx.args[1:]).strip()
        if not text:
            return "usage: todo add <text>"
        next_id = max((i.get("id", 0) for i in items if isinstance(i, dict)), default=0) + 1
        items.append({"id": next_id, "text": text, "done": False})
        err = _save(items)
        return err or f"➕ اتضافت مهمة #{next_id}"

    if action == "done":
        if len(ctx.args) < 2 or not ctx.args[1].isdigit():
            return "usage: todo done <id>"
        task_id = int(ctx.args[1])
        for item in items:
            if isinstance(item, dict) and item.get("id") == task_id:
                item["done"] = True
                err = _save(items)
                return err or f"✅ خلصت مهمة #{task_id}"
        return f"❌ مفيش مهمة رقم #{task_id}"

    if action == "clear":
        err = _save([])
        return err or "🗑 اتمسحت كل المهام"

    return "usage: todo [list|add <text>|done <id>|clear]"


def register(engine):
    engine.registry.register("todo", _cmd_todo, "todo [list|add <text>|done <id>|clear] — a local task list")
