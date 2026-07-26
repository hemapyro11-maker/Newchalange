"""
agents.py — subagents: نيزوكو بتقدر تشغّل "مساعِدين" متخصصين، كل واحد
بشخصية وأدوات محدودة، جوه محادثة منفصلة عن محادثتك.

**ليه ده مفيد فعلاً:** المحادثة الرئيسية بيتراكم فيها سياق كتير. لو
عايز مهمة متخصصة (مراجعة كود، بحث، تحليل قناة) من غير ما تلوّث السياق
الأساسي — بتشغّل subagent، هو بيشتغل لوحده ويرجّعلك الخلاصة بس.

**التوفير في الحصة:** لأن الـ subagent شايف تعليماته وأدواته المحدودة
بس (مش كل الـ 150 أمر ولا تاريخ محادثتك)، طلبه أصغر بكتير — يعني
توكنز أقل لكل نداء.

كل agent ملف markdown في `agents/` بنفس فكرة الـ SKILL.md: ترويسة
بسيطة في الأول (name/description/tools) وبعدين التعليمات:

    ---
    name: code-reviewer
    description: يراجع كود بايثون ويطلّع ملاحظات عملية
    tools: code_scan, vuln_scan, strings
    ---

    أنت مراجع كود خبير. ركّز على الأخطاء الحقيقية مش الشكليات...

**الأمان:** الـ subagent **مبينفذش أدوات لوحده**. بيقترح، والاقتراح
بيعدي على نفس بوابة التأكيد بتاعة المحرك بالظبط. `tools:` بتضيّق
اللي مسموح له يقترحه، مبتوسّعش أي صلاحية.
"""
from __future__ import annotations

import pathlib
import re
import sys

import brain

_HEADER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _base_dir() -> pathlib.Path:
    if getattr(sys, "frozen", False):
        return pathlib.Path(sys.executable).resolve().parent
    return pathlib.Path(__file__).resolve().parent


def agents_dir() -> pathlib.Path:
    d = _base_dir() / "agents"
    d.mkdir(parents=True, exist_ok=True)
    return d


def parse(text: str, fallback_name: str = "") -> dict | None:
    """بيفصل الترويسة عن التعليمات.

    الملف من غير ترويسة لسه صالح — بياخد اسمه من اسم الملف وكل محتواه
    تعليمات. أسهل على المستخدم من إجباره على صيغة كاملة.
    """
    match = _HEADER_RE.match(text)
    meta: dict[str, str] = {}
    body = text
    if match:
        for line in match.group(1).splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                meta[key.strip().lower()] = value.strip()
        body = text[match.end():]
    body = body.strip()
    if not body:
        return None
    tools = [t.strip() for t in meta.get("tools", "").split(",") if t.strip()]
    return {
        "name": meta.get("name") or fallback_name,
        "description": meta.get("description", ""),
        "tools": tools,
        "instructions": body,
    }


def load_all() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for path in sorted(agents_dir().glob("*.md")):
        try:
            parsed = parse(path.read_text(encoding="utf-8"), path.stem)
        except OSError:
            continue
        if parsed and parsed["name"]:
            out[parsed["name"]] = parsed
    return out


def get(name: str) -> dict | None:
    return load_all().get(name)


def save(name: str, description: str, instructions: str,
         tools: list[str] | None = None) -> pathlib.Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "-", name)[:60] or "agent"
    path = agents_dir() / f"{safe}.md"
    header = [f"name: {name}"]
    if description:
        header.append(f"description: {description}")
    if tools:
        header.append(f"tools: {', '.join(tools)}")
    path.write_text(
        "---\n" + "\n".join(header) + "\n---\n\n" + instructions.strip() + "\n",
        encoding="utf-8",
    )
    return path


def delete(name: str) -> bool:
    for path in agents_dir().glob("*.md"):
        parsed = None
        try:
            parsed = parse(path.read_text(encoding="utf-8"), path.stem)
        except OSError:
            continue
        if parsed and parsed["name"] == name:
            try:
                path.unlink()
                return True
            except OSError:
                return False
    return False


def allowed_tools(agent: dict, registry_names: set[str]) -> list[str]:
    """أدوات الـ agent، مفلترة على اللي مسجّل فعلاً.

    `tools:` فاضية معناها كل الأوامر — نفس صلاحية المحادثة العادية.
    لو محددة، بترجّع المتاح منها بس؛ الأسماء الوهمية بتتشال بدل ما
    تتعرض على النموذج فيهلوس بيها.
    """
    if not agent.get("tools"):
        return sorted(registry_names)
    return sorted(set(agent["tools"]) & registry_names)


def run(engine, name: str, task: str) -> tuple[str, str]:
    """بيشغّل subagent على مهمة. بيرجع (الرد، اسم المزوّد).

    السياق منفصل تمامًا: الـ agent مبيشوفش `engine.chat_history` ولا
    بيكتب فيها — عشان كده بيوفّر توكنز وبيسيب محادثتك نضيفة.
    """
    agent = get(name)
    if agent is None:
        return f"❌ no agent named {name}", ""

    b = brain.get_brain()
    if not b.ready():
        return "❌ no brain configured — run brain_setup", ""

    registry_names = {c.name for c in engine.registry.list_commands()}
    tools = allowed_tools(agent, registry_names)
    catalog = "\n".join(
        f"{c.name} — {c.description}"
        for c in engine.registry.list_commands() if c.name in tools
    )

    system = (
        f"{agent['instructions']}\n\n"
        "If you need to run a tool, write a line exactly like:\n"
        "TOOL: <command_name> <arguments>\n"
        "Use only the commands listed below; do not invent names. "
        "Do not claim you ran anything — the user confirms first.\n\n"
        f"Available commands:\n{catalog}"
    )
    reply = b.chat([
        {"role": "system", "content": system},
        {"role": "user", "content": task},
    ])
    if not reply:
        return f"❌ {reply.error}", ""
    return reply.text, reply.label


# ── أمثلة جاهزة بتتكتب أول مرة ───────────────────────────────────────

_STARTERS = {
    "code-reviewer": (
        "Reviews Python code and reports real defects",
        "code_scan, vuln_scan, strings, hexdump",
        "You are a careful code reviewer. Report only defects that would "
        "actually bite someone: wrong behaviour, security holes, resource "
        "leaks, race conditions. Skip style opinions. For each finding give "
        "the file, the line, and a concrete failure scenario. If the code is "
        "fine, say so plainly instead of inventing problems.",
    ),
    "youtube-analyst": (
        "Analyses a YouTube channel and explains what is holding it back",
        "channel_stats, channel_growth_report, video_stats, seo_title_score, "
        "thumbnail_analyze, comment_sentiment",
        "You analyse YouTube channels. Always look at the real numbers before "
        "offering an opinion — pull the channel stats first. Separate what the "
        "data shows from what you are inferring. Give at most three concrete "
        "actions, ordered by expected impact.",
    ),
    "file-detective": (
        "Works out what an unknown file is and whether it is safe",
        "identify, hexdump, strings, entropy, elf_info, pe_info, virus_scan, "
        "security_report",
        "You identify unknown files. Start from the bytes: file type, then "
        "structure, then contents. State clearly what you know versus what you "
        "suspect. Never declare a file safe on a single check alone.",
    ),
}


def write_starters() -> list[str]:
    """بيكتب الأمثلة الجاهزة لو المجلد فاضي. بيرجع اللي اتكتب."""
    if any(agents_dir().glob("*.md")):
        return []
    written = []
    for name, (desc, tools, body) in _STARTERS.items():
        save(name, desc, body, [t.strip() for t in tools.split(",")])
        written.append(name)
    return written
