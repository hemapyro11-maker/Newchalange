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
        return f"⚠  no version file on the server yet (HTTP {e.code})"
    except (urllib.error.URLError, TimeoutError):
        return "⚠  could not reach the server to check for updates (check your internet)"
    except Exception as e:
        return f"❌ error while checking for an update: {e}"

    if not isinstance(data, dict):
        return "❌ the version file on the server is not in the expected shape"

    latest = data.get("version", "unknown")
    notes = data.get("notes", "")
    if latest != current:
        return (
            f"🆕 a newer version is out: {latest} (you have: {current})\n{notes}\n"
            f"Download it yourself from: {data.get('url', '')}"
        )
    return f"✅ you are on the latest version ({current})"


def register(engine):
    engine.registry.register(
        "check_update", _cmd_check_update,
        "check_update — see whether a newer version exists (never updates on its own)",
    )
