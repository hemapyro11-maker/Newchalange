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

**Playbooks — تعليمات متخصصة بملفات markdown (مستوحاة من نظام
SKILL.md في أدوات زي Clawdbot):** بدل ما تكتب plugin بايثون كامل عشان
تعلّم النموذج حاجة متخصصة، تقدر تكتب ملف markdown بسيط في مجلد
`playbooks/` (زي: "لما حد يسأل عن تحليل قناة يوتيوب، ابدأ دايمًا بـ
channel_growth_report قبل أي حاجة تانية"). `think` بيفلتر أوتوماتيك
أقرب playbook لموضوع سؤالك (نفس أسلوب فلترة الأدوار فوق) ويحقنه في
سياق النموذج بس لو كان فعلاً ذو صلة — مش كل الـ playbooks كل مرة. سُمّي
"playbook" مش "skill" عشان الاسم ده مستخدم فعلاً لحاجة تانية تمامًا في
نيزوكو (سجل `skills.json`/أمر `skills` بتاع core_engine).

**الأمان أهم حاجة هنا:** النموذج ممكن "يقترح" يشغّل أي أداة، لكن
**مفيش أي تنفيذ تلقائي أبدًا** — نفس مبدأ المشروع كله. لازم تأكيد
صريح (`think y`) قبل ما أي أداة تتشغّل فعليًا، والنموذج بيتحقق من
الـ registry الحقيقي قبل ما يعرض أي اقتراح أداة (نفس حماية core_engine
ضد الهلوسة) — الفلترة الذكية للأدوار بتقلل مساحة الهلوسة كمان لأنها
بتشيل أسماء أوامر متشابهة/مربكة مش لها علاقة بالسؤال.

**قيد معماري معروف — الحالة (الجلسة/الذاكرة) مشتركة بين كل القنوات:**
سطح المكتب وTelegram وDiscord كلهم بينادوا على نفس محرك `think` (نفس
الجلسة الحوارية، نفس `think_memory.json`)، مش جلسة/ذاكرة منفصلة لكل
قناة. يعني لو مستخدم Telegram معتمَد سأل `think` سؤال، والمستخدم اللي
قدام الجهاز سأل سؤال تاني بعده، النموذج هيشوف الاتنين في نفس المحادثة.
ده مش bug — قرار معماري واعي متسق مع نموذج الثقة الحالي (أي مستخدم
Telegram/Discord متعمَد أصلاً عنده صلاحية تنفيذ أي أمر عبر `run`، يعني
مكافئة كاملة لوصول لوحة المفاتيح)، لكن لو حبيت جلسات/ذاكرة منفصلة لكل
قناة مستقبلاً، محتاج تصميم مختلف (session key لكل قناة بدل الحالة
المشتركة الحالية).

الأوامر: think, think_reset, think_status, think_model, think_critique,
think_remember, think_forget, think_playbooks
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
RELEVANT_PLAYBOOKS_LIMIT = 2
MAX_PLAYBOOK_CHARS = 2000

_TOOL_RE = re.compile(r"^TOOL:\s*(\S+)(.*)$", re.MULTILINE)
_PLAYBOOK_NAME_RE = re.compile(r"^[A-Za-z0-9_؀-ۿ-]+$")
_PLAN_RE = re.compile(r"^PLAN:\s*(.+)$", re.MULTILINE)
_YES = {"y", "yes", "نعم", "أيوه", "ايوه", "اه", "آه", "تمام"}
_NO = {"n", "no", "لا", "لأ"}
_ON = {"on", "y", "yes", "تشغيل", "شغل", "شغال"}
_OFF = {"off", "n", "no", "وقف", "إيقاف", "متوقف"}

CRITIQUE_INSTRUCTION = (
    "Look at your answer above critically: is anything missing, inaccurate, or "
    "vague? If it is sound and complete as it stands, repeat it exactly, unchanged. "
    "If it needs improving, write only the improved final version — with no "
    "commentary about the revision, and no TOOL: line at all in this reply."
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


# ── playbooks (تعليمات متخصصة بملفات markdown، مستوحاة من SKILL.md) ────

def _playbooks_dir() -> pathlib.Path:
    if getattr(sys, "frozen", False):
        base = pathlib.Path(sys.executable).resolve().parent
    else:
        base = pathlib.Path(__file__).resolve().parent.parent
    d = base / "playbooks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _valid_playbook_name(name: str) -> bool:
    return bool(_PLAYBOOK_NAME_RE.match(name))


def _list_playbooks() -> list[str]:
    return sorted(f.stem for f in _playbooks_dir().glob("*.md"))


def _read_playbook(name: str) -> str | None:
    if not _valid_playbook_name(name):
        return None
    path = _playbooks_dir() / f"{name}.md"
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _write_playbook(name: str, content: str) -> bool:
    if not _valid_playbook_name(name):
        return False
    try:
        (_playbooks_dir() / f"{name}.md").write_text(content, encoding="utf-8")
    except OSError:
        return False
    return True


def _delete_playbook(name: str) -> bool:
    if not _valid_playbook_name(name):
        return False
    path = _playbooks_dir() / f"{name}.md"
    if not path.is_file():
        return False
    try:
        path.unlink()
    except OSError:
        return False
    return True


def _relevant_playbooks(query: str) -> list[tuple[str, str]]:
    """بيرجع أقرب playbooks لموضوع السؤال بس — مش كل الملفات كل مرة،
    نفس فلسفة _relevant_tools بالظبط."""
    names = _list_playbooks()
    if not names or not query.strip():
        return []
    # بنستبعد الكلمات الأقصر من 3 حروف — حروف الجر/الروابط القصيرة زي
    # "عن"، "من"، "في" بتتكرر بالصدفة في أي نص عربي طبيعي، فلو سبناها
    # في الحساب هتعمل تطابق وهمي بين موضوعين مالهمش أي علاقة ببعض.
    q_tokens = {t for t in re.findall(r"\w+", query.lower()) if len(t) >= 3}
    if not q_tokens:
        return []
    scored: list[tuple[int, str, str]] = []
    for name in names:
        content = _read_playbook(name)
        if not content:
            continue
        c_tokens = {t for t in re.findall(r"\w+", content.lower()) if len(t) >= 3}
        overlap = len(q_tokens & c_tokens)
        if overlap > 0:
            scored.append((overlap, name, content))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [(name, content[:MAX_PLAYBOOK_CHARS]) for _, name, content in scored[:RELEVANT_PLAYBOOKS_LIMIT]]


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
    playbooks = _relevant_playbooks(query)
    if playbooks:
        for name, content in playbooks:
            parts.append(f"\nRelevant playbook '{name}':\n{content}\n")
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
        return "❌ that tool does not actually exist in Nezuko"
    from core_engine import CommandContext
    tool_ctx = CommandContext(raw=f"{name} {' '.join(args)}".strip(), args=args, engine=engine)
    try:
        result = cmd.handler(tool_ctx)
    except Exception as e:
        return f"❌ the tool raised an error: {e}"
    return str(result) if result else "(the tool ran and produced no output)"


_OLLAMA_MISSING_MSG = (
    "⚠️ No local model running (Ollama) to think with.\n"
    "It is completely free — get it from https://ollama.com then run:\n"
    "   ollama pull llama3.2\n"
    "For genuinely deeper reasoning, try a dedicated reasoning model like DeepSeek-R1 (also free):\n"
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
    state["history"].append({"role": "assistant", "content": f"[self-review] {revised}"})
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
            out.append(f"🗺 Plan: {plan}")
        out.append(f"🧠 {clean_reply}")
        out.append("")
        out.append(f"🔧 I need to run: {shown}")
        out.append("Go ahead? type: think y   (or think n to refuse)")
        return "\n".join(out)

    # إجابة نهائية — إما مفيش أداة مطلوبة، أو النموذج هلوس اسم أداة وهمي،
    # أو اتمنع من اقتراح أداة تانية بعد فشل متكرر
    final_text = clean_reply
    if state.get("critique_enabled", True) and final_text.strip():
        final_text = _self_critique(engine, final_text)
    if valid_tool is not None and suppress:
        # الملاحظة دي بتتضاف بعد المراجعة الذاتية، مش قبلها — عشان تفضل
        # مضمونة تظهر للمستخدم حتى لو النموذج أعاد صياغة كل حاجة تانية.
        final_text += "\n\n⚠️ (ignored another tool request after repeated failures — try phrasing what you want differently)"

    state["plan"] = None
    out = []
    if plan:
        out.append(f"🗺 Plan: {plan}")
    out.append(f"🧠 {final_text}")
    return "\n".join(out)


def _cmd_think(ctx) -> str:
    engine = ctx.engine
    state = _state(engine)

    parts = ctx.raw.split(maxsplit=1)
    text = parts[1].strip() if len(parts) > 1 else ""
    if not text:
        return (
            "usage: think <your message>\n"
            "   think y / think n — approve or refuse a proposed tool\n"
            "   think_reset — start a fresh conversation\n"
            "   think_status — state of the current session\n"
            "   think_model <name> — change which local model is used\n"
            "   think_critique on|off — turn self-review of answers on or off\n"
            "   think_remember <note> — save a fact that outlives sessions\n"
            "   think_forget — clear every saved note"
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
                    f"\n[automatic note: {cmd_name} has failed {state['tool_fail_streak']} times "
                    "in a row — try a completely different approach, or answer the user directly without "
                    "another tool right now.]"
                )
                state["tool_fail_streak"] = 0
                state["suppress_next_tool"] = True
            state["history"].append({"role": "user", "content": f"[output of {cmd_name}]:\n{result}{note}"})
            return _continue_reasoning(engine)
        if low in _NO:
            state["history"].append({"role": "user", "content": "[the user refused the proposed tool]"})
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
        f"🧹 session cleared ({n} messages). Start again with: think <your message>\n"
        "(any saved notes are still there — use think_forget to clear those)"
    )


def _cmd_think_status(ctx) -> str:
    state = _state(ctx.engine)
    lines = [
        f"🧠 Current model: {state['model']}",
        f"💬 Messages in this session: {len(state['history'])}",
        f"🔎 Self-review: {'on' if state.get('critique_enabled', True) else 'off'}",
        f"💾 Saved notes: {len(_load_memory())}",
    ]
    if state.get("plan"):
        lines.append(f"🗺 Current plan: {state['plan']}")
    if state["pending_tool"]:
        name, args = state["pending_tool"]
        lines.append(f"🔧 Waiting on approval for: {name} {' '.join(args)}".strip())
    return "\n".join(lines)


def _cmd_think_model(ctx) -> str:
    if not ctx.args:
        state = _state(ctx.engine)
        return f"Current model: {state['model']}\nusage: think_model <name>   (e.g. think_model deepseek-r1)"
    state = _state(ctx.engine)
    state["model"] = ctx.args[0]
    return f"✅ will use model: {state['model']}  (it must be installed — try: ollama pull {state['model']} if it does not work)"


def _cmd_think_critique(ctx) -> str:
    state = _state(ctx.engine)
    if not ctx.args:
        status = "on ✅" if state.get("critique_enabled", True) else "off ❌"
        return f"Self-review: {status}\nusage: think_critique on|off"
    arg = ctx.args[0].lower()
    if arg in _ON:
        state["critique_enabled"] = True
        return "✅ self-review is on — every final answer gets reviewed once before you see it"
    if arg in _OFF:
        state["critique_enabled"] = False
        return "❌ self-review is off — answers appear straight away (faster, but unreviewed)"
    return "usage: think_critique on|off"


def _cmd_think_remember(ctx) -> str:
    parts = ctx.raw.split(maxsplit=1)
    note = parts[1].strip() if len(parts) > 1 else ""
    if not note:
        return "usage: think_remember <a fact or note to keep permanently, across every future session>"
    notes = _load_memory()
    notes.append(note)
    _save_memory(notes)
    return f"💾 noted — {len(notes)} saved notes now (they survive think_reset)"


def _cmd_think_forget(ctx) -> str:
    n = len(_load_memory())
    _save_memory([])
    return f"🗑 cleared every saved note ({n} of them)"


def _playbooks_usage() -> str:
    return (
        "usage:\n"
        "  think_playbooks list                    — every saved playbook\n"
        "  think_playbooks add <name> <content...> — create or update a playbook (markdown)\n"
        "  think_playbooks show <name>             — print one playbook\n"
        "  think_playbooks remove <name>           — delete a playbook\n"
        "  (name: letters, digits, underscore, dash or Arabic only — no spaces or /)"
    )


def _cmd_think_playbooks(ctx) -> str:
    if not ctx.args:
        return _playbooks_usage()
    sub = ctx.args[0].lower()

    if sub == "list":
        names = _list_playbooks()
        if not names:
            return "No playbooks saved. Add one with: think_playbooks add <name> <content...>"
        return "📘 Available playbooks:\n" + "\n".join(f"  - {n}" for n in names)

    if sub == "add":
        parts = ctx.raw.split(maxsplit=3)
        if len(parts) < 4 or not parts[3].strip():
            return _playbooks_usage()
        name, content = parts[2], parts[3].strip()
        if not _valid_playbook_name(name):
            return f"❌ invalid name: '{name}' — letters, digits, underscore, dash or Arabic only, no spaces or /"
        if not _write_playbook(name, content):
            return f"❌ could not save playbook '{name}'"
        return f"✅ saved playbook '{name}' ({len(content)} characters)"

    if sub == "show":
        if len(ctx.args) < 2:
            return "usage: think_playbooks show <name>"
        content = _read_playbook(ctx.args[1])
        if content is None:
            return f"❌ no playbook named '{ctx.args[1]}'"
        return f"📘 {ctx.args[1]}:\n{content}"

    if sub == "remove":
        if len(ctx.args) < 2:
            return "usage: think_playbooks remove <name>"
        if not _delete_playbook(ctx.args[1]):
            return f"❌ no playbook named '{ctx.args[1]}'"
        return f"🗑 removed playbook '{ctx.args[1]}'"

    return _playbooks_usage()


def register(engine):
    engine.registry.register("think", _cmd_think,
                              "think <your message> — multi-turn deep reasoning that uses Nezuko's real commands as tools")
    engine.registry.register("think_reset", _cmd_think_reset,
                              "think_reset — start a fresh thinking session")
    engine.registry.register("think_status", _cmd_think_status,
                              "think_status — state of the current thinking session")
    engine.registry.register("think_model", _cmd_think_model,
                              "think_model <name> — change which local model does the thinking")
    engine.registry.register("think_critique", _cmd_think_critique,
                              "think_critique on|off — review answers before showing them, or not")
    engine.registry.register("think_remember", _cmd_think_remember,
                              "think_remember <note> — save a fact that outlives every future think session")
    engine.registry.register("think_forget", _cmd_think_forget,
                              "think_forget — clear every note saved with think_remember")
    engine.registry.register("think_playbooks", _cmd_think_playbooks,
                              "think_playbooks list|add|show|remove — markdown instructions injected into think when relevant")
