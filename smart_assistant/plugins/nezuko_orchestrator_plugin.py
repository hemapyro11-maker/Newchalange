"""Unified capability audit, cross-plugin workflows, and validated evolution routing."""
from __future__ import annotations

class Workflow:
    def __init__(self, purpose: str, steps: tuple[str, ...]):
        self.purpose = purpose
        self.steps = steps


WORKFLOWS = {
    "growth_video": Workflow(
        "Research winning channel patterns and produce an original upload",
        ("channel_view_growth_lab", "youtube_video_analyze", "video_learning_brief",
         "script_outline", "hook_analyzer", "thumbnail_generate", "natural_voice",
         "master_audio_pro", "create_video", "encode_video", "youtube_video_analyze"),
    ),
    "professional_edit": Workflow(
        "Inspect, edit, caption, master, encode, and quality-check a video",
        ("probe", "detect_scenes", "auto_trim_silence", "stabilize", "color_grade",
         "generate_subtitles", "master_audio_pro", "encode_video", "youtube_video_analyze"),
    ),
    "voice_studio": Workflow(
        "Prepare a reference, clone or select a voice, clean it, and master delivery",
        ("prepare_voice_sample", "clone_voice", "voice_reference", "voice_profile",
         "natural_voice", "denoise_audio", "master_audio_pro", "voice_status"),
    ),
    "coding": Workflow(
        "Inspect a project, make a focused change, test it, and review the diff",
        ("project", "list_files", "search", "read_file", "edit_file", "test", "git_diff"),
    ),
    "connectors": Workflow(
        "Inspect and use built-in, MCP, GitHub, messaging, and external tool connections",
        ("connectors", "github_status", "telegram_status", "discord_status", "external_list"),
    ),
    "repair": Workflow(
        "Diagnose the environment and plugins, repair safely, reload, and verify",
        ("env_check", "plugin_doctor", "media_doctor", "stt_status", "voice_status",
         "self_repair", "reload_plugins", "plugin_doctor"),
    ),
}


def _known(engine) -> dict:
    return {c.name: c for c in engine.registry.list_commands()}


def _cmd_nezuko_integrate(ctx) -> str:
    known = _known(ctx.engine)
    health = ctx.engine.plugin_health
    loaded = [name for name, state in health.items() if state.get("status") == "loaded"]
    broken = [(name, state.get("error") or state.get("status")) for name, state in health.items()
              if state.get("status") != "loaded"]
    collisions = [(name, state.get("collisions")) for name, state in health.items()
                  if state.get("collisions")]
    undocumented = [name for name, command in known.items() if not command.description.strip()]
    complete = []
    incomplete = []
    for name, workflow in WORKFLOWS.items():
        missing = [step for step in workflow.steps if step not in known]
        (incomplete if missing else complete).append((name, missing))
    lines = [
        "🧠 Jarvis unified tool system",
        f"Plugins: {len(loaded)}/{len(health)} healthy | Commands: {len(known)} integrated",
        f"Workflows: {len(complete)}/{len(WORKFLOWS)} complete",
        f"Descriptions: {len(known) - len(undocumented)}/{len(known)} documented for model selection",
    ]
    if broken:
        lines.append("Broken plugins: " + "; ".join(f"{n}: {e}" for n, e in broken))
    if collisions:
        lines.append("Blocked collisions: " + "; ".join(f"{n}: {', '.join(c)}" for n, c in collisions))
    if undocumented:
        lines.append("Undocumented commands: " + ", ".join(undocumented))
    if incomplete:
        lines.append("Incomplete workflows: " + "; ".join(f"{n} missing {', '.join(m)}" for n, m in incomplete))
    lines.append("Available workflows: " + ", ".join(WORKFLOWS))
    lines.append("Run `nezuko_workflow <name>` to see the verified cross-tool sequence.")
    return "\n".join(lines)


def _cmd_nezuko_workflow(ctx) -> str:
    if not ctx.args:
        return "Available integrated workflows:\n" + "\n".join(
            f"• {name}: {flow.purpose}" for name, flow in WORKFLOWS.items()
        )
    name = ctx.args[0].lower()
    flow = WORKFLOWS.get(name)
    if not flow:
        return "❌ unknown workflow. Choose: " + ", ".join(WORKFLOWS)
    known = _known(ctx.engine)
    lines = [f"🔗 Integrated workflow: {name}", flow.purpose]
    for i, step in enumerate(flow.steps, 1):
        command = known.get(step)
        lines.append(f"{i}. {'✅' if command else '❌'} {step}" + (f" — {command.description}" if command else " — missing"))
    if all(step in known for step in flow.steps):
        lines.append("All stages are loaded. Jarvis can chain them and inspect each real result before choosing the next stage.")
    return "\n".join(lines)


def _cmd_nezuko_evolve(ctx) -> str:
    if not ctx.args:
        return "usage: jarvis_evolve <plugin_name> — validated improvement with backup, tests, and rollback"
    target = ctx.args[0].removesuffix(".py")
    state = ctx.engine.plugin_health.get(target)
    if not state:
        return f"❌ unknown plugin: {target}. Run jarvis_integrate first."
    repair = ctx.engine.registry.get("self_repair")
    if not repair:
        return "❌ self_repair is not loaded"
    subctx = type(ctx)(raw=f"self_repair improve {target}", args=["improve", target], engine=ctx.engine)
    return repair.handler(subctx)


def register(engine):
    engine.registry.register("jarvis_integrate", _cmd_nezuko_integrate,
                             "jarvis_integrate — audit loaded tools and cross-tool workflows")
    engine.registry.register("jarvis_workflow", _cmd_nezuko_workflow,
                             "jarvis_workflow [growth_video|professional_edit|voice_studio|coding|connectors|repair] — inspect an integrated workflow")
    engine.registry.register("jarvis_evolve", _cmd_nezuko_evolve,
                             "jarvis_evolve <plugin_name> — validated improvement with backup, tests and rollback")
    engine.registry.register("nezuko_integrate", _cmd_nezuko_integrate,
                             "nezuko_integrate — audit every loaded plugin, command, collision, description, and cross-tool workflow")
    engine.registry.register("nezuko_workflow", _cmd_nezuko_workflow,
                             "nezuko_workflow [growth_video|professional_edit|voice_studio|coding|connectors|repair] — verified integrated sequences across Jarvis tools")
    engine.registry.register("nezuko_evolve", _cmd_nezuko_evolve,
                             "nezuko_evolve <plugin_name> — let Jarvis improve one of its own plugins through validated backup, tests, reload, and rollback")
