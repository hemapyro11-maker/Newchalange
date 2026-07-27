"""
hooks.py — أوامر بتتنفذ لوحدها عند أحداث معيّنة في نيزوكو.

مستوحى من hooks في Claude Code: بدل ما تفتكر تشغّل حاجة بعد كل مهمة،
تربطها بحدث مرة واحدة وتنساها.

الأحداث المتاحة:
    startup        أول ما المحرك يشتغل
    before_command قبل أي أمر ما ينفذ
    after_command  بعد ما أمر يخلص بنجاح
    on_error       لما أمر يرمي استثناء
    session_end    عند الخروج

**الأمان:** الأوامر المربوطة بتمشي في **نفس طابور التنفيذ العادي**،
يعني بتاخد نفس معاملة أي أمر بتكتبه بإيدك — بما فيها إن الأوامر
الخطيرة لسه محتاجة تأكيد. مفيش مسار تنفيذ مختصر للـ hooks.

الملف `hooks.json` محلي وخارج git.
"""
from __future__ import annotations

import json
import pathlib
import sys
import threading

_lock = threading.Lock()

EVENTS = ("startup", "before_command", "after_command", "on_error", "session_end")


def _base_dir() -> pathlib.Path:
    if getattr(sys, "frozen", False):
        return pathlib.Path(sys.executable).resolve().parent
    return pathlib.Path(__file__).resolve().parent


def _path() -> pathlib.Path:
    return _base_dir() / "hooks.json"


def load() -> dict[str, list[str]]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {e: [] for e in EVENTS}
    out = {e: [] for e in EVENTS}
    if isinstance(data, dict):
        for event in EVENTS:
            value = data.get(event, [])
            if isinstance(value, list):
                out[event] = [str(v) for v in value if isinstance(v, str)]
    return out


def _save(data: dict[str, list[str]]) -> None:
    try:
        _path().write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    except OSError:
        pass


def add(event: str, command: str) -> tuple[bool, str]:
    if event not in EVENTS:
        return False, f"❌ unknown event: {event} (available: {', '.join(EVENTS)})"
    command = command.strip()
    if not command:
        return False, "❌ empty command"
    with _lock:
        data = load()
        if command in data[event]:
            return True, "already bound"
        data[event].append(command)
        _save(data)
    return True, f"✅ bound to {event}: {command}"


def remove(event: str, command: str) -> bool:
    with _lock:
        data = load()
        if event not in data or command not in data[event]:
            return False
        data[event].remove(command)
        _save(data)
    return True


def clear() -> int:
    with _lock:
        data = load()
        n = sum(len(v) for v in data.values())
        _save({e: [] for e in EVENTS})
    return n


def commands_for(event: str) -> list[str]:
    return load().get(event, [])


def fire(engine, event: str, **context) -> None:
    """بيشغّل أوامر الحدث ده عبر طابور المحرك العادي.

    `{command}` في نص الـ hook بتتبدل باسم الأمر اللي شغّل الحدث —
    عشان تقدر تكتب حاجة زي: `echo خلص {command}`
    """
    for template in commands_for(event):
        text = template
        for key, value in context.items():
            text = text.replace("{" + key + "}", str(value))
        try:
            engine.submit_hook(text)
        except Exception:  # noqa: BLE001 - hook مكسور مايوقفش المحرك
            continue
