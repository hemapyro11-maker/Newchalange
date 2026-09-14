"""Evidence-based video analysis and a persistent production learning profile."""
from __future__ import annotations

import json
import math
import pathlib
import re
import statistics
import sys
import tempfile
from datetime import datetime, timezone

import media_runtime
import youtube_public

_MAX_RECORDS = 100


def _data_dir() -> pathlib.Path:
    return pathlib.Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) \
        else pathlib.Path(__file__).resolve().parent.parent


def _profile_path() -> pathlib.Path:
    return _data_dir() / "video_learning.json"


def _load_profile() -> dict:
    try:
        data = json.loads(_profile_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"records": []}
    except (OSError, json.JSONDecodeError):
        return {"records": []}


def _save_record(record: dict) -> None:
    data = _load_profile()
    records = [r for r in data.get("records", []) if r.get("source") != record.get("source")]
    records.append(record)
    data["records"] = records[-_MAX_RECORDS:]
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    _profile_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _number(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_rate(value: str) -> float:
    try:
        a, b = str(value).split("/", 1)
        return float(a) / float(b) if float(b) else 0.0
    except (ValueError, ZeroDivisionError):
        return 0.0


def _technical_metrics(path: pathlib.Path) -> dict:
    data = media_runtime.probe(path) or {}
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {})
    fmt = data.get("format", {})
    duration = _number(fmt.get("duration") or video.get("duration"))
    width, height = int(video.get("width") or 0), int(video.get("height") or 0)
    fps = round(_parse_rate(video.get("avg_frame_rate", "0/1")), 2)
    video_codec = video.get("codec_name") or "?"
    audio_codec = audio.get("codec_name") or "none"
    bitrate = round(_number(fmt.get("bit_rate")) / 1000)
    # imageio-ffmpeg bundles ffmpeg but not always ffprobe. FFmpeg's input
    # report still exposes the core technical fields, so packaged builds do
    # not return zeroes merely because the optional companion exe is absent.
    if not data and media_runtime.binary("ffmpeg"):
        try:
            report = media_runtime.run(["ffmpeg", "-hide_banner", "-i", str(path)], 30).stderr
            dm = re.search(r"Duration:\s*(\d+):(\d+):([0-9.]+)", report)
            if dm:
                duration = int(dm.group(1)) * 3600 + int(dm.group(2)) * 60 + float(dm.group(3))
            vm = re.search(r"Video:\s*([^,\s]+).*?(\d{2,5})x(\d{2,5}).*?([0-9.]+)\s*fps", report)
            if vm:
                video_codec, width, height, fps = vm.group(1), int(vm.group(2)), int(vm.group(3)), float(vm.group(4))
            am = re.search(r"Audio:\s*([^,\s]+)", report)
            if am:
                audio_codec = am.group(1)
            bm = re.search(r"bitrate:\s*(\d+)\s*kb/s", report)
            if bm:
                bitrate = int(bm.group(1))
        except Exception:
            pass
    return {
        "duration": round(duration, 2), "width": width, "height": height,
        "fps": round(fps, 2), "video_codec": video_codec,
        "audio_codec": audio_codec, "bitrate_kbps": bitrate,
    }


def _creative_metrics(path: pathlib.Path, duration: float) -> dict:
    ffmpeg = media_runtime.binary("ffmpeg")
    if not ffmpeg:
        return {"scene_count": None, "avg_shot_seconds": None, "silence_ratio": None, "mean_volume_db": None}
    scene_count = None
    silence_total = 0.0
    mean_volume = None
    peak_volume = None
    try:
        scene = media_runtime.run([
            "ffmpeg", "-hide_banner", "-i", str(path), "-vf",
            "select='gt(scene,0.30)',showinfo", "-an", "-f", "null", "-",
        ], 180)
        scene_count = len(re.findall(r"pts_time:", scene.stderr)) + 1
    except Exception:
        pass
    try:
        audio = media_runtime.run([
            "ffmpeg", "-hide_banner", "-i", str(path), "-af",
            "silencedetect=noise=-35dB:d=0.4,volumedetect", "-vn", "-f", "null", "-",
        ], 180)
        silence_total = sum(_number(x) for x in re.findall(r"silence_duration:\s*([0-9.]+)", audio.stderr))
        volume_match = re.search(r"mean_volume:\s*(-?[0-9.]+) dB", audio.stderr)
        mean_volume = _number(volume_match.group(1)) if volume_match else None
        peak_match = re.search(r"max_volume:\s*(-?[0-9.]+) dB", audio.stderr)
        peak_volume = _number(peak_match.group(1)) if peak_match else None
    except Exception:
        pass
    return {
        "scene_count": scene_count,
        "avg_shot_seconds": round(duration / scene_count, 2) if scene_count and duration else None,
        "silence_ratio": round(min(1.0, silence_total / duration), 4) if duration else None,
        "mean_volume_db": mean_volume,
        "peak_volume_db": peak_volume,
    }


def _visual_metrics(path: pathlib.Path) -> dict:
    """Sample the actual frames for exposure, colour, sharpness, and motion."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return {}
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        return {}
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    sample_count = min(48, max(1, frame_count))
    positions = np.linspace(0, max(0, frame_count - 1), sample_count, dtype=int)
    brightness, contrast, saturation, sharpness, motion = [], [], [], [], []
    previous = None
    try:
        for pos in positions:
            capture.set(cv2.CAP_PROP_POS_FRAMES, int(pos))
            ok, frame = capture.read()
            if not ok:
                continue
            small = cv2.resize(frame, (320, 180), interpolation=cv2.INTER_AREA)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
            brightness.append(float(gray.mean()))
            contrast.append(float(gray.std()))
            saturation.append(float(hsv[:, :, 1].mean()))
            sharpness.append(float(cv2.Laplacian(gray, cv2.CV_64F).var()))
            if previous is not None:
                motion.append(float(cv2.absdiff(gray, previous).mean()))
            previous = gray
    finally:
        capture.release()
    if not brightness:
        return {}
    return {
        "sampled_frames": len(brightness),
        "brightness": round(statistics.mean(brightness), 1),
        "contrast": round(statistics.mean(contrast), 1),
        "saturation": round(statistics.mean(saturation), 1),
        "sharpness": round(statistics.mean(sharpness), 1),
        "visual_motion": round(statistics.mean(motion), 1) if motion else 0.0,
        "dark_frame_ratio": round(sum(x < 45 for x in brightness) / len(brightness), 3),
    }


def _read_vtt(folder: pathlib.Path) -> str:
    lines, previous = [], ""
    for path in sorted(folder.glob("*.vtt")):
        try:
            raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in raw_lines:
            clean = re.sub(r"<[^>]+>", "", line).strip()
            if not clean or "-->" in clean or clean.startswith(("WEBVTT", "Kind:", "Language:")) or clean.isdigit():
                continue
            clean = " ".join(clean.split())
            if clean != previous:
                lines.append(clean)
                previous = clean
        if lines:
            break
    return " ".join(lines)[:8000]


def _title_features(title: str) -> dict:
    words = title.split()
    return {
        "title_words": len(words), "title_chars": len(title),
        "has_question": "?" in title or "؟" in title,
        "has_number": bool(re.search(r"\d", title)),
        "has_emoji": bool(re.search(r"[^\x00-\x7F\u0600-\u06FF\s\w|!?.,:'\"-]", title)),
    }


def _recommend(metrics: dict, transcript: str) -> list[str]:
    tips = []
    shot = metrics.get("avg_shot_seconds")
    silence = metrics.get("silence_ratio")
    volume = metrics.get("mean_volume_db")
    peak = metrics.get("peak_volume_db")
    if shot is not None:
        tips.append(f"Visual pacing: one cut about every {shot:.1f}s; compare this with retention before copying the pace.")
    if silence is not None:
        tips.append(f"Detected silence: {silence * 100:.1f}% of runtime; keep intentional pauses and remove dead air.")
    if volume is not None:
        tips.append(f"Measured mean volume: {volume:.1f} dB; master consistently and verify final loudness before export.")
    if peak is not None and peak > -1:
        tips.append(f"Audio peaks reach {peak:.1f} dB; leave more headroom to reduce clipping risk after platform encoding.")
    if metrics.get("sampled_frames"):
        tips.append(
            f"Visual sample ({metrics['sampled_frames']} frames): brightness {metrics['brightness']}/255, "
            f"contrast {metrics['contrast']}, saturation {metrics['saturation']}, "
            f"motion {metrics['visual_motion']}."
        )
        if metrics.get("dark_frame_ratio", 0) > .25:
            tips.append("More than a quarter of sampled frames are dark; check subject visibility on phone screens.")
    if transcript:
        opening = " ".join(transcript.split()[:35])
        tips.append(f"Opening speech sample: {opening}")
    tips.append("Use public performance as a hypothesis, then confirm CTR and retention in YouTube Studio; views alone do not prove why a video won.")
    return tips


def _analyse_local(path: pathlib.Path) -> tuple[dict, str]:
    tech = _technical_metrics(path)
    creative = _creative_metrics(path, tech.get("duration", 0))
    visual = _visual_metrics(path)
    transcript = _read_vtt(path.parent)
    return {**tech, **creative, **visual}, transcript


def _cmd_youtube_video_analyze(ctx) -> str:
    if not ctx.args:
        return "usage: youtube_video_analyze <youtube_url_or_video_file> [learn=true|false]"
    source = ctx.args[0]
    learn = not any(a.lower() == "learn=false" for a in ctx.args[1:])
    is_url = source.startswith(("http://", "https://"))
    public = {}
    access_note = "full media analysis"
    try:
        if is_url:
            public = youtube_public.inspect_url(source)
            try:
                with tempfile.TemporaryDirectory(prefix="nezuko-video-lab-") as tmp:
                    video_path, _ = youtube_public.download_video(source, tmp, height=480)
                    metrics, transcript = _analyse_local(video_path)
            except youtube_public.PublicYouTubeError as exc:
                # Deleted, private, age/region restricted, or owner-blocked media
                # can still expose useful public metadata. Keep the workflow
                # moving while naming the evidence we could not inspect.
                metrics, transcript = {}, ""
                access_note = f"metadata only; YouTube did not provide the media stream ({exc})"
        else:
            video_path = pathlib.Path(source)
            if not video_path.is_file():
                return f"❌ video not found: {video_path}"
            metrics, transcript = _analyse_local(video_path)
    except youtube_public.PublicYouTubeError as exc:
        return f"❌ video could not be read: {exc}"
    except OSError as exc:
        return f"❌ video analysis failed: {exc}"

    title = public.get("title") or pathlib.Path(source).stem
    metrics.update(_title_features(title))
    record = {
        "source": public.get("url") or str(pathlib.Path(source).resolve()), "title": title,
        "views": public.get("views"), "likes": public.get("likes"),
        "comments": public.get("comments"), "upload_date": public.get("upload_date"),
        "channel": public.get("channel"), "metrics": metrics,
        "transcript_opening": " ".join(transcript.split()[:80]),
        "learned_at": datetime.now(timezone.utc).isoformat(),
    }
    if learn:
        try:
            _save_record(record)
        except OSError as exc:
            return f"❌ analysis succeeded but learning profile could not be saved: {exc}"

    lines = [
        f"🎞️ Video intelligence: {title}",
        f"Source: {record['source']}",
        f"Performance: {int(_number(record.get('views'))):,} views | {int(_number(record.get('likes'))):,} likes | {int(_number(record.get('comments'))):,} comments",
        f"Content access: {access_note}",
        f"Technical: {metrics.get('width') or '?'}x{metrics.get('height') or '?'} | {metrics.get('fps') or '?'} fps | {metrics.get('video_codec') or '?'} + {metrics.get('audio_codec') or '?'} | {metrics.get('duration') or '?'}s",
        f"Editing: {metrics.get('scene_count') if metrics.get('scene_count') is not None else '?'} scenes | average shot {metrics.get('avg_shot_seconds') if metrics.get('avg_shot_seconds') is not None else '?'}s | silence {metrics.get('silence_ratio') * 100 if metrics.get('silence_ratio') is not None else '?'}%",
        f"Visual sample: brightness {metrics.get('brightness', '?')}/255 | contrast {metrics.get('contrast', '?')} | saturation {metrics.get('saturation', '?')} | motion {metrics.get('visual_motion', '?')}",
        f"Learning: {'saved to the production profile' if learn else 'analysis only'}",
        "\nEvidence-based observations:",
        *[f"• {tip}" for tip in _recommend(metrics, transcript)],
        "\nNEXT: Use video_learning_brief with the new topic before creating the next script, voice track, thumbnail, and render.",
    ]
    return "\n".join(lines)


def _performance_score(record: dict) -> float:
    views = _number(record.get("views"))
    likes = _number(record.get("likes"))
    comments = _number(record.get("comments"))
    return views + likes * 20 + comments * 50


def _cmd_video_learning_profile(ctx) -> str:
    records = _load_profile().get("records", [])
    if not records:
        return "📚 No analysed videos yet. Run youtube_video_analyze <url> first."
    ranked = sorted(records, key=_performance_score, reverse=True)
    top = ranked[:max(1, min(10, len(ranked)))]
    durations = [_number(r.get("metrics", {}).get("duration")) for r in top if _number(r.get("metrics", {}).get("duration")) > 0]
    shots = [_number(r.get("metrics", {}).get("avg_shot_seconds")) for r in top if _number(r.get("metrics", {}).get("avg_shot_seconds")) > 0]
    silences = [_number(r.get("metrics", {}).get("silence_ratio")) for r in top if r.get("metrics", {}).get("silence_ratio") is not None]
    lines = [f"📚 Production learning profile: {len(records)} analysed video(s)", "Top evidence:"]
    lines += [f"• {r.get('title', '?')} — {int(_number(r.get('views'))):,} views" for r in top[:5]]
    if durations:
        lines.append(f"Learned duration center: {statistics.median(durations):.0f}s")
    if shots:
        lines.append(f"Learned edit pace: about {statistics.median(shots):.1f}s per shot")
    if silences:
        lines.append(f"Learned silence center: {statistics.median(silences) * 100:.1f}%")
    lines.append("These are correlations from the videos supplied, not guarantees. Validate the next upload with CTR and retention.")
    return "\n".join(lines)


def _cmd_video_learning_brief(ctx) -> str:
    if not ctx.args:
        return "usage: video_learning_brief <new_topic>"
    topic = " ".join(ctx.args)
    records = _load_profile().get("records", [])
    if not records:
        return f"📝 Brief for {topic}: no learned video evidence yet. Analyze successful reference videos first."
    ranked = sorted(records, key=_performance_score, reverse=True)
    top = ranked[:max(1, math.ceil(len(ranked) / 3))]
    durations = [_number(r.get("metrics", {}).get("duration")) for r in top if _number(r.get("metrics", {}).get("duration"))]
    shots = [_number(r.get("metrics", {}).get("avg_shot_seconds")) for r in top if _number(r.get("metrics", {}).get("avg_shot_seconds"))]
    title_words = [_number(r.get("metrics", {}).get("title_words")) for r in top if _number(r.get("metrics", {}).get("title_words"))]
    target_duration = round(statistics.median(durations)) if durations else 60
    lines = [
        f"📝 Learned production brief: {topic}",
        f"Evidence base: strongest {len(top)} of {len(records)} analysed videos",
        f"Target duration: about {target_duration}s",
        f"Target edit pace: one visual change every {statistics.median(shots):.1f}s" if shots else "Target edit pace: establish with a reference analysis",
        f"Title length target: about {round(statistics.median(title_words))} words" if title_words else "Title: concise, specific, and audience-focused",
        "Structure: show the promise in the opening seconds, deliver the story/value without dead air, then end with one clear next action.",
        "Audio: natural voice, stable level, clean pauses, and a final loudness check.",
        "Originality: learn pacing and structure while writing new wording and visuals.",
        "\nNEXT: Create the script and assets from this brief, render the video, then analyse the finished file and compare its YouTube Studio CTR/retention after publishing.",
    ]
    return "\n".join(lines)


def _cmd_channel_view_growth_lab(ctx) -> str:
    if not ctx.args:
        return "usage: channel_view_growth_lab <channel_name_or_url> [max=15]"
    maximum, parts = 15, []
    for arg in ctx.args:
        if arg.startswith("max="):
            try:
                maximum = max(2, min(25, int(arg[4:])))
            except ValueError:
                return "❌ max must be a number"
        else:
            parts.append(arg)
    identifier = " ".join(parts)
    try:
        info = youtube_public.channel_info(identifier, maximum)
    except youtube_public.PublicYouTubeError as exc:
        return f"❌ channel lab failed: {exc}"
    videos = [v for v in info.get("videos", []) if v.get("views") is not None]
    if not videos:
        return f"📊 {info.get('title') or identifier}: no public view data was returned"
    median_views = statistics.median([_number(v.get("views")) for v in videos]) or 1
    ranked = sorted(videos, key=lambda v: _number(v.get("views")), reverse=True)
    lines = [f"🚀 Channel view-growth lab: {info.get('title') or identifier}", f"Analysed {len(videos)} public uploads | median {median_views:,.0f} views", "\nView outliers:"]
    for i, video in enumerate(ranked[:5], 1):
        outlier = _number(video.get("views")) / median_views
        lines.append(f"{i}. {video.get('title')} — {int(_number(video.get('views'))):,} views ({outlier:.2f}× channel median) — {video.get('url')}")
    lines.append("\nNEXT: Run youtube_video_analyze on the strongest outliers above to learn their real speech, scene pace, silence, and audio pattern; then use video_learning_brief. Do not assume the title alone caused the views.")
    return "\n".join(lines)


def register(engine):
    engine.registry.register("youtube_video_analyze", _cmd_youtube_video_analyze,
                             "youtube_video_analyze <youtube_url_or_file> [learn=true|false] — watch and measure the actual video, speech, scenes, pacing, silence, audio, metadata, then learn reusable production patterns")
    engine.registry.register("channel_view_growth_lab", _cmd_channel_view_growth_lab,
                             "channel_view_growth_lab <channel_name_or_url> [max=15] — rank a channel's view outliers, then analyze the winning videos themselves")
    engine.registry.register("video_learning_profile", _cmd_video_learning_profile,
                             "video_learning_profile — show evidence learned from analysed videos and audio")
    engine.registry.register("video_learning_brief", _cmd_video_learning_brief,
                             "video_learning_brief <new_topic> — turn learned high-performing production patterns into an original video brief")
