"""
screenplay_plugin.py — تحليل سيناريو حقيقي بصيغة Fountain (fountain.io،
صيغة مفتوحة ومجانية يستخدمها كتّاب سيناريو حقيقيين وأدوات زي
Highland/Slugline). بدون أي باكدج خارجي.

الأوامر: fountain_stats
"""
from __future__ import annotations

import pathlib
import re

_SCENE_HEADING = re.compile(r"^(INT|EXT|INT\.?/EXT|I/E|EST)[./\s]", re.IGNORECASE)
_TRANSITION = re.compile(r"^[A-Z][A-Z0-9 ]*TO:\s*$")
_LINES_PER_PAGE = 55  # تقدير شائع مستخدم في أدوات Fountain لتحويل أسطر لصفحات


def _parse_fountain(text: str) -> dict:
    lines = text.splitlines()
    scenes: list[str] = []
    characters: set[str] = set()
    dialogue_lines = 0
    action_lines = 0
    i, n = 0, len(lines)
    while i < n:
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if _SCENE_HEADING.match(line):
            scenes.append(line)
            i += 1
            continue
        if _TRANSITION.match(line):
            i += 1
            continue
        letters = [c for c in line if c.isalpha()]
        is_character_cue = bool(letters) and all(c.isupper() for c in letters) and len(line) < 60
        if is_character_cue and i + 1 < n and lines[i + 1].strip():
            name = re.sub(r"\(.*?\)", "", line).strip()
            characters.add(name)
            i += 1
            while i < n and lines[i].strip():
                dialogue_lines += 1
                i += 1
            continue
        action_lines += 1
        i += 1
    return {
        "scenes": scenes,
        "characters": sorted(characters),
        "dialogue_lines": dialogue_lines,
        "action_lines": action_lines,
    }


def _cmd_fountain_stats(ctx) -> str:
    if not ctx.args:
        return "usage: fountain_stats <file.fountain>"
    path = pathlib.Path(ctx.args[0])
    if not path.is_file():
        return f"❌ file not found: {path}"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return f"❌ could not read the file: {e}"
    if not text.strip():
        return "⚠  the file is empty"

    stats = _parse_fountain(text)
    total_lines = len([l for l in text.splitlines() if l.strip()])
    est_pages = max(1, round(total_lines / _LINES_PER_PAGE))

    lines_out = [
        f"🎬 {len(stats['scenes'])} scenes",
        f"🗣  {len(stats['characters'])} characters: {', '.join(stats['characters']) or '(none)'}",
        f"💬 {stats['dialogue_lines']} lines of dialogue",
        f"📝 {stats['action_lines']} lines of action and description",
        f"📄 estimated pages: ~{est_pages} (rough, ~{_LINES_PER_PAGE} lines per page)",
    ]
    if stats["scenes"]:
        lines_out.append("")
        lines_out.append("Scenes:")
        lines_out.extend(f"  {i}. {s}" for i, s in enumerate(stats["scenes"], 1))
    return "\n".join(lines_out)


def register(engine):
    engine.registry.register(
        "fountain_stats", _cmd_fountain_stats,
        "fountain_stats <file.fountain> — screenplay breakdown: scenes, characters, dialogue, page estimate",
    )
