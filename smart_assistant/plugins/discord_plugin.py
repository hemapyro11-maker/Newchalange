"""
discord_plugin.py — قناة تحكم عن بُعد تانية: تتحكم في نيزوكو من ديسكورد،
بنفس الأوامر بالظبط اللي telegram_plugin.py بتستخدمها ونفس نموذج
الأمان بالكامل (pairing إجباري من على الجهاز، allowlist صارم). مستوحى
من نفس فكرة الـ multi-channel messaging في Clawdbot.

**عن قصد مفيش أي import من telegram_plugin.py هنا** — كل plugin في
المشروع مستقل بالكامل (تقدر تشيل الملف ده لوحده من غير ما تكسر أي
plugin تاني)، فالمنطق (pairing، allowlist، تنفيذ عبر run_task) متكرر
هنا بدل ما يتشارك، بنفس فلسفة تكرار `_config_path()`/الحفظ المحلي في
كل plugin تاني في المشروع.

**الأمان — نفس نموذج telegram_plugin.py بالضبط:**
1. Pairing إجباري: مستخدم جديد بياخد كود، والموافقة الفعلية بتتم بأمر
   `discord_approve <code>` على الجهاز نفسه بس — مش من ديسكورد.
2. Allowlist صارم: غير الـ owner_ids، أي رسالة بترجع تعليمات pairing
   بس، بدون أي محاولة تنفيذ.
3. مفيش صلاحية مخفّضة: owner معتمد = نفس صلاحية القاعد على الجهاز.

**ملحوظة Discord-specific:** لازم تفعّل "Message Content Intent" من
Discord Developer Portal (إعدادات البوت) — من غيرها ديسكورد مش هيبعت
محتوى الرسائل للبوت خالص، وأي رسالة هتوصل فاضية. ولو البوت متضاف
لسيرفر عام (مش رسائل خاصة بس)، أي حد في السيرفر هيقدر يكلمه — الحماية
دي مش مشكلة (allowlist بيحميك برضه) لكن الأفضل تستخدمه في رسائل خاصة
(DM) بس لتجربة أنضف.

**تخزين التوكن بأمان (keyring):** نفس فكرة telegram_plugin.py بالظبط —
التوكن بيتحفظ في مخزن أسرار نظام التشغيل عبر `keyring` بدل نص عادي،
مع fallback تلقائي لنص عادي لو `keyring` مش متاح.

الأوامر (على الجهاز، مش على ديسكورد): discord_set_token,
discord_approve, discord_deauthorize, discord_status
"""
from __future__ import annotations

import datetime
import json
import pathlib
import queue
import secrets
import sys
import threading

try:
    import discord
    _HAS_DISCORD = True
except ImportError:
    _HAS_DISCORD = False

try:
    import keyring
    from keyring.errors import KeyringError
    _HAS_KEYRING = True
except ImportError:
    keyring = None
    KeyringError = Exception
    _HAS_KEYRING = False

_KEYRING_SERVICE = "nezuko-discord"
_TOKEN_KEY = "bot_token"
_MAX_PENDING_PAIRS = 20
_DISPATCH_TIMEOUT = 30
_PAIR_CODE_TTL = datetime.timedelta(hours=24)

# discord_config.json بيتقرا/يتكتب من تريدين مختلفين: thread البوت نفسه
# (asyncio، بينادي _request_pairing لما حد جديد يبعت رسالة) وthread
# المحرك الرئيسي (لما صاحب الجهاز يكتب discord_approve/discord_deauthorize/
# discord_set_token). من غير قفل، الاتنين ممكن يقروا نفس النسخة القديمة
# من الملف، يعدّلوا نسختهم في الذاكرة كل واحد لوحده، ويكتبوا فوق بعض —
# مين ما كتب أخيراً بيمسح تعديل التاني بالكامل (TOCTOU حقيقي، مش نظري).
_config_lock = threading.Lock()


def _config_path() -> pathlib.Path:
    base = pathlib.Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) \
        else pathlib.Path(__file__).resolve().parent.parent
    return base / "discord_config.json"


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


# ── تخزين آمن للتوكن (keyring أولاً، نص عادي كـ fallback) ────────────────

def _get_token() -> str | None:
    if _HAS_KEYRING:
        try:
            token = keyring.get_password(_KEYRING_SERVICE, _TOKEN_KEY)
        except KeyringError:
            token = None
        if token:
            return token
    return _load_config().get("bot_token")


def _set_token(token: str) -> bool:
    if not _HAS_KEYRING:
        return False
    try:
        keyring.set_password(_KEYRING_SERVICE, _TOKEN_KEY, token)
    except KeyringError:
        return False
    with _config_lock:
        data = _load_config()
        if data.get("bot_token"):
            data["bot_token"] = None
            _save_config(data)
    return True


# ── pairing ──────────────────────────────────────────────────────────────

def _generate_pair_code(existing_codes: set[str]) -> str:
    """كود عشوائي حقيقي عبر secrets (مش random العادية — مش آمنة
    تشفيريًا، وده كود بيتحكم في صلاحية وصول كاملة لنيزوكو) وفريد فعليًا
    بين الطلبات المعلّقة الحالية — عشان لو حصل تصادم كود بين طلبين،
    صاحب الجهاز يوافق بالغلط على مرسل مش قاصده."""
    for _ in range(50):
        code = f"{secrets.randbelow(1_000_000):06d}"
        if code not in existing_codes:
            return code
    return f"{secrets.randbelow(1_000_000):06d}"  # احتمال شبه مستحيل، لكن مينفعش نعلّق


def _request_pairing(sender_id: int) -> str:
    """بيسجل (أو يرجع الموجود) كود موافقة لمرسل مش معروف. مفيش تنفيذ
    أي أمر هنا خالص — بس توليد/استرجاع كود."""
    with _config_lock:
        data = _load_config()
        key = str(sender_id)
        existing = data["pending_pairs"].get(key)
        if existing:
            return existing["code"]
        existing_codes = {info["code"] for info in data["pending_pairs"].values()}
        code = _generate_pair_code(existing_codes)
        if len(data["pending_pairs"]) >= _MAX_PENDING_PAIRS:
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
    أمر مكتوب على الجهاز)، ويرجع نتيجته النصية للرد بيها على ديسكورد.
    بيلقط الرد عن طريق استبدال engine._log مؤقتًا أثناء تنفيذ المهمة
    دي بس — آمن لأن كل التنفيذ بيحصل بالتتابع على thread واحد."""
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
        result_holder.put("\n".join(captured) if captured else "(ran, with no text output)")

    engine.run_task(text, _task)
    try:
        return result_holder.get(timeout=_DISPATCH_TIMEOUT)
    except queue.Empty:
        return "⏱ the command is still queued — check that Nezuko is running (the ▶ button on your machine)"


def _handle_incoming(engine, sender_id: int, text: str) -> str:
    """المنطق الأمني الأساسي: owner معتمد بينفذ، غير كده بيرجع تعليمات
    pairing بس."""
    data = _load_config()
    if sender_id in data["owner_ids"]:
        return _run_and_capture(engine, text)
    code = _request_pairing(sender_id)
    return (
        "🔒 Nezuko does not recognise your account.\n"
        "If this is your machine, go to Nezuko on it and type:\n"
        f"discord_approve {code}"
    )


# ── أوامر الجهاز (desktop-side) ─────────────────────────────────────────

def _cmd_discord_set_token(ctx) -> str:
    if not ctx.args:
        return "usage: discord_set_token <token>   (from the Discord Developer Portal)"
    token = ctx.args[0]
    if _set_token(token):
        secure_note = "✅ Token saved safely in the operating system secret store (keyring)."
    else:
        with _config_lock:
            data = _load_config()
            data["bot_token"] = token
            _save_config(data)
        secure_note = (
            "⚠️ Token saved as plain text in discord_config.json — secure keyring storage is not available here.\n"
            "   For safer storage: pip install keyring"
        )
    _ensure_bot_started(ctx.engine)
    return (
        f"{secure_note}\n"
        "You must enable 'Message Content Intent' in the bot settings in the Discord "
        "Developer Portal, otherwise message content arrives empty.\n"
        "If no owner is set yet, the first person to message the bot will need approving "
        "from here with: discord_approve <code>"
    )


def _cmd_discord_approve(ctx) -> str:
    if not ctx.args:
        return "usage: discord_approve <code>"
    code = ctx.args[0]
    with _config_lock:
        data = _load_config()
        match_id = next((sid for sid, info in data["pending_pairs"].items() if info["code"] == code), None)
        if match_id is None:
            return "❌ that code does not exist, or has expired"
        requested_at = data["pending_pairs"][match_id].get("requested_at", "")
        try:
            age = datetime.datetime.now() - datetime.datetime.fromisoformat(requested_at)
        except ValueError:
            age = datetime.timedelta(0)
        del data["pending_pairs"][match_id]
        if age > _PAIR_CODE_TTL:
            _save_config(data)
            return "❌ that code expired (over 24 hours old) — ask them to message the bot again for a fresh one"
        if int(match_id) not in data["owner_ids"]:
            data["owner_ids"].append(int(match_id))
        _save_config(data)
    return f"✅ approved user {match_id} — they now have full control of Nezuko from Discord, as if sitting at your machine"


def _cmd_discord_deauthorize(ctx) -> str:
    if not ctx.args or not ctx.args[0].lstrip("-").isdigit():
        return "usage: discord_deauthorize <id>"
    target = int(ctx.args[0])
    with _config_lock:
        data = _load_config()
        if target not in data["owner_ids"]:
            return f"❌ user {target} was not approved in the first place"
        data["owner_ids"].remove(target)
        _save_config(data)
    return f"🚫 removed {target} — they can no longer control Nezuko from Discord"


def _cmd_discord_status(ctx) -> str:
    data = _load_config()
    token = _get_token()
    bot_thread = getattr(ctx.engine, "_discord_thread", None)
    lines = [
        "🎮 Discord channel status:",
        f"  Token: {'✅ configured' if token else '❌ not configured — discord_set_token <token>'}",
        f"  Bot: {'✅ running' if bot_thread is not None and bot_thread.is_alive() else '❌ not running'}",
        f"  Approved owners: {', '.join(str(i) for i in data['owner_ids']) or '(none)'}",
    ]
    if data["pending_pairs"]:
        lines.append(f"  Pending approval requests: {len(data['pending_pairs'])}")
    if not _HAS_KEYRING:
        lines.append("  ⚠️ keyring is not installed — the token is stored as plain text (pip install keyring for safer storage)")
    if not _HAS_DISCORD:
        lines.append("  ⚠️ discord.py is not installed — pip install discord.py")
    return "\n".join(lines)


# ── تشغيل البوت (thread خلفي منفصل، asyncio) ─────────────────────────────

def _run_bot(engine, token: str, stop_event: threading.Event) -> None:
    import asyncio

    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_message(message):
        if message.author == client.user:
            return
        reply = _handle_incoming(engine, message.author.id, message.content)
        await message.channel.send(reply or "(no reply)")

    async def _main():
        async with client:
            bot_task = asyncio.create_task(client.start(token))
            try:
                while not stop_event.is_set() and not bot_task.done():
                    await asyncio.sleep(1)
            finally:
                await client.close()
                try:
                    await bot_task
                except Exception:
                    pass

    asyncio.run(_main())


def _ensure_bot_started(engine) -> None:
    if not _HAS_DISCORD:
        return
    existing = getattr(engine, "_discord_thread", None)
    if existing is not None and existing.is_alive():
        return
    token = _get_token()
    if not token:
        return
    stop_event = threading.Event()
    thread = threading.Thread(
        target=_run_bot, args=(engine, token, stop_event), daemon=True, name="nezuko-discord",
    )
    engine._discord_stop = stop_event
    engine._discord_thread = thread
    thread.start()


def register(engine):
    engine.registry.register("discord_set_token", _cmd_discord_set_token,
                              "discord_set_token <token> — set up the Discord bot (from the Discord Developer Portal)")
    engine.registry.register("discord_approve", _cmd_discord_approve,
                              "discord_approve <code> — approve a Discord user who requested pairing")
    engine.registry.register("discord_deauthorize", _cmd_discord_deauthorize,
                              "discord_deauthorize <id> — revoke an approved Discord user")
    engine.registry.register("discord_status", _cmd_discord_status,
                              "discord_status — Discord channel status (bot, owners, pending requests)")
    _ensure_bot_started(engine)
