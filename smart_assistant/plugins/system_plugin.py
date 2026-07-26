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
        return "No saved conversations yet."
    lines = [f"💬 {len(rows)} saved conversations:\n"]
    for s in rows[:20]:
        lines.append(
            f"  {s['id']}\n"
            f"    {s['title']}\n"
            f"    {s['turns']} turns · {sessions.relative_time(s['updated'])}"
        )
    if len(rows) > 20:
        lines.append(f"\n… and {len(rows) - 20} more")
    lines.append("\nOpen one: session_open <id>   ·   in the UI: /resume")
    return "\n".join(lines)


def _cmd_session_open(ctx) -> str:
    if not ctx.args:
        return "usage: session_open <id>   (see: sessions)"
    session_id = ctx.args[0]
    messages = sessions.load(session_id)
    if messages is None:
        return f"❌ no conversation with that id: {session_id}"
    ctx.engine.session_id = session_id
    ctx.engine.chat_history = list(messages)
    meta = sessions.meta(session_id) or {}
    return (
        f"✅ opened: {meta.get('title', '—')}\n"
        f"   {len(messages)} messages · continuing from there."
    )


def _cmd_session_delete(ctx) -> str:
    if not ctx.args:
        return "usage: session_delete <id|--all>"
    if ctx.args[0] == "--all":
        return f"🗑️ deleted {sessions.delete_all()} conversations"
    ok = sessions.delete(ctx.args[0])
    return "🗑️ deleted" if ok else f"❌ no conversation with that id: {ctx.args[0]}"


# ── الصلاحيات ────────────────────────────────────────────────────────

def _cmd_allow(ctx) -> str:
    if not ctx.args:
        return "usage: allow <command>   (lets that command run without asking)"
    ok, message = permissions.allow(ctx.args[0])
    return message if ok else message


def _cmd_allow_list(ctx) -> str:
    allowed = sorted(permissions.allowed())
    lines = ["🔓 Commands that run without asking:"]
    if allowed:
        lines += [f"  • {name}" for name in allowed]
    else:
        lines.append("  (none — everything asks, which is the safe default)")
    lines.append("\n🔒 Never allowed, no matter what:")
    lines.append("  " + ", ".join(sorted(permissions.never_allowed())))
    lines.append(
        "\nThese execute code or take free-form input — they need your approval every time."
    )
    return "\n".join(lines)


def _cmd_disallow(ctx) -> str:
    if not ctx.args:
        return "usage: disallow <command|--all>"
    if ctx.args[0] == "--all":
        return f"🔒 revoked {permissions.revoke_all()} permissions"
    ok = permissions.revoke(ctx.args[0])
    return "🔒 permission revoked" if ok else f"❌ {ctx.args[0]} was not in the list"


# ── الأحداث ──────────────────────────────────────────────────────────

def _cmd_hook(ctx) -> str:
    usage = (
        "usage:\n"
        "  hook list\n"
        "  hook add <event> <command...>\n"
        "  hook remove <event> <command...>\n"
        "  hook clear\n"
        f"events: {', '.join(hooks.EVENTS)}"
    )
    if not ctx.args:
        return usage
    action = ctx.args[0].lower()

    if action == "list":
        data = hooks.load()
        lines = ["🪝 Bound hooks:"]
        total = 0
        for event in hooks.EVENTS:
            if data[event]:
                lines.append(f"\n  {event}:")
                for cmd in data[event]:
                    lines.append(f"    → {cmd}")
                total += len(data[event])
        if not total:
            lines.append("  (nothing bound)")
        lines.append("\n💡 {command} in a hook is replaced with the command that fired it")
        return "\n".join(lines)

    if action == "clear":
        return f"🗑️ unbound {hooks.clear()} hooks"

    if action in ("add", "remove"):
        if len(ctx.args) < 3:
            return usage
        event, command = ctx.args[1], " ".join(ctx.args[2:])
        if action == "add":
            _ok, message = hooks.add(event, command)
            return message
        ok = hooks.remove(event, command)
        return "🗑️ unbound" if ok else "❌ no such hook"

    return usage


def register(engine):
    r = engine.registry.register
    r("sessions", _cmd_sessions, "sessions — every saved conversation")
    r("session_open", _cmd_session_open, "session_open <id> — reopen a conversation and continue")
    r("session_delete", _cmd_session_delete, "session_delete <id|--all> — delete a conversation")
    r("allow", _cmd_allow, "allow <command> — let this command run without asking")
    r("allow_list", _cmd_allow_list, "allow_list — what is allowed and what never can be")
    r("disallow", _cmd_disallow, "disallow <command|--all> — revoke permission")
    r("hook", _cmd_hook, "hook list|add|remove|clear — bind commands to events")
