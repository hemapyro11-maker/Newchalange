import shutil
import subprocess

import pytest

import media_plugin as mm

requires_ffmpeg = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg/ffprobe not installed",
)


@pytest.fixture
def sample_clip(tmp_path):
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=10",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-shortest", str(clip), "-loglevel", "error"],
        check=True, capture_output=True,
    )
    return clip


def test_probe_missing_ffprobe_message_when_absent(make_ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(mm.shutil, "which", lambda name: None)
    result = mm._cmd_probe(make_ctx("probe", [str(tmp_path / "x.mp4")]))
    assert result.startswith("❌")


def test_convert_missing_input_file_fast_fails(make_ctx, tmp_path):
    result = mm._cmd_convert(make_ctx("convert", [str(tmp_path / "nope.mp4"), str(tmp_path / "out.avi")]))
    assert result.startswith("❌")
    assert "مش موجود" in result


@requires_ffmpeg
def test_probe_real_clip(make_ctx, sample_clip):
    result = mm._cmd_probe(make_ctx("probe", [str(sample_clip)]))
    assert "✅" in result
    assert "video" in result
    assert "audio" in result


@requires_ffmpeg
def test_probe_corrupt_file(make_ctx, tmp_path):
    corrupt = tmp_path / "corrupt.mp4"
    corrupt.write_text("not a real video file")
    result = mm._cmd_probe(make_ctx("probe", [str(corrupt)]))
    assert result.startswith("❌")


@requires_ffmpeg
def test_trim_produces_shorter_clip(make_ctx, sample_clip, tmp_path):
    out = tmp_path / "trimmed.mp4"
    result = mm._cmd_trim(make_ctx("trim", [str(sample_clip), "0", "1", str(out)]))
    assert result.startswith("✅")
    assert out.is_file()


@requires_ffmpeg
def test_extract_audio(make_ctx, sample_clip, tmp_path):
    out = tmp_path / "audio.mp3"
    result = mm._cmd_extract_audio(make_ctx("extract_audio", [str(sample_clip), str(out)]))
    assert result.startswith("✅")
    assert out.is_file()


@requires_ffmpeg
def test_thumbnail(make_ctx, sample_clip, tmp_path):
    out = tmp_path / "thumb.jpg"
    result = mm._cmd_thumbnail(make_ctx("thumbnail", [str(sample_clip), "1", str(out)]))
    assert result.startswith("✅")
    assert out.is_file()


@requires_ffmpeg
def test_overlay_text(make_ctx, sample_clip, tmp_path):
    out = tmp_path / "watermarked.mp4"
    result = mm._cmd_overlay_text(make_ctx("overlay_text", [str(sample_clip), "hello", str(out)]))
    assert result.startswith("✅")
    assert out.is_file()


@requires_ffmpeg
def test_concat_two_clips_gives_summed_duration(make_ctx, sample_clip, tmp_path):
    out = tmp_path / "joined.mp4"
    result = mm._cmd_concat(make_ctx("concat", [str(out), str(sample_clip), str(sample_clip)]))
    assert result.startswith("✅")
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1", str(out)],
        capture_output=True, text=True,
    )
    duration = float(probe.stdout.strip().split("=")[1])
    assert 3.5 < duration < 4.5  # ~2s + 2s


@requires_ffmpeg
def test_concat_handles_filename_with_single_quote(make_ctx, sample_clip, tmp_path):
    quoted_name = tmp_path / "it's a clip.mp4"
    shutil.copy(sample_clip, quoted_name)
    out = tmp_path / "joined2.mp4"
    result = mm._cmd_concat(make_ctx("concat", [str(out), str(sample_clip), str(quoted_name)]))
    assert result.startswith("✅")
    assert out.is_file() and out.stat().st_size > 0


@requires_ffmpeg
def test_merge_av_missing_files(make_ctx, tmp_path):
    result = mm._cmd_merge_av(make_ctx("merge_av", [str(tmp_path / "a.mp4"), str(tmp_path / "b.mp3"), str(tmp_path / "out.mp4")]))
    assert result.startswith("❌")
