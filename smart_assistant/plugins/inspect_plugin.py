"""
inspect_plugin.py — تحليل ملفات على مستوى البايتات: تحديد نوع الملف
(magic bytes)، hex dump، استخراج strings، وعرض محتويات أرشيف
(zip/tar) بدون فك ضغط — نفس تقنيات أدوات التحليل الجنائي/الديباج
القياسية (زي file/strings/xxd في يونكس)، مبنية بالكامل بمكتبة بايثون
القياسية بدون أي باكدج خارجي.

ملحوظة مهمة بخصوص النطاق: الأدوات دي لفهم/فحص بايتات ملف إنت مالكه أو
عندك صلاحية تحلله (تصحيح أخطاء، تحليل جنائي، فضول تقني، CTF...). مفيش
هنا ولا هيتضاف أي أداة لفك تشفير/كسر باسورد على ملفات محمية أو تجاوز
حماية برامج مدفوعة — ده خارج نطاق المشروع تماماً.
"""
from __future__ import annotations

import pathlib
import re
import tarfile
import zipfile

# (magic bytes, offset, type name)
_SIGNATURES = [
    (b"\x89PNG\r\n\x1a\n", 0, "PNG image"),
    (b"\xff\xd8\xff", 0, "JPEG image"),
    (b"GIF87a", 0, "GIF image"),
    (b"GIF89a", 0, "GIF image"),
    (b"%PDF-", 0, "PDF document"),
    (b"PK\x03\x04", 0, "ZIP archive (or .docx/.xlsx/.jar/.apk...)"),
    (b"PK\x05\x06", 0, "ZIP archive (empty)"),
    (b"\x7fELF", 0, "ELF executable/library (Linux)"),
    (b"MZ", 0, "PE executable (Windows .exe/.dll)"),
    (b"\x1f\x8b", 0, "GZIP archive"),
    (b"BZh", 0, "BZIP2 archive"),
    (b"7z\xbc\xaf\x27\x1c", 0, "7-Zip archive"),
    (b"Rar!\x1a\x07", 0, "RAR archive"),
    (b"SQLite format 3\x00", 0, "SQLite database"),
    (b"ID3", 0, "MP3 audio (ID3 tag)"),
    (b"OggS", 0, "OGG audio/video"),
    (b"RIFF", 0, "RIFF container (WAV/AVI)"),
    (b"ftyp", 4, "MP4/MOV video (ISO base media)"),
    (b"\x00\x00\x00\x18ftyp", 0, "MP4 video"),
    (b"<?xml", 0, "XML text"),
    (b"{", 0, "possibly JSON text"),
]


def _identify(data: bytes) -> str:
    for magic, offset, name in _SIGNATURES:
        if data[offset:offset + len(magic)] == magic:
            return name
    if all(32 <= b < 127 or b in (9, 10, 13) for b in data[:200]):
        return "plain text (ASCII)"
    return "unknown / raw binary"


def _cmd_identify(ctx) -> str:
    if not ctx.args:
        return "usage: identify <file>"
    path = pathlib.Path(ctx.args[0])
    if not path.is_file():
        return f"❌ الملف مش موجود: {path}"
    try:
        with path.open("rb") as f:
            data = f.read(4096)
        size = path.stat().st_size
    except OSError as e:
        return f"❌ تعذرت قراءة الملف: {e}"
    kind = _identify(data)
    return f"📄 {path.name}\n🔎 النوع المكتشف: {kind}\n📦 الحجم: {size} bytes"


MAX_HEXDUMP_LENGTH = 65536


def _cmd_hexdump(ctx) -> str:
    if not ctx.args:
        return "usage: hexdump <file> [offset] [length]"
    path = pathlib.Path(ctx.args[0])
    if not path.is_file():
        return f"❌ الملف مش موجود: {path}"
    try:
        offset = int(ctx.args[1]) if len(ctx.args) > 1 else 0
        length = int(ctx.args[2]) if len(ctx.args) > 2 else 256
    except ValueError:
        return "❌ offset و length لازم يكونوا أرقام صحيحة"
    if offset < 0:
        return "❌ offset مينفعش يكون سالب"
    if not (0 < length <= MAX_HEXDUMP_LENGTH):
        return f"❌ length لازم يكون بين 1 و{MAX_HEXDUMP_LENGTH}"
    try:
        with path.open("rb") as f:
            f.seek(offset)
            chunk = f.read(length)
    except OSError as e:
        return f"❌ تعذرت قراءة الملف: {e}"
    lines = []
    for i in range(0, len(chunk), 16):
        row = chunk[i:i + 16]
        hex_part = " ".join(f"{b:02x}" for b in row)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in row)
        lines.append(f"{offset + i:08x}  {hex_part:<47}  {ascii_part}")
    return "\n".join(lines) or "(فاضي)"


def _cmd_strings(ctx) -> str:
    if not ctx.args:
        return "usage: strings <file> [min_length=4]"
    path = pathlib.Path(ctx.args[0])
    if not path.is_file():
        return f"❌ الملف مش موجود: {path}"
    try:
        min_len = int(ctx.args[1]) if len(ctx.args) > 1 else 4
    except ValueError:
        return "❌ min_length لازم يكون رقم صحيح"
    if min_len < 1:
        return "❌ min_length لازم يكون 1 على الأقل"
    try:
        data = path.read_bytes()
    except OSError as e:
        return f"❌ تعذرت قراءة الملف: {e}"
    pattern = re.compile(rb"[\x20-\x7e]{%d,}" % min_len)
    found = [m.group().decode("ascii") for m in pattern.finditer(data)]
    if not found:
        return "مفيش نصوص واضحة اتلاقت"
    preview = found[:200]
    suffix = f"\n... ({len(found) - 200} نتيجة إضافية)" if len(found) > 200 else ""
    return "\n".join(preview) + suffix


def _cmd_archive_list(ctx) -> str:
    if not ctx.args:
        return "usage: archive_list <file>"
    path = pathlib.Path(ctx.args[0])
    if not path.is_file():
        return f"❌ الملف مش موجود: {path}"
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as zf:
                names = zf.namelist()
        elif tarfile.is_tarfile(path):
            with tarfile.open(path) as tf:
                names = tf.getnames()
        else:
            return "❌ مش ملف zip/tar معروف"
    except Exception as e:
        return f"❌ تعذرت قراءة الأرشيف: {e}"
    preview = names[:200]
    suffix = f"\n... ({len(names) - 200} ملف إضافي)" if len(names) > 200 else ""
    return f"📦 {len(names)} عنصر:\n" + "\n".join(preview) + suffix


def register(engine):
    engine.registry.register("identify", _cmd_identify, "identify <file> — determine a file's real type from its magic bytes")
    engine.registry.register("hexdump", _cmd_hexdump, "hexdump <file> [offset] [length] — show a file's raw bytes")
    engine.registry.register("strings", _cmd_strings, "strings <file> [min_len] — pull readable text out of a binary")
    engine.registry.register("archive_list", _cmd_archive_list, "archive_list <file> — list a zip/tar's contents without extracting it")
