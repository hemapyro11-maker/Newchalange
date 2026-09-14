"""
fetch_plugin.py — تحميل صفحة/رابط ويب وعرض نصه (شبيه بـ WebFetch في
Claude Code). GET بسيط عبر urllib (بدون أي مكتبة أو خدمة مدفوعة)، بيرجع
جزء من النص فقط عشان السجل مايتغرقش.
"""
from __future__ import annotations

import html
from html.parser import HTMLParser
import urllib.error
import urllib.parse
import urllib.request

import youtube_public

MAX_CHARS = 4000
TIMEOUT = 15


class _VisibleTextParser(HTMLParser):
    """Extract readable page text while discarding executable/style content."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._hidden_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"script", "style", "noscript", "template", "svg"}:
            self._hidden_depth += 1

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style", "noscript", "template", "svg"}:
            self._hidden_depth = max(0, self._hidden_depth - 1)

    def handle_data(self, data):
        if not self._hidden_depth and data.strip():
            self._parts.append(data)

    def text(self) -> str:
        return "\n".join(" ".join(part.split()) for part in self._parts if part.strip())


def _youtube_summary(url: str) -> str:
    try:
        info = youtube_public.inspect_url(url)
    except youtube_public.PublicYouTubeError as exc:
        return f"❌ YouTube could not be read: {exc}"
    if info.get("kind") == "channel":
        lines = [
            f"📺 {info.get('title') or 'YouTube channel'}",
            f"Channel: {info.get('url') or url}",
            f"Subscribers: {info.get('subscribers') if info.get('subscribers') is not None else '?'}",
            f"Videos: {info.get('video_count') if info.get('video_count') is not None else '?'}",
        ]
        if info.get("description"):
            lines.append(f"Description: {info['description']}")
        for video in (info.get("videos") or [])[:10]:
            lines.append(f"• {video.get('title') or '?'} — {video.get('views', '?')} views — {video.get('url') or ''}")
        return "\n".join(lines)
    return "\n".join(filter(None, [
        f"🎬 {info.get('title') or 'YouTube video'}",
        f"Channel: {info.get('channel') or '?'}",
        f"Views: {info.get('views') if info.get('views') is not None else '?'}",
        f"Duration: {info.get('duration') if info.get('duration') is not None else '?'} seconds",
        f"URL: {info.get('url') or url}",
        f"Description: {info.get('description')}" if info.get("description") else "",
    ]))


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
        return "❌ fetch only supports http and https"
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}:
        return _youtube_summary(url)
    req = urllib.request.Request(url, headers={"User-Agent": "SmartAssistant/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read(200_000)
    except urllib.error.HTTPError as e:
        return f"❌ HTTP {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return f"❌ could not reach that URL: {e.reason}"
    except Exception as e:
        return f"❌ error: {e}"

    text = raw.decode("utf-8", errors="replace")
    if "text/html" in content_type.lower() or "<html" in text[:500].lower():
        parser = _VisibleTextParser()
        try:
            parser.feed(text)
            text = html.unescape(parser.text())
        except Exception:
            # A malformed page must still return something safe and readable.
            text = ""
        if not text.strip():
            return f"📄 {url}  [{content_type}]\n\n(no readable page text)"
    truncated = text[:MAX_CHARS]
    suffix = "\n... (truncated)" if len(text) > MAX_CHARS else ""
    return f"📄 {url}  [{content_type}]\n\n{truncated}{suffix}"


def register(engine):
    engine.registry.register("fetch", _cmd_fetch, "fetch <url> — read a web page as clean visible text; YouTube links return structured video/channel data")
