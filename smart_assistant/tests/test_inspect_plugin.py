import inspect_plugin as ip


def _ctx(make_ctx, raw, args):
    return make_ctx(raw, args)


def test_identify_png(make_ctx, tmp_path):
    f = tmp_path / "x.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
    result = ip._cmd_identify(_ctx(make_ctx, "identify", [str(f)]))
    assert "PNG" in result


def test_identify_missing_file(make_ctx):
    result = ip._cmd_identify(_ctx(make_ctx, "identify", ["/no/such/file"]))
    assert result.startswith("❌")


def test_identify_plain_text(make_ctx, tmp_path):
    f = tmp_path / "t.txt"
    f.write_text("hello world")
    result = ip._cmd_identify(_ctx(make_ctx, "identify", [str(f)]))
    assert "text" in result.lower()


def test_hexdump_basic(make_ctx, tmp_path):
    f = tmp_path / "b.bin"
    f.write_bytes(bytes(range(16)))
    result = ip._cmd_hexdump(_ctx(make_ctx, "hexdump", [str(f), "0", "16"]))
    assert "00 01 02 03" in result


def test_hexdump_rejects_non_numeric(make_ctx, tmp_path):
    f = tmp_path / "b.bin"
    f.write_bytes(b"x")
    result = ip._cmd_hexdump(_ctx(make_ctx, "hexdump", [str(f), "abc"]))
    assert result.startswith("❌")


def test_hexdump_rejects_negative_offset(make_ctx, tmp_path):
    f = tmp_path / "b.bin"
    f.write_bytes(b"x")
    result = ip._cmd_hexdump(_ctx(make_ctx, "hexdump", [str(f), "-1"]))
    assert result.startswith("❌")


def test_hexdump_rejects_oversized_length(make_ctx, tmp_path):
    f = tmp_path / "b.bin"
    f.write_bytes(b"x")
    result = ip._cmd_hexdump(_ctx(make_ctx, "hexdump", [str(f), "0", "999999999"]))
    assert result.startswith("❌")


def test_strings_finds_embedded_text(make_ctx, tmp_path):
    f = tmp_path / "b.bin"
    f.write_bytes(b"\x00\x01\x02hello world\x00\x01" + b"tiny\x00")
    result = ip._cmd_strings(_ctx(make_ctx, "strings", [str(f), "5"]))
    assert "hello world" in result
    assert "tiny" not in result  # 4 chars, shorter than min_len=5


def test_strings_rejects_non_numeric_min_len(make_ctx, tmp_path):
    f = tmp_path / "b.bin"
    f.write_bytes(b"x")
    result = ip._cmd_strings(_ctx(make_ctx, "strings", [str(f), "abc"]))
    assert result.startswith("❌")


def test_strings_rejects_zero_min_len(make_ctx, tmp_path):
    f = tmp_path / "b.bin"
    f.write_bytes(b"x")
    result = ip._cmd_strings(_ctx(make_ctx, "strings", [str(f), "0"]))
    assert result.startswith("❌")


def test_archive_list_zip(make_ctx, tmp_path):
    import zipfile
    z = tmp_path / "a.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("readme.txt", "hi")
        zf.writestr("dir/nested.txt", "nested")
    result = ip._cmd_archive_list(_ctx(make_ctx, "archive_list", [str(z)]))
    assert "readme.txt" in result
    assert "dir/nested.txt" in result
    assert "2 عنصر" in result


def test_archive_list_not_an_archive(make_ctx, tmp_path):
    f = tmp_path / "notzip.bin"
    f.write_bytes(b"not a zip file")
    result = ip._cmd_archive_list(_ctx(make_ctx, "archive_list", [str(f)]))
    assert result.startswith("❌")
