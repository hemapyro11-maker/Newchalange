"""
system_plugin.py — أوامر إدارة أنظمة نيزوكو الأساسية من غير الواجهة:
الجلسات المحفوظة، الصلاحيات، والأحداث (hooks).

كل حاجة هنا متاحة كمان من قايمة الإعدادات (⚙)، بس موجودة كأوامر عشان
تشتغل من تليجرام/ديسكورد والجداول المؤقتة كمان — مش من الواجهة بس.

الأوامر: sessions, session_open, session_delete, allow, allow_list,
disallow, hook
"""
from __future__ import annotations

import hooks
import permissions
import sessions


# ── الجلسات ──────────────────────────────────────────────────────────

def _cmd_sessions(ctx) -> str:
    rows = sessions.list_all()
    if not rows:
        return "مفيش محادثات محفوظة لسه."
    lines = [f"💬 {len(rows)} محادثة محفوظة:\n"]
    for s in rows[:20]:
        lines.append(
            f"  {s['id']}\n"
            f"    {s['title']}\n"
            f"    {s['turns']} دور · {sessions.relative_time(s['updated'])}"
        )
    if len(rows) > 20:
        lines.append(f"\n… و{len(rows) - 20} كمان")
    lines.append("\nلفتح واحدة: session_open <id>   ·   من الواجهة: /resume")
    return "\n".join(lines)


def _cmd_session_open(ctx) -> str:
    if not ctx.args:
        return "usage: session_open <id>   (شوف sessions للقايمة)"
    session_id = ctx.args[0]
    messages = sessions.load(session_id)
    if messages is None:
        return f"❌ مفيش محادثة بالمعرّف ده: {session_id}"
    ctx.engine.session_id = session_id
    ctx.engine.chat_history = list(messages)
    meta = sessions.meta(session_id) or {}
    return (
        f"✅ اتفتحت: {meta.get('title', '—')}\n"
        f"   {len(messages)} رسالة · هكمّل من عندها."
    )


def _cmd_session_delete(ctx) -> str:
    if not ctx.args:
        return "usage: session_delete <id|--all>"
    if ctx.args[0] == "--all":
        return f"🗑️ اتمسحت {sessions.delete_all()} محادثة"
    ok = sessions.delete(ctx.args[0])
    return "🗑️ اتمسحت" if ok else f"❌ مفيش محادثة بالمعرّف ده: {ctx.args[0]}"


# ── الصلاحيات ────────────────────────────────────────────────────────

def _cmd_allow(ctx) -> str:
    if not ctx.args:
        return "usage: allow <command>   (بيخلي الأمر يعدي من غير سؤال)"
    ok, message = permissions.allow(ctx.args[0])
    return message if ok else message


def _cmd_allow_list(ctx) -> str:
    allowed = sorted(permissions.allowed())
    lines = ["🔓 أوامر بتعدي من غير سؤال:"]
    if allowed:
        lines += [f"  • {name}" for name in allowed]
    else:
        lines.append("  (مفيش — كل حاجة بتتسأل، وده الافتراضي الآمن)")
    lines.append("\n🔒 ممنوعة نهائيًا مهما حصل:")
    lines.append("  " + "، ".join(sorted(permissions.never_allowed())))
    lines.append(
        "\nدي بتنفذ كود أو بتوصل لحاجة بمدخلات حرة — محتاجة موافقتك كل مرة."
    )
    return "\n".join(lines)


def _cmd_disallow(ctx) -> str:
    if not ctx.args:
        return "usage: disallow <command|--all>"
    if ctx.args[0] == "--all":
        return f"🔒 اتسحبت {permissions.revoke_all()} صلاحية"
    ok = permissions.revoke(ctx.args[0])
    return "🔒 اتسحبت الصلاحية" if ok else f"❌ {ctx.args[0]} مش في القايمة أصلاً"


# ── الأحداث ──────────────────────────────────────────────────────────

def _cmd_hook(ctx) -> str:
    usage = (
        "usage:\n"
        "  hook list\n"
        "  hook add <event> <command...>\n"
        "  hook remove <event> <command...>\n"
        "  hook clear\n"
        f"الأحداث: {', '.join(hooks.EVENTS)}"
    )
    if not ctx.args:
        return usage
    action = ctx.args[0].lower()

    if action == "list":
        data = hooks.load()
        lines = ["🪝 الأحداث المربوطة:"]
        total = 0
        for event in hooks.EVENTS:
            if data[event]:
                lines.append(f"\n  {event}:")
                for cmd in data[event]:
                    lines.append(f"    → {cmd}")
                total += len(data[event])
        if not total:
            lines.append("  (مفيش حاجة مربوطة)")
        lines.append("\n💡 {command} في نص الـ hook بتتبدل باسم الأمر اللي شغّله")
        return "\n".join(lines)

    if action == "clear":
        return f"🗑️ اتفك {hooks.clear()} ربط"

    if action in ("add", "remove"):
        if len(ctx.args) < 3:
            return usage
        event, command = ctx.args[1], " ".join(ctx.args[2:])
        if action == "add":
            _ok, message = hooks.add(event, command)
            return message
        ok = hooks.remove(event, command)
        return "🗑️ اتفك الربط" if ok else "❌ الربط ده مش موجود"

    return usage


def register(engine):
    r = engine.registry.register
    r("sessions", _cmd_sessions, "sessions — كل المحادثات المحفوظة")
    r("session_open", _cmd_session_open, "session_open <id> — افتح محادثة محفوظة وكمّل عليها")
    r("session_delete", _cmd_session_delete, "session_delete <id|--all> — امسح محادثة")
    r("allow", _cmd_allow, "allow <command> — خلي الأمر ده يعدي من غير سؤال")
    r("allow_list", _cmd_allow_list, "allow_list — الأوامر المسموحة والممنوعة نهائيًا")
    r("disallow", _cmd_disallow, "disallow <command|--all> — اسحب السماح")
    r("hook", _cmd_hook, "hook list|add|remove|clear — اربط أوامر بأحداث نيزوكو")
