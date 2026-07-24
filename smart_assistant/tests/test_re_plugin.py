import pathlib
import struct

import pytest

import re_plugin as rp

LS = pathlib.Path("/bin/ls")
requires_ls = pytest.mark.skipif(not LS.is_file(), reason="/bin/ls not present (non-Linux?)")
requires_capstone = pytest.mark.skipif(not rp.CAPSTONE_AVAILABLE, reason="capstone not installed")


def _make_minimal_elf(bits=64, little_endian=True) -> bytes:
    ei_class = 2 if bits == 64 else 1
    ei_data = 1 if little_endian else 2
    e_ident = b"\x7fELF" + bytes([ei_class, ei_data, 1, 0]) + b"\x00" * 8
    endian = "<" if little_endian else ">"
    if bits == 64:
        header = struct.pack(
            endian + "HHIQQQIHHHHHH",
            2, 62, 1, 0x1000, 0, 0, 0, 64, 0, 0, 0, 0, 0,
        )
    else:
        header = struct.pack(
            endian + "HHIIIIIHHHHHH",
            2, 3, 1, 0x1000, 0, 0, 0, 52, 0, 0, 0, 0, 0,
        )
    return e_ident + header


def test_shannon_entropy_of_uniform_random_is_near_max():
    import os
    data = os.urandom(50_000)
    assert rp._shannon_entropy(data) > 7.9


def test_shannon_entropy_of_zeros_is_zero():
    assert rp._shannon_entropy(b"\x00" * 1000) == 0.0


def test_shannon_entropy_empty_is_zero():
    assert rp._shannon_entropy(b"") == 0.0


def test_entropy_command_flags_high_entropy(make_ctx, tmp_path):
    import os
    f = tmp_path / "random.bin"
    f.write_bytes(os.urandom(20_000))
    result = rp._cmd_entropy(make_ctx("entropy", [str(f)]))
    assert "عالية" in result or "🔥" in result


def test_entropy_rejects_bad_chunk_size(make_ctx, tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"abc")
    result = rp._cmd_entropy(make_ctx("entropy", [str(f), "notanumber"]))
    assert result.startswith("❌")
    result = rp._cmd_entropy(make_ctx("entropy", [str(f), "0"]))
    assert result.startswith("❌")


def test_parse_elf_minimal_64bit():
    data = _make_minimal_elf(64)
    info = rp._parse_elf(data)
    assert info["bits"] == 64
    assert info["machine"] == "x86-64"
    assert info["entry"] == 0x1000


def test_parse_elf_rejects_non_elf():
    with pytest.raises(ValueError):
        rp._parse_elf(b"not an elf file")


def test_parse_elf_rejects_truncated_header():
    with pytest.raises(ValueError):
        rp._parse_elf(b"\x7fELF\x02")


def test_elf_info_command_on_truncated_file_is_friendly(make_ctx, tmp_path):
    f = tmp_path / "trunc.bin"
    f.write_bytes(b"\x7fELF\x02")
    result = rp._cmd_elf_info(make_ctx("elf_info", [str(f)]))
    assert result.startswith("❌")


@requires_ls
def test_elf_info_on_real_binary_matches_readelf(make_ctx):
    import subprocess
    result = rp._cmd_elf_info(make_ctx("elf_info", [str(LS)]))
    assert "x86-64" in result

    readelf = subprocess.run(["readelf", "-h", str(LS)], capture_output=True, text=True)
    if readelf.returncode == 0:
        for line in readelf.stdout.splitlines():
            if "Entry point address" in line:
                entry_hex = line.split(":")[1].strip()
                assert entry_hex.replace("0x", "") in result


@requires_capstone
def test_disasm_on_truncated_elf_falls_back_gracefully(make_ctx, tmp_path):
    f = tmp_path / "trunc.bin"
    f.write_bytes(b"\x7fELF\x02")
    result = rp._cmd_disasm(make_ctx("disasm", [str(f)]))
    # should not crash — either disassembles from offset 0 or reports no instructions
    assert "❌" not in result or "arch" in result


@requires_capstone
@requires_ls
def test_disasm_real_binary_produces_instructions(make_ctx):
    result = rp._cmd_disasm(make_ctx("disasm", [str(LS)]))
    assert "0x" in result


@requires_capstone
def test_disasm_rejects_bad_offset(make_ctx, tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"\x90" * 32)
    result = rp._cmd_disasm(make_ctx("disasm", [str(f), "notanumber"]))
    assert result.startswith("❌")


@requires_capstone
def test_disasm_rejects_negative_offset(make_ctx, tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"\x90" * 32)
    result = rp._cmd_disasm(make_ctx("disasm", [str(f), "-1"]))
    assert result.startswith("❌")


@requires_capstone
def test_disasm_rejects_oversized_length(make_ctx, tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"\x90" * 32)
    result = rp._cmd_disasm(make_ctx("disasm", [str(f), "0", "999999999"]))
    assert result.startswith("❌")
