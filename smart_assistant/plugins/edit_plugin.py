"""
edit_plugin.py — قراءة الملفات وتعديلها. الحلقة اللي كانت ناقصة.

**الفجوة اللي بيسدها:** نيزوكو كان عندها 168 أمر ومفيش فيهم ولا واحد
بيقرا ملف كود أو بيعدّله. خريطة المشروع (repomap.py) بتخلي المخ يشوف
بنية المشروع، وسلسلة الخطوات بتخليه يشغّل الاختبارات ويقرا الخطأ — بس
لما ييجي يصلّح، مكانش قدامه غير إنه **يقولك** تعمل إيه. يعني الحلقة
كانت مقطوعة عند آخر خطوة، وهي أهم خطوة.

**صيغة التعديل: SEARCH/REPLACE.** اخترناها مش عشوائي — قياسات aider
المنشورة بتقول إن الصيغة دي وصيغة "الملف كامل" أداءهم متقارب والاتنين
أحسن من unified diff، لكن SEARCH/REPLACE بتستهلك توكنات أقل بكتير
وبتشتغل على ملفات أكبر. الشكل:

    edit_file path/to/file.py
    <<<<<<< SEARCH
    الكود القديم بالظبط
    =======
    الكود الجديد
    >>>>>>> REPLACE

**قواعد صارمة عن قصد:**
  - نص البحث لازم يتلاقى **مرة واحدة بالظبط**. لو اتلاقى أكتر من مرة
    بنرفض بدل ما نخمّن أنهي واحدة — تعديل المكان الغلط أسوأ من عدم
    التعديل، ولأن الغلطة دي بتعدي من غير ما حد ياخد باله.
  - لو ملقيناش النص، بنقول كده بوضوح عشان المخ يقدر يصحح ويجرب تاني.
  - كل تعديل بياخد نسخة احتياطية الأول.
  - `edit_file` في قايمة `_NEVER` — يعني **مستحيل** تتحط في المسموح
    التلقائي. بتكتب محتوى حر على القرص، وده قريب أوي من تنفيذ كود.

الأوامر: read_file, edit_file, create_file
"""
from __future__ import annotations

import pathlib
import re
import shutil

_MAX_READ_BYTES = 400_000
_MAX_READ_LINES = 2_000
_BACKUP_SUFFIX = ".nezuko-bak"

_BLOCK_RE = re.compile(
    r"^<{5,9} SEARCH\s*$\n(.*?)^={5,9}\s*$\n(.*?)^>{5,9} REPLACE\s*$",
    re.MULTILINE | re.DOTALL,
)


# ── قراءة ────────────────────────────────────────────────────────────

def _cmd_read_file(ctx) -> str:
    if not ctx.args:
        return "usage: read_file <path> [start_line] [end_line]"
    path = pathlib.Path(ctx.args[0]).expanduser()
    if not path.is_file():
        return f"❌ file not found: {path}"
    try:
        size = path.stat().st_size
    except OSError as e:
        return f"❌ could not stat the file: {e}"
    if size > _MAX_READ_BYTES:
        return (
            f"❌ {path} is {size / 1024:.0f}KB — over the {_MAX_READ_BYTES // 1024}KB "
            "read limit. Read a line range instead: read_file <path> <start> <end>"
        )
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        return f"❌ could not read the file: {e}"

    start, end = 1, len(lines)
    if len(ctx.args) > 1:
        try:
            start = max(1, int(ctx.args[1]))
        except ValueError:
            return "❌ start_line must be a whole number"
    if len(ctx.args) > 2:
        try:
            end = int(ctx.args[2])
        except ValueError:
            return "❌ end_line must be a whole number"
    if end < start:
        return "❌ end_line must not be before start_line"

    chunk = lines[start - 1:end][:_MAX_READ_LINES]
    if not chunk:
        return f"(nothing at lines {start}-{end}; the file has {len(lines)} lines)"
    width = len(str(start + len(chunk) - 1))
    body = "\n".join(
        f"{start + i:>{width}}  {line}" for i, line in enumerate(chunk)
    )
    header = f"📄 {path}  ({len(lines)} lines)"
    if start > 1 or end < len(lines):
        header += f"  — showing {start}-{start + len(chunk) - 1}"
    truncated = ""
    if len(lines[start - 1:end]) > _MAX_READ_LINES:
        truncated = f"\n… truncated at {_MAX_READ_LINES} lines"
    return f"{header}\n{body}{truncated}"


# ── تعديل ────────────────────────────────────────────────────────────

def parse_blocks(text: str) -> list[tuple[str, str]]:
    """بيطلّع كل كتل SEARCH/REPLACE من نص الأمر."""
    return [(m.group(1), m.group(2)) for m in _BLOCK_RE.finditer(text)]


def _apply_block(content: str, search: str, replace: str) -> tuple[str | None, str]:
    """بيطبّق كتلة واحدة. بيرجع (المحتوى الجديد أو None، رسالة)."""
    if not search:
        return content + replace, "appended"
    count = content.count(search)
    if count == 0:
        head = search.strip().splitlines()[0][:60] if search.strip() else ""
        return None, f"search text not found (starts: {head!r})"
    if count > 1:
        return None, (
            f"search text appears {count} times — include more surrounding "
            "lines so it matches exactly once"
        )
    return content.replace(search, replace, 1), "replaced"


def _cmd_edit_file(ctx) -> str:
    parts = ctx.raw.split(maxsplit=2)
    if len(parts) < 2:
        return (
            "usage: edit_file <path>\n"
            "<<<<<<< SEARCH\n"
            "the exact existing text\n"
            "=======\n"
            "the replacement\n"
            ">>>>>>> REPLACE\n\n"
            "The search text must match exactly once. Several blocks are fine."
        )
    path = pathlib.Path(parts[1]).expanduser()
    blocks = parse_blocks(ctx.raw)
    if not blocks:
        return (
            "❌ no SEARCH/REPLACE block found. The format is:\n"
            "<<<<<<< SEARCH\n...\n=======\n...\n>>>>>>> REPLACE"
        )
    if not path.is_file():
        return f"❌ file not found: {path}   (use create_file to make a new one)"

    try:
        original = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return f"❌ could not read the file: {e}"

    content = original
    applied, notes = 0, []
    for i, (search, replace) in enumerate(blocks, 1):
        updated, message = _apply_block(content, search, replace)
        if updated is None:
            # كله أو ولا حاجة — تعديل نص الطريق بيسيب الملف في حالة
            # مش هي القديمة ولا الجديدة، وده أسوأ حاجة ممكنة
            return (
                f"❌ block {i} of {len(blocks)}: {message}\n"
                f"Nothing was written — {path} is unchanged.\n"
                "Read the file again and match the existing text exactly."
            )
        content = updated
        applied += 1
        notes.append(f"  block {i}: {message}")

    if content == original:
        return f"ℹ️ every block matched but nothing changed — {path} is already like that"

    backup = path.with_suffix(path.suffix + _BACKUP_SUFFIX)
    try:
        shutil.copy2(path, backup)
    except OSError as e:
        return f"❌ could not write a backup, so nothing was changed: {e}"
    try:
        path.write_text(content, encoding="utf-8")
    except OSError as e:
        return f"❌ could not write the file: {e}   (backup kept at {backup})"

    delta = len(content.splitlines()) - len(original.splitlines())
    sign = f"+{delta}" if delta > 0 else str(delta)
    return (
        f"✅ {path} — {applied} block(s) applied ({sign} lines)\n"
        + "\n".join(notes)
        + f"\n  backup: {backup.name}"
    )


def _cmd_create_file(ctx) -> str:
    parts = ctx.raw.split(maxsplit=2)
    if len(parts) < 2:
        return "usage: create_file <path>\n<the file contents>"
    path = pathlib.Path(parts[1]).expanduser()
    body = parts[2] if len(parts) > 2 else ""
    if path.exists():
        return f"❌ {path} already exists — use edit_file to change it"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    except OSError as e:
        return f"❌ could not create the file: {e}"
    return f"✅ created {path} ({len(body.splitlines())} lines)"


def register(engine):
    r = engine.registry.register
    r("read_file", _cmd_read_file,
      "read_file <path> [start] [end] — read a file, with line numbers")
    r("edit_file", _cmd_edit_file,
      "edit_file <path> + SEARCH/REPLACE block — change existing text in a file")
    r("create_file", _cmd_create_file,
      "create_file <path> <contents> — write a new file (refuses to overwrite)")
