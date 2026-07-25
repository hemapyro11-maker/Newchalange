"""
think_plugin.py — مساعد تفكير عميق حقيقي: محادثة متعددة الأدوار (بتفتكر
اللي فات في نفس الجلسة، مش رد واحد وخلاص)، وقادر يستخدم أي أمر حقيقي
مسجّل في نيزوكو كـ "أداة" بنفسه عشان يجيب معلومة حقيقية بدل ما يخمّن —
عبر نموذج Ollama محلي مجاني، اتساقاً مع Zero-Cost First.

**بصراحة تامة عن الحدود:** ده مش "ذكاء خارق" — ده نموذج محلي (زي
llama3.2 الافتراضي) بحجم وقدرة محدودين مقارنة بنماذج سحابية ضخمة.
جودة "التفكير العميق" الفعلية بتعتمد بشكل كبير على النموذج اللي
مثبّته (`ollama list`) — نماذج مصممة للاستدلال زي DeepSeek-R1 أو QwQ
(مجانية ومفتوحة المصدر برضه، عبر Ollama) هتدّي تفكير أعمق بكتير من
النماذج العامة الصغيرة زي llama3.2 الافتراضي. استخدم `think_model
<name>` لتغييره.

**خمس طبقات ذكاء حقيقية (مش زخرفة) فوق أي نموذج مستخدم:**
1. **تخطيط متعدد الخطوات** — لمهام معقدة، النموذج بيكتب خطة (`PLAN: ...`)
   قبل ما يبدأ ينفذ، وبتتحفظ في الجلسة عشان يفضل ملتزم بيها عبر الأدوار.
2. **تعافي من فشل الأداة** — لو أداة فشلت 3 مرات متتالية، بنوقف اقتراح
   نفس النمط تلقائيًا ونجبره يجرب أسلوب مختلف أو يجاوب مباشرة.
3. **اختيار أدوات ذكي** — بدل ما نديله كل الأوامر المسجّلة (ممكن تبقى
   مئات) في كل رسالة، بنفلتر لأقرب الأدوات لموضوع السؤال (تشابه نصي)،
   مع `help` كباب خلفي دايمًا لو محتاج يشوف القائمة كاملة.
4. **مراجعة ذاتية (self-critique)** — قبل ما أي إجابة نهائية تتعرض،
   بنطلب من نفس النموذج يراجعها نقديًا مرة تانية (بدون أدوات) ويحسّنها
   لو محتاجة — قابل للإيقاف عبر `think_critique off` لو عايز رد أسرع.
5. **ذاكرة دائمة اختيارية** — `think_remember`/`think_forget` بيحفظوا
   حقايق مهمة في ملف محلي (`think_memory.json`، خارج git) بتفضل موجودة
   حتى بعد `think_reset` أو إعادة تشغيل البرنامج، وبتتحقن في كل محادثة
   جديدة كسياق طويل الأمد.

**الأمان أهم حاجة هنا:** النموذج ممكن "يقترح" يشغّل أي أداة، لكن
**مفيش أي تنفيذ تلقائي أبدًا** — نفس مبدأ المشروع كله. لازم تأكيد
صريح (`think y`) قبل ما أي أداة تتشغّل فعليًا، والنموذج بيتحقق من
الـ registry الحقيقي قبل ما يعرض أي اقتراح أداة (نفس حماية core_engine
ضد الهلوسة) — الفلترة الذكية للأدوار بتقلل مساحة الهلوسة كمان لأنها
بتشيل أسماء أوامر متشابهة/مربكة مش لها علاقة بالسؤال.

الأوامر: think, think_reset, think_status, think_model, think_critique,
think_remember, think_forget
"""
from __future__ import annotations

import difflib
import json
import pathlib
import re
import shlex
import sys
import urllib.error
import urllib.request

OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
DEFAULT_MODEL = "llama3.2"
CHAT_TIMEOUT = 120
MAX_HISTORY_MESSAGES = 30  # يمنع الـ context من الانفجار في محادثة طويلة جدًا
MAX_MEMORY_NOTES = 50
RELEVANT_TOOLS_LIMIT = 20
MAX_CONSECUTIVE_TOOL_FAILURES = 3

_TOOL_RE = re.compile(r"^TOOL:\s*(\S+)(.*)$", re.MULTILINE)
_PLAN_RE = re.compile(r"^PLAN:\s*(.+)$", re.MULTILINE)
_YES = {"y", "yes", "نعم", "أيوه", "ايوه", "اه", "آه", "تمام"}
_NO = {"n", "no", "لا", "لأ"}
_ON = {"on", "y", "yes", "تشغيل", "شغل", "شغال"}
_OFF = {"off", "n", "no", "وقف", "إيقاف", "متوقف"}

CRITIQUE_INSTRUCTION = (
    "راجع إجابتك اللي فوق دي بعين ناقدة: فيها حاجة ناقصة، غير دقيقة، أو "
    "غامضة؟ لو الإجابة سليمة وكاملة زي ما هي، اكتبها تاني بالظبط من غير "
    "تغيير. لو محتاجة تحسين، اكتب النسخة النهائية المحسّنة بس — من غير "
    "أي شرح عن التعديل نفسه، ومن غير أي TOOL: خالص في الرد ده."
)
CRITIQUE_SYSTEM = (
    "You are reviewing your own previous answer for accuracy and "
    "completeness before it is shown to the user. Do not call any tools "
    "in this step — just review and (if needed) improve the text."
)


class _NoOllama(Exception):
    pass


def _state(engine) -> dict:
    if not hasattr(engine, "_think_state"):
        engine._think_state = {
            "history": [],
            "pending_tool": None,
            "model": DEFAULT_MODEL,
            "plan": None,
            "tool_fail_streak": 0,
            "suppress_next_tool": False,
            "critique_enabled": True,
        }
    return engine._think_state


# ── ذاكرة دائمة (اختيارية، خارج git) ────────────────────────────────────

def _memory_path() -> pathlib.Path:
    if getattr(sys, "frozen", False):
        base = pathlib.Path(sys.executable).resolve().parent
    else:
        base = pathlib.Path(__file__).resolve().parent.parent
    return base / "think_memory.json"


def _load_memory() -> list[str]:
    path = _memory_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    notes = data.get("notes", [])
    return [str(n) for n in notes] if isinstance(notes, list) else []


def _save_memory(notes: list[str]) -> None:
    try:
        _memory_path().write_text(
            json.dumps({"notes": notes[-MAX_MEMORY_NOTES:]}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


# ── اختيار أدوات ذكي (بدل ما نديله كل الأوامر كل مرة) ───────────────────

def _relevant_tools(engine, query: str) -> list:
    commands = engine.registry.list_commands()
    if len(commands) <= RELEVANT_TOOLS_LIMIT or not query.strip():
        return commands
    q_tokens = set(re.findall(r"\w+", query.lower()))

    def score(cmd) -> float:
        text = f"{cmd.name} {cmd.description}".lower()
        c_tokens = set(re.findall(r"\w+", text))
        overlap = len(q_tokens & c_tokens)
        fuzzy = difflib.SequenceMatcher(None, query.lower(), text).ratio()
        return overlap * 10 + fuzzy

    ranked = sorted(commands, key=score, reverse=True)
    top = ranked[:RELEVANT_TOOLS_LIMIT]
    if not any(c.name == "help" for c in top):
        help_cmd = engine.registry.get("help")
        if help_cmd is not None:
            top = [*top, help_cmd]
    return sorted(top, key=lambda c: c.name)


def _latest_user_text(history: list[dict]) -> str:
    for msg in reversed(history):
        if msg["role"] == "user":
            return msg["content"]
    return ""


def _system_prompt(engine, query: str, state: dict) -> str:
    tools = _relevant_tools(engine, query)
    catalog = "\n".join(f"{c.name} — {c.description}" for c in tools)
    parts = [
        (
            "You are Nezuko, a deeply thoughtful problem-solving assistant embedded in a "
            "desktop automation tool. When the user brings you a problem:\n"
            "- Think step by step, out loud. Consider multiple angles before settling on an "
            "answer. Don't rush to a shallow response.\n"
            "- Reply in the same language the user writes in (Arabic or English).\n"
            "- For problems that need more than one tool call, start your FIRST response to "
            "a new problem with a single line `PLAN: step 1; step 2; step 3` (short "
            "semicolon-separated phrases) before anything else. State it once per problem, "
            "not on every follow-up turn.\n"
            "- You have access to real tools (commands) that can inspect the user's actual "
            "files, databases, code, and system — use them instead of guessing when they'd "
            "give you real information.\n"
            "- To use a tool, end your response with a line in EXACTLY this format (nothing "
            "after it on that line):\n"
            "  TOOL: <command_name> <arguments>\n"
            "  Only use tool names from the list below, spelled exactly as shown. Only issue "
            "ONE tool call per response. The list is filtered to what looks relevant to the "
            "current question — if you need something else, call `TOOL: help` first to see "
            "every available command.\n"
            "- Once you have enough real information (from a tool result, or your own "
            "reasoning alone), give your final answer WITHOUT any TOOL: line.\n"
        ),
    ]
    if state.get("plan"):
        parts.append(f"\nCurrent plan for this task: {state['plan']}\n")
    memory = _load_memory()
    if memory:
        notes = "\n".join(f"- {n}" for n in memory[-15:])
        parts.append(f"\nLong-term notes remembered from previous sessions:\n{notes}\n")
    parts.append(f"\nAvailable tools:\n{catalog}")
    return "".join(parts)


def _extract_tool_call(reply: str) -> tuple[str, list[str]] | None:
    m = _TOOL_RE.search(reply)
    if not m:
        return None
    name = m.group(1)
    try:
        args = shlex.split(m.group(2).strip())
    except ValueError:
        args = m.group(2).strip().split()
    return name, args


def _strip_tool_line(reply: str) -> str:
    return _TOOL_RE.sub("", reply).strip()


def _extract_plan(reply: str) -> str | None:
    m = _PLAN_RE.search(reply)
    return m.group(1).strip() if m else None


def _strip_plan_line(reply: str) -> str:
    return _PLAN_RE.sub("", reply).strip()


def _ask_ollama_chat(messages: list[dict], model: str) -> str:
    payload = json.dumps({"model": model, "messages": messages, "stream": False}).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_CHAT_URL, data=payload, headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=CHAT_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError, json.JSONDecodeError) as e:
        raise _NoOllama(str(e)) from e
    content = data.get("message", {}).get("content", "")
    if not content:
        raise _NoOllama("empty response")
    return content.strip()


def _invoke_tool(engine, name: str, args: list[str]) -> str:
    cmd = engine.registry.get(name)
    if cmd is None:
        return "❌ الأداة دي مش موجودة فعليًا في نيزوكو"
    from core_engine import CommandContext
    tool_ctx = CommandContext(raw=f"{name} {' '.join(args)}".strip(), args=args, engine=engine)
    try:
        result = cmd.handler(tool_ctx)
    except Exception as e:
        return f"❌ حصل خطأ أثناء تشغيل الأداة: {e}"
    return str(result) if result else "(الأداة اشتغلت من غير أي output)"


_OLLAMA_MISSING_MSG = (
    "⚠️ مفيش نموذج محلي شغال (Ollama) عشان أفكر معاك.\n"
    "ده مجاني بالكامل — نزّله من https://ollama.com وشغّل:\n"
    "   ollama pull llama3.2\n"
    "لتفكير أعمق فعليًا، جرب نموذج استدلال مخصص زي DeepSeek-R1 (مجاني برضه):\n"
    "   ollama pull deepseek-r1\n"
    "   think_model deepseek-r1"
)


def _self_critique(engine, draft: str) -> str:
    state = _state(engine)
    messages = (
        [{"role": "system", "content": CRITIQUE_SYSTEM}]
        + state["history"][-MAX_HISTORY_MESSAGES:]
        + [{"role": "user", "content": CRITIQUE_INSTRUCTION}]
    )
    try:
        revised = _ask_ollama_chat(messages, state["model"])
    except _NoOllama:
        return draft  # fail-open: الإجابة الأصلية أهم من فشل خطوة المراجعة
    revised = _strip_plan_line(_strip_tool_line(revised))
    if not revised:
        return draft
    state["history"].append({"role": "assistant", "content": f"[مراجعة ذاتية] {revised}"})
    return revised


def _continue_reasoning(engine) -> str:
    state = _state(engine)
    query = _latest_user_text(state["history"])
    messages = [{"role": "system", "content": _system_prompt(engine, query, state)}] + state["history"][-MAX_HISTORY_MESSAGES:]
    try:
        reply = _ask_ollama_chat(messages, state["model"])
    except _NoOllama:
        # ما بنحفظش رسالة المستخدم في التاريخ لو فشلنا نرد عليها خالص —
        # عشان الجلسة تفضل متسقة لو Ollama اتشغّل بعدين.
        if state["history"] and state["history"][-1]["role"] == "user":
            state["history"].pop()
        return _OLLAMA_MISSING_MSG

    plan = _extract_plan(reply)
    if plan:
        state["plan"] = plan
    tool_call = _extract_tool_call(reply)
    clean_reply = _strip_tool_line(_strip_plan_line(reply))
    state["history"].append({"role": "assistant", "content": reply})

    valid_tool = tool_call if tool_call and engine.registry.get(tool_call[0]) is not None else None
    suppress = state.pop("suppress_next_tool", False)

    if valid_tool is not None and not suppress:
        cmd_name, cmd_args = valid_tool
        state["pending_tool"] = (cmd_name, cmd_args)
        shown = f"{cmd_name} {' '.join(cmd_args)}".strip()
        out = []
        if plan:
            out.append(f"🗺 الخطة: {plan}")
        out.append(f"🧠 {clean_reply}")
        out.append("")
        out.append(f"🔧 محتاج أشغّل: {shown}")
        out.append("موافق؟ اكتب: think y   (أو think n للرفض)")
        return "\n".join(out)

    # إجابة نهائية — إما مفيش أداة مطلوبة، أو النموذج هلوس اسم أداة وهمي،
    # أو اتمنع من اقتراح أداة تانية بعد فشل متكرر
    final_text = clean_reply
    if state.get("critique_enabled", True) and final_text.strip():
        final_text = _self_critique(engine, final_text)
    if valid_tool is not None and suppress:
        # الملاحظة دي بتتضاف بعد المراجعة الذاتية، مش قبلها — عشان تفضل
        # مضمونة تظهر للمستخدم حتى لو النموذج أعاد صياغة كل حاجة تانية.
        final_text += "\n\n⚠️ (اتجاهل طلب تشغيل أداة تاني بعد فشل متكرر — جرب توضّح المطلوب بشكل مختلف)"

    state["plan"] = None
    out = []
    if plan:
        out.append(f"🗺 الخطة: {plan}")
    out.append(f"🧠 {final_text}")
    return "\n".join(out)


def _cmd_think(ctx) -> str:
    engine = ctx.engine
    state = _state(engine)

    parts = ctx.raw.split(maxsplit=1)
    text = parts[1].strip() if len(parts) > 1 else ""
    if not text:
        return (
            "usage: think <رسالتك>\n"
            "   think y / think n — تأكيد أو رفض تشغيل أداة مقترحة\n"
            "   think_reset — بداية محادثة جديدة\n"
            "   think_status — حالة الجلسة الحالية\n"
            "   think_model <name> — تغيير النموذج المحلي المستخدم\n"
            "   think_critique on|off — تشغيل/إيقاف المراجعة الذاتية للإجابات\n"
            "   think_remember <ملاحظة> — حفظ حقيقة دائمة تعدي الجلسات\n"
            "   think_forget — مسح كل الملاحظات الدائمة"
        )

    low = text.lower()
    if state["pending_tool"] is not None:
        cmd_name, cmd_args = state["pending_tool"]
        state["pending_tool"] = None
        if low in _YES:
            result = _invoke_tool(engine, cmd_name, cmd_args)
            if result.startswith("❌"):
                state["tool_fail_streak"] += 1
            else:
                state["tool_fail_streak"] = 0
            note = ""
            if state["tool_fail_streak"] >= MAX_CONSECUTIVE_TOOL_FAILURES:
                note = (
                    f"\n[تنبيه تلقائي: {cmd_name} فشلت {state['tool_fail_streak']} مرات "
                    "متتالية — جرب أسلوب مختلف تمامًا أو جاوب المستخدم مباشرة من غير "
                    "أداة تانية دلوقتي.]"
                )
                state["tool_fail_streak"] = 0
                state["suppress_next_tool"] = True
            state["history"].append({"role": "user", "content": f"[نتيجة تشغيل {cmd_name}]:\n{result}{note}"})
            return _continue_reasoning(engine)
        if low in _NO:
            state["history"].append({"role": "user", "content": "[رفضت تشغيل الأداة المقترحة]"})
            return _continue_reasoning(engine)
        # مش y ولا n — نسيب الاقتراح القديم ونعالج النص كرسالة جديدة عادية

    state["history"].append({"role": "user", "content": text})
    return _continue_reasoning(engine)


def _cmd_think_reset(ctx) -> str:
    engine = ctx.engine
    state = _state(engine)
    n = len(state["history"])
    state["history"] = []
    state["pending_tool"] = None
    state["plan"] = None
    state["tool_fail_streak"] = 0
    state["suppress_next_tool"] = False
    return (
        f"🧹 اتمسحت الجلسة ({n} رسالة). ابدأ من جديد بـ: think <رسالتك>\n"
        "(الملاحظات الدائمة لو فيه لسه محفوظة — استخدم think_forget لمسحها)"
    )


def _cmd_think_status(ctx) -> str:
    state = _state(ctx.engine)
    lines = [
        f"🧠 النموذج الحالي: {state['model']}",
        f"💬 عدد الرسائل في الجلسة: {len(state['history'])}",
        f"🔎 المراجعة الذاتية: {'شغالة' if state.get('critique_enabled', True) else 'متوقفة'}",
        f"💾 ملاحظات دائمة محفوظة: {len(_load_memory())}",
    ]
    if state.get("plan"):
        lines.append(f"🗺 الخطة الحالية: {state['plan']}")
    if state["pending_tool"]:
        name, args = state["pending_tool"]
        lines.append(f"🔧 في انتظار تأكيد أداة: {name} {' '.join(args)}".strip())
    return "\n".join(lines)


def _cmd_think_model(ctx) -> str:
    if not ctx.args:
        state = _state(ctx.engine)
        return f"النموذج الحالي: {state['model']}\nusage: think_model <name>   (زي: think_model deepseek-r1)"
    state = _state(ctx.engine)
    state["model"] = ctx.args[0]
    return f"✅ هيستخدم النموذج: {state['model']}  (لازم يكون متثبت — جرب: ollama pull {state['model']} لو مش شغال)"


def _cmd_think_critique(ctx) -> str:
    state = _state(ctx.engine)
    if not ctx.args:
        status = "شغالة ✅" if state.get("critique_enabled", True) else "متوقفة ❌"
        return f"المراجعة الذاتية: {status}\nusage: think_critique on|off"
    arg = ctx.args[0].lower()
    if arg in _ON:
        state["critique_enabled"] = True
        return "✅ المراجعة الذاتية بقت شغالة — كل إجابة نهائية هتتراجع مرة قبل ما تتعرض عليك"
    if arg in _OFF:
        state["critique_enabled"] = False
        return "❌ المراجعة الذاتية بقت متوقفة — الإجابات هتتعرض على طول (أسرع، لكن من غير مراجعة تانية)"
    return "usage: think_critique on|off"


def _cmd_think_remember(ctx) -> str:
    parts = ctx.raw.split(maxsplit=1)
    note = parts[1].strip() if len(parts) > 1 else ""
    if not note:
        return "usage: think_remember <حقيقة أو ملاحظة تتحفظ بشكل دائم عبر كل الجلسات القادمة>"
    notes = _load_memory()
    notes.append(note)
    _save_memory(notes)
    return f"💾 اتسجلت — {len(notes)} ملاحظة دائمة محفوظة دلوقتي (هتفضل موجودة حتى بعد think_reset)"


def _cmd_think_forget(ctx) -> str:
    n = len(_load_memory())
    _save_memory([])
    return f"🗑 اتمسحت كل الملاحظات الدائمة ({n} ملاحظة)"


def register(engine):
    engine.registry.register("think", _cmd_think,
                              "think <رسالتك> — تفكير عميق متعدد الأدوار، بيستخدم أوامر نيزوكو الحقيقية كأدوات")
    engine.registry.register("think_reset", _cmd_think_reset,
                              "think_reset — بداية جلسة تفكير جديدة")
    engine.registry.register("think_status", _cmd_think_status,
                              "think_status — حالة جلسة التفكير الحالية")
    engine.registry.register("think_model", _cmd_think_model,
                              "think_model <name> — تغيير النموذج المحلي المستخدم للتفكير")
    engine.registry.register("think_critique", _cmd_think_critique,
                              "think_critique on|off — تشغيل/إيقاف مراجعة الإجابات ذاتيًا قبل عرضها")
    engine.registry.register("think_remember", _cmd_think_remember,
                              "think_remember <ملاحظة> — حفظ حقيقة دائمة تعدي كل جلسات think المستقبلية")
    engine.registry.register("think_forget", _cmd_think_forget,
                              "think_forget — مسح كل الملاحظات الدائمة المحفوظة من think_remember")
