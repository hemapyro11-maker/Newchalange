"""
android_plugin.py — تحكم حقيقي في تطبيقات أندرويد عبر ADB (Android
Debug Bridge — جزء من Android SDK Platform Tools، مجاني ومفتوح
المصدر بالكامل): تثبيت/حذف APK، تشغيل تطبيق، لقطة شاشة، وتمرير أي
أمر shell مباشرة للجهاز/المحاكي — وده اللي بيدّي "نفّذ أي أمر
أقولّه عليه" فعليًا لأندرويد، لأن adb shell شامل جدًا (input tap/
swipe/text، am start، pm list packages، dumpsys...).

**محتاج جهاز أو محاكي متصل فعليًا** (Android Studio Emulator، أو
جهاز حقيقي بـ USB debugging مفعّل) — الأداة نفسها مجانية بالكامل،
لكن مش هتشتغل من غير جهاز/محاكي حقيقي يتوصل بيه.

الأوامر: android_devices, android_install, android_uninstall,
android_launch, android_shell, android_screenshot
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess

PLATFORM_TOOLS_URL = "https://developer.android.com/tools/releases/platform-tools"


def _adb_available() -> bool:
    return shutil.which("adb") is not None


def _require_adb() -> str | None:
    if not _adb_available():
        return f"❌ adb is not installed — it is part of the free Android SDK Platform Tools: {PLATFORM_TOOLS_URL}"
    return None


def _extract_device(args: list[str]) -> tuple[list[str], str | None]:
    """بتشيل [device=<id>] بس لو هو آخر توكن (زي ما موضح في كل usage
    strings — الفلاج ده دايمًا في الآخر). لو كنا بنفحص كل التوكنز، أي
    أمر android_shell بيحتوي على "device=" كنص حرفي جوه أوامره
    (مش كفلاج) كان هيتشال غلط ويتفسر كـ device selector."""
    if args and args[-1].startswith("device="):
        return list(args[:-1]), args[-1][len("device="):]
    return list(args), None


def _adb_prefix(device: str | None) -> list[str]:
    return ["adb", "-s", device] if device else ["adb"]


def _cmd_android_devices(ctx) -> str:
    err = _require_adb()
    if err:
        return err
    try:
        result = subprocess.run(["adb", "devices", "-l"], capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        return "⏱ adb did not respond — try: adb kill-server, then run it again"
    except OSError as e:
        return f"❌ could not run adb: {e}"

    lines = [ln for ln in result.stdout.splitlines()[1:] if ln.strip()]
    if not lines:
        return (
            "📵 no devices or emulators connected — start an emulator from Android Studio, "
            "or plug in a real device over USB with USB debugging enabled"
        )
    out = [f"📱 {len(lines)} device(s) connected:"]
    out += [f"   • {ln}" for ln in lines]
    return "\n".join(out)


def _cmd_android_install(ctx) -> str:
    err = _require_adb()
    if err:
        return err
    args, device = _extract_device(ctx.args)
    if not args:
        return "usage: android_install <apk_path> [device=<id>]"
    apk_path = pathlib.Path(args[0])
    if not apk_path.is_file():
        return f"❌ file not found: {apk_path}"
    if apk_path.suffix.lower() != ".apk":
        return "❌ the file must be an .apk"

    try:
        result = subprocess.run(
            [*_adb_prefix(device), "install", "-r", str(apk_path)],
            capture_output=True, text=True, timeout=120,
        )
    except subprocess.TimeoutExpired:
        return "⏱ installation took too long (120s) and was stopped"
    except OSError as e:
        return f"❌ error: {e}"

    out = ((result.stdout or "") + (result.stderr or "")).strip()
    if "Success" in out:
        return f"✅ installed {apk_path.name}"
    return f"❌ installation failed:\n{out}"


def _cmd_android_uninstall(ctx) -> str:
    err = _require_adb()
    if err:
        return err
    args, device = _extract_device(ctx.args)
    if not args:
        return "usage: android_uninstall <package_name> [device=<id>]"
    package = args[0]

    try:
        result = subprocess.run(
            [*_adb_prefix(device), "uninstall", package],
            capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        return "⏱ timeout (30s)"
    except OSError as e:
        return f"❌ error: {e}"

    out = ((result.stdout or "") + (result.stderr or "")).strip()
    if "Success" in out:
        return f"✅ uninstalled {package}"
    return f"❌ uninstall failed:\n{out}"


def _cmd_android_launch(ctx) -> str:
    err = _require_adb()
    if err:
        return err
    args, device = _extract_device(ctx.args)
    if not args:
        return "usage: android_launch <package_name> [device=<id>]"
    package = args[0]

    try:
        result = subprocess.run(
            [*_adb_prefix(device), "shell", "monkey", "-p", package,
             "-c", "android.intent.category.LAUNCHER", "1"],
            capture_output=True, text=True, timeout=20,
        )
    except subprocess.TimeoutExpired:
        return "⏱ timeout (20s)"
    except OSError as e:
        return f"❌ error: {e}"

    out = ((result.stdout or "") + (result.stderr or "")).strip()
    if "No activities found" in out or "Error" in out or "aborting" in out:
        return f"❌ could not launch the app (check the exact package name, e.g. com.example.app):\n{out}"
    return f"✅ launched {package}"


def _cmd_android_shell(ctx) -> str:
    err = _require_adb()
    if err:
        return err
    args, device = _extract_device(ctx.args)
    if not args:
        return "usage: android_shell <command...> [device=<id>]   — runs via adb shell on the device or emulator"

    try:
        result = subprocess.run(
            [*_adb_prefix(device), "shell", *args],
            capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        return "⏱ timeout (30s)"
    except OSError as e:
        return f"❌ error: {e}"

    out = ((result.stdout or "") + (result.stderr or "")).strip()
    return out or f"(exit code {result.returncode})"


def _cmd_android_screenshot(ctx) -> str:
    err = _require_adb()
    if err:
        return err
    args, device = _extract_device(ctx.args)
    if not args:
        return "usage: android_screenshot <out.png> [device=<id>]"
    out_path = pathlib.Path(args[0])

    try:
        # exec-out (مش shell) عشان نجيب بيانات PNG ثنائية من غير أي
        # تحويل نص (CRLF مثلاً) ممكن يبوّظ محتوى الصورة.
        result = subprocess.run(
            [*_adb_prefix(device), "exec-out", "screencap", "-p"],
            capture_output=True, timeout=20,
        )
    except subprocess.TimeoutExpired:
        return "⏱ timeout (20s)"
    except OSError as e:
        return f"❌ error: {e}"

    if result.returncode != 0 or not result.stdout:
        stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else "no device connected?"
        return f"❌ screenshot failed: {stderr}"

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(result.stdout)
    except OSError as e:
        return f"❌ could not save: {e}"
    return f"✅ screenshot saved to {out_path} ({len(result.stdout):,} bytes)"


def register(engine):
    engine.registry.register("android_devices", _cmd_android_devices,
                              "android_devices — list connected devices and emulators")
    engine.registry.register("android_install", _cmd_android_install,
                              "android_install <apk_path> [device=<id>] — install an APK")
    engine.registry.register("android_uninstall", _cmd_android_uninstall,
                              "android_uninstall <package_name> [device=<id>] — uninstall an app")
    engine.registry.register("android_launch", _cmd_android_launch,
                              "android_launch <package_name> [device=<id>] — launch an app")
    engine.registry.register("android_shell", _cmd_android_shell,
                              "android_shell <command...> [device=<id>] — run any adb shell command directly")
    engine.registry.register("android_screenshot", _cmd_android_screenshot,
                              "android_screenshot <out.png> [device=<id>] — take a screenshot from the device")
