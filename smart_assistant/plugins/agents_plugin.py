"""
agents_plugin.py — أوامر الـ subagents وأنماط الرد.

الأوامر: agents, agent, agent_new, agent_delete, style, styles
"""
from __future__ import annotations

import agents
import styles


# ── subagents ────────────────────────────────────────────────────────

def _cmd_agents(ctx) -> str:
    agents.write_starters()
    found = agents.load_all()
    if not found:
        return f"No agents yet. Drop a .md file into {agents.agents_dir()}"
    registry = {c.name for c in ctx.engine.registry.list_commands()}
    lines = [f"🤖 {len(found)} agents:\n"]
    for name, meta in sorted(found.items()):
        tools = agents.allowed_tools(meta, registry)
        scope = f"{len(tools)} tools" if meta["tools"] else "all tools"
        lines.append(f"  {name}")
        if meta["description"]:
            lines.append(f"    {meta['description']}")
        lines.append(f"    {scope}")
    lines.append("\nRun one:  agent <name> <task>")
    return "\n".join(lines)


def _cmd_agent(ctx) -> str:
    if len(ctx.args) < 2:
        return "usage: agent <name> <task...>   (see: agents)"
    name = ctx.args[0]
    # ctx.raw مش ctx.args — عشان المهمة تفضل زي ما المستخدم كتبها
    # بالظبط من غير ما shlex يقصّها
    task = ctx.raw.split(maxsplit=2)[2] if len(ctx.raw.split(maxsplit=2)) > 2 else ""
    if not task.strip():
        return "usage: agent <name> <task...>"
    reply, provider = agents.run(ctx.engine, name, task)
    return f"{reply}\n\n— {name} · {provider}" if provider else reply


def _cmd_agent_new(ctx) -> str:
    parts = ctx.raw.split(maxsplit=2)
    if len(parts) < 3:
        return (
            "usage: agent_new <name> <instructions...>\n"
            "Restrict its tools by editing the file afterwards:\n"
            f"  {agents.agents_dir()}"
        )
    path = agents.save(parts[1], "", parts[2])
    return f"✅ agent saved: {path}\nEdit that file to add a description or restrict its tools."


def _cmd_agent_delete(ctx) -> str:
    if not ctx.args:
        return "usage: agent_delete <name>"
    return "🗑️ deleted" if agents.delete(ctx.args[0]) else f"❌ no agent named {ctx.args[0]}"


# ── أنماط الرد ───────────────────────────────────────────────────────

def _cmd_styles(ctx) -> str:
    active = styles.current()
    lines = ["🎨 Output styles:\n"]
    for name, meta in sorted(styles.all_styles().items()):
        mark = "❯" if name == active else " "
        lines.append(f" {mark} {name:<10} {meta['desc']}")
    lines.append("\nSwitch:  style <name>")
    lines.append(f"Custom:  drop a .md file into {styles.styles_dir()}")
    return "\n".join(lines)


def _cmd_style(ctx) -> str:
    if not ctx.args:
        return f"Current style: {styles.current()}\nusage: style <name>   (see: styles)"
    _ok, message = styles.set_current(ctx.args[0].lower())
    return message


def register(engine):
    r = engine.registry.register
    r("agents", _cmd_agents, "agents — list specialised subagents")
    r("agent", _cmd_agent, "agent <name> <task> — run a subagent on a task")
    r("agent_new", _cmd_agent_new, "agent_new <name> <instructions> — create a subagent")
    r("agent_delete", _cmd_agent_delete, "agent_delete <name> — remove a subagent")
    r("styles", _cmd_styles, "styles — list output styles")
    r("style", _cmd_style, "style <name> — change how Nezuko writes replies")
