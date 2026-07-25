"""
core_engine.py — Core Engine للمساعد الذكي، بدون أي اعتماد على الواجهة.

مسؤول عن: تسجيل الأوامر (Command Registry)، تنفيذها بالتتابع على Thread
خلفي واحد (Task Queue) عشان الواجهة تفضل سلسة، تحميل الإضافات (Plugins)
ديناميكياً من مجلد plugins/ عشان المشروع يتوسع بسهولة من غير ما نلمس
الكود الأساسي، وتشغيل مهام أتمتة إضافية (callables) بنفس الآلية.
"""
from __future__ import annotations

import datetime
import difflib
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
import urllib.error
import urllib.request
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

log = logging.getLogger("assistant.core")

CommandHandler = Callable[["CommandContext"], str | None]

# عنصر فريد (object identity، مش نص) لإشارة الإيقاف جوه الطابور —
# لو استخدمنا نص عادي زي "__stop__" بدل كده، أي مستخدم يكتب "__stop__"
# فعليًا كنص أمر (أو نص جاي من macro/schedule/لصق) كان هيوقف الـ worker
# thread بصمت زي لو stop() اتنادت فعلاً، من غير أي رسالة أو تحذير.
# عنصر object() فريد مينفعش أي نص مكتوب "يطابقه" أبداً.
_STOP_SENTINEL = object()

# ── فهم النية (intent understanding) — الأمر مش متطابق حرفيًا؟ ─────────
# مرحلتين: (1) تصحيح إملائي زيرو-كوست دايمًا شغال (difflib، بدون أي
# اعتماد خارجي)، وبعدين (2) لو مفيش تصحيح واضح، محاولة فهم نية حرة عبر
# نموذج Ollama محلي مجاني (لو المستخدم مشغّله) — بنفس الـ endpoint اللي
# self_improve_plugin/plugin_forge_plugin بيستخدموه بالظبط. الاقتراحين
# مبيتنفذوش تلقائي أبدًا — لازم تأكيد صريح (y) زي أي حاجة تانية في
# المشروع ده، اتساقاً مع مبدأ "مفيش تنفيذ من غير أمر واضح".
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_INTENT_MODEL = "llama3.2"
OLLAMA_INTENT_TIMEOUT = 10
FUZZY_CUTOFF = 0.6
_CONFIRM_YES = {"y", "yes", "نعم", "أيوه", "ايوه", "اه", "آه", "تمام"}
_CONFIRM_NO = {"n", "no", "لا", "لأ"}


@dataclass
class CommandContext:
    """يوصل معلومات الأمر الحالي لمنطق التنفيذ (raw text, args, المحرك نفسه)."""
    raw: str
    args: list[str]
    engine: AssistantEngine


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

    def get(self, name: str) -> Command | None:
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

    def __init__(self, on_log=None, on_status=None, plugins_dirs: list[pathlib.Path] | None = None):
        self.on_log = on_log or (lambda msg, level="info": None)
        self.on_status = on_status or (lambda status: None)
        self.registry = CommandRegistry()
        self.log_history: deque[tuple[str, str]] = deque(maxlen=300)
        self.plugins_dirs = plugins_dirs or default_plugin_dirs()
        self._loaded_plugins: list[str] = []
        self.skills_path = default_state_dir() / "skills.json"
        self.skills = self._load_skills()
        self._queue: queue.Queue[tuple[str, object | None]] = queue.Queue()
        self._stop_flag = threading.Event()
        self._worker: threading.Thread | None = None
        self._pending_intent: tuple[str, list[str], str] | None = None
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
        self._queue.put(("", _STOP_SENTINEL))

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
            if fn is _STOP_SENTINEL:
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

        if self._pending_intent is not None:
            pending, self._pending_intent = self._pending_intent, None
            reply = text.lower()
            if reply in _CONFIRM_YES:
                pending_name, pending_args, pending_raw = pending
                self._log(f"↪ بينفذ: {pending_name} {' '.join(pending_args)}".strip(), "info")
                # لازم نبعت النص الأصلي (pending_raw)، مش رد التأكيد ("y")
                # نفسه — بعض الإضافات (زي database_plugin.py, connectors_plugin.py)
                # بتقرا ctx.raw مباشرة (مش ctx.args) عشان تتفادى مشاكل
                # shlex.split مع نصوص فيها JSON/SQL، فلو بعتنا "y" هنا
                # كانت هتشتغل على نص فاضي بدل الأمر اللي المستخدم أكّده فعلاً.
                self._execute(pending_name, pending_args, pending_raw)
                return
            if reply in _CONFIRM_NO:
                self._log("❌ اتلغى", "info")
                return
            # مش y ولا n — نسيب الاقتراح القديم ونعالج النص الجديد عادي

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
            suggestion = self._suggest_command(name, args)
            if suggestion:
                sugg_name, sugg_args, message, level = suggestion
                self._pending_intent = (sugg_name, sugg_args, text)
                self._log(message, level)
            else:
                self._log(f"❓ unknown command: {name} (try 'help')", "warn")
            return
        self._execute(name, args, text)

    def _execute(self, name: str, args: list[str], raw: str):
        cmd = self.registry.get(name)
        if cmd is None:
            self._log(f"❓ unknown command: {name} (try 'help')", "warn")
            return
        ctx = CommandContext(raw=raw, args=args, engine=self)
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

    # ── فهم النية (مش تطابق حرفي) ──────────────────────────────────────
    def _suggest_command(self, name: str, args: list[str]) -> tuple[str, list[str], str, str] | None:
        """بترجع (اسم الأمر المقترح، وسائطه، رسالة العرض، مستوى اللوج)
        أو None لو مفيش اقتراح — مبتنفذش حاجة بنفسها أبدًا، بس بترشّح."""
        known = [c.name for c in self.registry.list_commands()]
        close = difflib.get_close_matches(name.lower(), known, n=1, cutoff=FUZZY_CUTOFF)
        if close:
            return (
                close[0], args,
                f"❓ أمر مش معروف: {name}\n🤔 قصدك \"{close[0]}\"؟ اكتب y للتنفيذ أو أي حاجة تانية للإلغاء.",
                "warn",
            )

        raw_text = " ".join([name, *args])
        intent = self._try_llm_intent(raw_text)
        if intent is not None:
            intent_name, intent_args = intent
            shown = f"{intent_name} {' '.join(intent_args)}".strip()
            return (
                intent_name, intent_args,
                f"🧠 Ollama فهم قصدك: {shown}\nنفّذها؟ اكتب y للتأكيد أو أي حاجة تانية للإلغاء.",
                "info",
            )
        return None

    def _try_llm_intent(self, text: str) -> tuple[str, list[str]] | None:
        """بيحاول يفهم نص حر (عربي/إنجليزي) عبر نموذج Ollama محلي مجاني
        (لو شغال) ويطابقه مع أقرب أمر حقيقي مسجّل فعلاً. بيرجع None
        بهدوء تام لو Ollama مش شغال، أو لو ردّ باسم أمر مش موجود أصلاً —
        محدش بيصدّق النموذج أعمى، لازم يتحقق من الـ registry الحقيقي."""
        commands = self.registry.list_commands()
        if not commands:
            return None
        catalog = "\n".join(f"{c.name} — {c.description}" for c in commands)
        prompt = (
            "You are a command router for a desktop assistant app. Given the user's "
            "free-text request (Arabic or English) and the list of available commands "
            "below, reply with ONLY the exact command line to run — the command name "
            "followed by any arguments you can extract from the request. No explanation, "
            "no markdown, nothing else. If nothing genuinely matches, reply with exactly: NONE\n\n"
            f"Available commands:\n{catalog}\n\n"
            f"User request: {text}\n\n"
            "Command line:"
        )
        payload = json.dumps({"model": OLLAMA_INTENT_MODEL, "prompt": prompt, "stream": False}).encode("utf-8")
        req = urllib.request.Request(
            OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=OLLAMA_INTENT_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError, json.JSONDecodeError):
            return None
        reply = data.get("response", "").strip()
        if not reply or reply.upper() == "NONE":
            return None
        try:
            reply_parts = shlex.split(reply)
        except ValueError:
            return None
        if not reply_parts:
            return None
        guessed_name, guessed_args = reply_parts[0], reply_parts[1:]
        if self.registry.get(guessed_name) is None:
            # النموذج هلوس اسم أمر مش موجود فعليًا — نتجاهله بدل ما نصدّقه
            return None
        return guessed_name, guessed_args
