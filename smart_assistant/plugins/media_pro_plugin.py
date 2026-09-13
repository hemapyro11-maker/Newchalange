"""Production video presets, measured audio mastering, and media diagnostics."""
from __future__ import annotations

import json
import pathlib
import re
import tempfile

import media_runtime as mr

_PROFILES = {
    "web": ["-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"],
    "youtube": ["-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
                "-profile:v", "high", "-c:a", "aac", "-b:a", "320k", "-movflags", "+faststart"],
    "preview": ["-c:v", "libx264", "-preset", "veryfast", "-crf", "25", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart"],
}


def _error(result):
    return (result.stderr or result.stdout or "unknown error").strip()[-1200:]


def _output(path, kind=None):
    if not mr.valid_output(path):
        return False, "the command finished but produced no usable output file"
    if kind and mr.has_stream(path, kind) is False:
        return False, f"the output has no {kind} stream"
    return True, ""


def _same_file(src, dst):
    try:
        return src.resolve() == dst.resolve()
    except OSError:
        return False


def _cmd_media_doctor(ctx):
    ffmpeg, ffprobe, ffplay = (mr.binary(n) for n in ("ffmpeg", "ffprobe", "ffplay"))
    lines = ["Media readiness:", f"  {'✅' if ffmpeg else '❌'} FFmpeg encoder",
             f"  {'✅' if ffprobe else '⚠️'} FFprobe output verification",
             f"  {'✅' if ffplay else '⚠️'} FFplay audio preview"]
    if not ffmpeg:
        lines.append("  Install imageio-ffmpeg or set NEZUKO_FFMPEG to an FFmpeg executable.")
        return "\n".join(lines)
    capabilities = mr.run(["ffmpeg", "-hide_banner", "-filters"], 30)
    filters = capabilities.stdout + capabilities.stderr
    required_filters = ("loudnorm", "afftdn", "subtitles", "chromakey")
    missing_filters = [name for name in required_filters if name not in filters]
    lines.append(
        f"  {'✅' if not missing_filters else '⚠️'} Production filters"
        + ("" if not missing_filters else f" (missing: {', '.join(missing_filters)})")
    )
    try:
        with tempfile.TemporaryDirectory(prefix="nezuko_media_check_") as folder:
            out = pathlib.Path(folder) / "check.mp4"
            result = mr.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                             "-f", "lavfi", "-i", "color=c=black:s=64x64:d=0.15:r=10",
                             "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                             "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                             "-c:a", "aac", str(out)], 30)
            ok = result.returncode == 0 and mr.valid_output(out)
        lines.append(f"  {'✅' if ok else '❌'} Real H.264 + AAC encode")
        if not ok:
            lines.append("  " + _error(result))
    except Exception as exc:
        lines.append(f"  ❌ Real encode failed: {exc}")
    for module, label in (("faster_whisper", "Arabic/English transcription"),
                          ("TTS", "XTTS voice cloning"), ("demucs", "stem separation")):
        try:
            __import__(module)
            available = True
        except (ImportError, OSError):
            available = False
        lines.append(f"  {'✅' if available else '⬜'} {label}")
    lines.append("✅ means tested/importable here; ⬜ means an optional dependency is missing.")
    return "\n".join(lines)


def _cmd_encode_video(ctx):
    if len(ctx.args) < 2:
        return "usage: encode_video <input> <output.mp4> [profile=web|youtube|preview]"
    src, dst = pathlib.Path(ctx.args[0]), pathlib.Path(ctx.args[1])
    profile = ctx.args[2].removeprefix("profile=") if len(ctx.args) > 2 else "web"
    if not src.is_file():
        return f"❌ file not found: {src}"
    if _same_file(src, dst):
        return "❌ input and output must be different files"
    if profile not in _PROFILES:
        return "❌ profile must be web, youtube, or preview"
    if mr.binary("ffmpeg") is None:
        return "❌ FFmpeg is unavailable — run media_doctor"
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = mr.run(["ffmpeg", "-hide_banner", "-y", "-i", str(src),
                         "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                         *_PROFILES[profile], str(dst)], 3600)
    except Exception as exc:
        return f"❌ encode failed: {exc}"
    if result.returncode:
        return f"❌ encode failed:\n{_error(result)}"
    ok, error = _output(dst, "video")
    return f"✅ encoded {profile} video at {dst}" if ok else f"❌ encode failed: {error}"


def _cmd_create_video(ctx):
    if len(ctx.args) < 2:
        return "usage: create_video <image> <output.mp4> [duration=5] [audio=path]"
    image, dst = pathlib.Path(ctx.args[0]), pathlib.Path(ctx.args[1])
    if not image.is_file():
        return f"❌ image not found: {image}"
    if _same_file(image, dst):
        return "❌ image and output must be different files"
    duration = 5.0
    audio = None
    for value in ctx.args[2:]:
        if value.startswith("duration="):
            try:
                duration = float(value.split("=", 1)[1])
            except ValueError:
                return "❌ duration must be a number"
        elif value.startswith("audio="):
            audio = pathlib.Path(value.split("=", 1)[1])
        else:
            return "❌ optional values must use duration=seconds or audio=path"
    if not 0.5 <= duration <= 3600:
        return "❌ duration must be between 0.5 and 3600 seconds"
    if audio is not None and not audio.is_file():
        return f"❌ audio file not found: {audio}"
    if mr.binary("ffmpeg") is None:
        return "❌ FFmpeg is unavailable — run media_doctor"
    dst.parent.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-hide_banner", "-y", "-loop", "1", "-framerate", "30",
               "-i", str(image)]
    if audio is not None:
        command += ["-i", str(audio)]
    command += ["-t", str(duration), "-vf",
                "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p",
                "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                "-movflags", "+faststart"]
    if audio is not None:
        command += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
    command.append(str(dst))
    try:
        result = mr.run(command, min(7200, max(120, int(duration * 4))))
    except Exception as exc:
        return f"❌ video creation failed: {exc}"
    if result.returncode:
        return f"❌ video creation failed:\n{_error(result)}"
    ok, error = _output(dst, "video")
    return f"✅ created H.264 video at {dst}" if ok else f"❌ video creation failed: {error}"


def _loudnorm_json(stderr):
    matches = re.findall(r"\{[^{]*\"input_i\".*?\}", stderr, re.DOTALL)
    if not matches:
        return None
    try:
        return json.loads(matches[-1])
    except json.JSONDecodeError:
        return None


def _cmd_master_audio_pro(ctx):
    if len(ctx.args) < 2:
        return "usage: master_audio_pro <input> <output> [target_lufs=-16]"
    src, dst = pathlib.Path(ctx.args[0]), pathlib.Path(ctx.args[1])
    if not src.is_file():
        return f"❌ file not found: {src}"
    if _same_file(src, dst):
        return "❌ input and output must be different files"
    try:
        target = float(ctx.args[2]) if len(ctx.args) > 2 else -16.0
    except ValueError:
        return "❌ target_lufs must be a number"
    if not -40 <= target <= -5:
        return "❌ target_lufs must be between -40 and -5"
    if mr.binary("ffmpeg") is None:
        return "❌ FFmpeg is unavailable — run media_doctor"
    try:
        first = mr.run(["ffmpeg", "-hide_banner", "-i", str(src), "-af",
                        f"loudnorm=I={target}:TP=-1.5:LRA=11:print_format=json",
                        "-f", "null", "-"], 1800)
        measured = _loudnorm_json(first.stderr)
        if first.returncode or not measured:
            return f"❌ loudness analysis failed:\n{_error(first)}"
        filt = (f"loudnorm=I={target}:TP=-1.5:LRA=11:"
                f"measured_I={measured['input_i']}:measured_TP={measured['input_tp']}:"
                f"measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}:"
                f"offset={measured['target_offset']}:linear=true:print_format=summary")
        dst.parent.mkdir(parents=True, exist_ok=True)
        second = mr.run(["ffmpeg", "-hide_banner", "-y", "-i", str(src), "-af", filt, str(dst)], 1800)
    except Exception as exc:
        return f"❌ mastering failed: {exc}"
    if second.returncode:
        return f"❌ mastering failed:\n{_error(second)}"
    ok, error = _output(dst, "audio")
    return f"✅ two-pass loudness master ({target:g} LUFS, true peak -1.5 dBTP) at {dst}" if ok else f"❌ mastering failed: {error}"


def _cmd_prepare_voice_sample(ctx):
    if len(ctx.args) < 2:
        return "usage: prepare_voice_sample <input> <output.wav> [start=0] [duration=10]"
    src, dst = pathlib.Path(ctx.args[0]), pathlib.Path(ctx.args[1])
    if not src.is_file():
        return f"❌ file not found: {src}"
    if _same_file(src, dst):
        return "❌ input and output must be different files"
    try:
        start = max(0.0, float(ctx.args[2])) if len(ctx.args) > 2 else 0.0
        duration = float(ctx.args[3]) if len(ctx.args) > 3 else 10.0
    except ValueError:
        return "❌ start and duration must be numbers"
    if not 3 <= duration <= 30:
        return "❌ use a clean 3-30 second sample (6-12 seconds is usually best)"
    if mr.binary("ffmpeg") is None:
        return "❌ FFmpeg is unavailable — run media_doctor"
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = mr.run([
            "ffmpeg", "-hide_banner", "-y", "-ss", str(start), "-t", str(duration),
            "-i", str(src), "-vn", "-ac", "1", "-ar", "24000",
            "-af", "highpass=f=70,lowpass=f=11000,afftdn=nf=-25,loudnorm=I=-20:TP=-3:LRA=7",
            "-c:a", "pcm_s16le", str(dst),
        ], 600)
    except Exception as exc:
        return f"❌ sample preparation failed: {exc}"
    if result.returncode:
        return f"❌ sample preparation failed:\n{_error(result)}"
    ok, error = _output(dst, "audio")
    if not ok:
        return f"❌ sample preparation failed: {error}"
    return (f"✅ clean mono 24 kHz voice sample at {dst}\n"
            "Use a single consenting speaker, no music/reverb, then run clone_voice with this WAV.")


def register(engine):
    engine.registry.register("media_doctor", _cmd_media_doctor, "media_doctor — run a real media readiness check")
    engine.registry.register("encode_video", _cmd_encode_video, "encode_video <in> <out.mp4> [profile] — reliable H.264/AAC delivery encode")
    engine.registry.register("create_video", _cmd_create_video, "create_video <IMAGE> <out.mp4> [duration=5] [audio=VOICE.wav] — image first, MP4 second, optional audio only via audio=")
    engine.registry.register("master_audio_pro", _cmd_master_audio_pro, "master_audio_pro <in> <out> [lufs] — measured two-pass loudness mastering")
    engine.registry.register("prepare_voice_sample", _cmd_prepare_voice_sample, "prepare_voice_sample <in> <out.wav> [start] [duration] — clean a sample for XTTS")
