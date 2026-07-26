"""
permissions.py — قايمة أوامر مسموح لها تتنفذ من غير ما تتسأل.

**المبدأ الأساسي مش بيتغير:** الافتراضي إن **مفيش أي حاجة بتتنفذ
تلقائي**. القايمة دي بتبدأ فاضية، وإنت اللي بتضيف فيها بنفسك — إما من
الإعدادات أو لما تأكّد أمر وتقول "متسأليش تاني على ده".

ليه الميزة دي موجودة أصلاً: لو بتشتغل على نفس النوع من المهام طول
اليوم (تفحص ملفات، تحوّل فيديوهات)، السؤال في كل مرة بيبقى ضوضاء مش
حماية. الحماية الحقيقية إنك تختار **إيه** اللي يعدي.

**أوامر ممنوع تتحط في القايمة نهائيًا** (`_NEVER`): الأوامر اللي
بتنفذ كود أو بتغيّر صلاحيات أو بتوصل لشبكة بمدخلات حرة. دي محتاجة
عين بشرية في كل مرة مهما كانت مريحة — والمنع هنا في الكود نفسه، مش
مجرد تحذير في الواجهة.
"""
from __future__ import annotations

import threading

import brain

_lock = threading.Lock()

# أوامر مينفعش تتسمح أبدًا مهما حصل. السبب لكل واحد:
#   run           — بينفذ أي أمر نظام؛ السماح بيه = السماح بكل حاجة
#   create_plugin — بيولّد كود وبيشغّله للتحقق
#   fix_plugin    — نفس السبب
#   approve_plugin— بينقل كود مولّد لتشغيل حي بصلاحيات كاملة
#   android_shell — نفس منطق run بس على الموبايل
#   db_query      — SQL حر (DROP/DELETE)
#   external_add  — بيسجّل برنامج خارجي كأمر دائم
_NEVER = frozenset({
    "run", "create_plugin", "fix_plugin", "approve_plugin",
    "android_shell", "db_query", "external_add", "quarantine_restore",
})


def never_allowed() -> frozenset[str]:
    return _NEVER


def allowed() -> set[str]:
    raw = brain.load_config().get("allowed_commands", [])
    return {str(x) for x in raw if isinstance(x, str)} - _NEVER


def is_allowed(command: str) -> bool:
    """الأمر ده ينفع يعدي من غير تأكيد؟"""
    return command.lower() in allowed()


def allow(command: str) -> tuple[bool, str]:
    """بيضيف أمر للقايمة. بيرجع (نجح، رسالة)."""
    name = command.lower().strip()
    if not name:
        return False, "empty name"
    if name in _NEVER:
        return False, (
            f"❌ {name} can never be allowed — it executes code or takes "
            "free-form input, so it needs your approval every time."
        )
    with _lock:
        cfg = brain.load_config()
        current = set(cfg.get("allowed_commands", []))
        if name in current:
            return True, f"{name} is already allowed"
        current.add(name)
        cfg["allowed_commands"] = sorted(current)
        brain.save_config(cfg)
    return True, f"✅ {name} will run without asking from now on"


def revoke(command: str) -> bool:
    name = command.lower().strip()
    with _lock:
        cfg = brain.load_config()
        current = set(cfg.get("allowed_commands", []))
        if name not in current:
            return False
        current.discard(name)
        cfg["allowed_commands"] = sorted(current)
        brain.save_config(cfg)
    return True


def revoke_all() -> int:
    with _lock:
        cfg = brain.load_config()
        n = len(cfg.get("allowed_commands", []))
        cfg["allowed_commands"] = []
        brain.save_config(cfg)
    return n
