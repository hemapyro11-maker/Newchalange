"""
re_plugin.py — هندسة عكسية متقدمة (static analysis): تحليل بنية ملفات
ELF (لينكس) وPE (ويندوز .exe/.dll) على مستوى الـ headers/sections/
imports، حساب الـ entropy (لاكتشاف مناطق مضغوطة/مشفرة/محتمل packed)،
وفك تجميع (disassembly) بايتات لتعليمات معالج حقيقية عبر Capstone
(مكتبة disassembly مفتوحة المصدر ومجانية بالكامل، نفس المحرك المستخدم
في أدوات RE قياسية زي Ghidra/radare2/IDA plugins).

النطاق: تحليل *ساكن* (static) لبنية ملف عندك حق تحلله — فهم شكل الكود،
الاعتماديات (imports)، ودلائل التغليف/التشفير. **مفيش هنا أي كسر
باسورد أو تجاوز حماية أو فك تشفير محتوى محمي** — ده خارج نطاق المشروع
بالكامل ومش هيتضاف تحت أي مسمى.
"""
from __future__ import annotations

import math
import pathlib
import struct
from collections import Counter

try:
    import capstone
    CAPSTONE_AVAILABLE = True
except ImportError:
    CAPSTONE_AVAILABLE = False


# ═══════════════════════════════════════════════════════════════════
# Entropy
# ═══════════════════════════════════════════════════════════════════

def _shannon_entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = Counter(data)
    length = len(data)
    return max(0.0, -sum((n / length) * math.log2(n / length) for n in counts.values()))


def _cmd_entropy(ctx) -> str:
    if not ctx.args:
        return "usage: entropy <file> [chunk_size=4096]"
    path = pathlib.Path(ctx.args[0])
    if not path.is_file():
        return f"❌ الملف مش موجود: {path}"
    chunk_size = int(ctx.args[1]) if len(ctx.args) > 1 else 4096
    data = path.read_bytes()
    overall = _shannon_entropy(data)
    lines = [f"📊 entropy إجمالي: {overall:.2f} / 8.0 bits/byte  (حجم: {len(data)} bytes)"]
    if overall > 7.5:
        lines.append("⚠  إنتروبيا عالية جداً — الملف كله ممكن يكون مضغوط أو مشفّر أو packed")

    hot_chunks = []
    for i in range(0, len(data), chunk_size):
        chunk = data[i:i + chunk_size]
        e = _shannon_entropy(chunk)
        if e > 7.5:
            hot_chunks.append((i, e))
    if hot_chunks:
        lines.append(f"🔥 {len(hot_chunks)} جزء بإنتروبيا عالية (>7.5) من أصل {math.ceil(len(data) / chunk_size)}:")
        for offset, e in hot_chunks[:15]:
            lines.append(f"   0x{offset:08x}: {e:.2f}")
        if len(hot_chunks) > 15:
            lines.append(f"   ... و{len(hot_chunks) - 15} جزء إضافي")
    else:
        lines.append("✅ مفيش مناطق بإنتروبيا عالية غير طبيعية")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# ELF parsing (readelf-equivalent, stdlib only)
# ═══════════════════════════════════════════════════════════════════

_ELF_MACHINES = {3: "x86 (i386)", 40: "ARM", 62: "x86-64", 183: "AArch64", 8: "MIPS", 20: "PowerPC"}


def _parse_elf(data: bytes) -> dict:
    if data[:4] != b"\x7fELF":
        raise ValueError("مش ملف ELF")
    ei_class = data[4]          # 1=32-bit, 2=64-bit
    ei_data = data[5]           # 1=LE, 2=BE
    is64 = ei_class == 2
    endian = "<" if ei_data == 1 else ">"

    if is64:
        (e_type, e_machine, e_version, e_entry, e_phoff, e_shoff, e_flags,
         e_ehsize, e_phentsize, e_phnum, e_shentsize, e_shnum, e_shstrndx) = struct.unpack_from(
            endian + "HHIQQQIHHHHHH", data, 16)
    else:
        (e_type, e_machine, e_version, e_entry, e_phoff, e_shoff, e_flags,
         e_ehsize, e_phentsize, e_phnum, e_shentsize, e_shnum, e_shstrndx) = struct.unpack_from(
            endian + "HHIIIIIHHHHHH", data, 16)

    sections = []
    if e_shoff and e_shnum:
        raw_sections = []
        for i in range(e_shnum):
            off = e_shoff + i * e_shentsize
            if is64:
                sh_name, sh_type, sh_flags, sh_addr, sh_offset, sh_size, sh_link, sh_info, _, _ = \
                    struct.unpack_from(endian + "IIQQQQIIQQ", data, off)
            else:
                sh_name, sh_type, sh_flags, sh_addr, sh_offset, sh_size, sh_link, sh_info, _, _ = \
                    struct.unpack_from(endian + "IIIIIIIIII", data, off)
            raw_sections.append({
                "name_off": sh_name, "type": sh_type, "addr": sh_addr,
                "offset": sh_offset, "size": sh_size, "link": sh_link,
            })
        if 0 <= e_shstrndx < len(raw_sections):
            strtab = raw_sections[e_shstrndx]
            strtab_data = data[strtab["offset"]:strtab["offset"] + strtab["size"]]
            for s in raw_sections:
                end = strtab_data.find(b"\x00", s["name_off"])
                s["name"] = strtab_data[s["name_off"]:end].decode("ascii", "replace")
                sections.append(s)

    needed = []
    dynamic_section = next((s for s in sections if s["name"] == ".dynamic"), None)
    dynstr_section = next((s for s in sections if s["name"] == ".dynstr"), None)
    if dynamic_section and dynstr_section:
        dynstr_data = data[dynstr_section["offset"]:dynstr_section["offset"] + dynstr_section["size"]]
        entry_size = 16 if is64 else 8
        tag_fmt = endian + ("qQ" if is64 else "iI")
        count = dynamic_section["size"] // entry_size
        for i in range(count):
            off = dynamic_section["offset"] + i * entry_size
            d_tag, d_val = struct.unpack_from(tag_fmt, data, off)
            if d_tag == 0:  # DT_NULL
                break
            if d_tag == 1:  # DT_NEEDED
                end = dynstr_data.find(b"\x00", d_val)
                needed.append(dynstr_data[d_val:end].decode("ascii", "replace"))

    return {
        "bits": 64 if is64 else 32,
        "endian": "little" if ei_data == 1 else "big",
        "machine": _ELF_MACHINES.get(e_machine, f"unknown(0x{e_machine:x})"),
        "entry": e_entry,
        "sections": sections,
        "needed": needed,
    }


def _cmd_elf_info(ctx) -> str:
    if not ctx.args:
        return "usage: elf_info <file>"
    path = pathlib.Path(ctx.args[0])
    if not path.is_file():
        return f"❌ الملف مش موجود: {path}"
    data = path.read_bytes()
    try:
        info = _parse_elf(data)
    except (ValueError, struct.error) as e:
        return f"❌ مش ملف ELF صالح: {e}"

    lines = [
        f"🐧 ELF {info['bits']}-bit, {info['endian']}-endian, {info['machine']}",
        f"🎯 entry point: 0x{info['entry']:x}",
        f"📚 مكتبات مطلوبة (DT_NEEDED): {', '.join(info['needed']) or '(مفيش/static)'}",
        f"🧩 {len(info['sections'])} section:",
    ]
    for s in info["sections"][:30]:
        if s["name"]:
            lines.append(f"   {s['name']:<20} addr=0x{s['addr']:<10x} size={s['size']}")
    if len(info["sections"]) > 30:
        lines.append(f"   ... و{len(info['sections']) - 30} section إضافي")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# PE parsing (objdump/pefile-equivalent, stdlib only)
# ═══════════════════════════════════════════════════════════════════

_PE_MACHINES = {0x14c: "x86", 0x8664: "x86-64", 0x1c0: "ARM", 0xaa64: "ARM64"}


def _rva_to_offset(sections: list[dict], rva: int) -> int | None:
    for s in sections:
        if s["virt_addr"] <= rva < s["virt_addr"] + max(s["virt_size"], s["raw_size"]):
            return s["raw_ptr"] + (rva - s["virt_addr"])
    return None


def _read_cstr(data: bytes, offset: int, limit: int = 256) -> str:
    end = data.find(b"\x00", offset, offset + limit)
    if end == -1:
        end = offset + limit
    return data[offset:end].decode("ascii", "replace")


def _parse_pe(data: bytes) -> dict:
    if data[:2] != b"MZ":
        raise ValueError("مش ملف PE (مفيش MZ magic)")
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    if data[e_lfanew:e_lfanew + 4] != b"PE\x00\x00":
        raise ValueError("مفيش PE signature في المكان المتوقع")

    coff_off = e_lfanew + 4
    machine, num_sections, timestamp, _, _, opt_size, _ = struct.unpack_from(
        "<HHIIIHH", data, coff_off)

    opt_off = coff_off + 20
    magic = struct.unpack_from("<H", data, opt_off)[0]
    is_pe32_plus = magic == 0x20b

    entry_rva = struct.unpack_from("<I", data, opt_off + 16)[0]
    if is_pe32_plus:
        image_base = struct.unpack_from("<Q", data, opt_off + 24)[0]
        data_dir_off = opt_off + 112
    else:
        image_base = struct.unpack_from("<I", data, opt_off + 28)[0]
        data_dir_off = opt_off + 96
    num_rva_sizes = struct.unpack_from("<I", data, data_dir_off - 4)[0]
    import_dir_rva, import_dir_size = struct.unpack_from("<II", data, data_dir_off + 8) if num_rva_sizes > 1 else (0, 0)

    sections = []
    sec_off = opt_off + opt_size
    for i in range(num_sections):
        off = sec_off + i * 40
        raw = data[off:off + 40]
        name = raw[:8].rstrip(b"\x00").decode("ascii", "replace")
        virt_size, virt_addr, raw_size, raw_ptr = struct.unpack_from("<IIII", raw, 8)
        sections.append({"name": name, "virt_size": virt_size, "virt_addr": virt_addr,
                          "raw_size": raw_size, "raw_ptr": raw_ptr})

    imports: dict[str, list[str]] = {}
    if import_dir_rva:
        desc_off = _rva_to_offset(sections, import_dir_rva)
        if desc_off is not None:
            i = 0
            while True:
                base = desc_off + i * 20
                if base + 20 > len(data):
                    break
                orig_thunk, _, _, name_rva, first_thunk = struct.unpack_from("<IIIII", data, base)
                if orig_thunk == 0 and name_rva == 0 and first_thunk == 0:
                    break
                name_off = _rva_to_offset(sections, name_rva)
                dll_name = _read_cstr(data, name_off) if name_off is not None else f"<rva 0x{name_rva:x}>"
                funcs = []
                thunk_rva = orig_thunk or first_thunk
                thunk_off = _rva_to_offset(sections, thunk_rva) if thunk_rva else None
                if thunk_off is not None:
                    is64 = is_pe32_plus
                    entry_size = 8 if is64 else 4
                    ordinal_bit = 1 << 63 if is64 else 1 << 31
                    j = 0
                    while True:
                        toff = thunk_off + j * entry_size
                        if toff + entry_size > len(data):
                            break
                        value = struct.unpack_from("<Q" if is64 else "<I", data, toff)[0]
                        if value == 0:
                            break
                        if value & ordinal_bit:
                            funcs.append(f"ordinal#{value & 0xFFFF}")
                        else:
                            name_addr = _rva_to_offset(sections, value & 0x7FFFFFFF)
                            if name_addr is not None:
                                funcs.append(_read_cstr(data, name_addr + 2))
                        j += 1
                        if j > 2000:
                            break
                imports[dll_name] = funcs
                i += 1
                if i > 500:
                    break

    return {
        "machine": _PE_MACHINES.get(machine, f"unknown(0x{machine:x})"),
        "is64": is_pe32_plus,
        "timestamp": timestamp,
        "entry_rva": entry_rva,
        "image_base": image_base,
        "sections": sections,
        "imports": imports,
    }


def _cmd_pe_info(ctx) -> str:
    if not ctx.args:
        return "usage: pe_info <file>"
    path = pathlib.Path(ctx.args[0])
    if not path.is_file():
        return f"❌ الملف مش موجود: {path}"
    data = path.read_bytes()
    try:
        info = _parse_pe(data)
    except (ValueError, struct.error) as e:
        return f"❌ مش ملف PE صالح: {e}"

    import datetime
    ts = datetime.datetime.utcfromtimestamp(info["timestamp"]).isoformat() if info["timestamp"] else "?"
    lines = [
        f"🪟 PE {'32+' if info['is64'] else '32'}, {info['machine']}",
        f"🕒 وقت البناء (COFF timestamp): {ts} UTC",
        f"🎯 entry point RVA: 0x{info['entry_rva']:x}  (image base: 0x{info['image_base']:x})",
        f"🧩 {len(info['sections'])} section:",
    ]
    for s in info["sections"][:30]:
        lines.append(f"   {s['name']:<10} virt=0x{s['virt_addr']:<10x} raw_size={s['raw_size']}")

    if info["imports"]:
        total_funcs = sum(len(v) for v in info["imports"].values())
        lines.append(f"📚 {len(info['imports'])} DLL مستوردة ({total_funcs} دالة):")
        for dll, funcs in list(info["imports"].items())[:20]:
            preview = ", ".join(funcs[:6]) + (f" ... (+{len(funcs) - 6})" if len(funcs) > 6 else "")
            lines.append(f"   {dll}: {preview or '(مفيش دوال متلاقية)'}")
    else:
        lines.append("📚 مفيش imports متلاقية")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# Disassembly (Capstone)
# ═══════════════════════════════════════════════════════════════════

_ARCH_MAP = {}
if CAPSTONE_AVAILABLE:
    _ARCH_MAP = {
        "x86": (capstone.CS_ARCH_X86, capstone.CS_MODE_32),
        "x64": (capstone.CS_ARCH_X86, capstone.CS_MODE_64),
        "arm": (capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM),
        "arm64": (capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM),
    }


def _auto_entry_offset(data: bytes) -> tuple[int, str] | None:
    """يحاول يلاقي offset نقطة الدخول (entry point) جوه الملف نفسه، ويرجع
    (offset, arch_hint) لو الملف ELF أو PE معروف، وإلا None."""
    if data[:4] == b"\x7fELF":
        info = _parse_elf(data)
        for s in info["sections"]:
            if s["addr"] <= info["entry"] < s["addr"] + s["size"] and s["addr"]:
                arch = "x64" if info["bits"] == 64 and "x86" in info["machine"] else \
                    ("x86" if "x86" in info["machine"] else "arm64" if "AArch64" in info["machine"] else "arm")
                return s["offset"] + (info["entry"] - s["addr"]), arch
    elif data[:2] == b"MZ":
        info = _parse_pe(data)
        off = _rva_to_offset(info["sections"], info["entry_rva"])
        if off is not None:
            arch = "x64" if info["is64"] else "x86"
            return off, arch
    return None


def _cmd_disasm(ctx) -> str:
    if not CAPSTONE_AVAILABLE:
        return "❌ باكدج capstone مش متثبت — ثبّته بـ: pip install capstone"
    if not ctx.args:
        return "usage: disasm <file> [offset] [length=128] [arch=x86|x64|arm|arm64]"
    path = pathlib.Path(ctx.args[0])
    if not path.is_file():
        return f"❌ الملف مش موجود: {path}"
    data = path.read_bytes()

    offset = None
    arch = "x64"
    if len(ctx.args) > 1:
        offset = int(ctx.args[1], 0)
    if len(ctx.args) > 3:
        arch = ctx.args[3]

    note = ""
    if offset is None:
        auto = _auto_entry_offset(data)
        if auto:
            offset, arch = auto
            note = f"(تلقائي: entry point عند 0x{offset:x}, arch={arch})\n"
        else:
            offset = 0

    length = int(ctx.args[2]) if len(ctx.args) > 2 else 128
    if arch not in _ARCH_MAP:
        return f"❌ arch غير مدعوم: {arch} (المتاح: {', '.join(_ARCH_MAP)})"

    chunk = data[offset:offset + length]
    cs_arch, cs_mode = _ARCH_MAP[arch]
    md = capstone.Cs(cs_arch, cs_mode)
    lines = [f"{note}🧮 disassembly من offset 0x{offset:x}, arch={arch}:"]
    count = 0
    for insn in md.disasm(chunk, offset):
        lines.append(f"   0x{insn.address:08x}:  {insn.mnemonic}\t{insn.op_str}")
        count += 1
    if count == 0:
        lines.append("   (مفيش تعليمات قابلة للفك — جرب offset/arch مختلف)")
    return "\n".join(lines)


def register(engine):
    engine.registry.register("entropy", _cmd_entropy, "entropy <file> [chunk] — كشف مناطق مضغوطة/مشفّرة/packed")
    engine.registry.register("elf_info", _cmd_elf_info, "elf_info <file> — تحليل بنية ملف ELF (لينكس)")
    engine.registry.register("pe_info", _cmd_pe_info, "pe_info <file> — تحليل بنية ملف PE (ويندوز exe/dll) + imports")
    if CAPSTONE_AVAILABLE:
        engine.registry.register(
            "disasm", _cmd_disasm,
            "disasm <file> [offset] [length] [arch] — فك تجميع بايتات لتعليمات معالج (Capstone)",
        )
    else:
        engine.registry.register(
            "disasm", _cmd_disasm, "disasm — يحتاج: pip install capstone"
        )
