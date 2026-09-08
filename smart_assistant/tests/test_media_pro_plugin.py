import pathlib
from types import SimpleNamespace

import media_pro_plugin as mp
import media_runtime as mr


def _ctx(args):
    return SimpleNamespace(args=[str(a) for a in args])


def _make_source(path):
    result = mr.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=1:size=162x122:rate=12",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
        "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", str(path),
    ], 30)
    assert result.returncode == 0, result.stderr


def test_media_doctor_runs_real_encode():
    result = mp._cmd_media_doctor(_ctx([]))
    assert "✅ Real H.264 + AAC encode" in result


def test_encode_profile_produces_real_output(tmp_path):
    source, output = tmp_path / "source.mp4", tmp_path / "delivery.mp4"
    _make_source(source)
    result = mp._cmd_encode_video(_ctx([source, output, "preview"]))
    assert result.startswith("✅")
    assert mr.valid_output(output, minimum_bytes=500)


def test_create_video_from_image_and_audio(tmp_path):
    image, audio, output = tmp_path / "cover.png", tmp_path / "music.wav", tmp_path / "video.mp4"
    made_image = mr.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                         "-i", "color=c=navy:s=320x180", "-frames:v", "1", str(image)], 30)
    made_audio = mr.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                         "-i", "sine=frequency=440:duration=1", str(audio)], 30)
    assert made_image.returncode == made_audio.returncode == 0
    result = mp._cmd_create_video(_ctx([image, output, "duration=1", f"audio={audio}"]))
    assert result.startswith("✅")
    assert mr.valid_output(output, minimum_bytes=500)


def test_two_pass_master_produces_audio(tmp_path):
    source, output = tmp_path / "source.wav", tmp_path / "master.wav"
    made = mr.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                   "-i", "sine=frequency=440:duration=2:sample_rate=48000", str(source)], 30)
    assert made.returncode == 0
    result = mp._cmd_master_audio_pro(_ctx([source, output, "-16"]))
    assert result.startswith("✅ two-pass")
    assert mr.valid_output(output, minimum_bytes=1000)


def test_prepare_voice_sample_creates_mono_24k_wav(tmp_path):
    source, output = tmp_path / "source.wav", tmp_path / "voice.wav"
    made = mr.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                   "-i", "sine=frequency=300:duration=4:sample_rate=48000", str(source)], 30)
    assert made.returncode == 0
    result = mp._cmd_prepare_voice_sample(_ctx([source, output, "0", "3"]))
    assert result.startswith("✅")
    assert mr.valid_output(output, minimum_bytes=1000)


def test_never_overwrites_input(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    assert "different" in mp._cmd_encode_video(_ctx([source, source]))
    assert source.read_bytes() == b"source"
