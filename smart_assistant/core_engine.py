"""
core_engine.py — Core Engine للمساعد الذكي، بدون أي اعتماد على الواجهة.

مسؤول عن: تسجيل الأوامر (Command Registry)، تنفيذها بالتتابع على Thread
خلفي واحد (Task Queue) عشان الواجهة تفضل سلسة، وتشغيل مهام أتمتة إضافية
(callables) بنفس الآلية.
"""
from __future__ import annotations

import logging
import queue
import shlex
import subprocess
import threading
import time
import traceback
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


class AssistantEngine:
    """
    المحرك الأساسي: يستقبل نصوص أوامر أو مهام أتمتة (callables) ويشغّلهم
    بالتتابع على Thread خلفي واحد، ويبلغ الواجهة بالنتائج عبر callbacks.
    """

    def __init__(self, on_log=None, on_status=None):
        self.on_log = on_log or (lambda msg, level="info": None)
        self.on_status = on_status or (lambda status: None)
        self.registry = CommandRegistry()
        self._queue: "queue.Queue[tuple[str, Optional[Callable]]]" = queue.Queue()
        self._stop_flag = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._register_builtin_commands()

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

    # ── builtin commands ──────────────────────────────────────────────
    def _register_builtin_commands(self):
        self.registry.register("help", self._cmd_help, "عرض كل الأوامر المتاحة")
        self.registry.register("echo", self._cmd_echo, "طباعة نص")
        self.registry.register("run", self._cmd_run, "تنفيذ أمر نظام (subprocess, بدون shell)")

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

    # ── internal ───────────────────────────────────────────────────────
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
                self.on_log(traceback.format_exc(), "error")
        self.on_status("stopped")

    def _dispatch(self, text: str):
        text = text.strip()
        if not text:
            return
        try:
            parts = shlex.split(text)
        except ValueError as e:
            self.on_log(f"❌ parse error: {e}", "error")
            return
        if not parts:
            return
        name, args = parts[0], parts[1:]
        cmd = self.registry.get(name)
        if cmd is None:
            self.on_log(f"❓ unknown command: {name} (try 'help')", "warn")
            return
        ctx = CommandContext(raw=text, args=args, engine=self)
        start = time.time()
        try:
            result = cmd.handler(ctx)
        except Exception:
            self.on_log(traceback.format_exc(), "error")
            return
        log.debug("command %s finished in %.3fs", name, time.time() - start)
        if result:
            self.on_log(str(result), "info")
