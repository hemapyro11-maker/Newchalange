"""
plugin_forge_plugin.py — المساعد يقدر يصمم Plugins جديدة بنفسه، ويكتشف
أخطاءها ويصلحها تلقائياً (generate → validate → feed error back → retry،
لحد سقف محاولات محدود)، باستخدام نموذج محلي مجاني (Ollama) — بدون أي
API مدفوع، اتساقاً مع self_improve_plugin.py.

النطاق الآمن: الكود المتولد بيتحط في plugins_pending/ (مش plugins/)
ومش بيتحمّل **جوه محرك نيزوكو الحي** غير بعد أمر approve_plugin صريح
منك، بعد ما تقدر تراجعه بـ review_pending — الخطوة الوحيدة المحتاجة
إذنك فعليًا.

**ملحوظة صادقة مهمة (مش تفصيلة صغيرة):** حلقة "توليد → تحقق → تصحيح
→ إعادة محاولة" بتنفذ الكود المتولد فعليًا وقت كل محاولة تحقق —
`_validate_candidate()` بتعمل `exec_module()` وتنادي `register(engine)`
الحقيقية بتاعة الكود المرشّح، في subprocess منفصل (مهلة 10 ثواني،
بدون أي عزل/sandboxing حقيقي على مستوى نظام التشغيل — نفس صلاحيات
حسابك بالظبط) — لحد MAX_ATTEMPTS (4) مرات، **قبل ما تشوفه إنت خالص**
عبر review_pending. يعني كود غلط أو غير متوقع من النموذج المحلي (حتى
من غير أي نية سيئة، مجرد هلوسة نموذج) ممكن يتنفذ فعليًا على جهازك —
مش بس "يتفحص نظريًا" — قبل ما توافق على حاجة. عزل حقيقي (container/
sandbox) خارج نطاق مشروع مساعد سطح مكتب بسيط زي ده، فالحماية الوحيدة
العملية دلوقتي هي إنك متستخدمش create_plugin/fix_plugin على وصف مهمة
حساسة (زي "امسح ملفات قديمة") من غير ما تكون واثق في النموذج المحلي
بتاعك.
"""
from __future__ import annotations

import datetime
import json
import pathlib
import subprocess
import sys
import textwrap
import urllib.error
import urllib.request

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "llama3.2"
MAX_ATTEMPTS = 4

PLUGIN_CONTRACT = """\
Plugin API contract for this assistant:
- The file must define a top-level function `register(engine)`.
- Inside register(engine), call `engine.registry.register(name, handler, description)`
  once per command the plugin adds.
- Each handler has the signature `def handler(ctx) -> str`, where `ctx.args` is a
  list[str] of the command's whitespace-split arguments and `ctx.raw` is the full
  raw command text as typed by the user.
- The handler's return value (a string) is shown to the user; return "" or None
  for silent commands.
- Only use the Python standard library unless the task explicitly needs something
  else (never assume third-party packages are installed).
- Output ONLY the complete Python source code for the file. No markdown code
  fences, no explanations, no comments about what you're doing — just the code.
"""

_VALIDATION_HARNESS = textwrap.dedent("""
    import importlib.util, sys

    class _FakeRegistry:
        def __init__(self):
            self.registered = []
        def register(self, name, handler, description=""):
            self.registered.append(name)

    class _FakeEngine:
        def __init__(self):
            self.registry = _FakeRegistry()
            self.log_history = []
            self.skills = {"plugins": {}, "commands": {}}
        def _log(self, msg, level="info"):
            pass

    spec = importlib.util.spec_from_file_location("candidate", sys.argv[1])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "register") or not callable(module.register):
        print("ERROR: file does not define a callable register(engine) function")
        sys.exit(1)
    engine = _FakeEngine()
    module.register(engine)
    if not engine.registry.registered:
        print("ERROR: register(engine) ran without raising, but registered zero commands")
        sys.exit(1)
    print("OK: registered commands: " + ", ".join(engine.registry.registered))
""")


def _pending_dir() -> pathlib.Path:
    base = pathlib.Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) \
        else pathlib.Path(__file__).resolve().parent.parent
    d = base / "plugins_pending"
    d.mkdir(parents=True, exist_ok=True)
    return d


_INVALID_NAME_CHARS = set('/\\:*?"<>|')


def _validate_name(name: str) -> str | None:
    """يرجع رسالة خطأ لو اسم الـ plugin غير آمن كاسم ملف، وإلا None.
    مهم بالذات هنا: approve_plugin بينقل الملف لـ plugins/ اللي بيتحمّل
    ويتنفذ تلقائياً، فاسم فيه path traversal (زي ../../x) خطر حقيقي."""
    if not name or name in (".", ".."):
        return "❌ the plugin name must not be empty, '.' or '..'"
    if any(c in _INVALID_NAME_CHARS for c in name) or ".." in name:
        return "❌ the plugin name may not contain path separators or odd characters"
    return None


def _clean_code(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip() + "\n"


def _ask_ollama(prompt: str, model: str = DEFAULT_MODEL) -> str:
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode("utf-8")
    req = urllib.request.Request(OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("response", "").strip()


def _validate_candidate(code_path: pathlib.Path) -> tuple[bool, str]:
    harness_path = code_path.parent / f"_harness_{code_path.stem}.py"
    harness_path.write_text(_VALIDATION_HARNESS, encoding="utf-8")
    try:
        result = subprocess.run(
            [sys.executable, str(harness_path), str(code_path)],
            capture_output=True, text=True, timeout=10,
        )
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT: the code hung for over 10 seconds (possible infinite loop)"
    finally:
        harness_path.unlink(missing_ok=True)
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode == 0, output.strip()[-3000:]


def _generate_with_retries(engine, initial_prompt: str, name: str, ask=_ask_ollama) -> tuple[bool, str, str, int]:
    """بيولّد كود، يتحقق منه، ولو فشل بيبعت الخطأ تاني للنموذج ويجرب
    تصحيح — بدون أي تدخل بشري في حلقة المحاولات دي — لحد MAX_ATTEMPTS."""
    prompt = initial_prompt
    code = ""
    ok = False
    msg = ""
    attempts = 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        attempts = attempt
        try:
            raw = ask(prompt)
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            return False, "", (
                "⚠  No local model running (Ollama). It is completely free — get it from "
                f"https://ollama.com then run: ollama pull {DEFAULT_MODEL}"
            ), attempt
        except Exception as e:
            return False, "", f"❌ could not reach the model: {e}", attempt

        code = _clean_code(raw)
        tmp_path = _pending_dir() / f"_draft_{name}.py"
        tmp_path.write_text(code, encoding="utf-8")
        ok, msg = _validate_candidate(tmp_path)
        tmp_path.unlink(missing_ok=True)
        engine._log(
            f"🔧 attempt {attempt}/{MAX_ATTEMPTS} for '{name}': "
            + ("✅ passed" if ok else "❌ failed — " + msg[:200]),
            "ok" if ok else "warn",
        )
        if ok:
            break
        prompt = (
            PLUGIN_CONTRACT
            + f"\nThe previous version of this file failed validation with this error:\n{msg}\n\n"
            + f"Previous code:\n{code}\n\nFix the code and output the complete corrected file."
        )
    return ok, code, msg, attempts


def _save_candidate(name: str, code: str, description: str, ok: bool, attempts: int, msg: str):
    out_path = _pending_dir() / f"{name}.py"
    out_path.write_text(code, encoding="utf-8")
    meta = {
        "description": description, "attempts": attempts, "validated": ok,
        "validation_message": msg,
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    (_pending_dir() / f"{name}.meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _cmd_create_plugin(ctx) -> str:
    if len(ctx.args) < 2:
        return "usage: create_plugin <name> <description...>"
    name = ctx.args[0]
    name_error = _validate_name(name)
    if name_error:
        return name_error
    description = " ".join(ctx.args[1:])
    prompt = PLUGIN_CONTRACT + f"\nTask: {description}\n\nWrite the complete plugin file now."
    ok, code, msg, attempts = _generate_with_retries(ctx.engine, prompt, name)
    if not code and not ok:
        return msg  # Ollama unreachable/connection error — msg already explains

    _save_candidate(name, code, description, ok, attempts, msg)
    status = "✅ generated and verified working" if ok else f"⚠  generated, but still broken after {attempts} attempts"
    return (
        f"{status} — {name}\n"
        f"📁 saved to plugins_pending/{name}.py (not active in the app yet)\n"
        f"Review it with: review_pending {name}\n"
        f"If it looks right: approve_plugin {name}   |   to discard it: reject_plugin {name}"
    )


def _cmd_fix_plugin(ctx) -> str:
    if not ctx.args:
        return "usage: fix_plugin <name> [error_text...]"
    name = ctx.args[0]
    name_error = _validate_name(name)
    if name_error:
        return name_error
    error_text = " ".join(ctx.args[1:])

    live_path = None
    for d in ctx.engine.plugins_dirs:
        candidate = d / f"{name}.py"
        if candidate.is_file():
            live_path = candidate
            break
    pending_path = _pending_dir() / f"{name}.py"
    source_path = live_path or (pending_path if pending_path.is_file() else None)
    if source_path is None:
        return f"❌ no plugin named {name} in plugins/ or plugins_pending/"

    if not error_text:
        for level, msg in reversed(ctx.engine.log_history):
            if level == "error" and name in msg:
                error_text = msg
                break
    if not error_text:
        return f"❌ no known error for {name} — pass error_text, or run the failing command first so it lands in the log"

    code = source_path.read_text(encoding="utf-8")
    prompt = (
        PLUGIN_CONTRACT
        + f"\nThis plugin file has a bug. It failed with:\n{error_text}\n\n"
        + f"Current code:\n{code}\n\nFix the bug and output the complete corrected file."
    )
    ok, fixed_code, msg, attempts = _generate_with_retries(ctx.engine, prompt, name)
    if not fixed_code and not ok:
        return msg

    _save_candidate(name, fixed_code, f"fix for: {error_text[:200]}", ok, attempts, msg)
    status = "✅ repaired and verified working" if ok else f"⚠  repair attempted, but still broken after {attempts} attempts"
    return f"{status} — the repaired copy is in plugins_pending/{name}.py; review it with review_pending {name}"


def _cmd_list_pending(ctx) -> str:
    metas = sorted(_pending_dir().glob("*.meta.json"))
    if not metas:
        return "No plugins waiting for review"
    lines = []
    for meta_path in metas:
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        name = meta_path.name.removesuffix(".meta.json")
        mark = "✅" if meta.get("validated") else "⚠"
        lines.append(f"{mark} {name} — {meta.get('description', '')[:80]}")
    return "\n".join(lines)


def _cmd_review_pending(ctx) -> str:
    if not ctx.args:
        return "usage: review_pending <name>"
    name = ctx.args[0]
    name_error = _validate_name(name)
    if name_error:
        return name_error
    code_path = _pending_dir() / f"{name}.py"
    meta_path = _pending_dir() / f"{name}.meta.json"
    if not code_path.is_file():
        return f"❌ no pending plugin named {name}"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        meta = {}
    header = (
        f"📋 {name} — {'✅ verified working' if meta.get('validated') else '⚠ still broken'}\n"
        f"Description: {meta.get('description', '?')}\n"
        f"Attempts: {meta.get('attempts', '?')}\n"
        f"Last check said: {meta.get('validation_message', '?')}\n"
        f"{'─' * 40}\n"
    )
    return header + code_path.read_text(encoding="utf-8")


def _cmd_approve_plugin(ctx) -> str:
    if not ctx.args:
        return "usage: approve_plugin <name> [--force]"
    force = "--force" in ctx.args
    args = [a for a in ctx.args if a != "--force"]
    if not args:
        return "usage: approve_plugin <name> [--force]"
    name = args[0]
    name_error = _validate_name(name)
    if name_error:
        return name_error
    code_path = _pending_dir() / f"{name}.py"
    if not code_path.is_file():
        return f"❌ no pending plugin named {name}"
    target_dir = ctx.engine.plugins_dirs[-1]  # جنب الـ exe/كود المصدر (قابل للكتابة)، مش الـ bundle للقراءة بس
    target_path = target_dir / f"{name}.py"
    if target_path.is_file() and not force:
        return (
            f"⚠️ a plugin named {name}.py already exists — approving would replace it entirely with the generated code.\n"
            f"If you are sure you want to replace it: approve_plugin {name} --force"
        )
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path.write_text(code_path.read_text(encoding="utf-8"), encoding="utf-8")
        code_path.unlink()
        (_pending_dir() / f"{name}.meta.json").unlink(missing_ok=True)
    except OSError as e:
        return f"❌ could not move it into plugins/: {e}"
    ctx.engine.load_plugins()
    return f"✅ moved {name} into plugins/ and loaded it. Try: help"


def _cmd_reject_plugin(ctx) -> str:
    if not ctx.args:
        return "usage: reject_plugin <name>"
    name = ctx.args[0]
    name_error = _validate_name(name)
    if name_error:
        return name_error
    removed = False
    for suffix in (".py", ".meta.json"):
        p = _pending_dir() / f"{name}{suffix}"
        if p.is_file():
            p.unlink()
            removed = True
    return f"🗑 removed {name} from plugins_pending/" if removed else f"❌ nothing named {name}"


def register(engine):
    engine.registry.register(
        "create_plugin", _cmd_create_plugin,
        "create_plugin <name> <description> — generate a new plugin and verify it runs (free local model)",
    )
    engine.registry.register("fix_plugin", _cmd_fix_plugin, "fix_plugin <name> [error] — repair an existing plugin automatically")
    engine.registry.register("list_pending", _cmd_list_pending, "list_pending — generated plugins waiting for your approval")
    engine.registry.register("review_pending", _cmd_review_pending, "review_pending <name> — read a pending plugin's code before approving it")
    engine.registry.register("approve_plugin", _cmd_approve_plugin, "approve_plugin <name> [--force] — activate a plugin after you reviewed it (refuses to replace an existing one without --force)")
    engine.registry.register("reject_plugin", _cmd_reject_plugin, "reject_plugin <name> — reject and delete a pending plugin")
