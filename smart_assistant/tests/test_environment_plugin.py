import subprocess

import environment_plugin as ep

# ── _current_os / _linux_pkg_manager ──────────────────────────────────

def test_current_os_maps_known_systems(monkeypatch):
    monkeypatch.setattr(ep.platform, "system", lambda: "Linux")
    assert ep._current_os() == "linux"
    monkeypatch.setattr(ep.platform, "system", lambda: "Darwin")
    assert ep._current_os() == "macos"
    monkeypatch.setattr(ep.platform, "system", lambda: "Windows")
    assert ep._current_os() == "windows"
    monkeypatch.setattr(ep.platform, "system", lambda: "SomethingElse")
    assert ep._current_os() == "unknown"


def test_linux_pkg_manager_picks_first_available(monkeypatch):
    monkeypatch.setattr(ep.shutil, "which", lambda name: "/usr/bin/dnf" if name == "dnf" else None)
    assert ep._linux_pkg_manager() == "dnf"


def test_linux_pkg_manager_none_when_nothing_found(monkeypatch):
    monkeypatch.setattr(ep.shutil, "which", lambda name: None)
    assert ep._linux_pkg_manager() is None


# ── _check_binary / _check_python / _check_ollama ──────────────────────

def test_check_binary_true_when_found(monkeypatch):
    monkeypatch.setattr(ep.shutil, "which", lambda name: "/usr/bin/" + name)
    assert ep._check_binary("ffmpeg") is True


def test_check_binary_false_when_missing(monkeypatch):
    monkeypatch.setattr(ep.shutil, "which", lambda name: None)
    assert ep._check_binary("nope") is False


def test_check_python_true_for_real_stdlib_module():
    assert ep._check_python("json") is True


def test_check_python_false_for_nonexistent_module():
    assert ep._check_python("this_module_does_not_exist_xyz") is False


def test_check_ollama_true_when_server_responds(monkeypatch):
    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(ep.urllib.request, "urlopen", lambda url, timeout: FakeResp())
    assert ep._check_ollama() is True


def test_check_ollama_false_when_unreachable(monkeypatch):
    def fake_urlopen(url, timeout):
        raise ep.urllib.error.URLError("connection refused")
    monkeypatch.setattr(ep.urllib.request, "urlopen", fake_urlopen)
    assert ep._check_ollama() is False


# ── _install_command_for_current_os ────────────────────────────────────

def test_install_command_python_tool_uses_pip():
    cmd = ep._install_command_for_current_os("customtkinter")
    assert "pip install customtkinter" in cmd


def test_install_command_linux_uses_detected_manager(monkeypatch):
    monkeypatch.setattr(ep, "_current_os", lambda: "linux")
    monkeypatch.setattr(ep, "_linux_pkg_manager", lambda: "apt")
    cmd = ep._install_command_for_current_os("ffmpeg")
    assert cmd == "sudo apt install -y ffmpeg"


def test_install_command_same_as_alias_resolves_to_target_tool(monkeypatch):
    # ffprobe/ffplay مالهومش باكدج منفصل في TOOLS (same_as: "ffmpeg") —
    # قبل الإصلاح كانت الدالة بترجع None ليهم دايمًا بدل ما تدلّك على
    # تثبيت ffmpeg اللي بيجيبهم معاه.
    monkeypatch.setattr(ep, "_current_os", lambda: "linux")
    monkeypatch.setattr(ep, "_linux_pkg_manager", lambda: "apt")
    assert ep._install_command_for_current_os("ffprobe") == "sudo apt install -y ffmpeg"
    assert ep._install_command_for_current_os("ffplay") == "sudo apt install -y ffmpeg"


def test_install_command_macos_uses_brew(monkeypatch):
    monkeypatch.setattr(ep, "_current_os", lambda: "macos")
    cmd = ep._install_command_for_current_os("ffmpeg")
    assert cmd == "brew install ffmpeg"


def test_install_command_windows_uses_winget(monkeypatch):
    monkeypatch.setattr(ep, "_current_os", lambda: "windows")
    cmd = ep._install_command_for_current_os("ffmpeg")
    assert cmd == "winget install Gyan.FFmpeg"


def test_install_command_none_when_no_manager_available(monkeypatch):
    monkeypatch.setattr(ep, "_current_os", lambda: "linux")
    monkeypatch.setattr(ep, "_linux_pkg_manager", lambda: None)
    assert ep._install_command_for_current_os("ffmpeg") is None


def test_install_command_gcc_none_on_windows(monkeypatch):
    monkeypatch.setattr(ep, "_current_os", lambda: "windows")
    assert ep._install_command_for_current_os("gcc") is None


# ── env_check ────────────────────────────────────────────────────────

def test_env_check_reports_summary(make_ctx):
    result = ep._cmd_env_check(make_ctx("env_check", []))
    assert "فحص بيئة العمل" in result
    assert "الخلاصة" in result


def test_env_check_shows_missing_tool_with_install_hint(make_ctx, monkeypatch):
    monkeypatch.setattr(ep, "_is_installed", lambda key: key != "ffmpeg")
    monkeypatch.setattr(ep, "_current_os", lambda: "linux")
    monkeypatch.setattr(ep, "_linux_pkg_manager", lambda: "apt")
    result = ep._cmd_env_check(make_ctx("env_check", []))
    assert "❌ FFmpeg" in result
    assert "apt install -y ffmpeg" in result


def test_env_check_shows_ollama_specific_hint_when_missing(make_ctx, monkeypatch):
    monkeypatch.setattr(ep, "_is_installed", lambda key: key != "ollama")
    result = ep._cmd_env_check(make_ctx("env_check", []))
    assert "ollama.com" in result


def test_env_check_all_installed_shows_celebration(make_ctx, monkeypatch):
    monkeypatch.setattr(ep, "_is_installed", lambda key: True)
    result = ep._cmd_env_check(make_ctx("env_check", []))
    assert "كل حاجة متاحة" in result


# ── env_install ──────────────────────────────────────────────────────

def test_env_install_no_args(make_ctx):
    result = ep._cmd_env_install(make_ctx("env_install", []))
    assert result.startswith("usage")


def test_env_install_unknown_tool(make_ctx):
    result = ep._cmd_env_install(make_ctx("env_install", ["not_a_real_tool"]))
    assert result.startswith("❌")


def test_env_install_already_installed(make_ctx, monkeypatch):
    monkeypatch.setattr(ep, "_is_installed", lambda key: True)
    result = ep._cmd_env_install(make_ctx("env_install", ["pandas"]))
    assert result.startswith("✅")
    assert "متثبتة بالفعل" in result


def test_env_install_ollama_gives_manual_instructions(make_ctx, monkeypatch):
    monkeypatch.setattr(ep, "_is_installed", lambda key: False)
    result = ep._cmd_env_install(make_ctx("env_install", ["ollama"]))
    assert "ollama.com" in result
    assert "ollama pull" in result


def test_env_install_system_tool_never_auto_executes(make_ctx, monkeypatch):
    """أداة نظام (زي docker) - حتى مع --yes، الأداة لازم توري الأمر بس
    ومتحاولش تشغّله فعليًا (بيحتاج صلاحيات النظام)."""
    monkeypatch.setattr(ep, "_is_installed", lambda key: False)
    monkeypatch.setattr(ep, "_current_os", lambda: "linux")
    monkeypatch.setattr(ep, "_linux_pkg_manager", lambda: "apt")

    def fail_if_called(*a, **kw):
        raise AssertionError("subprocess.run should NEVER be called for a system tool")
    monkeypatch.setattr(ep.subprocess, "run", fail_if_called)

    result = ep._cmd_env_install(make_ctx("env_install", ["docker", "--yes"]))
    assert "انسخ وشغّل بنفسك" in result
    assert "apt install" in result


def test_env_install_python_tool_dry_run_without_yes(make_ctx, monkeypatch):
    monkeypatch.setattr(ep, "_is_installed", lambda key: False)

    def fail_if_called(*a, **kw):
        raise AssertionError("subprocess.run should not run without --yes")
    monkeypatch.setattr(ep.subprocess, "run", fail_if_called)

    result = ep._cmd_env_install(make_ctx("env_install", ["pandas"]))
    assert "هيتشغّل" in result
    assert "--yes" in result


def test_env_install_python_tool_actually_installs_with_yes(make_ctx, monkeypatch):
    monkeypatch.setattr(ep, "_is_installed", lambda key: False)
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
    monkeypatch.setattr(ep.subprocess, "run", fake_run)

    result = ep._cmd_env_install(make_ctx("env_install", ["pandas", "--yes"]))
    assert result.startswith("✅")
    assert "pandas" in captured["cmd"]


def test_env_install_python_tool_reports_failure(make_ctx, monkeypatch):
    monkeypatch.setattr(ep, "_is_installed", lambda key: False)

    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="network unreachable")
    monkeypatch.setattr(ep.subprocess, "run", fake_run)

    result = ep._cmd_env_install(make_ctx("env_install", ["pandas", "--yes"]))
    assert result.startswith("❌")
    assert "network unreachable" in result


def test_env_install_timeout_reported(make_ctx, monkeypatch):
    monkeypatch.setattr(ep, "_is_installed", lambda key: False)

    def fake_run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 300)
    monkeypatch.setattr(ep.subprocess, "run", fake_run)

    result = ep._cmd_env_install(make_ctx("env_install", ["pandas", "--yes"]))
    assert result.startswith("❌")


# ── env_install_all ──────────────────────────────────────────────────

def test_env_install_all_nothing_missing(make_ctx, monkeypatch):
    monkeypatch.setattr(ep, "_is_installed", lambda key: True)
    result = ep._cmd_env_install_all(make_ctx("env_install_all", []))
    assert "كل الأدوات متاحة" in result


def test_env_install_all_dry_run_lists_pip_packages(make_ctx, monkeypatch):
    monkeypatch.setattr(ep, "_is_installed", lambda key: key not in ("pandas", "matplotlib"))
    result = ep._cmd_env_install_all(make_ctx("env_install_all", []))
    assert "pandas" in result
    assert "matplotlib" in result
    assert "--yes" in result


def test_env_install_all_yes_installs_pip_packages_in_one_call(make_ctx, monkeypatch):
    monkeypatch.setattr(ep, "_is_installed", lambda key: key not in ("pandas", "matplotlib"))
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
    monkeypatch.setattr(ep.subprocess, "run", fake_run)

    result = ep._cmd_env_install_all(make_ctx("env_install_all", ["--yes"]))
    assert "اتثبتت" in result
    assert "pandas" in captured["cmd"]
    assert "matplotlib" in captured["cmd"]


def test_env_install_all_separates_system_tools(make_ctx, monkeypatch):
    monkeypatch.setattr(ep, "_is_installed", lambda key: key != "ffmpeg")
    monkeypatch.setattr(ep, "_current_os", lambda: "linux")
    monkeypatch.setattr(ep, "_linux_pkg_manager", lambda: "apt")
    result = ep._cmd_env_install_all(make_ctx("env_install_all", ["--yes"]))
    assert "أدوات نظام محتاجة تثبيت يدوي" in result
    assert "FFmpeg" in result


def test_env_install_all_lists_ollama_separately(make_ctx, monkeypatch):
    monkeypatch.setattr(ep, "_is_installed", lambda key: key != "ollama")
    result = ep._cmd_env_install_all(make_ctx("env_install_all", ["--yes"]))
    assert "ollama.com" in result


# ── register ─────────────────────────────────────────────────────────

def test_register_adds_all_commands():
    class FakeRegistry:
        def __init__(self):
            self.names = []

        def register(self, name, handler, description=""):
            self.names.append(name)

    class FakeEngine:
        registry = FakeRegistry()

    ep.register(FakeEngine)
    for cmd in ("env_check", "env_install", "env_install_all"):
        assert cmd in FakeEngine.registry.names
