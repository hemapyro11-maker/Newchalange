"""
self_improve_plugin.py — يقترح تحسينات بالاعتماد على نفس نظام "المخ"
(brain.py) اللي الشات بيستخدمه — بيجرب أفضل مزوّد متاح (سحابي مجاني لو
عنده حصة فاضية، وإلا محلي عبر Ollama)، اتساقاً مع مبدأ Zero-Cost First
لكن من غير ما نحبس نفسنا في موديل محلي صغير لو فيه أحسن منه متاح فعلاً.

بالتصميم: الاقتراحات نصية فقط ومحدش بيتعدل تلقائي — القرار والتطبيق
دايماً للمستخدم. مفيش هنا أي تنزيل/تشغيل كود من الإنترنت من غير مراجعة،
لأن ده بيفتح ثغرة تنفيذ كود غير موثوق (RCE) على جهاز المستخدم.

**ليه بنبعت خريطة الكود + قايمة الإضافات الحقيقية مع الطلب:** موديل
صغير (زي llama3.1 المحلي، أو حتى موديل سحابي مجاني ضعيف) لو اتبعتله
سجل الأحداث النصي بس، بيهلوس — بيقترح إضافة plugin موجود أصلاً، أو
يدّعي إن plugin تاني "مش موثّق" رغم إنه موثّق، لأنه ببساطة معندوش أي
فكرة عن الكود الحقيقي. نفس منطق repomap.py المستخدم في core_engine.py
لشغل الكود العادي: بنديله خريطة حقيقية (تعريفات فعلية، مش تخمين) +
قايمة الأوامر المسجّلة فعليًا — بغض النظر عن أي موديل بيرد.

**ليه مش بنستخدم brain.chat() لكل حاجة ونستغنى عن Ollama المباشر
خالص:** لو كل المزوّدين السحابيين المجانيين حصتهم خلصت أو مفيش مفتاح
متسجّل خالص، وOllama شغال محليًا لكن مش داخل قايمة `chain()` بتاعة
brain (زي لو المستخدم عطّله من الإعدادات)، لسه عايزين احتياطي مباشر.
فبنجرب brain.get_brain().chat() الأول (بتختار أفضل مزوّد متاح لوحدها
وتتنقل بينهم لو فشل واحد)، ولو رجعت فاضية أو بخطأ نرجع لـ Ollama
المباشر كضمانة أخيرة.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import urllib.error
import urllib.request

import brain
import repomap

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "llama3.2"
_REPOMAP_BUDGET = 2500

# نفس نمط استخراج "أسماء شكلها كود" اللي core_engine.py بيستخدمه، عشان
# خريطة الكود تتمركز حوالين اللي فعلاً ظهر في الأخطاء (اسم دالة/ملف).
_SYMBOLish = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")


def _configured_model() -> str:
    """اسم الموديل اللي المستخدم اختاره فعلاً لـ Ollama (عبر brain_model)،
    مش قيمة ثابتة — للاستخدام كضمانة أخيرة لو brain.chat() فشلت بالكامل،
    ومايديش رسالة مضللة لو المستخدم عنده موديل تاني متحمّل غير الافتراضي."""
    try:
        cfg = brain.load_config()
        return cfg.get("models", {}).get("ollama", DEFAULT_MODEL)
    except Exception:
        return DEFAULT_MODEL


def _nezuko_root() -> pathlib.Path:
    """جذر كود نيزوكو نفسها (مش مشروع المستخدم) — عشان الأمر ده بالتحديد
    بيحسّن نيزوكو ذات نفسها. في الـ exe المبني (frozen)، الملفات
    المصدرية مبعوتة عبر --add-data وبتتفك في sys._MEIPASS وقت التشغيل."""
    if getattr(sys, "frozen", False):
        return pathlib.Path(getattr(sys, "_MEIPASS", "."))
    return pathlib.Path(__file__).resolve().parent.parent


def _real_plugin_list(engine) -> str:
    """قايمة الأوامر المسجّلة فعليًا (مش تخمين) — بتمنع الموديل من
    الادّعاء إن plugin "مش موجود" أو "مش موثّق" وهو أصلاً شغال."""
    try:
        commands = engine.registry.list_commands()
    except Exception:
        return ""
    if not commands:
        return ""
    lines = ["Commands actually registered right now (do NOT claim these are missing):"]
    for cmd in commands:
        desc = f" — {cmd.description}" if cmd.description else ""
        lines.append(f"  {cmd.name}{desc}")
    return "\n".join(lines)


def _ask_ollama_direct(prompt: str, model: str) -> str:
    """نداء مباشر لـ Ollama من غير المرور بـ brain.py — ضمانة أخيرة فقط،
    مش المسار الأساسي (شوف الشرح فوق)."""
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("response", "").strip()


def _ask_best_available(prompt: str) -> tuple[str, str]:
    """بيرجع (النص, وصف مين رد). بيجرب brain.chat() الأول (أفضل مزوّد
    متاح فعليًا دلوقتي، سحابي أو محلي)، وبيرجع لـ Ollama المباشر بس
    لو brain.chat() رجعت فاضية بالكامل (مثلاً كل المزوّدين مسجلين
    فشلوا/محبوسين، بس Ollama شغال محليًا برا قايمة chain لأي سبب)."""
    reply = brain.get_brain().chat(
        [{"role": "user", "content": prompt}], temperature=0.3, max_tokens=800,
    )
    if reply and reply.text:
        return reply.text.strip(), reply.label or reply.provider or "brain"
    model = _configured_model()
    text = _ask_ollama_direct(prompt, model)  # ممكن يطلع Exception، وده متعمّد
    return text, f"Ollama (محلي، مباشر) — {model}"


def _cmd_self_improve(ctx) -> str:
    engine = ctx.engine
    recent = list(engine.log_history)[-40:]
    if not recent:
        return "Not enough history to analyse yet — run a few commands first"
    transcript = "\n".join(f"[{lvl}] {msg}" for lvl, msg in recent)

    mentioned = set(_SYMBOLish.findall(transcript))
    try:
        code_map = repomap.build(_nezuko_root(), mentioned=mentioned, budget_chars=_REPOMAP_BUDGET)
    except Exception:
        code_map = ""  # الخريطة تحسين، مش شرط — لو فشلت نكمل من غيرها

    plugin_list = _real_plugin_list(engine)

    context_blocks = []
    if code_map:
        context_blocks.append(f"Real map of Nezuko's own source code:\n{code_map}")
    if plugin_list:
        context_blocks.append(plugin_list)
    context = "\n\n".join(context_blocks)

    prompt = (
        "You are reviewing the recent activity log of a local desktop assistant app "
        "called Nezuko (nickname 'nezuko'), written in Python.\n"
        "Base every suggestion ONLY on the real code map and command list below, plus "
        "the log — never invent a plugin name, a missing command, or code in a language "
        "other than Python. If a plugin is listed as registered, it exists and is documented; "
        "do not claim otherwise.\n\n"
        f"{context}\n\n"
        "Point out any recurring errors/warnings in the log below, and suggest concrete, "
        "safe improvements grounded in the actual code above, in at most 5 bullet points, "
        "written in Arabic. If nothing concrete is wrong, say so plainly instead of inventing "
        "an issue.\n\n"
        f"Log:\n{transcript}"
    )
    try:
        suggestion, who = _ask_best_available(prompt)
    except urllib.error.HTTPError as e:
        model = _configured_model()
        if e.code == 404:
            return (
                f"⚠  Ollama is running, but the model '{model}' isn't pulled yet.\n"
                f"Run: ollama pull {model}\n"
                "(or switch the configured model with: brain_model ollama <name>)"
            )
        return f"❌ Ollama returned an error ({e.code}): {e}"
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        return (
            "⚠  No provider available (cloud quota exhausted and no local Ollama running).\n"
            "Add a free key via brain_key, or run Ollama:\n"
            f"   ollama pull {_configured_model()}\n"
            "Then try this command again."
        )
    except Exception as e:
        return f"❌ error while asking for suggestions: {e}"
    if not suggestion:
        return "⚠  No model returned anything — check brain_status"
    return f"💡 Suggested improvements (via {who}, review them and apply what you like, by hand):\n" + suggestion


def register(engine):
    engine.registry.register(
        "self_improve", _cmd_self_improve,
        "self_improve — read the recent log + a real map of Nezuko's own code and suggest "
        "grounded improvements via the best available model (cloud or local); changes nothing on its own",
    )
