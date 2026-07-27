import subprocess

import android_plugin as ap


def _fake_completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


# ── _require_adb / no-adb messaging ────────────────────────────────────

def test_no_adb_reports_clear_message(make_ctx, monkeypatch):
    monkeypatch.setattr(ap.shutil, "which", lambda name: None)
    result = ap._cmd_android_devices(make_ctx("android_devices", []))
    assert result.startswith("❌")
    assert "adb" in result
    assert "developer.android.com" in result


def test_all_commands_report_no_adb_consistently(make_ctx, monkeypatch):
    monkeypatch.setattr(ap.shutil, "which", lambda name: None)
    for fn, args in (
        (ap._cmd_android_devices, []),
        (ap._cmd_android_install, ["x.apk"]),
        (ap._cmd_android_uninstall, ["com.example"]),
        (ap._cmd_android_launch, ["com.example"]),
        (ap._cmd_android_shell, ["echo", "hi"]),
        (ap._cmd_android_screenshot, ["out.png"]),
    ):
        result = fn(make_ctx("cmd", args))
        assert result.startswith("❌"), f"{fn.__name__} should report missing adb"


# ── _extract_device ──────────────────────────────────────────────────

def test_extract_device_finds_flag():
    remaining, device = ap._extract_device(["pkg.name", "device=emulator-5554"])
    assert remaining == ["pkg.name"]
    assert device == "emulator-5554"


def test_extract_device_none_when_absent():
    remaining, device = ap._extract_device(["pkg.name"])
    assert remaining == ["pkg.name"]
    assert device is None


def test_extract_device_ignores_literal_device_equals_mid_command():
    # راجع: android_shell بياخد <command...> حر — لو كانت الأداة بتدور
    # على device= في أي مكان، أمر shell شرعي زي "setprop device=foo"
    # كان هيتقطع منه device=foo غلط ويتفسر كـ adb -s device selector
    # بدل ما يتبعت كجزء من الأمر نفسه. دلوقتي بنقبل device= بس لو
    # آخر توكن، زي ما موضح في كل usage strings.
    remaining, device = ap._extract_device(["setprop", "device=foo", "1"])
    assert remaining == ["setprop", "device=foo", "1"]
    assert device is None


def test_extract_device_still_works_as_trailing_flag_on_shell_command():
    remaining, device = ap._extract_device(["input", "tap", "500", "800", "device=emulator-5554"])
    assert remaining == ["input", "tap", "500", "800"]
    assert device == "emulator-5554"


def test_adb_prefix_includes_device_flag():
    assert ap._adb_prefix("emulator-5554") == ["adb", "-s", "emulator-5554"]
    assert ap._adb_prefix(None) == ["adb"]


# ── android_devices ──────────────────────────────────────────────────

def test_devices_no_devices_connected(make_ctx, monkeypatch):
    monkeypatch.setattr(ap.shutil, "which", lambda name: "/usr/bin/adb")
    monkeypatch.setattr(ap.subprocess, "run", lambda *a, **kw: _fake_completed(stdout="List of devices attached\n\n"))
    result = ap._cmd_android_devices(make_ctx("android_devices", []))
    assert "no devices or emulators connected" in result


def test_devices_lists_connected_devices(make_ctx, monkeypatch):
    monkeypatch.setattr(ap.shutil, "which", lambda name: "/usr/bin/adb")
    monkeypatch.setattr(
        ap.subprocess, "run",
        lambda *a, **kw: _fake_completed(stdout="List of devices attached\nemulator-5554\tdevice product:sdk\n"),
    )
    result = ap._cmd_android_devices(make_ctx("android_devices", []))
    assert "1 device(s) connected" in result
    assert "emulator-5554" in result


def test_devices_timeout(make_ctx, monkeypatch):
    monkeypatch.setattr(ap.shutil, "which", lambda name: "/usr/bin/adb")

    def fake_run(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="adb", timeout=15)
    monkeypatch.setattr(ap.subprocess, "run", fake_run)
    result = ap._cmd_android_devices(make_ctx("android_devices", []))
    assert result.startswith("⏱")


# ── android_install ──────────────────────────────────────────────────

def test_install_no_args(make_ctx, monkeypatch):
    monkeypatch.setattr(ap.shutil, "which", lambda name: "/usr/bin/adb")
    result = ap._cmd_android_install(make_ctx("android_install", []))
    assert result.startswith("usage")


def test_install_missing_file(make_ctx, monkeypatch, tmp_path):
    monkeypatch.setattr(ap.shutil, "which", lambda name: "/usr/bin/adb")
    result = ap._cmd_android_install(make_ctx("android_install", [str(tmp_path / "nope.apk")]))
    assert result.startswith("❌")


def test_install_rejects_non_apk(make_ctx, monkeypatch, tmp_path):
    monkeypatch.setattr(ap.shutil, "which", lambda name: "/usr/bin/adb")
    f = tmp_path / "file.txt"
    f.write_text("x")
    result = ap._cmd_android_install(make_ctx("android_install", [str(f)]))
    assert result.startswith("❌")
    assert ".apk" in result


def test_install_success(make_ctx, monkeypatch, tmp_path):
    monkeypatch.setattr(ap.shutil, "which", lambda name: "/usr/bin/adb")
    apk = tmp_path / "app.apk"
    apk.write_bytes(b"fake apk content")
    monkeypatch.setattr(ap.subprocess, "run", lambda *a, **kw: _fake_completed(stdout="Success\n"))
    result = ap._cmd_android_install(make_ctx("android_install", [str(apk)]))
    assert result.startswith("✅")


def test_install_failure_reported(make_ctx, monkeypatch, tmp_path):
    monkeypatch.setattr(ap.shutil, "which", lambda name: "/usr/bin/adb")
    apk = tmp_path / "app.apk"
    apk.write_bytes(b"fake apk content")
    monkeypatch.setattr(ap.subprocess, "run", lambda *a, **kw: _fake_completed(stdout="Failure [INSTALL_FAILED_INVALID_APK]\n"))
    result = ap._cmd_android_install(make_ctx("android_install", [str(apk)]))
    assert result.startswith("❌")


def test_install_passes_device_flag_through(make_ctx, monkeypatch, tmp_path):
    monkeypatch.setattr(ap.shutil, "which", lambda name: "/usr/bin/adb")
    apk = tmp_path / "app.apk"
    apk.write_bytes(b"x")
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return _fake_completed(stdout="Success\n")
    monkeypatch.setattr(ap.subprocess, "run", fake_run)
    ap._cmd_android_install(make_ctx("android_install", [str(apk), "device=emulator-5554"]))
    assert captured["cmd"][:3] == ["adb", "-s", "emulator-5554"]


# ── android_uninstall ────────────────────────────────────────────────

def test_uninstall_no_args(make_ctx, monkeypatch):
    monkeypatch.setattr(ap.shutil, "which", lambda name: "/usr/bin/adb")
    result = ap._cmd_android_uninstall(make_ctx("android_uninstall", []))
    assert result.startswith("usage")


def test_uninstall_success(make_ctx, monkeypatch):
    monkeypatch.setattr(ap.shutil, "which", lambda name: "/usr/bin/adb")
    monkeypatch.setattr(ap.subprocess, "run", lambda *a, **kw: _fake_completed(stdout="Success\n"))
    result = ap._cmd_android_uninstall(make_ctx("android_uninstall", ["com.example.app"]))
    assert result.startswith("✅")


def test_uninstall_failure(make_ctx, monkeypatch):
    monkeypatch.setattr(ap.shutil, "which", lambda name: "/usr/bin/adb")
    monkeypatch.setattr(ap.subprocess, "run", lambda *a, **kw: _fake_completed(stdout="Failure\n"))
    result = ap._cmd_android_uninstall(make_ctx("android_uninstall", ["com.example.app"]))
    assert result.startswith("❌")


# ── android_launch ───────────────────────────────────────────────────

def test_launch_no_args(make_ctx, monkeypatch):
    monkeypatch.setattr(ap.shutil, "which", lambda name: "/usr/bin/adb")
    result = ap._cmd_android_launch(make_ctx("android_launch", []))
    assert result.startswith("usage")


def test_launch_success(make_ctx, monkeypatch):
    monkeypatch.setattr(ap.shutil, "which", lambda name: "/usr/bin/adb")
    monkeypatch.setattr(ap.subprocess, "run", lambda *a, **kw: _fake_completed(stdout="Events injected: 1\n"))
    result = ap._cmd_android_launch(make_ctx("android_launch", ["com.example.app"]))
    assert result.startswith("✅")


def test_launch_no_activity_found(make_ctx, monkeypatch):
    monkeypatch.setattr(ap.shutil, "which", lambda name: "/usr/bin/adb")
    monkeypatch.setattr(ap.subprocess, "run", lambda *a, **kw: _fake_completed(stdout="No activities found to run, monkey aborted.\n"))
    result = ap._cmd_android_launch(make_ctx("android_launch", ["com.bad.package"]))
    assert result.startswith("❌")


# ── android_shell (generic passthrough) ─────────────────────────────

def test_shell_no_args(make_ctx, monkeypatch):
    monkeypatch.setattr(ap.shutil, "which", lambda name: "/usr/bin/adb")
    result = ap._cmd_android_shell(make_ctx("android_shell", []))
    assert result.startswith("usage")


def test_shell_passes_arbitrary_command(make_ctx, monkeypatch):
    monkeypatch.setattr(ap.shutil, "which", lambda name: "/usr/bin/adb")
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return _fake_completed(stdout="package:com.android.chrome\n")
    monkeypatch.setattr(ap.subprocess, "run", fake_run)
    result = ap._cmd_android_shell(make_ctx("android_shell", ["pm", "list", "packages"]))
    assert captured["cmd"] == ["adb", "shell", "pm", "list", "packages"]
    assert "chrome" in result


def test_shell_with_device_flag(make_ctx, monkeypatch):
    monkeypatch.setattr(ap.shutil, "which", lambda name: "/usr/bin/adb")
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return _fake_completed(stdout="ok")
    monkeypatch.setattr(ap.subprocess, "run", fake_run)
    ap._cmd_android_shell(make_ctx("android_shell", ["input", "tap", "500", "800", "device=emulator-5554"]))
    assert captured["cmd"] == ["adb", "-s", "emulator-5554", "shell", "input", "tap", "500", "800"]


def test_shell_reports_exit_code_when_no_output(make_ctx, monkeypatch):
    monkeypatch.setattr(ap.shutil, "which", lambda name: "/usr/bin/adb")
    monkeypatch.setattr(ap.subprocess, "run", lambda *a, **kw: _fake_completed(stdout="", returncode=1))
    result = ap._cmd_android_shell(make_ctx("android_shell", ["false"]))
    assert "exit code 1" in result


# ── android_screenshot ───────────────────────────────────────────────

def test_screenshot_no_args(make_ctx, monkeypatch):
    monkeypatch.setattr(ap.shutil, "which", lambda name: "/usr/bin/adb")
    result = ap._cmd_android_screenshot(make_ctx("android_screenshot", []))
    assert result.startswith("usage")


def test_screenshot_saves_binary_png_data(make_ctx, monkeypatch, tmp_path):
    monkeypatch.setattr(ap.shutil, "which", lambda name: "/usr/bin/adb")
    fake_png_bytes = b"\x89PNG\r\n\x1a\nfakepngdata"
    monkeypatch.setattr(
        ap.subprocess, "run",
        lambda *a, **kw: subprocess.CompletedProcess([], 0, stdout=fake_png_bytes, stderr=b""),
    )
    out = tmp_path / "shot.png"
    result = ap._cmd_android_screenshot(make_ctx("android_screenshot", [str(out)]))
    assert result.startswith("✅")
    assert out.read_bytes() == fake_png_bytes


def test_screenshot_failure_reported(make_ctx, monkeypatch, tmp_path):
    monkeypatch.setattr(ap.shutil, "which", lambda name: "/usr/bin/adb")
    monkeypatch.setattr(
        ap.subprocess, "run",
        lambda *a, **kw: subprocess.CompletedProcess([], 1, stdout=b"", stderr=b"no devices/emulators found"),
    )
    result = ap._cmd_android_screenshot(make_ctx("android_screenshot", [str(tmp_path / "shot.png")]))
    assert result.startswith("❌")


# ── register ─────────────────────────────────────────────────────────

def test_register_adds_all_commands():
    class FakeRegistry:
        def __init__(self):
            self.names = []

        def register(self, name, handler, description=""):
            self.names.append(name)

    class FakeEngine:
        registry = FakeRegistry()

    ap.register(FakeEngine)
    for cmd in ("android_devices", "android_install", "android_uninstall",
                "android_launch", "android_shell", "android_screenshot"):
        assert cmd in FakeEngine.registry.names
