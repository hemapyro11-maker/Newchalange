"""
core_engine.py — Core Engine للمساعد الذكي، بدون أي اعتماد على الواجهة.

مسؤول عن: تسجيل الأوامر (Command Registry)، تنفيذها بالتتابع على Thread
خلفي واحد (Task Queue) عشان الواجهة تفضل سلسة، تحميل الإضافات (Plugins)
ديناميكياً من مجلد plugins/ عشان المشروع يتوسع بسهولة من غير ما نلمس
الكود الأساسي، وتشغيل مهام أتمتة إضافية (callables) بنفس الآلية.
"""
from __future__ import annotations

import datetime
import importlib.util
import json
import logging
import pathlib
import queue
import shlex
import subprocess
import sys
import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass
from typing import Callable, Optional

log = logging.getLogger("assistant.core")

CommandHandler = Callable[["CommandContext"], Optional[str]]


@dataclass
class CommandContext:
    """يوصل معلومات الأمر الحالي لمنطق التنفيذ (raw text, args, المحرك نفسه)."""
    raw: str
    args: list[str]
    engine: "AssistantEngine"


@dataclass
class Command:
    name: str
    handler: CommandHandler
    description: str = ""


class CommandRegistry:
    def __init__(self):
        self._commands: dict[str, Command] = {}

    def register(self, name: str, handler: CommandHandler, description: str = ""):
        self._commands[name.lower()] = Command(name.lower(), handler, description)

    def unregister(self, name: str):
        self._commands.pop(name.lower(), None)

    def get(self, name: str) -> Optional[Command]:
        return self._commands.get(name.lower())

    def list_commands(self) -> list[Command]:
        return sorted(self._commands.values(), key=lambda c: c.name)


def default_state_dir() -> pathlib.Path:
    """مجلد ملفات الحالة الدائمة (زي skills.json) — جنب الـ exe أو جنب هذا الملف."""
    if getattr(sys, "frozen", False):
        return pathlib.Path(sys.executable).resolve().parent
    return pathlib.Path(__file__).resolve().parent


def default_plugin_dirs() -> list[pathlib.Path]:
    """
    مجلدات الإضافات: لو التطبيق شغال كـ exe (PyInstaller onefile)، بنرجع
    مجلد الإضافات المدمجة جوه الـ bundle *و* مجلد plugins/ جنب ملف الـ exe
    نفسه (عشان المستخدم يقدر يضيف إضافات جديدة بمجرد ما يحط ملف .py فيه،
    من غير ما يعيد بناء التطبيق). في وضع التطوير العادي بنرجع plugins/
    جنب هذا الملف.
    """
    dirs: list[pathlib.Path] = []
    if getattr(sys, "frozen", False):
        bundled = pathlib.Path(getattr(sys, "_MEIPASS", "")) / "plugins"
        if bundled.exists():
            dirs.append(bundled)
        dirs.append(pathlib.Path(sys.executable).resolve().parent / "plugins")
    else:
        dirs.append(pathlib.Path(__file__).resolve().parent / "plugins")
    seen: set[pathlib.Path] = set()
    unique: list[pathlib.Path] = []
    for d in dirs:
        key = d.resolve() if d.exists() else d
        if key not in seen:
            seen.add(key)
            unique.append(d)
    return unique


class AssistantEngine:
    """
    المحرك الأساسي: يستقبل نصوص أوامر أو مهام أتمتة (callables) ويشغّلهم
    بالتتابع على Thread خلفي واحد، ويبلغ الواجهة بالنتائج عبر callbacks،
    ويحمّل إضافات (plugins) ديناميكياً لتوسيع الأوامر المتاحة.
    """

    def __init__(self, on_log=None, on_status=None, plugins_dirs: Optional[list[pathlib.Path]] = None):
        self.on_log = on_log or (lambda msg, level="info": None)
        self.on_status = on_status or (lambda status: None)
        self.registry = CommandRegistry()
        self.log_history: "deque[tuple[str, str]]" = deque(maxlen=300)
        self.plugins_dirs = plugins_dirs or default_plugin_dirs()
        self._loaded_plugins: list[str] = []
        self.skills_path = default_state_dir() / "skills.json"
        self.skills = self._load_skills()
        self._queue: "queue.Queue[tuple[str, Optional[Callable]]]" = queue.Queue()
        self._stop_flag = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._register_builtin_commands()
        self.load_plugins()

    # ── skills ledger (تعلّم تراكمي دائم — بيتراكم ومبيتنساش) ─────────
    def _load_skills(self) -> dict:
        if self.skills_path.exists():
            try:
                return json.loads(self.skills_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"plugins": {}, "commands": {}}

    def _save_skills(self):
        try:
            self.skills_path.write_text(
                json.dumps(self.skills, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            pass

    def _record_plugin_learned(self, name: str):
        """يسجل إن الإضافة دي اتعلمت — إدخال إضافي بس، مبيتمسحش حتى لو
        الإضافة نفسها اتشالت بعدين، عشان المهارة تفضل معروفة إنها اتعلمت."""
        if name not in self.skills["plugins"]:
            self.skills["plugins"][name] = {
                "first_seen": datetime.datetime.now().isoformat(timespec="seconds"),
            }
            self._save_skills()

    def _record_command_used(self, name: str):
        entry = self.skills["commands"].setdefault(name, {"count": 0, "first_used": None})
        entry["count"] += 1
        entry["last_used"] = datetime.datetime.now().isoformat(timespec="seconds")
        if entry["first_used"] is None:
            entry["first_used"] = entry["last_used"]
        self._save_skills()

    # ── lifecycle ──────────────────────────────────────────────────────
    def start(self):
        if self._worker and self._worker.is_alive():
            return
        self._stop_flag.clear()
        self._worker = threading.Thread(target=self._run_loop, daemon=True)
        self._worker.start()
        self.on_status("running")

    def stop(self):
        if not self.is_running():
            return
        self._stop_flag.set()
        self._queue.put(("__stop__", None))

    def is_running(self) -> bool:
        return bool(self._worker and self._worker.is_alive())

    # ── public API ─────────────────────────────────────────────────────
    def submit(self, text: str):
        """يضيف أمر (نص من المستخدم) لطابور التنفيذ."""
        self._queue.put((text, None))

    def run_task(self, name: str, fn: Callable[[CommandContext], None]):
        """يضيف مهمة أتمتة (callable) لنفس طابور التنفيذ."""
        self._queue.put((name, fn))

    # ── plugins ────────────────────────────────────────────────────────
    def load_plugins(self) -> list[str]:
        """
        يمسح مجلدات الإضافات ويحمّل أي ملف .py فيه دالة register(engine).
        بيُستدعى عند الإنشاء، وبيتقدر يتنادى تاني وقت التشغيل (أمر
        reload_plugins) عشان يلتقط إضافات جديدة اتحطت من غير ريستارت.
        """
        loaded: list[str] = []
        for plugins_dir in self.plugins_dirs:
            plugins_dir.mkdir(parents=True, exist_ok=True)
            for path in sorted(plugins_dir.glob("*.py")):
                if path.name.startswith("_"):
                    continue
                try:
                    spec = importlib.util.spec_from_file_location(f"assistant_plugin_{path.stem}", path)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)  # type: ignore[union-attr]
                    register = getattr(module, "register", None)
                    if not callable(register):
                        self._log(f"⚠ plugin {path.stem} has no register(engine)", "warn")
                        continue
                    register(self)
                    loaded.append(path.stem)
                    self._record_plugin_learned(path.stem)
                    self._log(f"🧩 plugin loaded: {path.stem}", "ok")
                except Exception:
                    self._log(f"❌ failed to load plugin {path.name}:\n{traceback.format_exc()}", "error")
        # self._loaded_plugins بيعكس نتيجة آخر مسح بس (مش تراكمي) — عشان
        # أمر "plugins" يفضل صادق لو ملف اتشال والمستخدم عمل reload_plugins.
        # (سجل "اتعلمت قبل كده" الدائم هو self.skills["plugins"] مش ده.)
        self._loaded_plugins = sorted(loaded)
        return loaded

    # ── builtin commands ──────────────────────────────────────────────
    def _register_builtin_commands(self):
        self.registry.register("help", self._cmd_help, "عرض كل الأوامر المتاحة")
        self.registry.register("echo", self._cmd_echo, "طباعة نص")
        self.registry.register("run", self._cmd_run, "تنفيذ أمر نظام (subprocess, بدون shell)")
        self.registry.register("plugins", self._cmd_plugins, "عرض الإضافات المحمّلة حالياً")
        self.registry.register("reload_plugins", self._cmd_reload_plugins, "إعادة مسح مجلد plugins/ وتحميل أي إضافة جديدة")
        self.registry.register("skills", self._cmd_skills, "عرض كل المهارات (إضافات/أوامر) اللي اتعلمتها من الأول — تراكمي ومبيتنساش")

    def _cmd_help(self, ctx: CommandContext) -> str:
        return "\n".join(f"{c.name} — {c.description}" for c in self.registry.list_commands())

    def _cmd_echo(self, ctx: CommandContext) -> str:
        return " ".join(ctx.args)

    def _cmd_run(self, ctx: CommandContext) -> str:
        if not ctx.args:
            return "usage: run <command> [args...]"
        try:
            result = subprocess.run(
                ctx.args, capture_output=True, text=True, timeout=30, shell=False,
            )
            out = (result.stdout or "") + (result.stderr or "")
            return out.strip() or f"(exit code {result.returncode})"
        except FileNotFoundError:
            return f"❌ command not found: {ctx.args[0]}"
        except subprocess.TimeoutExpired:
            return "⏱ timeout (30s)"
        except Exception as e:
            return f"❌ error: {e}"

    def _cmd_plugins(self, ctx: CommandContext) -> str:
        if not self._loaded_plugins:
            return "no plugins loaded — drop a .py file with a register(engine) function into plugins/"
        return "loaded plugins: " + ", ".join(self._loaded_plugins)

    def _cmd_reload_plugins(self, ctx: CommandContext) -> str:
        before = set(self._loaded_plugins)
        self.load_plugins()
        new = sorted(set(self._loaded_plugins) - before)
        return f"reload done — {len(new)} new plugin(s): {', '.join(new) or 'none'}"

    def _cmd_skills(self, ctx: CommandContext) -> str:
        plugins = self.skills.get("plugins", {})
        commands = self.skills.get("commands", {})
        lines = [f"🧠 {len(plugins)} إضافة اتعلمتها، {len(commands)} أمر مختلف استخدمتهم من الأول:"]
        for name, info in sorted(plugins.items()):
            lines.append(f"  🧩 {name} — من {info.get('first_seen', '?')}")
        top = sorted(commands.items(), key=lambda kv: -kv[1]["count"])[:10]
        if top:
            lines.append("أكتر الأوامر استخداماً:")
            for name, info in top:
                lines.append(f"  • {name} — {info['count']} مرة")
        return "\n".join(lines)

    # ── internal ───────────────────────────────────────────────────────
    def _log(self, msg: str, level: str = "info"):
        self.log_history.append((level, msg))
        self.on_log(msg, level)

    def _run_loop(self):
        while not self._stop_flag.is_set():
            try:
                text, fn = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if text == "__stop__" and fn is None:
                break
            try:
                if fn is not None:
                    fn(CommandContext(raw=text, args=[], engine=self))
                else:
                    self._dispatch(text)
            except Exception:
                self._log(traceback.format_exc(), "error")
        self.on_status("stopped")

    def _dispatch(self, text: str):
        text = text.strip()
        if not text:
            return
        try:
            parts = shlex.split(text)
        except ValueError as e:
            self._log(f"❌ parse error: {e}", "error")
            return
        if not parts:
            return
        name, args = parts[0], parts[1:]
        cmd = self.registry.get(name)
        if cmd is None:
            self._log(f"❓ unknown command: {name} (try 'help')", "warn")
            return
        ctx = CommandContext(raw=text, args=args, engine=self)
        start = time.time()
        try:
            result = cmd.handler(ctx)
        except Exception:
            self._log(traceback.format_exc(), "error")
            return
        self._record_command_used(name)
        log.debug("command %s finished in %.3fs", name, time.time() - start)
        if result:
            self._log(str(result), "info")
