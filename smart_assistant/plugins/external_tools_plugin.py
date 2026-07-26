"""
external_tools_plugin.py — ربط أي برنامج خارجي (أداة CLI، سكربت
بايثون/جافا/شل، أو تطبيق سطح مكتب) كأمر دائم في نيزوكو، بنفس فلسفة
macros_plugin.py بالظبط: قالب أمر فيه {args}، محفوظ في ملف، وبيتسجل
كأمر حي فورًا وبعد كل إعادة تشغيل.

**نموذج الثقة:** زي أمر run المدمج بالظبط — subprocess بدون shell=True
(مفيش command injection كلاسيكي)، لكن ده مش حماية من البرنامج نفسه:
لو سجّلت أداة خطيرة، هتتنفذ بصلاحياتك زي أي حاجة تانية تشغّلها بنفسك.

الأوامر: external_add, external_remove, external_list, external_reload
"""
from __future__ import annotations

import json
import pathlib
import shlex
import subprocess
import sys

TIMEOUT_CLI = 60
_TOOL_MARKER = "external tool ("
_VALID_TYPES = ("cli", "desktop")


def _config_path() -> pathlib.Path:
    base = pathlib.Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) \
        else pathlib.Path(__file__).resolve().parent.parent
    return base / "external_tools.json"


def _load_registry() -> dict:
    path = _config_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_registry(data: dict) -> None:
    _config_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _expand_command(template: str, args: list[str]) -> str:
    args_text = " ".join(args)
    if "{args}" in template:
        return template.replace("{args}", args_text)
    return f"{template} {args_text}".strip()


def _make_handler(command_template: str, tool_type: str):
    def handler(ctx) -> str:
        expanded = _expand_command(command_template, ctx.args)
        try:
            argv = shlex.split(expanded)
        except ValueError as e:
            return f"❌ could not parse the command after substituting {{args}}: {e}"
        if not argv:
            return "❌ the command is empty after substitution"

        if tool_type == "desktop":
            # تطبيقات سطح المكتب بتتشغّل في الخلفية (مش بننتظرها تقفل)
            # عشان مانوقّفش طابور تنفيذ نيزوكو لحد ما البرنامج يتقفل.
            try:
                subprocess.Popen(argv)
            except FileNotFoundError:
                return f"❌ program not found: {argv[0]}"
            except OSError as e:
                return f"❌ could not start the program: {e}"
            return f"✅ started \"{argv[0]}\" in the background"

        try:
            result = subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT_CLI, shell=False)
        except FileNotFoundError:
            return f"❌ program not found: {argv[0]}"
        except subprocess.TimeoutExpired:
            return f"⏱ timed out after {TIMEOUT_CLI}s — if it needs longer, use --type desktop"
        except OSError as e:
            return f"❌ could not run it: {e}"
        out = (result.stdout or "") + (result.stderr or "")
        return out.strip() or f"(exit code {result.returncode})"
    return handler


def _cmd_external_add(ctx) -> str:
    if len(ctx.args) < 2:
        return (
            "usage: external_add <name> <command_template...> [--type cli|desktop]\n"
            "   Put {args} in the template to control exactly where arguments land,\n"
            "   otherwise they are appended at the end automatically."
        )
    args = list(ctx.args)
    tool_type = "cli"
    if "--type" in args:
        idx = args.index("--type")
        if idx + 1 >= len(args):
            return "❌ --type needs a value (cli or desktop)"
        tool_type = args[idx + 1]
        del args[idx:idx + 2]
    if tool_type not in _VALID_TYPES:
        return f"❌ --type must be one of: {', '.join(_VALID_TYPES)}"
    if len(args) < 2:
        return "usage: external_add <name> <command_template...> [--type cli|desktop]"

    name, command_template = args[0], " ".join(args[1:])
    if not name.replace("_", "").isalnum():
        return "❌ the name may only contain letters, digits and underscores"

    existing = ctx.engine.registry.get(name)
    if existing is not None and not existing.description.startswith(_TOOL_MARKER):
        return f"❌ the name '{name}' collides with a built-in Nezuko command — pick another"

    registry_data = _load_registry()
    registry_data[name] = {"command": command_template, "type": tool_type}
    _save_registry(registry_data)
    ctx.engine.registry.register(
        name, _make_handler(command_template, tool_type),
        f"{_TOOL_MARKER}{command_template})",
    )
    return f"✅ registered '{name}' ← {command_template}  (type: {tool_type})\nTry it now: {name} <your arguments here>"


def _cmd_external_remove(ctx) -> str:
    if not ctx.args:
        return "usage: external_remove <name>"
    name = ctx.args[0]
    registry_data = _load_registry()
    if name not in registry_data:
        return f"❌ no external tool registered under that name: {name}"
    del registry_data[name]
    _save_registry(registry_data)
    ctx.engine.registry.unregister(name)
    return f"✅ removed '{name}'"


def _cmd_external_list(ctx) -> str:
    registry_data = _load_registry()
    if not registry_data:
        return "No external tools registered — use external_add <name> <command>"
    lines = [f"🔌 {len(registry_data)} external tools registered:"]
    for name, info in sorted(registry_data.items()):
        lines.append(f"  • {name} ({info.get('type', 'cli')}) ← {info.get('command', '')}")
    return "\n".join(lines)


def _cmd_external_reload(ctx) -> str:
    n = load_external_tools(ctx.engine)
    return f"Loaded {n} external tools"


def load_external_tools(engine) -> int:
    registry_data = _load_registry()
    loaded = 0
    for name, info in registry_data.items():
        existing = engine.registry.get(name)
        if existing is not None and not existing.description.startswith(_TOOL_MARKER):
            engine._log(f"⚠  ignoring external tool '{name}' — it collides with a built-in command of the same name", "warn")
            continue
        command_template = info.get("command", "")
        tool_type = info.get("type", "cli")
        engine.registry.register(
            name, _make_handler(command_template, tool_type), f"{_TOOL_MARKER}{command_template})",
        )
        loaded += 1
    return loaded


def register(engine):
    engine.registry.register("external_add", _cmd_external_add,
                              "external_add <name> <command...> [--type cli|desktop] — register an external program as a permanent command")
    engine.registry.register("external_remove", _cmd_external_remove,
                              "external_remove <name> — unregister an external tool")
    engine.registry.register("external_list", _cmd_external_list,
                              "external_list — list every registered external tool")
    engine.registry.register("external_reload", _cmd_external_reload,
                              "external_reload — reload external tools from the file")
    load_external_tools(engine)
