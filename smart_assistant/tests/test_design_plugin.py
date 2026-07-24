import pytest

import design_plugin as dp

requires_pil = pytest.mark.skipif(not dp.PIL_AVAILABLE, reason="Pillow not installed")


@requires_pil
def test_make_logo_creates_correct_size_image(make_ctx, tmp_path):
    out = tmp_path / "logo.png"
    result = dp._cmd_make_logo(make_ctx("make_logo", ["Smart Assistant", str(out)]))
    assert result.startswith("✅")
    from PIL import Image
    img = Image.open(out)
    assert img.size == (512, 512)


@requires_pil
def test_make_logo_uses_initials(make_ctx, tmp_path):
    out = tmp_path / "logo.png"
    result = dp._cmd_make_logo(make_ctx("make_logo", ["Smart Assistant", str(out)]))
    assert "SA" in result


@requires_pil
def test_make_logo_single_word_uses_one_initial(make_ctx, tmp_path):
    out = tmp_path / "logo.png"
    result = dp._cmd_make_logo(make_ctx("make_logo", ["Ahmed", str(out)]))
    assert "(A)" in result


@requires_pil
def test_make_logo_custom_size(make_ctx, tmp_path):
    out = tmp_path / "logo.png"
    dp._cmd_make_logo(make_ctx("make_logo", ["X", str(out), "256"]))
    from PIL import Image
    assert Image.open(out).size == (256, 256)


@requires_pil
def test_make_logo_rejects_bad_size(make_ctx, tmp_path):
    out = tmp_path / "logo.png"
    result = dp._cmd_make_logo(make_ctx("make_logo", ["X", str(out), "notanumber"]))
    assert result.startswith("❌")
    result = dp._cmd_make_logo(make_ctx("make_logo", ["X", str(out), "0"]))
    assert result.startswith("❌")
    result = dp._cmd_make_logo(make_ctx("make_logo", ["X", str(out), "999999"]))
    assert result.startswith("❌")


@requires_pil
def test_make_logo_rejects_bad_color(make_ctx, tmp_path):
    out = tmp_path / "logo.png"
    result = dp._cmd_make_logo(make_ctx("make_logo", ["X", str(out), "100", "notacolor"]))
    assert result.startswith("❌")


@requires_pil
def test_app_icons_generates_full_set(make_ctx, tmp_path):
    from PIL import Image
    src = tmp_path / "source.png"
    Image.new("RGBA", (200, 200), "#ff0000").save(src)
    out_dir = tmp_path / "icons"
    result = dp._cmd_app_icons(make_ctx("app_icons", [str(src), str(out_dir)]))
    assert result.startswith("✅")

    expected_count = len(dp.IOS_ICON_SIZES) + len(dp.ANDROID_ICON_SIZES)
    assert str(expected_count) in result

    icon_1024 = Image.open(out_dir / "ios" / "icon_1024x1024.png")
    assert icon_1024.size == (1024, 1024)
    icon_xxxhdpi = Image.open(out_dir / "android" / "mipmap-xxxhdpi" / "ic_launcher.png")
    assert icon_xxxhdpi.size == (192, 192)


@requires_pil
def test_app_icons_missing_source(make_ctx, tmp_path):
    result = dp._cmd_app_icons(make_ctx("app_icons", [str(tmp_path / "nope.png"), str(tmp_path / "out")]))
    assert result.startswith("❌")


@requires_pil
def test_app_icons_invalid_image(make_ctx, tmp_path):
    bad = tmp_path / "notanimage.png"
    bad.write_bytes(b"this is not a real image file")
    result = dp._cmd_app_icons(make_ctx("app_icons", [str(bad), str(tmp_path / "out")]))
    assert result.startswith("❌")
