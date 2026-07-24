"""
update_plugin.py — تحقق آمن من وجود إصدار أحدث (مجاني، عبر GitHub raw
content). بيبلّغ المستخدم برابط التحديث بس — مبيحمّلش أو يستبدل ملف الـ
exe الشغال تلقائياً، عشان استبدال البرنامج وهو شغال عملية خطرة/صعب
التراجع عنها ولازم تكون بقرار المستخدم.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

VERSION_URL = (
    "https://raw.githubusercontent.com/hemapyro11-maker/Newchalange/"
    "claude/project-guidelines-architecture-dcn5vq/smart_assistant/version.json"
)


def _cmd_check_update(ctx) -> str:
    try:
        from version import __version__ as current
    except ImportError:
        current = "unknown"

    try:
        with urllib.request.urlopen(VERSION_URL, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return f"⚠  ملف الإصدار مش موجود على السيرفر بعد (HTTP {e.code})"
    except (urllib.error.URLError, TimeoutError):
        return "⚠  تعذر الاتصال بالسيرفر للتحقق من التحديثات (تأكد من الإنترنت)"
    except Exception as e:
        return f"❌ خطأ أثناء التحقق من التحديث: {e}"

    latest = data.get("version", "unknown")
    notes = data.get("notes", "")
    if latest != current:
        return (
            f"🆕 فيه إصدار أحدث: {latest} (الحالي: {current})\n{notes}\n"
            f"حمّله يدوياً من: {data.get('url', '')}"
        )
    return f"✅ إنت على آخر إصدار ({current})"


def register(engine):
    engine.registry.register(
        "check_update", _cmd_check_update,
        "يتحقق من وجود إصدار أحدث للتطبيق (بدون تحديث تلقائي)",
    )
