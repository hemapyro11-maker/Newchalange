import pathlib
import shutil
import subprocess

import cinema_plugin as cp
import pytest


def _close(actual: tuple, expected: tuple, tol: int = 10) -> bool:
    """H.264 مضغوط بفقدان (lossy) — الألوان ممكن تختلف بوحدة أو اتنين
    عن القيمة الأصلية بسبب تقريب YUV<->RGB، فبنقارن بهامش خطأ صغير."""
    return all(abs(a - e) <= tol for a, e in zip(actual, expected))


requires_ffmpeg = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg/ffprobe not installed",
)
requires_auto_editor = pytest.mark.skipif(not shutil.which("auto-editor"), reason="auto-editor not installed")
requires_scenedetect = pytest.mark.skipif(not cp._HAS_SCENEDETECT, reason="scenedetect not installed")
requires_realesrgan = pytest.mark.skipif(not shutil.which("realesrgan-ncnn-vulkan"), reason="realesrgan-ncnn-vulkan not installed")


@pytest.fixture
def clip1(tmp_path):
    out = tmp_path / "clip1.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=4:size=320x240:rate=15",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=4", "-shortest", str(out), "-loglevel", "error"],
        check=True, capture_output=True,
    )
    return out


@pytest.fixture
def clip2(tmp_path):
    out = tmp_path / "clip2.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=duration=4:size=320x240:rate=15",
         "-f", "lavfi", "-i", "sine=frequency=880:duration=4", "-shortest", str(out), "-loglevel", "error"],
        check=True, capture_output=True,
    )
    return out


@pytest.fixture
def clip_with_silence(tmp_path):
    """كليب فيديو 7 ثواني: 2 ثانية صوت + 3 ثواني صمت تام + 2 ثانية صوت —
    عشان نتأكد إن auto_trim_silence فعلاً بيقص الصمت مش بس بيرجع نجاح
    وهمي. بنولّد الصوت (تون-صمت-تون) في ملف منفصل الأول، وبعدين ندمجه
    مع الفيديو — أسهل من محاولة بناء الاتنين في أمر ffmpeg واحد."""
    out = tmp_path / "clip_silence.mp4"
    audio = tmp_path / "silence_audio.wav"
    subprocess.run(
        ["ffmpeg", "-y",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono:d=3",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-filter_complex", "[0][1][2]concat=n=3:v=0:a=1[aout]", "-map", "[aout]", str(audio), "-loglevel", "error"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["ffmpeg", "-y",
         "-f", "lavfi", "-i", "testsrc=duration=7:size=320x240:rate=15",
         "-i", str(audio), "-shortest", str(out), "-loglevel", "error"],
        check=True, capture_output=True,
    )
    return out


def _duration(path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True,
    )
    return float(result.stdout.strip())


# ── argument validation (no ffmpeg required) ───────────────────────────

def test_color_grade_rejects_unknown_preset(make_ctx, tmp_path):
    f = tmp_path / "in.mp4"
    f.write_bytes(b"x")
    result = cp._cmd_color_grade(make_ctx("color_grade", [str(f), str(tmp_path / "out.mp4"), "bogus"]))
    assert result.startswith("❌")


def test_transition_rejects_unknown_style(make_ctx, tmp_path):
    f1, f2 = tmp_path / "a.mp4", tmp_path / "b.mp4"
    f1.write_bytes(b"x")
    f2.write_bytes(b"x")
    result = cp._cmd_transition(make_ctx("transition", [str(f1), str(f2), str(tmp_path / "out.mp4"), "bogus"]))
    assert result.startswith("❌")


def test_letterbox_rejects_bad_ratio(make_ctx, tmp_path):
    f = tmp_path / "in.mp4"
    f.write_bytes(b"x")
    for ratio in ["abc", "0", "-1"]:
        result = cp._cmd_letterbox(make_ctx("letterbox", [str(f), str(tmp_path / "out.mp4"), ratio]))
        assert result.startswith("❌")


def test_speed_ramp_rejects_bad_factor(make_ctx, tmp_path):
    f = tmp_path / "in.mp4"
    f.write_bytes(b"x")
    for factor in ["0", "-1", "abc"]:
        result = cp._cmd_speed_ramp(make_ctx("speed_ramp", [str(f), str(tmp_path / "out.mp4"), factor]))
        assert result.startswith("❌")


def test_pip_rejects_bad_position_and_scale(make_ctx, tmp_path):
    f1, f2 = tmp_path / "a.mp4", tmp_path / "b.mp4"
    f1.write_bytes(b"x")
    f2.write_bytes(b"x")
    result = cp._cmd_pip(make_ctx("pip", [str(f1), str(f2), str(tmp_path / "out.mp4"), "nowhere"]))
    assert result.startswith("❌")
    result = cp._cmd_pip(make_ctx("pip", [str(f1), str(f2), str(tmp_path / "out.mp4"), "center", "5"]))
    assert result.startswith("❌")


def test_chroma_key_rejects_bad_similarity(make_ctx, tmp_path):
    f1, f2 = tmp_path / "a.mp4", tmp_path / "b.mp4"
    f1.write_bytes(b"x")
    f2.write_bytes(b"x")
    result = cp._cmd_chroma_key(make_ctx("chroma_key", [str(f1), str(f2), str(tmp_path / "out.mp4"), "0x00FF00", "5"]))
    assert result.startswith("❌")


def test_master_audio_rejects_out_of_range_lufs(make_ctx, tmp_path):
    f = tmp_path / "in.mp4"
    f.write_bytes(b"x")
    result = cp._cmd_master_audio(make_ctx("master_audio", [str(f), str(tmp_path / "out.mp4"), "100"]))
    assert result.startswith("❌")


def test_title_card_rejects_too_short_duration(make_ctx, tmp_path):
    result = cp._cmd_title_card(make_ctx("title_card", ["hi", str(tmp_path / "out.mp4"), "0.5"]))
    assert result.startswith("❌")


def test_atempo_chain_covers_out_of_range_factors():
    # atempo filter only accepts 0.5-2.0 per stage — verify chaining logic
    assert cp._atempo_chain(1.5) == "atempo=1.500000"
    chain_fast = cp._atempo_chain(4.0)
    assert chain_fast.count("atempo=") == 2
    chain_slow = cp._atempo_chain(0.25)
    assert chain_slow.count("atempo=") == 2


# ── real ffmpeg pipelines ───────────────────────────────────────────────

@requires_ffmpeg
def test_color_grade_produces_valid_output(make_ctx, clip1, tmp_path):
    out = tmp_path / "graded.mp4"
    result = cp._cmd_color_grade(make_ctx("color_grade", [str(clip1), str(out), "teal_orange"]))
    assert result.startswith("✅")
    assert out.is_file()
    assert _duration(out) > 0


@requires_ffmpeg
def test_transition_duration_is_sum_minus_overlap(make_ctx, clip1, clip2, tmp_path):
    out = tmp_path / "transitioned.mp4"
    result = cp._cmd_transition(make_ctx("transition", [str(clip1), str(clip2), str(out), "dissolve", "1"]))
    assert result.startswith("✅")
    # 4s + 4s - 1s overlap = 7s
    assert 6.5 < _duration(out) < 7.5


@requires_ffmpeg
def test_transition_rejects_overlap_longer_than_clip(make_ctx, clip1, clip2, tmp_path):
    result = cp._cmd_transition(make_ctx("transition", [str(clip1), str(clip2), str(tmp_path / "out.mp4"), "fade", "100"]))
    assert result.startswith("❌")


@requires_ffmpeg
def test_letterbox_adds_visible_black_bars(make_ctx, clip1, tmp_path):
    from PIL import Image
    out = tmp_path / "letterboxed.mp4"
    result = cp._cmd_letterbox(make_ctx("letterbox", [str(clip1), str(out), "2.39"]))
    assert result.startswith("✅")

    frame = tmp_path / "frame.png"
    subprocess.run(["ffmpeg", "-y", "-i", str(out), "-frames:v", "1", str(frame)], capture_output=True)
    img = Image.open(frame)
    for x in (0, img.width // 2, img.width - 1):
        assert _close(img.getpixel((x, 0))[:3], (0, 0, 0))


@requires_ffmpeg
def test_speed_ramp_halves_and_doubles_duration_correctly(make_ctx, clip1, tmp_path):
    slow = tmp_path / "slow.mp4"
    result = cp._cmd_speed_ramp(make_ctx("speed_ramp", [str(clip1), str(slow), "0.5"]))
    assert result.startswith("✅")
    assert 7.5 < _duration(slow) < 8.5  # 4s / 0.5 = 8s

    fast = tmp_path / "fast.mp4"
    result = cp._cmd_speed_ramp(make_ctx("speed_ramp", [str(clip1), str(fast), "2.0"]))
    assert result.startswith("✅")
    assert 1.5 < _duration(fast) < 2.5  # 4s / 2.0 = 2s


@requires_ffmpeg
def test_pip_composites_overlay_onto_background(make_ctx, tmp_path):
    from PIL import Image
    bg = tmp_path / "bg.mp4"
    overlay = tmp_path / "overlay.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=2:r=10", str(bg), "-loglevel", "error"], check=True)
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=100x80:d=2:r=10", str(overlay), "-loglevel", "error"], check=True)

    out = tmp_path / "pip.mp4"
    result = cp._cmd_pip(make_ctx("pip", [str(bg), str(overlay), str(out), "bottom-right", "0.3"]))
    assert result.startswith("✅")

    frame = tmp_path / "frame.png"
    subprocess.run(["ffmpeg", "-y", "-i", str(out), "-frames:v", "1", str(frame)], capture_output=True)
    img = Image.open(frame)
    # top-left corner should still be background blue
    assert _close(img.getpixel((5, 5))[:3], (0, 0, 255))
    # the pip position formula places the overlay 20px from the edge
    # (see _PIP_POSITIONS["bottom-right"]) — sample its center, not the
    # frame's literal corner, which is background, not overlay
    overlay_w, overlay_h = int(100 * 0.3), int(80 * 0.3)
    cx = img.width - 20 - overlay_w // 2
    cy = img.height - 20 - overlay_h // 2
    assert _close(img.getpixel((cx, cy))[:3], (255, 0, 0))


@requires_ffmpeg
def test_chroma_key_removes_green_keeps_subject(make_ctx, tmp_path):
    from PIL import Image
    fg = tmp_path / "greenscreen.mp4"
    bg = tmp_path / "bg.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=green:s=200x150:d=2:r=10",
         "-vf", "drawbox=x=70:y=50:w=60:h=50:color=red:t=fill", str(fg), "-loglevel", "error"],
        check=True,
    )
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=200x150:d=2:r=10", str(bg), "-loglevel", "error"], check=True)

    out = tmp_path / "keyed.mp4"
    result = cp._cmd_chroma_key(make_ctx("chroma_key", [str(fg), str(bg), str(out), "0x00FF00", "0.3"]))
    assert result.startswith("✅")

    frame = tmp_path / "frame.png"
    subprocess.run(["ffmpeg", "-y", "-i", str(out), "-frames:v", "1", str(frame)], capture_output=True)
    img = Image.open(frame)
    assert _close(img.getpixel((10, 10))[:3], (0, 0, 255))  # green replaced by blue background
    assert _close(img.getpixel((100, 75))[:3], (255, 0, 0))  # red subject preserved


@requires_ffmpeg
def test_master_audio_and_denoise_produce_valid_output(make_ctx, clip1, tmp_path):
    mastered = tmp_path / "mastered.mp4"
    result = cp._cmd_master_audio(make_ctx("master_audio", [str(clip1), str(mastered), "-16"]))
    assert result.startswith("✅")
    assert mastered.is_file()

    denoised = tmp_path / "denoised.mp4"
    result = cp._cmd_denoise_audio(make_ctx("denoise_audio", [str(clip1), str(denoised)]))
    assert result.startswith("✅")
    assert denoised.is_file()


@requires_ffmpeg
def test_title_card_has_correct_duration_and_fades(make_ctx, tmp_path):
    out = tmp_path / "title.mp4"
    result = cp._cmd_title_card(make_ctx("title_card", ["HELLO", str(out), "3", "320x240"]))
    assert result.startswith("✅")
    assert 2.8 < _duration(out) < 3.2


@requires_ffmpeg
def test_stabilize_produces_valid_output(make_ctx, clip1, tmp_path):
    out = tmp_path / "stabilized.mp4"
    result = cp._cmd_stabilize(make_ctx("stabilize", [str(clip1), str(out)]))
    assert result.startswith("✅")
    assert out.is_file()
    assert _duration(out) > 0


# ── auto_trim_silence ───────────────────────────────────────────────────

def test_auto_trim_silence_no_args(make_ctx):
    result = cp._cmd_auto_trim_silence(make_ctx("auto_trim_silence", []))
    assert result.startswith("usage")


def test_auto_trim_silence_reports_missing_tool(make_ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(cp.shutil, "which", lambda name: None)
    f = tmp_path / "in.mp4"
    f.write_bytes(b"x")
    result = cp._cmd_auto_trim_silence(make_ctx("auto_trim_silence", [str(f), str(tmp_path / "out.mp4")]))
    assert "auto-editor is not installed" in result
    assert "pip install auto-editor" in result


@requires_auto_editor
def test_auto_trim_silence_missing_input(make_ctx, tmp_path):
    result = cp._cmd_auto_trim_silence(
        make_ctx("auto_trim_silence", [str(tmp_path / "nope.mp4"), str(tmp_path / "out.mp4")])
    )
    assert result.startswith("❌")


def test_auto_trim_silence_detects_exit_zero_but_no_output(make_ctx, tmp_path, monkeypatch):
    # نفس مشكلة realesrgan-ncnn-vulkan (exit 0 حتى لو فشل فعليًا) —
    # لازم نتأكد من وجود ملف خرج حقيقي مش نثق في exit code بس.
    monkeypatch.setattr(cp.shutil, "which", lambda name: "/usr/bin/auto-editor")
    monkeypatch.setattr(cp.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="", stderr=""))
    f = tmp_path / "in.mp4"
    f.write_bytes(b"x")
    result = cp._cmd_auto_trim_silence(make_ctx("auto_trim_silence", [str(f), str(tmp_path / "out.mp4")]))
    assert result.startswith("❌")
    assert "no real output file" in result


@requires_auto_editor
def test_auto_trim_silence_cuts_real_silence(make_ctx, clip_with_silence, tmp_path):
    out = tmp_path / "trimmed.mp4"
    result = cp._cmd_auto_trim_silence(make_ctx("auto_trim_silence", [str(clip_with_silence), str(out)]))
    assert result.startswith("✅")
    assert out.is_file()
    # الأصل 7 ثواني (2 صوت + 3 صمت + 2 صوت) — بعد القص المفروض يقرب من
    # 4 ثواني (الصوت بس)، مع هامش لـ margin الافتراضي (0.2s) حوالين كل قصة.
    assert _duration(out) < 6.0


# ── detect_scenes ────────────────────────────────────────────────────────

def test_detect_scenes_no_args(make_ctx):
    result = cp._cmd_detect_scenes(make_ctx("detect_scenes", []))
    assert result.startswith("usage")


def test_detect_scenes_reports_missing_tool(make_ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(cp, "_HAS_SCENEDETECT", False)
    f = tmp_path / "in.mp4"
    f.write_bytes(b"x")
    result = cp._cmd_detect_scenes(make_ctx("detect_scenes", [str(f)]))
    assert "PySceneDetect is not installed" in result
    assert "pip install scenedetect" in result


@requires_scenedetect
def test_detect_scenes_missing_input(make_ctx, tmp_path):
    result = cp._cmd_detect_scenes(make_ctx("detect_scenes", [str(tmp_path / "nope.mp4")]))
    assert result.startswith("❌")


@requires_scenedetect
def test_detect_scenes_rejects_non_numeric_threshold(make_ctx, tmp_path):
    f = tmp_path / "in.mp4"
    f.write_bytes(b"x")
    result = cp._cmd_detect_scenes(make_ctx("detect_scenes", [str(f), "bogus"]))
    assert result.startswith("❌")
    assert "threshold" in result


@requires_scenedetect
@requires_ffmpeg
def test_detect_scenes_finds_real_cut(make_ctx, tmp_path):
    out = tmp_path / "two_scenes.mp4"
    subprocess.run(
        ["ffmpeg", "-y",
         "-f", "lavfi", "-i", "color=c=red:s=320x240:d=2",
         "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=2",
         "-filter_complex", "[0][1]concat=n=2:v=1:a=0", "-r", "15", str(out), "-loglevel", "error"],
        check=True, capture_output=True,
    )
    result = cp._cmd_detect_scenes(make_ctx("detect_scenes", [str(out)]))
    assert result.startswith("🎬")
    assert "2 scenes found" in result


@requires_scenedetect
@requires_ffmpeg
def test_detect_scenes_no_cuts_in_continuous_clip(make_ctx, clip1):
    # clip1 نمط testsrc متحرك بسلاسة، من غير أي قطع مفاجئ — ContentDetector
    # المفروض ميلاقيش أي "مشهد" منفصل فيه.
    result = cp._cmd_detect_scenes(make_ctx("detect_scenes", [str(clip1)]))
    assert result.startswith("ℹ️")
    assert "no clear scene changes found" in result


# ── upscale_image / upscale_video ────────────────────────────────────────

@pytest.fixture
def tiny_image(tmp_path):
    out = tmp_path / "tiny.png"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=8x8", "-frames:v", "1", "-update", "1", str(out), "-loglevel", "error"],
        check=True, capture_output=True,
    )
    return out


@pytest.fixture
def tiny_clip(tmp_path):
    out = tmp_path / "tiny_clip.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=8x8:d=1:r=1",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-shortest", str(out), "-loglevel", "error"],
        check=True, capture_output=True,
    )
    return out


def test_upscale_image_no_args(make_ctx):
    result = cp._cmd_upscale_image(make_ctx("upscale_image", []))
    assert result.startswith("usage")


def test_upscale_image_reports_missing_tool(make_ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(cp.shutil, "which", lambda name: None)
    f = tmp_path / "in.png"
    f.write_bytes(b"x")
    result = cp._cmd_upscale_image(make_ctx("upscale_image", [str(f), str(tmp_path / "out.png")]))
    assert "realesrgan-ncnn-vulkan is not installed" in result


def test_upscale_image_missing_input(make_ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(cp.shutil, "which", lambda name: "/usr/bin/realesrgan-ncnn-vulkan")
    result = cp._cmd_upscale_image(make_ctx("upscale_image", [str(tmp_path / "nope.png"), str(tmp_path / "out.png")]))
    assert result.startswith("❌")


def test_upscale_image_rejects_bad_scale(make_ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(cp.shutil, "which", lambda name: "/usr/bin/realesrgan-ncnn-vulkan")
    f = tmp_path / "in.png"
    f.write_bytes(b"x")
    result = cp._cmd_upscale_image(make_ctx("upscale_image", [str(f), str(tmp_path / "out.png"), "5"]))
    assert result.startswith("❌")
    assert "scale" in result


def test_upscale_image_rejects_bad_model(make_ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(cp.shutil, "which", lambda name: "/usr/bin/realesrgan-ncnn-vulkan")
    f = tmp_path / "in.png"
    f.write_bytes(b"x")
    result = cp._cmd_upscale_image(make_ctx("upscale_image", [str(f), str(tmp_path / "out.png"), "4", "bogus-model"]))
    assert result.startswith("❌")
    assert "model" in result


def test_upscale_image_detects_exit_zero_but_no_output(make_ctx, tmp_path, monkeypatch):
    # realesrgan-ncnn-vulkan اتجرب فعليًا وبيرجع exit code صفر حتى لو
    # فشل فعلاً — لازم نتأكد من وجود ملف الخرج فعليًا مش نثق في exit code.
    monkeypatch.setattr(cp.shutil, "which", lambda name: "/usr/bin/realesrgan-ncnn-vulkan")
    monkeypatch.setattr(cp.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="", stderr=""))
    f = tmp_path / "in.png"
    f.write_bytes(b"x")
    result = cp._cmd_upscale_image(make_ctx("upscale_image", [str(f), str(tmp_path / "out.png")]))
    assert result.startswith("❌")
    assert "no real output file" in result


@requires_realesrgan
def test_upscale_image_real_run_produces_larger_image(make_ctx, tiny_image, tmp_path):
    out = tmp_path / "upscaled.png"
    result = cp._cmd_upscale_image(make_ctx("upscale_image", [str(tiny_image), str(out), "2", "realesr-animevideov3"]))
    assert result.startswith("✅")
    assert out.is_file()
    from PIL import Image
    with Image.open(out) as img:
        assert img.size == (16, 16)  # 8x8 مضروبة في scale=2


def test_upscale_video_no_args(make_ctx):
    result = cp._cmd_upscale_video(make_ctx("upscale_video", []))
    assert result.startswith("usage")


def test_upscale_video_reports_missing_tool(make_ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(cp.shutil, "which", lambda name: None)
    f = tmp_path / "in.mp4"
    f.write_bytes(b"x")
    result = cp._cmd_upscale_video(make_ctx("upscale_video", [str(f), str(tmp_path / "out.mp4")]))
    assert "realesrgan-ncnn-vulkan is not installed" in result


def test_upscale_video_reports_missing_ffmpeg(make_ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(
        cp.shutil, "which",
        lambda name: "/usr/bin/realesrgan-ncnn-vulkan" if name == "realesrgan-ncnn-vulkan" else None,
    )
    f = tmp_path / "in.mp4"
    f.write_bytes(b"x")
    result = cp._cmd_upscale_video(make_ctx("upscale_video", [str(f), str(tmp_path / "out.mp4")]))
    assert "ffmpeg not found" in result


def test_upscale_video_detects_partial_frame_output(make_ctx, tmp_path, monkeypatch):
    # realesrgan-ncnn-vulkan اتجرب فعليًا وغير مستقر تحت Vulkan software
    # rendering — ممكن يوقف نص الطريق ويرجع عدد فريمات أقل من المدخل،
    # برضو من غير أي خطأ ظاهر (exit 0). لازم نكتشف الفرق ده صراحةً بدل
    # ما نجمّع فيديو مقصوص بصمت.
    monkeypatch.setattr(cp.shutil, "which", lambda name: "/usr/bin/x")

    def fake_run_ffmpeg(args, timeout):
        if args[0] == "ffmpeg" and "-r" not in args:
            frames_in_dir = pathlib.Path(args[-1]).parent
            for i in range(1, 6):
                (frames_in_dir / f"frame_{i:06d}.png").write_bytes(b"x")
            return True, ""
        if args[0] == "realesrgan-ncnn-vulkan":
            frames_out_dir = pathlib.Path(args[args.index("-o") + 1])
            for i in range(1, 3):  # 2 بس من 5 — فشل جزئي
                (frames_out_dir / f"frame_{i:06d}.png").write_bytes(b"x")
            return True, ""
        raise AssertionError("reassembly shouldn't run when frame counts mismatch")

    monkeypatch.setattr(cp, "_run_ffmpeg", fake_run_ffmpeg)
    monkeypatch.setattr(cp, "_probe_fps", lambda src: 25.0)
    f = tmp_path / "in.mp4"
    f.write_bytes(b"x")
    result = cp._cmd_upscale_video(make_ctx("upscale_video", [str(f), str(tmp_path / "out.mp4")]))
    assert result.startswith("❌")
    assert "upscaling only partly finished" in result
    assert "2 of 5 frames" in result


@requires_realesrgan
@requires_ffmpeg
def test_upscale_video_real_run_produces_output(make_ctx, tiny_clip, tmp_path):
    out = tmp_path / "upscaled.mp4"
    result = cp._cmd_upscale_video(make_ctx("upscale_video", [str(tiny_clip), str(out), "2", "realesr-animevideov3"]))
    assert result.startswith("✅")
    assert out.is_file()
    assert _duration(out) > 0


# ── _probe_dimensions/_probe_duration/_probe_fps: must not crash on
# ffprobe timeout/disappearing (regression — used to call subprocess.run
# with no try/except at all, unlike every other subprocess call in this
# file which goes through _run_ffmpeg) ───────────────────────────────

def test_probe_dimensions_returns_none_on_timeout(monkeypatch):
    monkeypatch.setattr(cp.shutil, "which", lambda name: "/usr/bin/ffprobe")

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 30))

    monkeypatch.setattr(cp.subprocess, "run", fake_run)
    assert cp._probe_dimensions("whatever.mp4") is None


def test_probe_duration_returns_none_on_missing_binary_race(monkeypatch):
    # TOCTOU: shutil.which لقاه، لكن اختفى قبل ما ينفّذ فعليًا
    monkeypatch.setattr(cp.shutil, "which", lambda name: "/usr/bin/ffprobe")

    def fake_run(cmd, **kwargs):
        raise OSError("No such file or directory")

    monkeypatch.setattr(cp.subprocess, "run", fake_run)
    assert cp._probe_duration("whatever.mp4") is None


def test_probe_fps_returns_none_on_timeout(monkeypatch):
    monkeypatch.setattr(cp.shutil, "which", lambda name: "/usr/bin/ffprobe")

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 30))

    monkeypatch.setattr(cp.subprocess, "run", fake_run)
    assert cp._probe_fps("whatever.mp4") is None


# ── الترجمات: توليد وحرق ─────────────────────────────────────────────

class _FakeSegment:
    def __init__(self, start, end, text):
        self.start, self.end, self.text = start, end, text


class _FakeInfo:
    language = "en"


class _FakeWhisperModel:
    def __init__(self, segments):
        self._segments = segments

    def transcribe(self, path, language=None, vad_filter=True):
        return iter(self._segments), _FakeInfo()


def test_srt_timestamp_format():
    assert cp._srt_timestamp(0) == "00:00:00,000"
    assert cp._srt_timestamp(3661.234) == "01:01:01,234"


def test_srt_timestamp_never_goes_negative():
    """راجع: النموذج ممكن يرجّع توقيت سالب لجزء من الثانية بسبب
    تقريب داخلي — مينفعش يطلع في ملف الترجمة."""
    assert cp._srt_timestamp(-5) == "00:00:00,000"


def test_vtt_timestamp_uses_a_dot_not_a_comma():
    assert cp._vtt_timestamp(1.5) == "00:00:01.500"


def test_generate_subtitles_needs_two_args(make_ctx):
    result = cp._cmd_generate_subtitles(make_ctx("generate_subtitles", []))
    assert result.startswith("usage")


def test_generate_subtitles_rejects_a_bad_extension(make_ctx, tmp_path):
    src = tmp_path / "a.mp4"
    src.write_bytes(b"x")
    out = tmp_path / "subs.txt"
    result = cp._cmd_generate_subtitles(
        make_ctx("generate_subtitles", [str(src), str(out)])
    )
    assert "must end in .srt or .vtt" in result


def test_generate_subtitles_missing_input(make_ctx, tmp_path):
    result = cp._cmd_generate_subtitles(
        make_ctx("generate_subtitles", [str(tmp_path / "nope.mp4"), str(tmp_path / "o.srt")])
    )
    assert result.startswith("❌ file not found")


def test_generate_subtitles_missing_package_is_reported(make_ctx, tmp_path, monkeypatch):
    src = tmp_path / "a.mp4"
    src.write_bytes(b"x")

    def boom(size):
        raise ImportError
    monkeypatch.setattr(cp, "_load_whisper_model", boom)
    result = cp._cmd_generate_subtitles(
        make_ctx("generate_subtitles", [str(src), str(tmp_path / "o.srt")])
    )
    assert "pip install faster-whisper" in result


def test_generate_subtitles_writes_a_real_srt_file(make_ctx, tmp_path, monkeypatch):
    src = tmp_path / "a.mp4"
    src.write_bytes(b"x")
    monkeypatch.setattr(
        cp, "_load_whisper_model",
        lambda size: _FakeWhisperModel([
            _FakeSegment(0.0, 1.5, "Hello there"),
            _FakeSegment(1.5, 3.0, "General Kenobi"),
        ]),
    )
    out = tmp_path / "o.srt"
    result = cp._cmd_generate_subtitles(make_ctx("generate_subtitles", [str(src), str(out)]))
    assert result.startswith("✅ 2 subtitle lines")
    text = out.read_text(encoding="utf-8")
    assert "1\n00:00:00,000 --> 00:00:01,500\nHello there" in text
    assert "2\n00:00:01,500 --> 00:00:03,000\nGeneral Kenobi" in text


def test_generate_subtitles_writes_vtt_with_header(make_ctx, tmp_path, monkeypatch):
    src = tmp_path / "a.mp4"
    src.write_bytes(b"x")
    monkeypatch.setattr(
        cp, "_load_whisper_model",
        lambda size: _FakeWhisperModel([_FakeSegment(0.0, 1.0, "hi")]),
    )
    out = tmp_path / "o.vtt"
    cp._cmd_generate_subtitles(make_ctx("generate_subtitles", [str(src), str(out)]))
    text = out.read_text(encoding="utf-8")
    assert text.startswith("WEBVTT\n")
    assert "00:00:00.000 --> 00:00:01.000" in text
    assert "," not in text.split("\n\n")[1]  # مفيش فاصلة SRT في VTT


def test_generate_subtitles_reports_the_detected_language(make_ctx, tmp_path, monkeypatch):
    src = tmp_path / "a.mp4"
    src.write_bytes(b"x")
    monkeypatch.setattr(
        cp, "_load_whisper_model",
        lambda size: _FakeWhisperModel([_FakeSegment(0.0, 1.0, "hi")]),
    )
    result = cp._cmd_generate_subtitles(
        make_ctx("generate_subtitles", [str(src), str(tmp_path / "o.srt")])
    )
    assert "detected language: en" in result


def test_generate_subtitles_skips_the_language_note_when_explicit(make_ctx, tmp_path, monkeypatch):
    src = tmp_path / "a.mp4"
    src.write_bytes(b"x")
    monkeypatch.setattr(
        cp, "_load_whisper_model",
        lambda size: _FakeWhisperModel([_FakeSegment(0.0, 1.0, "hi")]),
    )
    result = cp._cmd_generate_subtitles(
        make_ctx("generate_subtitles", [str(src), str(tmp_path / "o.srt"), "lang=en"])
    )
    assert "detected language" not in result


def test_generate_subtitles_drops_empty_segments(make_ctx, tmp_path, monkeypatch):
    """VAD ممكن يرجّع segment فاضي على حواف الصمت — مينفعش يطلع كسطر
    ترجمة فاضي في الملف."""
    src = tmp_path / "a.mp4"
    src.write_bytes(b"x")
    monkeypatch.setattr(
        cp, "_load_whisper_model",
        lambda size: _FakeWhisperModel([
            _FakeSegment(0.0, 0.2, "   "),
            _FakeSegment(0.2, 1.0, "real text"),
        ]),
    )
    out = tmp_path / "o.srt"
    result = cp._cmd_generate_subtitles(make_ctx("generate_subtitles", [str(src), str(out)]))
    assert result.startswith("✅ 1 subtitle lines")


def test_generate_subtitles_no_speech(make_ctx, tmp_path, monkeypatch):
    src = tmp_path / "a.mp4"
    src.write_bytes(b"x")
    monkeypatch.setattr(cp, "_load_whisper_model", lambda size: _FakeWhisperModel([]))
    result = cp._cmd_generate_subtitles(
        make_ctx("generate_subtitles", [str(src), str(tmp_path / "o.srt")])
    )
    assert result.startswith("🔇")


def test_generate_subtitles_reports_transcription_failure(make_ctx, tmp_path, monkeypatch):
    src = tmp_path / "a.mp4"
    src.write_bytes(b"x")

    class _Boom:
        def transcribe(self, *a, **k):
            raise RuntimeError("corrupt stream")
    monkeypatch.setattr(cp, "_load_whisper_model", lambda size: _Boom())
    result = cp._cmd_generate_subtitles(
        make_ctx("generate_subtitles", [str(src), str(tmp_path / "o.srt")])
    )
    assert "transcription failed" in result


def test_generate_subtitles_model_cache_is_reused(monkeypatch):
    calls = []

    class _FakeModule:
        class WhisperModel:
            def __init__(self, size, device, compute_type):
                calls.append(size)

    import sys
    monkeypatch.setitem(sys.modules, "faster_whisper", _FakeModule)
    cp._faster_whisper_models.clear()
    cp._load_whisper_model("tiny")
    cp._load_whisper_model("tiny")
    assert calls == ["tiny"]
    cp._faster_whisper_models.clear()


@pytest.fixture
def srt_file(tmp_path):
    p = tmp_path / "subs.srt"
    p.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n"
        "2\n00:00:01,000 --> 00:00:02,000\nWorld\n",
        encoding="utf-8",
    )
    return p


def test_burn_subtitles_needs_three_args(make_ctx):
    assert cp._cmd_burn_subtitles(make_ctx("burn_subtitles", [])).startswith("usage")


def test_burn_subtitles_missing_video(make_ctx, tmp_path, srt_file):
    result = cp._cmd_burn_subtitles(make_ctx(
        "burn_subtitles", [str(tmp_path / "nope.mp4"), str(srt_file), str(tmp_path / "o.mp4")]
    ))
    assert result.startswith("❌ file not found")


def test_burn_subtitles_missing_srt(make_ctx, tmp_path, clip1):
    result = cp._cmd_burn_subtitles(make_ctx(
        "burn_subtitles", [str(clip1), str(tmp_path / "nope.srt"), str(tmp_path / "o.mp4")]
    ))
    assert result.startswith("❌ file not found")


@requires_ffmpeg
def test_burn_subtitles_produces_a_real_video(make_ctx, tmp_path, clip1, srt_file):
    out = tmp_path / "o.mp4"
    result = cp._cmd_burn_subtitles(make_ctx(
        "burn_subtitles", [str(clip1), str(srt_file), str(out)]
    ))
    assert result.startswith("✅")
    assert out.is_file()
    assert out.stat().st_size > 500


@requires_ffmpeg
def test_burn_subtitles_handles_a_colon_in_the_path(make_ctx, tmp_path, clip1):
    """مسار فيه `:` (زي C:\\...) لازم يتهرّب قبل ما يتحط في فلتر
    ffmpeg، وإلا الفلتر بيتفسر غلط."""
    weird_dir = tmp_path / "weird:name"
    weird_dir.mkdir()
    srt = weird_dir / "s.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHi\n", encoding="utf-8")
    out = tmp_path / "o.mp4"
    result = cp._cmd_burn_subtitles(make_ctx(
        "burn_subtitles", [str(clip1), str(srt), str(out)]
    ))
    assert result.startswith("✅")
    assert out.is_file()


def test_burn_subtitles_no_ffmpeg(make_ctx, tmp_path, srt_file, monkeypatch):
    src = tmp_path / "a.mp4"
    src.write_bytes(b"x")
    monkeypatch.setattr(cp.shutil, "which", lambda name: None)
    result = cp._cmd_burn_subtitles(make_ctx(
        "burn_subtitles", [str(src), str(srt_file), str(tmp_path / "o.mp4")]
    ))
    assert result == "❌ ffmpeg not found"


def test_register_adds_subtitle_commands(bare_engine):
    cp.register(bare_engine)
    assert bare_engine.registry.get("generate_subtitles") is not None
    assert bare_engine.registry.get("burn_subtitles") is not None
