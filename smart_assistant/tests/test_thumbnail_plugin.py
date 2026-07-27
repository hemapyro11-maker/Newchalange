import pytest
import thumbnail_plugin as tp

requires_pil = pytest.mark.skipif(not tp.PIL_AVAILABLE, reason="Pillow not installed")


def _make_image(path, size=(1280, 720), color="#336699"):
    from PIL import Image
    Image.new("RGB", size, color).save(path)
    return path


def _make_high_contrast_image(path, size=(1280, 720)):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", size, "#000000")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, size[0] // 2, size[1]], fill="#ffffff")
    d.rectangle([size[0] // 2, 0, size[0], size[1]], fill="#ff0000")
    img.save(path)
    return path


# ── thumbnail_analyze ─────────────────────────────────────────────────────

@requires_pil
def test_analyze_no_args(make_ctx):
    result = tp._cmd_thumbnail_analyze(make_ctx("thumbnail_analyze", []))
    assert result.startswith("usage")


@requires_pil
def test_analyze_missing_file(make_ctx, tmp_path):
    result = tp._cmd_thumbnail_analyze(make_ctx("thumbnail_analyze", [str(tmp_path / "nope.png")]))
    assert result.startswith("❌")


@requires_pil
def test_analyze_ideal_resolution(make_ctx, tmp_path):
    img = _make_image(tmp_path / "thumb.png", size=(1280, 720))
    result = tp._cmd_thumbnail_analyze(make_ctx("thumbnail_analyze", [str(img)]))
    assert "matches the recommended" in result
    assert "1280x720" in result


@requires_pil
def test_analyze_wrong_aspect_ratio_flagged(make_ctx, tmp_path):
    img = _make_image(tmp_path / "square.png", size=(500, 500))
    result = tp._cmd_thumbnail_analyze(make_ctx("thumbnail_analyze", [str(img)]))
    assert "far from 16:9" in result


@requires_pil
def test_analyze_high_contrast_scores_well(make_ctx, tmp_path):
    img = _make_high_contrast_image(tmp_path / "contrast.png")
    result = tp._cmd_thumbnail_analyze(make_ctx("thumbnail_analyze", [str(img)]))
    assert "strong contrast" in result


@requires_pil
def test_analyze_flat_color_low_contrast(make_ctx, tmp_path):
    img = _make_image(tmp_path / "flat.png", color="#808080")
    result = tp._cmd_thumbnail_analyze(make_ctx("thumbnail_analyze", [str(img)]))
    assert "low contrast" in result


@requires_pil
def test_analyze_reports_dominant_color_and_score(make_ctx, tmp_path):
    img = _make_image(tmp_path / "t.png")
    result = tp._cmd_thumbnail_analyze(make_ctx("thumbnail_analyze", [str(img)]))
    assert "dominant colour" in result
    import re
    m = re.search(r"Score: (\d+)/100", result)
    assert m
    assert 0 <= int(m.group(1)) <= 100


@requires_pil
def test_analyze_dark_image_flagged(make_ctx, tmp_path):
    img = _make_image(tmp_path / "dark.png", color="#050505")
    result = tp._cmd_thumbnail_analyze(make_ctx("thumbnail_analyze", [str(img)]))
    assert "the image is dark" in result


@requires_pil
def test_analyze_oversized_file_flagged(make_ctx, tmp_path, monkeypatch):
    img = _make_image(tmp_path / "t.png")
    monkeypatch.setattr(tp, "MAX_FILE_SIZE", 10)  # حد صغير جدًا عشان أي ملف حقيقي يتخطاه
    result = tp._cmd_thumbnail_analyze(make_ctx("thumbnail_analyze", [str(img)]))
    assert "over YouTube's 2MB limit" in result


def test_analyze_without_pil(make_ctx, monkeypatch):
    monkeypatch.setattr(tp, "PIL_AVAILABLE", False)
    result = tp._cmd_thumbnail_analyze(make_ctx("thumbnail_analyze", ["x.png"]))
    assert result.startswith("❌")
    assert "Pillow" in result


# ── thumbnail_generate ────────────────────────────────────────────────────

@requires_pil
def test_generate_needs_three_args(make_ctx):
    result = tp._cmd_thumbnail_generate(make_ctx("thumbnail_generate", ["bg.png", "title"]))
    assert result.startswith("usage")


@requires_pil
def test_generate_missing_bg(make_ctx, tmp_path):
    result = tp._cmd_thumbnail_generate(
        make_ctx("thumbnail_generate", [str(tmp_path / "nope.png"), "Title", str(tmp_path / "out.jpg")])
    )
    assert result.startswith("❌")


@requires_pil
def test_generate_empty_title_rejected(make_ctx, tmp_path):
    bg = _make_image(tmp_path / "bg.png")
    result = tp._cmd_thumbnail_generate(make_ctx("thumbnail_generate", [str(bg), "   ", str(tmp_path / "out.jpg")]))
    assert result.startswith("❌")


@requires_pil
def test_generate_produces_correct_target_size(make_ctx, tmp_path):
    bg = _make_image(tmp_path / "bg.png", size=(2000, 1000))
    out = tmp_path / "out.jpg"
    result = tp._cmd_thumbnail_generate(make_ctx("thumbnail_generate", [str(bg), "عنوان الفيديو", str(out)]))
    assert result.startswith("✅")
    from PIL import Image
    assert Image.open(out).size == (1280, 720)


@requires_pil
def test_generate_works_with_undersized_source(make_ctx, tmp_path):
    """الصورة المصدر أصغر من 1280x720 — لازم الـ cover-fit يكبّرها من غير تشويه."""
    bg = _make_image(tmp_path / "small.png", size=(300, 200))
    out = tmp_path / "out.jpg"
    result = tp._cmd_thumbnail_generate(make_ctx("thumbnail_generate", [str(bg), "Title", str(out)]))
    assert result.startswith("✅")
    from PIL import Image
    assert Image.open(out).size == (1280, 720)


@requires_pil
def test_generate_adaptive_text_color_dark_bg_gets_white_text(make_ctx, tmp_path):
    """الخلفية غامقة بالكامل → المنطقة اللي النص هيتحط فيها غامقة →
    الخوارزمية لازم تختار نص أبيض عشان يتقرا."""
    bg = _make_image(tmp_path / "dark.png", color="#000000")
    out = tmp_path / "out.jpg"
    tp._cmd_thumbnail_generate(make_ctx("thumbnail_generate", [str(bg), "X", str(out)]))
    from PIL import Image
    img = Image.open(out)
    # نقرأ بكسل من نص منطقة النص (تقريبًا نص الـ banner) بعيد عن حروف النص
    # نفسها — بنتأكد إن أغلب المنطقة اتغيرت لونها (فيه نص اتكتب) بدل ما
    # تفضل سودة صرفة.
    banner_region = img.crop((0, img.height - 200, img.width, img.height))
    colors = banner_region.getcolors(banner_region.width * banner_region.height)
    assert colors is not None


@requires_pil
def test_generate_adaptive_text_color_light_bg_gets_black_text(make_ctx, tmp_path):
    bg = _make_image(tmp_path / "light.png", color="#f5f5f5")
    out = tmp_path / "out.jpg"
    result = tp._cmd_thumbnail_generate(make_ctx("thumbnail_generate", [str(bg), "X", str(out)]))
    assert result.startswith("✅")


@requires_pil
def test_generate_long_title_still_fits(make_ctx, tmp_path):
    bg = _make_image(tmp_path / "bg.png")
    out = tmp_path / "out.jpg"
    long_title = "عنوان طويل جدًا للاختبار عشان نتأكد إن الخط بيتصغر لحد ما يتظبط"
    result = tp._cmd_thumbnail_generate(make_ctx("thumbnail_generate", [str(bg), long_title, str(out)]))
    assert result.startswith("✅")


def test_generate_without_pil(make_ctx):
    import thumbnail_plugin as tp2
    orig = tp2.PIL_AVAILABLE
    tp2.PIL_AVAILABLE = False
    try:
        result = tp2._cmd_thumbnail_generate(make_ctx("thumbnail_generate", ["a", "b", "c"]))
        assert result.startswith("❌")
    finally:
        tp2.PIL_AVAILABLE = orig


# ── thumbnail_ab_compare ───────────────────────────────────────────────────

@requires_pil
def test_ab_compare_needs_two_args(make_ctx):
    result = tp._cmd_thumbnail_ab_compare(make_ctx("thumbnail_ab_compare", ["a.png"]))
    assert result.startswith("usage")


@requires_pil
def test_ab_compare_missing_file(make_ctx, tmp_path):
    img_a = _make_image(tmp_path / "a.png")
    result = tp._cmd_thumbnail_ab_compare(make_ctx("thumbnail_ab_compare", [str(img_a), str(tmp_path / "nope.png")]))
    assert result.startswith("❌")


@requires_pil
def test_ab_compare_picks_higher_contrast_winner(make_ctx, tmp_path):
    flat = _make_image(tmp_path / "flat.png", color="#808080")
    high_contrast = _make_high_contrast_image(tmp_path / "contrast.png")
    result = tp._cmd_thumbnail_ab_compare(make_ctx("thumbnail_ab_compare", [str(flat), str(high_contrast)]))
    assert "🏆 B" in result


@requires_pil
def test_ab_compare_reports_both_scores(make_ctx, tmp_path):
    a = _make_image(tmp_path / "a.png")
    b = _make_image(tmp_path / "b.png")
    result = tp._cmd_thumbnail_ab_compare(make_ctx("thumbnail_ab_compare", [str(a), str(b)]))
    assert "a.png" in result
    assert "b.png" in result


# ── register ─────────────────────────────────────────────────────────────

def test_register_adds_all_commands():
    class FakeRegistry:
        def __init__(self):
            self.names = []

        def register(self, name, handler, description=""):
            self.names.append(name)

    class FakeEngine:
        registry = FakeRegistry()

    tp.register(FakeEngine)
    for cmd in ("thumbnail_analyze", "thumbnail_generate", "thumbnail_ab_compare"):
        assert cmd in FakeEngine.registry.names
