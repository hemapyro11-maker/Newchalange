"""
environment_plugin.py — "طبيب" بيئة العمل: فحص شامل لكل الأدوات
الخارجية ومكتبات بايثون اللي أي أمر في نيزوكو (أو أي مشروع سقالة
scaffold وّلدته) ممكن يحتاجها، مع تعليمات تثبيت مضبوطة على نظام
تشغيلك فعليًا (apt/dnf/pacman/brew/winget/choco)، وتثبيت تلقائي حقيقي
لمكتبات بايثون (عبر pip — آمن، مساحة المستخدم، بدون صلاحيات مرتفعة).

**قرار تصميم مقصود:** الأدوات اللي محتاجة صلاحيات نظام (apt/dnf/...)
أو تثبيت خارج بايثون (Docker, Node.js, gcc...) **مبيتثبتش تلقائيًا
أبدًا** — بس بتوريك الأمر الجاهز تنسخه وتشغّله بنفسك. تشغيل sudo
تلقائي من جوه تطبيق من غير علمك الصريح ثغرة صلاحيات، مش راحة.

الأوامر: env_check, env_install, env_install_all
"""
from __future__ import annotations

import importlib.util
import platform
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

OLLAMA_URL = "http://localhost:11434/api/tags"

# كل أداة: category (تصنيف العرض)، kind (طريقة الفحص)، وبيانات التثبيت
# لكل نظام تشغيل/مدير حزم معروف. bin/module فاضي يعني "مش قابل للفحص
# بالطريقة دي".
TOOLS: dict[str, dict] = {
    # ── الأساسيات (لازمة عشان نيزوكو نفسها تشتغل) ──────────────────────
    "customtkinter": {
        "category": "الأساسيات", "label": "CustomTkinter (واجهة نيزوكو)",
        "kind": "python", "module": "customtkinter", "pip": "customtkinter",
    },
    "mcp": {
        "category": "الأساسيات", "label": "MCP (Connectors)",
        "kind": "python", "module": "mcp", "pip": "mcp",
    },
    "capstone": {
        "category": "الأساسيات", "label": "Capstone (هندسة عكسية — re_plugin)",
        "kind": "python", "module": "capstone", "pip": "capstone",
    },
    "pillow": {
        "category": "الأساسيات", "label": "Pillow (design_plugin/thumbnail_plugin)",
        "kind": "python", "module": "PIL", "pip": "Pillow",
    },
    "pandas": {
        "category": "الأساسيات", "label": "pandas (data_science_plugin)",
        "kind": "python", "module": "pandas", "pip": "pandas",
    },
    "matplotlib": {
        "category": "الأساسيات", "label": "matplotlib (data_science_plugin)",
        "kind": "python", "module": "matplotlib", "pip": "matplotlib",
    },
    "edge-tts": {
        "category": "الأساسيات", "label": "edge-tts (صوت نيزوكو الأساسي)",
        "kind": "python", "module": "edge_tts", "pip": "edge-tts",
    },
    "piper-tts": {
        "category": "الأساسيات", "label": "Piper (صوت نيزوكو المحلي)",
        "kind": "python", "module": "piper", "pip": "piper-tts",
    },

    # ── وسائط وصوت ──────────────────────────────────────────────────────
    "ffmpeg": {
        "category": "وسائط", "label": "FFmpeg (media_plugin/cinema_plugin/voice_plugin)",
        "kind": "binary", "bin": "ffmpeg",
        "apt": "ffmpeg", "dnf": "ffmpeg", "pacman": "ffmpeg", "brew": "ffmpeg",
        "winget": "Gyan.FFmpeg", "choco": "ffmpeg",
    },
    "ffprobe": {
        "category": "وسائط", "label": "FFprobe (تحليل ميديا)",
        "kind": "binary", "bin": "ffprobe", "same_as": "ffmpeg",
    },
    "ffplay": {
        "category": "وسائط", "label": "FFplay (تشغيل صوت نيزوكو)",
        "kind": "binary", "bin": "ffplay", "same_as": "ffmpeg",
    },
    "espeak-ng": {
        "category": "وسائط", "label": "espeak-ng (الصوت الاحتياطي الأخير)",
        "kind": "binary", "bin": "espeak-ng",
        "apt": "espeak-ng", "dnf": "espeak-ng", "pacman": "espeak-ng",
        "brew": "espeak-ng", "winget": "eSpeak-NG.eSpeak-NG",
    },

    # ── أمان ─────────────────────────────────────────────────────────────
    "clamav": {
        "category": "أمان", "label": "ClamAV (virus_scan)",
        "kind": "binary", "bin": "clamscan",
        "apt": "clamav", "dnf": "clamav", "pacman": "clamav",
        "brew": "clamav", "winget": "ClamWin.ClamWin",
    },
    "pip-audit": {
        "category": "أمان", "label": "pip-audit (vuln_scan)",
        "kind": "binary_or_pip", "bin": "pip-audit", "pip": "pip-audit",
    },

    # ── أدوات تطوير (لتشغيل مشاريع scaffold نفسها + MCP servers) ──────
    "node": {
        "category": "أدوات تطوير", "label": "Node.js/npm (MCP servers، سقالات web/arvr/blockchain)",
        "kind": "binary", "bin": "npm",
        "apt": "nodejs npm", "dnf": "nodejs", "pacman": "nodejs npm",
        "brew": "node", "winget": "OpenJS.NodeJS", "choco": "nodejs",
    },
    "gcc": {
        "category": "أدوات تطوير", "label": "GCC (سقالات embedded/kernel_module)",
        "kind": "binary", "bin": "gcc",
        "apt": "build-essential", "dnf": "gcc", "pacman": "base-devel",
        "brew": "gcc", "winget": None,
    },
    "docker": {
        "category": "أدوات تطوير", "label": "Docker (سقالة docker)",
        "kind": "binary", "bin": "docker",
        "apt": "docker.io", "dnf": "docker", "pacman": "docker",
        "brew": "--cask docker", "winget": "Docker.DockerDesktop",
    },
    "kotlinc": {
        "category": "أدوات تطوير", "label": "Kotlin compiler (سقالة android)",
        "kind": "binary", "bin": "kotlinc",
        "apt": None, "brew": "kotlin", "winget": "JetBrains.Kotlin",
    },
    "adb": {
        "category": "أدوات تطوير", "label": "ADB (android_plugin — تحكم في تطبيقات أندرويد)",
        "kind": "binary", "bin": "adb",
        "apt": "android-tools-adb", "dnf": "android-tools", "pacman": "android-tools",
        "brew": "android-platform-tools", "winget": "Google.PlatformTools",
    },

    # ── ذكاء اصطناعي محلي ────────────────────────────────────────────────
    "ollama": {
        "category": "AI محلي", "label": "Ollama (self_improve_plugin/plugin_forge_plugin)",
        "kind": "ollama",
    },

    # ── مكتبات بايثون اختيارية (لمشاريع scaffold المولّدة) ─────────────
    "scikit-learn": {
        "category": "مكتبات سقالات", "label": "scikit-learn (سقالة ml)",
        "kind": "python", "module": "sklearn", "pip": "scikit-learn",
    },
    "qiskit-aer": {
        "category": "مكتبات سقالات", "label": "Qiskit Aer (سقالة quantum)",
        "kind": "python", "module": "qiskit_aer", "pip": "qiskit-aer",
    },
    "pygame": {
        "category": "مكتبات سقالات", "label": "Pygame (سقالة game)",
        "kind": "python", "module": "pygame", "pip": "pygame",
    },
}

_CATEGORY_ORDER = ["الأساسيات", "وسائط", "أمان", "أدوات تطوير", "AI محلي", "مكتبات سقالات"]


def _current_os() -> str:
    return {"Linux": "linux", "Darwin": "macos", "Windows": "windows"}.get(platform.system(), "unknown")


def _linux_pkg_manager() -> str | None:
    for mgr in ("apt", "dnf", "pacman", "apk", "zypper"):
        if shutil.which(mgr):
            return mgr
    return None


def _check_binary(bin_name: str) -> bool:
    return shutil.which(bin_name) is not None


def _check_python(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _check_ollama() -> bool:
    try:
        with urllib.request.urlopen(OLLAMA_URL, timeout=2):
            return True
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _is_installed(key: str) -> bool:
    spec = TOOLS[key]
    kind = spec["kind"]
    if kind == "python":
        return _check_python(spec["module"])
    if kind == "binary":
        return _check_binary(spec["bin"])
    if kind == "binary_or_pip":
        return _check_binary(spec["bin"]) or _check_python(spec["bin"].replace("-", "_"))
    if kind == "ollama":
        return _check_ollama()
    return False


def _install_command_for_current_os(key: str) -> str | None:
    """بيرجع أمر التثبيت المضبوط لنظام تشغيلك الفعلي، أو None لو مفيش
    طريقة معروفة (زي gcc على ويندوز — محتاج MSYS2/MinGW يدوي)."""
    spec = TOOLS[key]
    os_name = _current_os()
    if spec["kind"] == "python":
        return f"{sys.executable} -m pip install {spec['pip']}"
    if spec["kind"] == "binary_or_pip" and "pip" in spec:
        return f"{sys.executable} -m pip install {spec['pip']}"
    if os_name == "linux":
        mgr = _linux_pkg_manager()
        pkg = spec.get(mgr) if mgr else None
        if mgr and pkg:
            sudo_prefix = "sudo " if mgr in ("apt", "dnf", "pacman", "zypper") else ""
            install_verb = {"apt": "install -y", "dnf": "install -y", "pacman": "-S --noconfirm", "zypper": "install -y"}.get(mgr, "install")
            return f"{sudo_prefix}{mgr} {install_verb} {pkg}"
        return None
    if os_name == "macos":
        pkg = spec.get("brew")
        return f"brew install {pkg}" if pkg else None
    if os_name == "windows":
        winget_id = spec.get("winget")
        if winget_id:
            return f"winget install {winget_id}"
        choco_pkg = spec.get("choco")
        return f"choco install {choco_pkg}" if choco_pkg else None
    return None


def _cmd_env_check(ctx) -> str:
    os_name = _current_os()
    lines = [f"🩺 فحص بيئة العمل — النظام المكتشف: {os_name}\n"]

    total = 0
    installed = 0
    for category in _CATEGORY_ORDER:
        items = [k for k, v in TOOLS.items() if v["category"] == category and "same_as" not in v]
        if not items:
            continue
        lines.append(f"📦 {category}:")
        for key in items:
            spec = TOOLS[key]
            ok = _is_installed(key)
            total += 1
            installed += 1 if ok else 0
            if ok:
                lines.append(f"   ✅ {spec['label']}")
            elif spec["kind"] == "ollama":
                lines.append(f"   ❌ {spec['label']} — نزّله يدوي من https://ollama.com وشغّل: ollama pull llama3.2")
            else:
                cmd = _install_command_for_current_os(key)
                hint = f"— ثبّته بـ: {cmd}" if cmd else "— مفيش أمر تثبيت تلقائي معروف لنظامك، دوّر عليه يدوي"
                lines.append(f"   ❌ {spec['label']} {hint}")
        lines.append("")

    lines.append(f"📊 الخلاصة: {installed}/{total} أداة متاحة.")
    if installed < total:
        lines.append(
            "💡 استخدم `env_install <tool>` لتثبيت مكتبة بايثون واحدة "
            "تلقائيًا، أو `env_install_all --yes` تثبّت كل مكتبات "
            "بايثون الناقصة دفعة واحدة. أدوات النظام (زي FFmpeg/Docker) "
            "لازم تتثبت يدويًا بالأمر المعروض فوق — الأداة مش بتشغّل "
            "sudo أو مثبتات نظام تلقائيًا لأي سبب."
        )
    else:
        lines.append("🎉 كل حاجة متاحة!")
    return "\n".join(lines)


def _cmd_env_install(ctx) -> str:
    if not ctx.args:
        return "usage: env_install <tool_key> [--yes]   (env_check يوريك كل الـ tool_key المتاحة)"
    key = ctx.args[0].lower()
    confirm = "--yes" in ctx.args[1:]
    if key not in TOOLS:
        return f"❌ مفيش أداة معروفة بالاسم ده. الأسماء المتاحة: {', '.join(sorted(TOOLS))}"

    spec = TOOLS[key]
    if _is_installed(key):
        return f"✅ {spec['label']} متثبتة بالفعل"

    if spec["kind"] == "ollama":
        return (
            "🤖 Ollama مش حاجة بايثون بتتثبت بـ pip — محتاج تحميل يدوي "
            "من https://ollama.com، وبعدين شغّل: ollama pull llama3.2"
        )

    is_pip_installable = spec["kind"] == "python" or (spec["kind"] == "binary_or_pip" and "pip" in spec)
    cmd = _install_command_for_current_os(key)
    if cmd is None:
        return f"❌ مفيش أمر تثبيت تلقائي معروف لـ {spec['label']} على نظامك — دوّر عليه يدوي"

    if not is_pip_installable:
        return (
            f"📋 {spec['label']} أداة نظام محتاجة صلاحيات — الأداة دي مش "
            f"بتشغّلها تلقائيًا. انسخ وشغّل بنفسك:\n\n   {cmd}"
        )

    if not confirm:
        return f"📋 هيتشغّل: {cmd}\n\nلو موافق، أعد المحاولة بـ: env_install {key} --yes"

    try:
        proc = subprocess.run(cmd.split(), capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return "❌ التثبيت أخد وقت أطول من المتوقع (5 دقايق) واتوقف"
    except OSError as e:
        return f"❌ تعذر تشغيل أمر التثبيت: {e}"

    if proc.returncode != 0:
        return f"❌ فشل تثبيت {spec['label']}:\n{proc.stderr[-1000:]}"
    return f"✅ اتثبتت {spec['label']} بنجاح"


def _cmd_env_install_all(ctx) -> str:
    confirm = "--yes" in ctx.args
    missing = [k for k in TOOLS if not _is_installed(k)]
    if not missing:
        return "🎉 كل الأدوات متاحة بالفعل — مفيش حاجة تتثبت"

    pip_missing = [k for k in missing if TOOLS[k]["kind"] == "python" or (TOOLS[k]["kind"] == "binary_or_pip" and "pip" in TOOLS[k])]
    system_missing = [k for k in missing if k not in pip_missing and TOOLS[k]["kind"] != "ollama"]
    ollama_missing = [k for k in missing if TOOLS[k]["kind"] == "ollama"]

    lines = []
    if pip_missing:
        if not confirm:
            pkgs = ", ".join(TOOLS[k].get("pip", k) for k in pip_missing)
            lines.append(f"📋 مكتبات بايثون هيتثبتوا: {pkgs}\nأعد المحاولة بـ: env_install_all --yes")
        else:
            packages = [TOOLS[k]["pip"] for k in pip_missing]
            lines.append(f"⏳ بتثبيت {len(packages)} مكتبة بايثون...")
            try:
                proc = subprocess.run(
                    [sys.executable, "-m", "pip", "install", *packages],
                    capture_output=True, text=True, timeout=600,
                )
            except subprocess.TimeoutExpired:
                return "❌ التثبيت أخد وقت أطول من المتوقع (10 دقايق) واتوقف"
            except OSError as e:
                return f"❌ تعذر تشغيل pip: {e}"
            if proc.returncode != 0:
                lines.append(f"❌ فشل جزء من التثبيت:\n{proc.stderr[-1000:]}")
            else:
                lines.append(f"✅ اتثبتت {len(packages)} مكتبة بايثون بنجاح")

    if system_missing:
        lines.append("\n📋 أدوات نظام محتاجة تثبيت يدوي (محتاجة صلاحيات — مش بتتثبت تلقائيًا):")
        for k in system_missing:
            cmd = _install_command_for_current_os(k)
            lines.append(f"   • {TOOLS[k]['label']}: {cmd or 'مفيش أمر معروف لنظامك'}")

    if ollama_missing:
        lines.append("\n🤖 Ollama: نزّله يدوي من https://ollama.com وشغّل: ollama pull llama3.2")

    return "\n".join(lines)


def register(engine):
    engine.registry.register("env_check", _cmd_env_check,
                              "env_check — فحص شامل لكل الأدوات/المكتبات اللي نيزوكو ممكن تحتاجها")
    engine.registry.register("env_install", _cmd_env_install,
                              "env_install <tool_key> [--yes] — تثبيت أداة واحدة (تلقائي لمكتبات بايثون فقط)")
    engine.registry.register("env_install_all", _cmd_env_install_all,
                              "env_install_all [--yes] — تثبيت كل مكتبات بايثون الناقصة + عرض أوامر أدوات النظام")
