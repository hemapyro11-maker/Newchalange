"""
sessions.py — محادثات محفوظة تقدر ترجعلها بعدين.

قبل كده كانت محادثة نيزوكو في الذاكرة بس (`engine.chat_history`) —
تقفل البرنامج، تروح. ده الملف اللي بيخليها تفضل.

كل جلسة ملف JSON لوحده في `sessions/`. سبب إنها ملفات منفصلة مش ملف
واحد كبير: حفظ جلسة مش بيلمس باقي الجلسات، فلو الملف اتقطع وسط
الكتابة (قفل مفاجئ، بطارية خلصت) بتخسر الجلسة دي بس مش كل تاريخك.

العنوان بيتولّد من أول رسالة منك — مفيش نداء نموذج، فمفيش استهلاك حصة.
"""
from __future__ import annotations

import datetime
import json
import pathlib
import re
import secrets
import sys
import threading

_lock = threading.Lock()

MAX_SESSIONS = 100      # أقدم من كده بيتشال تلقائيًا
TITLE_MAX = 48


def _base_dir() -> pathlib.Path:
    if getattr(sys, "frozen", False):
        return pathlib.Path(sys.executable).resolve().parent
    return pathlib.Path(__file__).resolve().parent


def sessions_dir() -> pathlib.Path:
    d = _base_dir() / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def new_id() -> str:
    """معرّف جلسة فريد.

    الوقت لوحده مش كفاية: نداءين في نفس المللي ثانية كانوا بيدّوا نفس
    المعرّف، فجلسة تكتب فوق التانية وتضيع. اللاحقة العشوائية بتمنع ده.
    """
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
    return f"{stamp}-{secrets.token_hex(3)}"


def make_title(messages: list[dict]) -> str:
    """عنوان من أول رسالة للمستخدم. محليًا بالكامل — من غير نموذج."""
    first = next(
        (m.get("content", "") for m in messages if m.get("role") == "user"), ""
    )
    title = " ".join(first.split())
    if len(title) > TITLE_MAX:
        title = title[:TITLE_MAX].rstrip() + "…"
    return title or "محادثة من غير عنوان"


def _path(session_id: str) -> pathlib.Path:
    # اسم الملف بيتنضف من أي حاجة مش آمنة في المسارات — معرّف الجلسة
    # بيتولّد داخليًا، بس ممكن ييجي من ملف على القرص عدّله حد.
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id)[:80]
    return sessions_dir() / f"{safe}.json"


def save(session_id: str, messages: list[dict], *, title: str = "") -> None:
    """بيحفظ الجلسة. الرسايل الفاضية مبتتحفظش عشان مانملاش القايمة
    بجلسات فاضية كل ما المستخدم يفتح البرنامج ويقفله."""
    if not messages:
        return
    with _lock:
        path = _path(session_id)
        existing_created = ""
        try:
            existing_created = json.loads(path.read_text(encoding="utf-8")).get("created", "")
        except (OSError, json.JSONDecodeError):
            pass
        now = datetime.datetime.now().isoformat(timespec="seconds")
        data = {
            "id": session_id,
            "title": title or make_title(messages),
            "created": existing_created or now,
            "updated": now,
            "messages": messages,
        }
        try:
            # كتابة على ملف مؤقت وبعدين استبدال ذري — عشان لو البرنامج
            # اتقفل وسط الكتابة، الملف القديم يفضل سليم بدل ما يبقى نص
            # JSON مقطوع مينفعش يتقرا.
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            return
    _prune()


def load(session_id: str) -> list[dict] | None:
    try:
        data = json.loads(_path(session_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    messages = data.get("messages")
    return messages if isinstance(messages, list) else None


def meta(session_id: str) -> dict | None:
    try:
        data = json.loads(_path(session_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    data.pop("messages", None)
    return data


def list_all() -> list[dict]:
    """كل الجلسات، الأحدث الأول. الملفات المكسورة بتتجاهل بهدوء بدل
    ما تكسر القايمة كلها."""
    out = []
    for path in sessions_dir().glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict) or "id" not in data:
            continue
        msgs = data.get("messages") or []
        out.append({
            "id": data["id"],
            "title": data.get("title") or "—",
            "created": data.get("created", ""),
            "updated": data.get("updated", ""),
            "turns": sum(1 for m in msgs if m.get("role") == "user"),
        })
    out.sort(key=lambda s: s["updated"], reverse=True)
    return out


def delete(session_id: str) -> bool:
    try:
        _path(session_id).unlink()
        return True
    except OSError:
        return False


def delete_all() -> int:
    n = 0
    for path in sessions_dir().glob("*.json"):
        try:
            path.unlink()
            n += 1
        except OSError:
            pass
    return n


def _prune() -> None:
    """بيشيل أقدم الجلسات فوق الحد — عشان المجلد ميكبرش بلا نهاية."""
    items = list_all()
    for stale in items[MAX_SESSIONS:]:
        delete(stale["id"])


def relative_time(iso: str) -> str:
    """وقت مقروء بالعربي (`من ساعتين`) بدل تاريخ ISO خام."""
    try:
        then = datetime.datetime.fromisoformat(iso)
    except ValueError:
        return iso or "—"
    delta = datetime.datetime.now() - then
    secs = int(delta.total_seconds())
    if secs < 60:
        return "دلوقتي"
    if secs < 3600:
        return f"من {secs // 60} دقيقة"
    if secs < 86400:
        return f"من {secs // 3600} ساعة"
    if secs < 86400 * 30:
        return f"من {secs // 86400} يوم"
    return then.strftime("%Y-%m-%d")
