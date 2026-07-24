import xml.etree.ElementTree as ET

import scaffold_plugin as sp


def test_scaffold_no_args_lists_types(make_ctx):
    result = sp._cmd_scaffold(make_ctx("scaffold", []))
    assert "web" in result and "android" in result and "ios" in result


def test_scaffold_unknown_type(make_ctx, tmp_path):
    result = sp._cmd_scaffold(make_ctx("scaffold", ["bogus", "X", str(tmp_path)]))
    assert result.startswith("❌")


def test_scaffold_rejects_path_traversal_name(make_ctx, tmp_path):
    result = sp._cmd_scaffold(make_ctx("scaffold", ["web", "../../evil", str(tmp_path)]))
    assert result.startswith("❌")


def test_scaffold_rejects_existing_nonempty_dir(make_ctx, tmp_path):
    project = tmp_path / "MyApp"
    project.mkdir()
    (project / "existing.txt").write_text("already here")
    result = sp._cmd_scaffold(make_ctx("scaffold", ["web", "MyApp", str(tmp_path)]))
    assert result.startswith("❌")


def test_scaffold_web_creates_valid_files(make_ctx, tmp_path):
    result = sp._cmd_scaffold(make_ctx("scaffold", ["web", "MySite", str(tmp_path)]))
    assert result.startswith("✅")
    root = tmp_path / "MySite"
    assert (root / "index.html").is_file()
    assert (root / "style.css").is_file()
    assert (root / "script.js").is_file()
    assert "MySite" in (root / "index.html").read_text(encoding="utf-8")


def test_scaffold_android_produces_wellformed_manifest(make_ctx, tmp_path):
    result = sp._cmd_scaffold(make_ctx("scaffold", ["android", "MyApp", str(tmp_path)]))
    assert result.startswith("✅")
    manifest = tmp_path / "MyApp" / "app" / "src" / "main" / "AndroidManifest.xml"
    ET.parse(manifest)  # raises if malformed


def test_scaffold_android_package_fallback_for_non_alnum_name(make_ctx, tmp_path):
    # regression: "!!!"  has zero alnum chars — package must fall back
    # to com.example.app, not the malformed "com.example."
    result = sp._cmd_scaffold(make_ctx("scaffold", ["android", "!!!", str(tmp_path)]))
    assert result.startswith("✅")
    manifest_kt_dir = tmp_path / "!!!" / "app" / "src" / "main" / "java" / "com" / "example" / "app"
    assert manifest_kt_dir.is_dir()
    build_gradle = (tmp_path / "!!!" / "app" / "build.gradle.kts").read_text(encoding="utf-8")
    assert 'namespace = "com.example.app"' in build_gradle
    assert 'namespace = "com.example."' not in build_gradle


def test_scaffold_ios_creates_swift_files(make_ctx, tmp_path):
    result = sp._cmd_scaffold(make_ctx("scaffold", ["ios", "MyIOSApp", str(tmp_path)]))
    assert result.startswith("✅")
    assert (tmp_path / "MyIOSApp" / "MyIOSAppApp.swift").is_file()
    assert (tmp_path / "MyIOSApp" / "ContentView.swift").is_file()


def test_scaffold_python_creates_runnable_main(make_ctx, tmp_path):
    result = sp._cmd_scaffold(make_ctx("scaffold", ["python", "MyScript", str(tmp_path)]))
    assert result.startswith("✅")
    import py_compile
    py_compile.compile(str(tmp_path / "MyScript" / "main.py"), doraise=True)


def test_scaffold_game_creates_runnable_pygame_source(make_ctx, tmp_path):
    result = sp._cmd_scaffold(make_ctx("scaffold", ["game", "MyGame", str(tmp_path)]))
    assert result.startswith("✅")
    import py_compile
    py_compile.compile(str(tmp_path / "MyGame" / "main.py"), doraise=True)
    assert "pygame" in (tmp_path / "MyGame" / "requirements.txt").read_text(encoding="utf-8")
