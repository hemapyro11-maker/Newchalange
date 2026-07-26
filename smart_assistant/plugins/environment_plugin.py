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
        "category": "Core", "label": "CustomTkinter (Nezuko's interface)",
        "kind": "python", "module": "customtkinter", "pip": "customtkinter",
    },
    "mcp": {
        "category": "Core", "label": "MCP (Connectors)",
        "kind": "python", "module": "mcp", "pip": "mcp",
    },
    "capstone": {
        "category": "Core", "label": "Capstone (reverse engineering — re_plugin)",
        "kind": "python", "module": "capstone", "pip": "capstone",
    },
    "pillow": {
        "category": "Core", "label": "Pillow (design_plugin/thumbnail_plugin)",
        "kind": "python", "module": "PIL", "pip": "Pillow",
    },
    "pandas": {
        "category": "Core", "label": "pandas (data_science_plugin)",
        "kind": "python", "module": "pandas", "pip": "pandas",
    },
    "matplotlib": {
        "category": "Core", "label": "matplotlib (data_science_plugin)",
        "kind": "python", "module": "matplotlib", "pip": "matplotlib",
    },
    "edge-tts": {
        "category": "Core", "label": "edge-tts (Nezuko's primary voice)",
        "kind": "python", "module": "edge_tts", "pip": "edge-tts",
    },
    "piper-tts": {
        "category": "Core", "label": "Piper (Nezuko's local voice)",
        "kind": "python", "module": "piper", "pip": "piper-tts",
    },

    # ── وسائط وصوت ──────────────────────────────────────────────────────
    "ffmpeg": {
        "category": "Media", "label": "FFmpeg (media_plugin/cinema_plugin/voice_plugin)",
        "kind": "binary", "bin": "ffmpeg",
        "apt": "ffmpeg", "dnf": "ffmpeg", "pacman": "ffmpeg", "brew": "ffmpeg",
        "winget": "Gyan.FFmpeg", "choco": "ffmpeg",
    },
    "ffprobe": {
        "category": "Media", "label": "FFprobe (media analysis)",
        "kind": "binary", "bin": "ffprobe", "same_as": "ffmpeg",
    },
    "ffplay": {
        "category": "Media", "label": "FFplay (plays Nezuko's voice)",
        "kind": "binary", "bin": "ffplay", "same_as": "ffmpeg",
    },
    "espeak-ng": {
        "category": "Media", "label": "espeak-ng (last-resort voice)",
        "kind": "binary", "bin": "espeak-ng",
        "apt": "espeak-ng", "dnf": "espeak-ng", "pacman": "espeak-ng",
        "brew": "espeak-ng", "winget": "eSpeak-NG.eSpeak-NG",
    },

    # ── أمان ─────────────────────────────────────────────────────────────
    "clamav": {
        "category": "Security", "label": "ClamAV (virus_scan)",
        "kind": "binary", "bin": "clamscan",
        "apt": "clamav", "dnf": "clamav", "pacman": "clamav",
        "brew": "clamav", "winget": "ClamWin.ClamWin",
    },
    "pip-audit": {
        "category": "Security", "label": "pip-audit (vuln_scan)",
        "kind": "binary_or_pip", "bin": "pip-audit", "pip": "pip-audit",
    },

    # ── أدوات تطوير (لتشغيل مشاريع scaffold نفسها + MCP servers) ──────
    "node": {
        "category": "Dev tools", "label": "Node.js/npm (MCP servers; web/arvr/blockchain scaffolds)",
        "kind": "binary", "bin": "npm",
        "apt": "nodejs npm", "dnf": "nodejs", "pacman": "nodejs npm",
        "brew": "node", "winget": "OpenJS.NodeJS", "choco": "nodejs",
    },
    "gcc": {
        "category": "Dev tools", "label": "GCC (embedded and kernel_module scaffolds)",
        "kind": "binary", "bin": "gcc",
        "apt": "build-essential", "dnf": "gcc", "pacman": "base-devel",
        "brew": "gcc", "winget": None,
    },
    "docker": {
        "category": "Dev tools", "label": "Docker (docker scaffold)",
        "kind": "binary", "bin": "docker",
        "apt": "docker.io", "dnf": "docker", "pacman": "docker",
        "brew": "--cask docker", "winget": "Docker.DockerDesktop",
    },
    "kotlinc": {
        "category": "Dev tools", "label": "Kotlin compiler (android scaffold)",
        "kind": "binary", "bin": "kotlinc",
        "apt": None, "brew": "kotlin", "winget": "JetBrains.Kotlin",
    },
    "adb": {
        "category": "Dev tools", "label": "ADB (android_plugin — control Android apps)",
        "kind": "binary", "bin": "adb",
        "apt": "android-tools-adb", "dnf": "android-tools", "pacman": "android-tools",
        "brew": "android-platform-tools", "winget": "Google.PlatformTools",
    },

    # ── ذكاء اصطناعي محلي ────────────────────────────────────────────────
    "ollama": {
        "category": "Local AI", "label": "Ollama (self_improve_plugin/plugin_forge_plugin)",
        "kind": "ollama",
    },

    # ── مكتبات بايثون اختيارية (لمشاريع scaffold المولّدة) ─────────────
    "scikit-learn": {
        "category": "Scaffold libraries", "label": "scikit-learn (ml scaffold)",
        "kind": "python", "module": "sklearn", "pip": "scikit-learn",
    },
    "qiskit-aer": {
        "category": "Scaffold libraries", "label": "Qiskit Aer (quantum scaffold)",
        "kind": "python", "module": "qiskit_aer", "pip": "qiskit-aer",
    },
    "pygame": {
        "category": "Scaffold libraries", "label": "Pygame (game scaffold)",
        "kind": "python", "module": "pygame", "pip": "pygame",
    },
}

_CATEGORY_ORDER = ["Core", "Media", "Security", "Dev tools", "Local AI", "Scaffold libraries"]


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
    if "same_as" in spec:
        # ffprobe/ffplay مالهومش باكدج منفصل — بييجوا مع تثبيت ffmpeg
        spec = TOOLS[spec["same_as"]]
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
    lines = [f"🩺 Environment check — detected system: {os_name}\n"]

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
                lines.append(f"   ❌ {spec['label']} — install it yourself from https://ollama.com then run: ollama pull llama3.2")
            else:
                cmd = _install_command_for_current_os(key)
                hint = f"— install with: {cmd}" if cmd else "— no known automatic install command for your system; find it yourself"
                lines.append(f"   ❌ {spec['label']} {hint}")
        lines.append("")

    lines.append(f"📊 Summary: {installed}/{total} tools available.")
    if installed < total:
        lines.append(
            "💡 Use `env_install <tool>` to install a single Python package "
            "automatically, or `env_install_all --yes` to install every missing "
            "Python package at once. System tools (FFmpeg, Docker and the like) "
            "must be installed by hand using the command shown above — this never "
            "runs sudo or a system installer on your behalf, for any reason."
        )
    else:
        lines.append("🎉 Everything is available!")
    return "\n".join(lines)


def _cmd_env_install(ctx) -> str:
    if not ctx.args:
        return "usage: env_install <tool_key> [--yes]   (env_check lists every available tool_key)"
    key = ctx.args[0].lower()
    confirm = "--yes" in ctx.args[1:]
    if key not in TOOLS:
        return f"❌ no tool by that name. Available: {', '.join(sorted(TOOLS))}"

    spec = TOOLS[key]
    if _is_installed(key):
        return f"✅ {spec['label']} is already installed"

    if spec["kind"] == "ollama":
        return (
            "🤖 Ollama is not a Python package installable with pip — download it "
            "from https://ollama.com, then run: ollama pull llama3.2"
        )

    is_pip_installable = spec["kind"] == "python" or (spec["kind"] == "binary_or_pip" and "pip" in spec)
    cmd = _install_command_for_current_os(key)
    if cmd is None:
        return f"❌ no known automatic install command for {spec['label']} on your system — find it yourself"

    if not is_pip_installable:
        return (
            f"📋 {spec['label']} is a system tool needing privileges — this never "
            f"runs it for you. Copy and run it yourself:\n\n   {cmd}"
        )

    if not confirm:
        return f"📋 Would run: {cmd}\n\nIf that is fine, run it again as: env_install {key} --yes"

    try:
        proc = subprocess.run(cmd.split(), capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return "❌ the install took longer than expected (5 minutes) and was stopped"
    except OSError as e:
        return f"❌ could not run the install command: {e}"

    if proc.returncode != 0:
        return f"❌ installing {spec['label']} failed:\n{proc.stderr[-1000:]}"
    return f"✅ {spec['label']} installed successfully"


def _cmd_env_install_all(ctx) -> str:
    confirm = "--yes" in ctx.args
    missing = [k for k in TOOLS if not _is_installed(k)]
    if not missing:
        return "🎉 Every tool is already available — nothing to install"

    pip_missing = [k for k in missing if TOOLS[k]["kind"] == "python" or (TOOLS[k]["kind"] == "binary_or_pip" and "pip" in TOOLS[k])]
    system_missing = [k for k in missing if k not in pip_missing and TOOLS[k]["kind"] != "ollama"]
    ollama_missing = [k for k in missing if TOOLS[k]["kind"] == "ollama"]

    lines = []
    if pip_missing:
        if not confirm:
            pkgs = ", ".join(TOOLS[k].get("pip", k) for k in pip_missing)
            lines.append(f"📋 Python packages that would be installed: {pkgs}\nRun it again as: env_install_all --yes")
        else:
            packages = [TOOLS[k]["pip"] for k in pip_missing]
            lines.append(f"⏳ installing {len(packages)} Python packages...")
            try:
                proc = subprocess.run(
                    [sys.executable, "-m", "pip", "install", *packages],
                    capture_output=True, text=True, timeout=600,
                )
            except subprocess.TimeoutExpired:
                return "❌ the install took longer than expected (10 minutes) and was stopped"
            except OSError as e:
                return f"❌ could not run pip: {e}"
            if proc.returncode != 0:
                lines.append(f"❌ part of the install failed:\n{proc.stderr[-1000:]}")
            else:
                lines.append(f"✅ installed {len(packages)} Python packages successfully")

    if system_missing:
        lines.append("\n📋 System tools needing manual installation (they require privileges, so they are never installed automatically):")
        for k in system_missing:
            cmd = _install_command_for_current_os(k)
            lines.append(f"   • {TOOLS[k]['label']}: {cmd or 'no known command for your system'}")

    if ollama_missing:
        lines.append("\n🤖 Ollama: install it yourself from https://ollama.com then run: ollama pull llama3.2")

    return "\n".join(lines)


def register(engine):
    engine.registry.register("env_check", _cmd_env_check,
                              "env_check — check every tool and library Nezuko might need")
    engine.registry.register("env_install", _cmd_env_install,
                              "env_install <tool_key> [--yes] — install one tool (automatic for Python packages only)")
    engine.registry.register("env_install_all", _cmd_env_install_all,
                              "env_install_all [--yes] — install every missing Python package and print the system-tool commands")
