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
import re
import shlex
import subprocess
import sys
import threading
import time
import traceback
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

import brain
import hooks
import intents
import permissions
import sessions
import styles

log = logging.getLogger("assistant.core")

CommandHandler = Callable[["CommandContext"], str | None]

# عنصر فريد (object identity، مش نص) لإشارة الإيقاف جوه الطابور —
# لو استخدمنا نص عادي زي "__stop__" بدل كده، أي مستخدم يكتب "__stop__"
# فعليًا كنص أمر (أو نص جاي من macro/schedule/لصق) كان هيوقف الـ worker
# thread بصمت زي لو stop() اتنادت فعلاً، من غير أي رسالة أو تحذير.
# عنصر object() فريد مينفعش أي نص مكتوب "يطابقه" أبداً.
_STOP_SENTINEL = object()

# الأوامر الجاية من hook بتتعلّم بالعلامة دي عشان تنفيذها ميولّدش
# أحداث جديدة — من غير كده، hook مربوط بـ after_command بيشغّل أمر،
# والأمر ده بيطلّع after_command تاني، وهكذا بلا نهاية.
_HOOK_SENTINEL = object()

# ── فهم النية: أربع مراحل، أرخصها الأول ──────────────────────────────
#
#   1. أمر مطابق حرفيًا            → 🆓 صفر حصة
#   2. قاموس محلي + ذاكرة متعلّمة  → 🆓 صفر حصة   (intents.py)
#   3. تصحيح إملائي (difflib)      → 🆓 صفر حصة
#   4. محادثة مع المخ              → ⚡ نداء واحد (brain.py)
#
# المراحل التلاتة الأولى بتغطي ~96% من الأوامر المسجّلة، فالمخ مبيتنداش
# إلا للكلام اللي فعلاً محتاج فهم. ولما المخ يفهم صيغة جديدة والمستخدم
# يأكّدها، بنحفظها في القاموس المتعلّم — فنفس الصيغة تاني مرة بتبقى 🆓.
#
# مبدأ ثابت مش بيتكسر: **مفيش تنفيذ تلقائي لأي أمر اقترحه نموذج**.
# لازم تأكيد صريح (y) قبل أي تنفيذ، زي باقي المشروع بالظبط.
FUZZY_CUTOFF = 0.6
_CONFIRM_YES = {"y", "yes", "نعم", "أيوه", "ايوه", "اه", "آه", "تمام"}
_CONFIRM_NO = {"n", "no", "لا", "لأ"}
# "اسمح دايمًا" — بينفذ وبيضيف الأمر لقايمة المسموح (permissions.py)
_CONFIRM_ALWAYS = {"a", "always", "دايما", "دايمًا", "اسمح"}

# أقصى عدد رسائل بنحتفظ بيها في محادثة المخ (brain.py بيقصّها كمان حسب
# سياق المزوّد النشط، ده حد أعلى إضافي عشان الذاكرة متكبرش بلا نهاية)
_MAX_CHAT_TURNS = 30

_SYSTEM_PROMPT = (
    "أنتي نيزوكو، مساعدة ذكية مصرية بتتكلمي عامية مصرية طبيعية ومختصرة. "
    "بتشتغلي جوه برنامج على جهاز المستخدم، وعندك أدوات حقيقية تقدري تشغّليها.\n\n"
    "لو المستخدم عايز حاجة محتاجة أداة، اكتبي سطر لوحده بالشكل ده بالظبط:\n"
    "TOOL: <اسم_الأمر> <الوسائط>\n\n"
    "قواعد مهمة:\n"
    "- استخدمي بس الأوامر الموجودة في القايمة تحت. متخترعيش أسماء أوامر.\n"
    "- لو السؤال عادي (سلام، رأي، شرح) جاوبي عادي من غير أي TOOL.\n"
    "- سطر TOOL لازم يكون آخر حاجة في ردك، ومعاه سطر واحد بس بيشرح ليه.\n"
    "- متقوليش إنك نفّذتي حاجة — المستخدم لازم يأكّد الأول.\n"
)


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
        # وسائط ناقصة لأمر اتعرف محليًا (زي مسار ملف) — بتتملي من رسالة
        # المستخدم الجاية، وكل ده **بصفر حصة** (مفيش نموذج بيتنادى)
        self._pending_args: tuple[str, list[str], list, str] | None = None
        # محادثة المخ (مش متسجّلة على القرص — بتتصفّر مع كل تشغيل)
        self.chat_history: list[dict] = []
        # معرّف الجلسة الحالية — المحادثة بتتحفظ على القرص بعد كل
        # دور، فقفل البرنامج مبيضيّعش الكلام زي الأول
        self.session_id = sessions.new_id()
        self._in_hook = False
        # الواجهة بتحطه عشان تفتح نافذة اختيار ملف بدل ما تسأل بالنص
        self.on_need_file = None
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
        hooks.fire(self, "startup")

    def stop(self):
        if not self.is_running():
            return
        hooks.fire(self, "session_end")
        self._stop_flag.set()
        self._queue.put(("", _STOP_SENTINEL))

    def is_running(self) -> bool:
        return bool(self._worker and self._worker.is_alive())

    # ── public API ─────────────────────────────────────────────────────
    def submit(self, text: str):
        """يضيف أمر (نص من المستخدم) لطابور التنفيذ."""
        self._queue.put((text, None))

    def submit_hook(self, text: str):
        """إرسال من hook — بيمشي في نفس الطابور والفحوصات، بس
        تنفيذه مبيطلّعش أحداث جديدة (منعًا للتكرار اللانهائي)."""
        self._queue.put((text, _HOOK_SENTINEL))

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
                if fn is _HOOK_SENTINEL:
                    self._in_hook = True
                    try:
                        self._dispatch(text)
                    finally:
                        self._in_hook = False
                elif fn is not None:
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
            if reply in _CONFIRM_ALWAYS:
                pending_name, pending_args, pending_raw = pending
                ok, message = permissions.allow(pending_name)
                self._log(message, "ok" if ok else "warn")
                if ok:
                    intents.remember(pending_raw, pending_name)
                    self._execute(pending_name, pending_args, pending_raw)
                return
            if reply in _CONFIRM_YES:
                pending_name, pending_args, pending_raw = pending
                # المستخدم أكّد إن الصيغة دي معناها الأمر ده — نحفظها
                # في القاموس المتعلّم عشان نفس الصيغة تاني مرة تتحل
                # محليًا بصفر حصة، من غير ما نسأل المخ تاني أبدًا.
                intents.remember(pending_raw, pending_name)
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

        # وسيطة ناقصة مستنية؟ الرسالة دي هي الإجابة — كل ده 🆓
        if self._pending_args is not None and self._fill_pending_arg(text):
            return

        known = {c.name for c in self.registry.list_commands()}

        # ── 1+2: أمر مطابق، أو قاموس محلي، أو ذاكرة متعلّمة — كله 🆓 ──
        match = intents.resolve(text, known)
        if match is not None:
            if match.source == "exact":
                try:
                    parts = shlex.split(text)
                except ValueError as e:
                    self._log(f"❌ parse error: {e}", "error")
                    return
                self._execute(parts[0], parts[1:], text)
                return
            if match.is_complete():
                self._log(f"↪ {match.command_line()}", "info")
                self._execute(match.command, match.args, match.command_line())
                return
            # اتعرف الأمر بس ناقصه وسيطة — نسأل عليها من غير أي نموذج
            self._ask_for_arg(match, text)
            return

        # ── 3: تصحيح إملائي — 🆓 ──
        try:
            first = shlex.split(text)[0]
        except (ValueError, IndexError):
            first = text.split(maxsplit=1)[0] if text.split() else ""
        close = difflib.get_close_matches(first.lower(), sorted(known), n=1, cutoff=FUZZY_CUTOFF)
        if close:
            rest = text.split(maxsplit=1)
            args = shlex.split(rest[1]) if len(rest) > 1 else []
            self._pending_intent = (close[0], args, text)
            self._log(
                f"❓ أمر مش معروف: {first}\n"
                f'🤔 قصدك "{close[0]}"؟ اكتب y للتنفيذ أو أي حاجة تانية للإلغاء.',
                "warn",
            )
            return

        # ── 4: المخ — ⚡ نداء واحد ──
        self._converse_async(text)

    # ── ملء الوسائط الناقصة محليًا (بصفر حصة) ─────────────────────────
    def _ask_for_arg(self, match, original_text: str):
        """أمر اتعرف محليًا بس ناقصه وسيطة (زي مسار ملف).

        بنسأل المستخدم مباشرة بدل ما نستدعي نموذج — الأمر نفسه معروف
        بالفعل، اللي ناقص بيانات مش فهم.
        """
        spec = match.missing[0]
        self._pending_args = (match.command, list(match.args), list(match.missing), original_text)
        if spec.kind in (intents.FILE, intents.DIR) and callable(self.on_need_file):
            # الواجهة هتفتح نافذة اختيار — أسرع وأنضف من كتابة المسار
            self.on_need_file(spec, self._submit_arg_value)
            return
        prompt = spec.prompt or "محتاجة الحاجة الناقصة دي"
        self._log(f"📝 {prompt} — ابعتهالي في رسالة جاية (أو اكتب: إلغاء)", "warn")

    def _submit_arg_value(self, value: str):
        """بتتنادى من الواجهة لما المستخدم يختار ملف من النافذة."""
        if value:
            self.submit(value)
        else:
            self._pending_args = None

    def _fill_pending_arg(self, text: str) -> bool:
        """بتحط قيمة في أول وسيطة ناقصة. بترجع True لو استهلكت الرسالة."""
        command, args, missing, original = self._pending_args
        if intents.normalize(text) in {"الغاء", "إلغاء", "cancel", "لا"}:
            self._pending_args = None
            self._log("❌ اتلغى", "info")
            return True

        missing.pop(0)
        args.append(text.strip())
        # ملف الخرج بيتشتق من ملف الدخل اللي المستخدم لسه مدخله
        while missing and missing[0].kind == intents.OUT:
            args.append(intents.derive_output(args[0], missing.pop(0)))
        if missing:
            self._pending_args = (command, args, missing, original)
            nxt = missing[0]
            if nxt.kind in (intents.FILE, intents.DIR) and callable(self.on_need_file):
                self.on_need_file(nxt, self._submit_arg_value)
            else:
                self._log(f"📝 {nxt.prompt or 'الحاجة الجاية'}", "warn")
            return True

        self._pending_args = None
        line = intents.IntentMatch(command, args).command_line()
        self._log(f"↪ {line}", "info")
        self._execute(command, args, line)
        return True

    def _execute(self, name: str, args: list[str], raw: str):
        cmd = self.registry.get(name)
        if cmd is None:
            self._log(f"❓ unknown command: {name} (try 'help')", "warn")
            return
        ctx = CommandContext(raw=raw, args=args, engine=self)
        start = time.time()
        if not self._in_hook:
            hooks.fire(self, "before_command", command=name)
        try:
            result = cmd.handler(ctx)
        except Exception:
            self._log(traceback.format_exc(), "error")
            if not self._in_hook:
                hooks.fire(self, "on_error", command=name)
            return
        self._record_command_used(name)
        log.debug("command %s finished in %.3fs", name, time.time() - start)
        if result:
            self._log(str(result), "info")
        if not self._in_hook:
            hooks.fire(self, "after_command", command=name)

    # ── محادثة مع المخ (المرحلة الوحيدة اللي بتستهلك حصة) ─────────────
    def _tool_catalog(self) -> str:
        return "\n".join(
            f"{c.name} — {c.description}" for c in self.registry.list_commands()
        )

    def _converse_async(self, text: str):
        """بينادي المخ على thread منفصل.

        مهم: `_run_loop` بيشتغل على thread واحد بينفذ كل حاجة بالتتابع.
        نداء نموذج بياخد 20-30 ثانية، ولو عملناه هنا على طول كان هيقفل
        كل حاجة تانية (الجداول المؤقتة، رسايل تليجرام، أي أمر تاني)
        طول المدة دي. فبنفصله على thread لوحده والطابور يفضل ماشي.
        """
        threading.Thread(
            target=self._converse, args=(text,), daemon=True,
            name="nezuko-brain",
        ).start()

    def _converse(self, text: str):
        b = brain.get_brain()
        if not b.ready():
            self._log(
                f"❓ مش فاهمة: {text}\n"
                "مفيش مخ متظبط عشان يفهم الكلام الحر. ظبّط واحد مجاني بـ: "
                "brain_setup   (أو اكتب help لقايمة الأوامر)",
                "warn",
            )
            return

        style = styles.prompt_for()
        messages = [
            {"role": "system", "content": (
                _SYSTEM_PROMPT
                + (f"\n{style}\n" if style else "")
                + "\nالأوامر المتاحة:\n" + self._tool_catalog()
            )},
            *self.chat_history[-_MAX_CHAT_TURNS:],
            {"role": "user", "content": text},
        ]
        cfg = brain.load_config()
        reply = b.deep_chat(messages) if cfg.get("deep_mode") else b.chat(messages)

        if not reply:
            self._log(f"❌ المخ مردش: {reply.error}", "error")
            return

        body, tool = self._split_tool_call(reply.text)
        badge = f"{'🔒' if reply.is_local else '☁️'} {reply.label}"

        self.chat_history.append({"role": "user", "content": text})
        self.chat_history.append({"role": "assistant", "content": reply.text})
        del self.chat_history[:-_MAX_CHAT_TURNS]
        sessions.save(self.session_id, self.chat_history)

        if tool is None:
            self._log(f"{body}\n\n— {badge}", "info")
            return

        tool_name, tool_args = tool
        if self.registry.get(tool_name) is None:
            # النموذج هلوس اسم أمر مش موجود — منعرضهوش أصلاً
            self._log(f"{body}\n\n— {badge}", "info")
            return

        shown = f"{tool_name} {' '.join(tool_args)}".strip()

        # الأمر ده في قايمة المسموح؟ ينفذ على طول من غير سؤال.
        # القايمة بتبدأ فاضية دايمًا — إنت اللي بتضيف فيها بنفسك.
        if permissions.is_allowed(tool_name):
            intents.remember(text, tool_name)
            self._log(f"{body}\n\n↪ {shown}\n— {badge}", "info")
            self._execute(tool_name, tool_args, text)
            return

        self._pending_intent = (tool_name, tool_args, text)
        self._log(
            f"{body}\n\n🔧 محتاجة أشغّل: {shown}\n"
            "اكتب y للتنفيذ، أو a عشان تسمح بالأمر ده دايمًا، "
            "أو أي حاجة تانية للإلغاء.\n"
            f"— {badge}",
            "info",
        )

    @staticmethod
    def _split_tool_call(reply: str) -> tuple[str, tuple[str, list[str]] | None]:
        """بيفصل نص الرد عن سطر `TOOL:` لو موجود.

        بنستخدم بروتوكول نصي بدل function-calling الخاص بكل مزوّد، عشان
        نفس الكود يشتغل على أي نموذج من غير ترجمة schema لكل واحد.
        """
        tool = None
        kept: list[str] = []
        for line in reply.splitlines():
            m = re.match(r"^\s*TOOL:\s*(\S+)(.*)$", line)
            if m and tool is None:
                try:
                    tool = (m.group(1), shlex.split(m.group(2).strip()))
                except ValueError:
                    tool = (m.group(1), m.group(2).split())
                continue
            kept.append(line)
        return "\n".join(kept).strip(), tool

