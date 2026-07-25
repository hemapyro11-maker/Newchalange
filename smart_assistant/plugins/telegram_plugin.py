"""
telegram_plugin.py — قناة تحكم عن بُعد: تتحكم في نيزوكو من موبايلك عبر
بوت تليجرام، بيستخدم نفس الـ 100+ أمر المسجّلة بالظبط، من غير أي مسار
تنفيذ "خاص" أو مختصر. مستوحى من فكرة الـ multi-channel messaging في
أدوات زي Clawdbot، لكن بنطاق أبسط بكتير (قناة واحدة، مش gateway كامل).

**الأمان أولاً — ده أول مرة نيزوكو بيتعرّض لمدخلات من الإنترنت:**
كل الأدوات التانية في المشروع بتفترض إن اللي بيكتب الأمر هو نفسه اللي
قاعد قدام الجهاز. القناة دي بتكسر الافتراض ده، فمحتاجة حماية حقيقية:

1. **Pairing إجباري (زي Clawdbot بالظبط):** أول مرة حد يكلم البوت،
   بيتولّد له كود، والبوت بيقوله يروح لنيزوكو نفسه على الجهاز ويكتب
   `telegram_approve <code>`. يعني **قرار الموافقة بيتاخد من على
   الجهاز نفسه**، مش من تليجرام — محدش يقدر يوافق على نفسه عن بُعد.
2. **Allowlist صارم:** غير الـ owner_ids المعتمدين، أي رسالة من أي
   حد تاني بترجع رسالة pairing بس — **مفيش تنفيذ أي أمر أبدًا** لغير
   المعتمدين، حتى محاولة واحدة.
3. **مفيش صلاحية مخفّضة للمعتمدين:** لما توافق على شخص، هو بقى عنده
   **نفس صلاحية إنك تقعد على الكيبورد بتاعك بالظبط** — بما فيها أوامر
   زي `run` (تنفيذ أي أمر نظام). ده قرار مقصود موثّق في SECURITY.md،
   مش قصور — التوافق نفسه هو حاجز الحماية الوحيد.

**التنفيذ الفعلي:** أي رسالة من owner معتمد بتتبعت لنفس طابور التنفيذ
العادي بتاع core_engine (`run_task`، مش مسار مختصر)، فبتاخد بالظبط نفس
معاملة أي أمر متكتوب على الجهاز (فحص typo correction، تأكيد الأوامر
الغامضة، تسجيل في اللوج المحلي كمان — مش مخفي عن صاحب الجهاز).

الأوامر (على الجهاز، مش على تليجرام): telegram_set_token,
telegram_approve, telegram_deauthorize, telegram_status
"""
from __future__ import annotations

import datetime
import json
import pathlib
import queue
import random
import sys
import threading

try:
    from telegram.ext import Application, CommandHandler, MessageHandler, filters
    _HAS_PTB = True
except ImportError:
    _HAS_PTB = False

_MAX_PENDING_PAIRS = 20
_DISPATCH_TIMEOUT = 30


def _config_path() -> pathlib.Path:
    base = pathlib.Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) \
        else pathlib.Path(__file__).resolve().parent.parent
    return base / "telegram_config.json"


def _default_config() -> dict:
    return {"bot_token": None, "owner_ids": [], "pending_pairs": {}}


def _load_config() -> dict:
    path = _config_path()
    if not path.exists():
        return _default_config()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_config()
    if not isinstance(data, dict):
        return _default_config()
    data.setdefault("bot_token", None)
    data.setdefault("owner_ids", [])
    data.setdefault("pending_pairs", {})
    return data


def _save_config(data: dict) -> None:
    try:
        _config_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


# ── pairing ──────────────────────────────────────────────────────────────

def _generate_pair_code() -> str:
    return f"{random.randint(0, 999999):06d}"


def _request_pairing(sender_id: int) -> str:
    """بيسجل (أو يرجع الموجود) كود موافقة لمرسل مش معروف. مفيش تنفيذ
    أي أمر هنا خالص — بس توليد/استرجاع كود."""
    data = _load_config()
    key = str(sender_id)
    existing = data["pending_pairs"].get(key)
    if existing:
        return existing["code"]
    code = _generate_pair_code()
    if len(data["pending_pairs"]) >= _MAX_PENDING_PAIRS:
        # منع نمو غير محدود من سبام طلبات pairing وهمية — نشيل أقدم واحد
        oldest_key = min(data["pending_pairs"], key=lambda k: data["pending_pairs"][k]["requested_at"])
        del data["pending_pairs"][oldest_key]
    data["pending_pairs"][key] = {
        "code": code, "requested_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    _save_config(data)
    return code


# ── تنفيذ حقيقي عبر نفس طابور core_engine (مش مسار مختصر) ───────────────

def _run_and_capture(engine, text: str) -> str:
    """بينفذ النص كأمر عادي تمامًا عبر run_task (نفس الطابور بتاع أي
    أمر مكتوب على الجهاز)، ويرجع نتيجته النصية للرد بيها على تليجرام.
    بيلقط الرد عن طريق استبدال engine._log مؤقتًا أثناء تنفيذ المهمة
    دي بس — آمن لأن كل التنفيذ بيحصل بالتتابع على thread واحد، فمفيش
    تداخل مع أي أمر تاني وقت اللقط ده."""
    result_holder: queue.Queue = queue.Queue(maxsize=1)

    def _task(ctx):
        captured: list[str] = []
        original_log = engine._log

        def capturing_log(msg, level="info"):
            captured.append(str(msg))
            original_log(msg, level)  # لسه بيتسجل في لوج نيزوكو المحلي كمان

        engine._log = capturing_log
        try:
            engine._dispatch(text)
        finally:
            engine._log = original_log
        result_holder.put("\n".join(captured) if captured else "(نُفّذ من غير أي رد نصي)")

    engine.run_task(text, _task)
    try:
        return result_holder.get(timeout=_DISPATCH_TIMEOUT)
    except queue.Empty:
        return "⏱ الأمر لسه في طابور التنفيذ — اتأكد إن نيزوكو شغالة (زرار ▶ تشغيل على الجهاز)"


def _handle_incoming(engine, sender_id: int, text: str) -> str:
    """المنطق الأمني الأساسي: owner معتمد بينفذ، غير كده بيرجع تعليمات
    pairing بس — القلب الحقيقي لحماية القناة دي، ومختبر بشكل مباشر
    من غير أي اعتماد على تليجرام نفسه."""
    data = _load_config()
    if sender_id in data["owner_ids"]:
        return _run_and_capture(engine, text)
    code = _request_pairing(sender_id)
    return (
        "🔒 معرفك مش معروف لنيزوكو.\n"
        "لو انت صاحب الجهاز ده، روح لنيزوكو على جهازك واكتب:\n"
        f"telegram_approve {code}"
    )


# ── أوامر الجهاز (desktop-side) ─────────────────────────────────────────

def _cmd_telegram_set_token(ctx) -> str:
    if not ctx.args:
        return "usage: telegram_set_token <token>   (احصل عليه من @BotFather على تليجرام)"
    data = _load_config()
    data["bot_token"] = ctx.args[0]
    _save_config(data)
    _ensure_bot_started(ctx.engine)
    return (
        "✅ اتسجل الـ token.\n"
        "لو مفيش owner متظبط لسه، أول حد يكلم البوت على تليجرام هيحتاج "
        "يتوافق عليه من هنا بـ: telegram_approve <code>"
    )


def _cmd_telegram_approve(ctx) -> str:
    if not ctx.args:
        return "usage: telegram_approve <code>"
    code = ctx.args[0]
    data = _load_config()
    match_id = next((sid for sid, info in data["pending_pairs"].items() if info["code"] == code), None)
    if match_id is None:
        return "❌ الكود ده مش موجود أو منتهي"
    del data["pending_pairs"][match_id]
    if int(match_id) not in data["owner_ids"]:
        data["owner_ids"].append(int(match_id))
    _save_config(data)
    return f"✅ اتوافق على المستخدم {match_id} — بقى يقدر يتحكم في نيزوكو بالكامل من تليجرام (زي ما لو قاعد على جهازك)"


def _cmd_telegram_deauthorize(ctx) -> str:
    if not ctx.args or not ctx.args[0].lstrip("-").isdigit():
        return "usage: telegram_deauthorize <id>"
    target = int(ctx.args[0])
    data = _load_config()
    if target not in data["owner_ids"]:
        return f"❌ المستخدم {target} مش موافق عليه أصلاً"
    data["owner_ids"].remove(target)
    _save_config(data)
    return f"🚫 اتشال {target} — مش هيقدر يتحكم في نيزوكو من تليجرام تاني"


def _cmd_telegram_status(ctx) -> str:
    data = _load_config()
    bot_thread = getattr(ctx.engine, "_telegram_thread", None)
    lines = [
        "📱 حالة قناة تليجرام:",
        f"  Token: {'✅ متظبط' if data['bot_token'] else '❌ مش متظبط — telegram_set_token <token>'}",
        f"  البوت: {'✅ شغال' if bot_thread is not None and bot_thread.is_alive() else '❌ مش شغال'}",
        f"  Owners معتمدين: {', '.join(str(i) for i in data['owner_ids']) or '(مفيش)'}",
    ]
    if data["pending_pairs"]:
        lines.append(f"  طلبات موافقة معلّقة: {len(data['pending_pairs'])}")
    if not _HAS_PTB:
        lines.append("  ⚠️ python-telegram-bot مش متثبت — pip install python-telegram-bot")
    return "\n".join(lines)


# ── تشغيل البوت (thread خلفي منفصل، asyncio) ─────────────────────────────

def _run_bot(engine, token: str, stop_event: threading.Event) -> None:
    import asyncio

    async def _on_start(update, context):
        await update.message.reply_text("أهلاً! أنا نيزوكو 🦊 — لو انت صاحب الجهاز، ابعتلي أي أمر.")

    async def _on_message(update, context):
        if update.effective_user is None or update.message is None or update.message.text is None:
            return
        reply = _handle_incoming(engine, update.effective_user.id, update.message.text)
        await update.message.reply_text(reply or "(مفيش رد)")

    async def _main():
        app = Application.builder().token(token).build()
        app.add_handler(CommandHandler("start", _on_start))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _on_message))
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        try:
            while not stop_event.is_set():
                await asyncio.sleep(1)
        finally:
            await app.updater.stop()
            await app.stop()
            await app.shutdown()

    asyncio.run(_main())


def _ensure_bot_started(engine) -> None:
    if not _HAS_PTB:
        return
    existing = getattr(engine, "_telegram_thread", None)
    if existing is not None and existing.is_alive():
        return
    data = _load_config()
    token = data.get("bot_token")
    if not token:
        return
    stop_event = threading.Event()
    thread = threading.Thread(
        target=_run_bot, args=(engine, token, stop_event), daemon=True, name="nezuko-telegram",
    )
    engine._telegram_stop = stop_event
    engine._telegram_thread = thread
    thread.start()


def register(engine):
    engine.registry.register("telegram_set_token", _cmd_telegram_set_token,
                              "telegram_set_token <token> — تظبيط بوت تليجرام (من @BotFather)")
    engine.registry.register("telegram_approve", _cmd_telegram_approve,
                              "telegram_approve <code> — الموافقة على مستخدم تليجرام طلب pairing")
    engine.registry.register("telegram_deauthorize", _cmd_telegram_deauthorize,
                              "telegram_deauthorize <id> — إلغاء صلاحية مستخدم تليجرام معتمد")
    engine.registry.register("telegram_status", _cmd_telegram_status,
                              "telegram_status — حالة قناة تليجرام (البوت، الـ owners، الطلبات المعلّقة)")
    _ensure_bot_started(engine)
