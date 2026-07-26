"""
self_improve_plugin.py — يقترح تحسينات بالاعتماد على نموذج محلي مجاني
(Ollama — ollama.com) بدل أي API مدفوع، اتساقاً مع مبدأ Zero-Cost First.

بالتصميم: الاقتراحات نصية فقط ومحدش بيتعدل تلقائي — القرار والتطبيق
دايماً للمستخدم. مفيش هنا أي تنزيل/تشغيل كود من الإنترنت من غير مراجعة،
لأن ده بيفتح ثغرة تنفيذ كود غير موثوق (RCE) على جهاز المستخدم.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "llama3.2"


def _ask_ollama(prompt: str, model: str = DEFAULT_MODEL) -> str:
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("response", "").strip()


def _cmd_self_improve(ctx) -> str:
    engine = ctx.engine
    recent = list(engine.log_history)[-40:]
    if not recent:
        return "Not enough history to analyse yet — run a few commands first"
    transcript = "\n".join(f"[{lvl}] {msg}" for lvl, msg in recent)
    prompt = (
        "You are reviewing the recent activity log of a local desktop assistant app. "
        "Point out any recurring errors/warnings and suggest concrete, safe improvements "
        "(new plugin commands, fixes) in at most 5 bullet points, written in Arabic.\n\n"
        f"Log:\n{transcript}"
    )
    try:
        suggestion = _ask_ollama(prompt)
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        return (
            "⚠  No local model running (Ollama) to suggest improvements.\n"
            "It is completely free — get it from https://ollama.com then run:\n"
            f"   ollama pull {DEFAULT_MODEL}\n"
            "Then try this command again."
        )
    except Exception as e:
        return f"❌ error while asking for suggestions: {e}"
    if not suggestion:
        return "⚠  The local model returned nothing — try another model or check it is running"
    return "💡 Suggested improvements (review them and apply what you like, by hand):\n" + suggestion


def register(engine):
    engine.registry.register(
        "self_improve", _cmd_self_improve,
        "self_improve — read the recent log and suggest improvements via a free local model (Ollama); changes nothing on its own",
    )
