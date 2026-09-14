"""Public YouTube discovery through yt-dlp, with no Data API key required."""
from __future__ import annotations

import html
import pathlib
import re
from typing import Any


class PublicYouTubeError(RuntimeError):
    pass


def _ydl():
    try:
        from yt_dlp import YoutubeDL
    except ImportError as exc:
        raise PublicYouTubeError("YouTube reader is not installed in this build") from exc
    return YoutubeDL({
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
        "socket_timeout": 20,
        "retries": 1,
    })


def clean(value: Any, limit: int = 500) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    text = " ".join(text.split())
    return text[:limit]


def search_videos(query: str, max_results: int = 10) -> list[dict]:
    try:
        with _ydl() as ydl:
            info = ydl.extract_info(f"ytsearch{max_results}:{query}", download=False)
    except Exception as exc:
        raise PublicYouTubeError(clean(exc, 240)) from exc
    rows = []
    for item in (info or {}).get("entries") or []:
        if not item:
            continue
        rows.append({
            "id": clean(item.get("id"), 32),
            "title": clean(item.get("title"), 240),
            "url": clean(item.get("url") or item.get("webpage_url"), 500),
            "channel": clean(item.get("channel") or item.get("uploader"), 160),
            "channel_id": clean(item.get("channel_id"), 64),
            "channel_url": clean(item.get("channel_url"), 500),
            "views": item.get("view_count"),
            "duration": item.get("duration"),
            "timestamp": item.get("timestamp"),
        })
    return rows


def _channel_url(identifier: str) -> str:
    value = identifier.strip()
    if value.startswith(("https://", "http://")):
        if "/watch?" in value or "youtu.be/" in value:
            results = search_videos(value, 1)
            if results and results[0].get("channel_url"):
                return results[0]["channel_url"]
        return value.rstrip("/")
    if re.fullmatch(r"UC[\w-]{22}", value):
        return f"https://www.youtube.com/channel/{value}"
    if value.startswith("@"):
        return f"https://www.youtube.com/{value}"
    results = search_videos(value, 10)
    normalized = value.casefold().strip()
    exact = next((r for r in results if r.get("channel", "").casefold() == normalized), None)
    chosen = exact or (results[0] if results else None)
    if not chosen or not chosen.get("channel_url"):
        raise PublicYouTubeError(f"no public YouTube channel found for: {clean(value)}")
    return chosen["channel_url"]


def channel_info(identifier: str, max_videos: int = 15) -> dict:
    url = _channel_url(identifier)
    if not any(part in url for part in ("/videos", "/shorts", "/streams")):
        url = url.rstrip("/") + "/videos"
    try:
        with _ydl() as ydl:
            ydl.params["playlistend"] = max_videos
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        raise PublicYouTubeError(clean(exc, 240)) from exc
    if not info:
        raise PublicYouTubeError("YouTube returned no channel information")
    videos = []
    for item in info.get("entries") or []:
        if item:
            videos.append({
                "id": clean(item.get("id"), 32),
                "title": clean(item.get("title"), 240),
                "url": clean(item.get("url") or item.get("webpage_url"), 500),
                "views": item.get("view_count"),
                "duration": item.get("duration"),
                "timestamp": item.get("timestamp"),
            })
    return {
        "id": clean(info.get("channel_id") or info.get("id"), 64),
        "title": clean(info.get("channel") or info.get("uploader") or info.get("title"), 180),
        "handle": clean(info.get("uploader_id"), 100),
        "url": clean(info.get("channel_url") or url, 500),
        "description": clean(info.get("description"), 1200),
        "subscribers": info.get("channel_follower_count"),
        "video_count": info.get("playlist_count") or len(videos),
        "videos": videos,
    }


def inspect_url(url: str) -> dict:
    lower = url.lower()
    if "/channel/" in lower or "/@" in lower or lower.rstrip("/").endswith("/videos"):
        return {"kind": "channel", **channel_info(url)}
    try:
        from yt_dlp import YoutubeDL
        with YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True,
                        "socket_timeout": 20, "retries": 1}) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        raise PublicYouTubeError(clean(exc, 240)) from exc
    return {
        "kind": "video",
        "id": clean(info.get("id"), 32), "title": clean(info.get("title"), 240),
        "channel": clean(info.get("channel") or info.get("uploader"), 160),
        "channel_url": clean(info.get("channel_url"), 500),
        "description": clean(info.get("description"), 1200),
        "views": info.get("view_count"), "duration": info.get("duration"),
        "likes": info.get("like_count"), "comments": info.get("comment_count"),
        "upload_date": clean(info.get("upload_date"), 16),
        "categories": [clean(x, 80) for x in (info.get("categories") or [])[:8]],
        "tags": [clean(x, 80) for x in (info.get("tags") or [])[:20]],
        "url": clean(info.get("webpage_url") or url, 500),
    }


def download_video(url: str, output_dir: str | pathlib.Path, *, height: int = 480) -> tuple[pathlib.Path, dict]:
    """Download one public video at analysis quality into a caller-owned temp folder."""
    folder = pathlib.Path(output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    try:
        from yt_dlp import YoutubeDL
    except ImportError as exc:
        raise PublicYouTubeError("YouTube reader is not installed in this build") from exc
    options = {
        "quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True,
        "socket_timeout": 25, "retries": 2,
        "format": (
            f"bestvideo[height<={height}]+bestaudio/"
            f"bestvideo[height<={height}]/bestvideo+bestaudio/best"
        ),
        "merge_output_format": "mp4",
        "outtmpl": str(folder / "%(id)s.%(ext)s"),
        "max_filesize": 500 * 1024 * 1024,
    }
    try:
        import imageio_ffmpeg
        options["ffmpeg_location"] = imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, OSError, RuntimeError):
        pass
    try:
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as exc:
        raise PublicYouTubeError(clean(exc, 300)) from exc
    video_id = clean((info or {}).get("id"), 80)
    candidates = [
        p for p in folder.glob(f"{video_id}.*")
        if p.suffix.lower() not in {".vtt", ".srt", ".part", ".json"}
    ]
    if not candidates:
        raise PublicYouTubeError("the video download completed but no media file was found")
    # Captions are useful but optional. Fetch them separately so a caption
    # rate limit never turns a successful media download into a failed watch.
    subtitle_options = {
        "quiet": True, "no_warnings": True, "noprogress": True,
        "noplaylist": True, "skip_download": True, "ignoreerrors": True,
        "outtmpl": str(folder / "%(id)s.%(ext)s"),
        "writesubtitles": True, "writeautomaticsub": True,
        "subtitleslangs": ["ar", "en"], "subtitlesformat": "vtt",
    }
    try:
        with YoutubeDL(subtitle_options) as ydl:
            ydl.extract_info(url, download=True)
    except Exception:
        pass
    return max(candidates, key=lambda p: p.stat().st_size), (info or {})
