import fetch_plugin as fp


def test_no_url_shows_usage(make_ctx):
    result = fp._cmd_fetch(make_ctx("fetch", []))
    assert "usage" in result


def test_file_scheme_is_blocked(make_ctx):
    result = fp._cmd_fetch(make_ctx("fetch", ["file:///etc/passwd"]))
    assert result.startswith("❌")
    assert "http" in result


def test_ftp_scheme_is_blocked(make_ctx):
    result = fp._cmd_fetch(make_ctx("fetch", ["ftp://example.com/x"]))
    assert result.startswith("❌")


def test_bare_domain_with_port_is_not_misdetected_as_scheme(make_ctx, monkeypatch):
    """localhost:8080/x لازم يتفهم كـ https://localhost:8080/x مش يتترفض
    غلط لأن urlsplit ممكن تفهم 'localhost' كـ scheme."""
    captured = {}

    class FakeResp:
        headers = {"Content-Type": "text/plain"}

        def read(self, n):
            return b"ok"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        return FakeResp()

    monkeypatch.setattr(fp.urllib.request, "urlopen", fake_urlopen)
    fp._cmd_fetch(make_ctx("fetch", ["localhost:8080/x"]))
    assert captured["url"] == "https://localhost:8080/x"


def test_https_url_used_verbatim(make_ctx, monkeypatch):
    captured = {}

    class FakeResp:
        headers = {"Content-Type": "text/html"}

        def read(self, n):
            return b"<html>hi</html>"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        return FakeResp()

    monkeypatch.setattr(fp.urllib.request, "urlopen", fake_urlopen)
    result = fp._cmd_fetch(make_ctx("fetch", ["https://example.com/page"]))
    assert captured["url"] == "https://example.com/page"
    assert "hi" in result
