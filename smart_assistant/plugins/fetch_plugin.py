"""
fetch_plugin.py — تحميل صفحة/رابط ويب وعرض نصه (شبيه بـ WebFetch في
Claude Code). GET بسيط عبر urllib (بدون أي مكتبة أو خدمة مدفوعة)، بيرجع
جزء من النص فقط عشان السجل مايتغرقش.
"""
from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request

MAX_CHARS = 4000
TIMEOUT = 15


def _cmd_fetch(ctx) -> str:
    if not ctx.args:
        return "usage: fetch <url>"
    url = ctx.args[0]
    if "://" not in url:
        # مفيش scheme خالص (زي "example.com" أو "localhost:8080/x") — نفترض https
        url = "https://" + url
    elif urllib.parse.urlsplit(url).scheme not in ("http", "https"):
        # نمنع عمداً أي scheme غير http/https (زي file:// أو ftp://) — أداة
        # "تحميل صفحة ويب" ميفترضش تقرأ ملفات محلية أو بروتوكولات تانية.
        return "❌ fetch بيدعم http/https بس"
    req = urllib.request.Request(url, headers={"User-Agent": "SmartAssistant/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read(200_000)
    except urllib.error.HTTPError as e:
        return f"❌ HTTP {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return f"❌ تعذر الوصول للرابط: {e.reason}"
    except Exception as e:
        return f"❌ خطأ: {e}"

    text = raw.decode("utf-8", errors="replace")
    truncated = text[:MAX_CHARS]
    suffix = "\n... (مقصوص)" if len(text) > MAX_CHARS else ""
    return f"📄 {url}  [{content_type}]\n\n{truncated}{suffix}"


def register(engine):
    engine.registry.register("fetch", _cmd_fetch, "fetch <url> — تحميل صفحة ويب وعرض نصها")
