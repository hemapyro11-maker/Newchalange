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
        return f"❌ adb مش متثبت — جزء من Android SDK Platform Tools (مجاني): {PLATFORM_TOOLS_URL}"
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
        return "⏱ adb ماردش (timeout) — جرب: adb kill-server ثم أعد المحاولة"
    except OSError as e:
        return f"❌ خطأ تشغيل adb: {e}"

    lines = [ln for ln in result.stdout.splitlines()[1:] if ln.strip()]
    if not lines:
        return (
            "📵 مفيش أجهزة/محاكيات متصلة — شغّل محاكي من Android Studio، "
            "أو وصّل جهاز حقيقي بكابل USB مع تفعيل USB debugging"
        )
    out = [f"📱 {len(lines)} جهاز متصل:"]
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
        return f"❌ الملف مش موجود: {apk_path}"
    if apk_path.suffix.lower() != ".apk":
        return "❌ الملف لازم يكون .apk"

    try:
        result = subprocess.run(
            [*_adb_prefix(device), "install", "-r", str(apk_path)],
            capture_output=True, text=True, timeout=120,
        )
    except subprocess.TimeoutExpired:
        return "⏱ التثبيت أخد وقت طويل جدًا (120s) واتوقف"
    except OSError as e:
        return f"❌ خطأ: {e}"

    out = ((result.stdout or "") + (result.stderr or "")).strip()
    if "Success" in out:
        return f"✅ اتثبت {apk_path.name}"
    return f"❌ فشل التثبيت:\n{out}"


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
        return f"❌ خطأ: {e}"

    out = ((result.stdout or "") + (result.stderr or "")).strip()
    if "Success" in out:
        return f"✅ اتشال {package}"
    return f"❌ فشل الحذف:\n{out}"


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
        return f"❌ خطأ: {e}"

    out = ((result.stdout or "") + (result.stderr or "")).strip()
    if "No activities found" in out or "Error" in out or "aborting" in out:
        return f"❌ تعذر فتح التطبيق (اتأكد من اسم الـ package بالظبط، زي com.example.app):\n{out}"
    return f"✅ اتفتح {package}"


def _cmd_android_shell(ctx) -> str:
    err = _require_adb()
    if err:
        return err
    args, device = _extract_device(ctx.args)
    if not args:
        return "usage: android_shell <command...> [device=<id>]   — بيتنفذ عبر adb shell على الجهاز/المحاكي"

    try:
        result = subprocess.run(
            [*_adb_prefix(device), "shell", *args],
            capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        return "⏱ timeout (30s)"
    except OSError as e:
        return f"❌ خطأ: {e}"

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
        return f"❌ خطأ: {e}"

    if result.returncode != 0 or not result.stdout:
        stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else "مفيش جهاز متصل؟"
        return f"❌ فشل أخذ لقطة الشاشة: {stderr}"

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(result.stdout)
    except OSError as e:
        return f"❌ تعذر الحفظ: {e}"
    return f"✅ اتحفظت لقطة الشاشة في {out_path} ({len(result.stdout):,} بايت)"


def register(engine):
    engine.registry.register("android_devices", _cmd_android_devices,
                              "android_devices — عرض الأجهزة/المحاكيات المتصلة")
    engine.registry.register("android_install", _cmd_android_install,
                              "android_install <apk_path> [device=<id>] — تثبيت APK")
    engine.registry.register("android_uninstall", _cmd_android_uninstall,
                              "android_uninstall <package_name> [device=<id>] — حذف تطبيق")
    engine.registry.register("android_launch", _cmd_android_launch,
                              "android_launch <package_name> [device=<id>] — تشغيل تطبيق")
    engine.registry.register("android_shell", _cmd_android_shell,
                              "android_shell <command...> [device=<id>] — أي أمر adb shell مباشرة")
    engine.registry.register("android_screenshot", _cmd_android_screenshot,
                              "android_screenshot <out.png> [device=<id>] — لقطة شاشة من الجهاز")
