import hashlib
import socket
import threading

import security_plugin as sp


def test_hash_file_matches_known_vector(make_ctx, tmp_path):
    f = tmp_path / "h.txt"
    f.write_text("hello world")
    result = sp._cmd_hash_file(make_ctx("hash_file", [str(f)]))
    expected = hashlib.sha256(b"hello world").hexdigest()
    assert expected in result


def test_hash_file_md5(make_ctx, tmp_path):
    f = tmp_path / "h.txt"
    f.write_bytes(b"abc")
    result = sp._cmd_hash_file(make_ctx("hash_file", [str(f), "md5"]))
    assert hashlib.md5(b"abc").hexdigest() in result


def test_hash_file_unsupported_algo(make_ctx, tmp_path):
    f = tmp_path / "h.txt"
    f.write_text("x")
    result = sp._cmd_hash_file(make_ctx("hash_file", [str(f), "not_a_real_algo"]))
    assert result.startswith("❌")


def test_hash_file_missing(make_ctx):
    result = sp._cmd_hash_file(make_ctx("hash_file", ["/no/such/file"]))
    assert result.startswith("❌")


def test_port_scan_finds_real_listener(make_ctx):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.listen(1)

    def accept_loop():
        while True:
            try:
                conn, _ = srv.accept()
                conn.close()
            except OSError:
                break

    t = threading.Thread(target=accept_loop, daemon=True)
    t.start()
    try:
        result = sp._cmd_port_scan(make_ctx("port_scan", ["127.0.0.1", str(port), str(port)]))
        assert str(port) in result
        assert "🔓" in result
    finally:
        srv.close()


def test_port_scan_unresolvable_host_is_friendly(make_ctx):
    result = sp._cmd_port_scan(make_ctx("port_scan", ["this-host-does-not-exist-xyz123.invalid", "1", "5"]))
    assert result.startswith("❌")


def test_port_scan_rejects_bad_port_range(make_ctx):
    result = sp._cmd_port_scan(make_ctx("port_scan", ["127.0.0.1", "0", "5"]))
    assert result.startswith("❌")
    result = sp._cmd_port_scan(make_ctx("port_scan", ["127.0.0.1", "70000", "70005"]))
    assert result.startswith("❌")


def test_port_scan_rejects_oversized_range(make_ctx):
    result = sp._cmd_port_scan(make_ctx("port_scan", ["127.0.0.1", "1", "5000"]))
    assert result.startswith("❌")


def test_port_scan_rejects_non_numeric(make_ctx):
    result = sp._cmd_port_scan(make_ctx("port_scan", ["127.0.0.1", "abc", "5"]))
    assert result.startswith("❌")
