import hashlib
import shutil
import socket
import ssl
import subprocess
import threading

import pytest
import security_plugin as sp

requires_openssl = pytest.mark.skipif(not shutil.which("openssl"), reason="openssl not installed")


def _make_self_signed_cert(tmp_path, cn="localhost", days=365):
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", str(key), "-out", str(cert),
            "-days", str(days), "-nodes", "-subj", f"/CN={cn}",
            "-addext", f"subjectAltName=DNS:{cn}",
        ],
        capture_output=True, text=True, check=True,
    )
    return cert, key


def _serve_tls_once(cert, key, port):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(cert), str(key))
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(5)

    def accept_loop():
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                break
            try:
                tls = ctx.wrap_socket(conn, server_side=True)
                tls.close()
            except OSError:
                pass

    t = threading.Thread(target=accept_loop, daemon=True)
    t.start()
    return srv


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


@requires_openssl
def test_tls_check_rejects_untrusted_self_signed_by_default(make_ctx, tmp_path):
    cert, key = _make_self_signed_cert(tmp_path)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.close()
    server = _serve_tls_once(cert, key, port)
    try:
        result = sp._cmd_tls_check(make_ctx("tls_check", ["localhost", str(port)]))
        assert result.startswith("❌")
        assert "--insecure" in result
    finally:
        server.close()


@requires_openssl
def test_tls_check_insecure_shows_real_cert_details(make_ctx, tmp_path):
    cert, key = _make_self_signed_cert(tmp_path, cn="mytestcert.local", days=365)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.close()
    server = _serve_tls_once(cert, key, port)
    try:
        result = sp._cmd_tls_check(make_ctx("tls_check", ["localhost", str(port), "--insecure"]))
        assert result.startswith("🔒")
        assert "mytestcert.local" in result
        assert "✅" in result  # cert valid for ~365 days, well outside the 30-day warning window
    finally:
        server.close()


@requires_openssl
def test_tls_check_warns_on_soon_expiring_cert(make_ctx, tmp_path):
    cert, key = _make_self_signed_cert(tmp_path, cn="expiring.local", days=5)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.close()
    server = _serve_tls_once(cert, key, port)
    try:
        result = sp._cmd_tls_check(make_ctx("tls_check", ["localhost", str(port), "--insecure"]))
        assert "⚠️" in result
        assert "هتنتهي" in result
    finally:
        server.close()


def test_tls_check_no_args(make_ctx):
    result = sp._cmd_tls_check(make_ctx("tls_check", []))
    assert result.startswith("usage")


def test_tls_check_bad_port(make_ctx):
    result = sp._cmd_tls_check(make_ctx("tls_check", ["localhost", "not_a_port"]))
    assert result.startswith("❌")


def test_tls_check_unresolvable_host(make_ctx):
    result = sp._cmd_tls_check(make_ctx("tls_check", ["this-host-does-not-exist-xyz123.invalid"]))
    assert result.startswith("❌")


def test_tls_check_connection_refused(make_ctx):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.close()  # closed immediately -> nothing listening
    result = sp._cmd_tls_check(make_ctx("tls_check", ["127.0.0.1", str(port)]))
    assert result.startswith("❌")


def test_file_perms_no_args(make_ctx):
    result = sp._cmd_file_perms(make_ctx("file_perms", []))
    assert result.startswith("usage")


def test_file_perms_missing_path(make_ctx, tmp_path):
    result = sp._cmd_file_perms(make_ctx("file_perms", [str(tmp_path / "nope")]))
    assert result.startswith("❌")


def test_file_perms_clean_file_reports_ok(make_ctx, tmp_path):
    f = tmp_path / "clean.txt"
    f.write_text("hi")
    f.chmod(0o644)
    result = sp._cmd_file_perms(make_ctx("file_perms", [str(f)]))
    assert result.startswith("✅")


def test_file_perms_flags_world_writable(make_ctx, tmp_path):
    f = tmp_path / "bad.txt"
    f.write_text("hi")
    f.chmod(0o666)
    result = sp._cmd_file_perms(make_ctx("file_perms", [str(f)]))
    assert "world-writable" in result
    assert str(f) in result


def test_file_perms_flags_suid(make_ctx, tmp_path):
    f = tmp_path / "suid_bin"
    shutil.copy("/bin/true", f)
    f.chmod(0o4755)
    result = sp._cmd_file_perms(make_ctx("file_perms", [str(f)]))
    assert "SUID" in result


def test_file_perms_flags_readable_secret_file(make_ctx, tmp_path):
    f = tmp_path / ".env"
    f.write_text("SECRET_KEY=abc")
    f.chmod(0o644)
    result = sp._cmd_file_perms(make_ctx("file_perms", [str(f)]))
    assert "حساس" in result


def test_file_perms_directory_scan_flags_only_the_bad_file(make_ctx, tmp_path):
    (tmp_path / "normal.txt").write_text("x")
    (tmp_path / "normal.txt").chmod(0o644)
    (tmp_path / "worldwritable.txt").write_text("x")
    (tmp_path / "worldwritable.txt").chmod(0o666)
    (tmp_path / "secret.txt").write_text("x")
    (tmp_path / "secret.txt").chmod(0o600)
    result = sp._cmd_file_perms(make_ctx("file_perms", [str(tmp_path)]))
    assert "🔍" in result
    assert "1 مشكلة" in result
    assert "worldwritable.txt" in result
    assert "normal.txt" not in result
    assert "secret.txt" not in result


def test_file_perms_ignores_symlinks(make_ctx, tmp_path):
    target = tmp_path / "target.txt"
    target.write_text("x")
    target.chmod(0o644)
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    result = sp._cmd_file_perms(make_ctx("file_perms", [str(tmp_path)]))
    assert result.startswith("✅")
