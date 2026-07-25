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

**الأمان أهم حاجة هنا:** النموذج ممكن "يقترح" يشغّل أي أداة، لكن
**مفيش أي تنفيذ تلقائي أبدًا** — نفس مبدأ المشروع كله. لازم تأكيد
صريح (`think y`) قبل ما أي أداة تتشغّل فعليًا، والنموذج بيتحقق من
الـ registry الحقيقي قبل ما يعرض أي اقتراح أداة (نفس حماية core_engine
ضد الهلوسة).

الأوامر: think, think_reset, think_status, think_model
"""
from __future__ import annotations

import json
import re
import shlex
import urllib.error
import urllib.request

OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
DEFAULT_MODEL = "llama3.2"
CHAT_TIMEOUT = 120
MAX_HISTORY_MESSAGES = 30  # يمنع الـ context من الانفجار في محادثة طويلة جدًا
_TOOL_RE = re.compile(r"^TOOL:\s*(\S+)(.*)$", re.MULTILINE)
_YES = {"y", "yes", "نعم", "أيوه", "ايوه", "اه", "آه", "تمام"}
_NO = {"n", "no", "لا", "لأ"}


class _NoOllama(Exception):
    pass


def _state(engine) -> dict:
    if not hasattr(engine, "_think_state"):
        engine._think_state = {"history": [], "pending_tool": None, "model": DEFAULT_MODEL}
    return engine._think_state


def _system_prompt(engine) -> str:
    catalog = "\n".join(f"{c.name} — {c.description}" for c in engine.registry.list_commands())
    return (
        "You are Nezuko, a deeply thoughtful problem-solving assistant embedded in a "
        "desktop automation tool. When the user brings you a problem:\n"
        "- Think step by step, out loud. Consider multiple angles before settling on an "
        "answer. Don't rush to a shallow response.\n"
        "- Reply in the same language the user writes in (Arabic or English).\n"
        "- You have access to real tools (commands) that can inspect the user's actual "
        "files, databases, code, and system — use them instead of guessing when they'd "
        "give you real information.\n"
        "- To use a tool, end your response with a line in EXACTLY this format (nothing "
        "after it on that line):\n"
        "  TOOL: <command_name> <arguments>\n"
        "  Only use tool names from the list below, spelled exactly as shown. Only issue "
        "ONE tool call per response.\n"
        "- Once you have enough real information (from a tool result, or your own "
        "reasoning alone), give your final answer WITHOUT any TOOL: line.\n\n"
        f"Available tools:\n{catalog}"
    )


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


def _continue_reasoning(engine) -> str:
    state = _state(engine)
    messages = [{"role": "system", "content": _system_prompt(engine)}] + state["history"][-MAX_HISTORY_MESSAGES:]
    try:
        reply = _ask_ollama_chat(messages, state["model"])
    except _NoOllama:
        # ما بنحفظش رسالة المستخدم في التاريخ لو فشلنا نرد عليها خالص —
        # عشان الجلسة تفضل متسقة لو Ollama اتشغّل بعدين.
        if state["history"] and state["history"][-1]["role"] == "user":
            state["history"].pop()
        return _OLLAMA_MISSING_MSG

    tool_call = _extract_tool_call(reply)
    clean_reply = _strip_tool_line(reply)
    state["history"].append({"role": "assistant", "content": reply})

    if tool_call is None:
        return f"🧠 {clean_reply}"

    cmd_name, cmd_args = tool_call
    if engine.registry.get(cmd_name) is None:
        # النموذج هلوس اسم أداة مش موجودة — نتجاهل اقتراح الأداة ونوريه
        # كإجابة عادية بدل ما نصدّقه أعمى.
        return f"🧠 {clean_reply}"

    state["pending_tool"] = (cmd_name, cmd_args)
    shown = f"{cmd_name} {' '.join(cmd_args)}".strip()
    return (
        f"🧠 {clean_reply}\n\n"
        f"🔧 محتاج أشغّل: {shown}\n"
        f"موافق؟ اكتب: think y   (أو think n للرفض)"
    )


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
            "   think_model <name> — تغيير النموذج المحلي المستخدم"
        )

    low = text.lower()
    if state["pending_tool"] is not None:
        cmd_name, cmd_args = state["pending_tool"]
        state["pending_tool"] = None
        if low in _YES:
            result = _invoke_tool(engine, cmd_name, cmd_args)
            state["history"].append({"role": "user", "content": f"[نتيجة تشغيل {cmd_name}]:\n{result}"})
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
    return f"🧹 اتمسحت الجلسة ({n} رسالة). ابدأ من جديد بـ: think <رسالتك>"


def _cmd_think_status(ctx) -> str:
    state = _state(ctx.engine)
    lines = [
        f"🧠 النموذج الحالي: {state['model']}",
        f"💬 عدد الرسائل في الجلسة: {len(state['history'])}",
    ]
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


def register(engine):
    engine.registry.register("think", _cmd_think,
                              "think <رسالتك> — تفكير عميق متعدد الأدوار، بيستخدم أوامر نيزوكو الحقيقية كأدوات")
    engine.registry.register("think_reset", _cmd_think_reset,
                              "think_reset — بداية جلسة تفكير جديدة")
    engine.registry.register("think_status", _cmd_think_status,
                              "think_status — حالة جلسة التفكير الحالية")
    engine.registry.register("think_model", _cmd_think_model,
                              "think_model <name> — تغيير النموذج المحلي المستخدم للتفكير")
