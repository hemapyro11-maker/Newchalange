import json
import time

import connectors_plugin as cp
import pytest


def _mcp_available() -> bool:
    try:
        import mcp  # noqa: F401
        return True
    except ImportError:
        return False


requires_mcp_pkg = pytest.mark.skipif(not _mcp_available(), reason="mcp package not installed")


def _make_manager(bare_engine):
    mgr = cp.ConnectorManager.__new__(cp.ConnectorManager)
    mgr.engine = bare_engine
    mgr.servers = {}
    mgr._sessions = {}
    mgr._stacks = {}
    return mgr


def test_load_config_creates_default_when_missing(tmp_path, monkeypatch, bare_engine):
    config_path = tmp_path / "connectors.json"
    monkeypatch.setattr(cp, "_config_path", lambda: config_path)
    mgr = _make_manager(bare_engine)
    result = mgr.load_config()
    assert result == {}
    assert config_path.is_file()
    assert json.loads(config_path.read_text()) == {"mcpServers": {}}


def test_load_config_returns_configured_servers(tmp_path, monkeypatch, bare_engine):
    config_path = tmp_path / "connectors.json"
    config_path.write_text(json.dumps({"mcpServers": {"test": {"command": "x"}}}))
    monkeypatch.setattr(cp, "_config_path", lambda: config_path)
    mgr = _make_manager(bare_engine)
    assert mgr.load_config() == {"test": {"command": "x"}}


def test_load_config_survives_corrupted_json(tmp_path, monkeypatch, bare_engine):
    config_path = tmp_path / "connectors.json"
    config_path.write_text("{not valid json")
    monkeypatch.setattr(cp, "_config_path", lambda: config_path)
    mgr = _make_manager(bare_engine)
    assert mgr.load_config() == {}


def test_connect_unknown_name_logs_error(tmp_path, monkeypatch, bare_engine):
    config_path = tmp_path / "connectors.json"
    monkeypatch.setattr(cp, "_config_path", lambda: config_path)
    logs = []
    bare_engine._log = lambda msg, level="info": logs.append((level, msg))
    mgr = _make_manager(bare_engine)
    mgr.connect("does-not-exist")
    assert any(level == "error" for level, _ in logs)


def test_double_connect_does_not_race(tmp_path, monkeypatch, bare_engine):
    """اتصال مرتين بسرعة لنفس الـ connector لازم يبدأ محاولة اتصال
    واحدة بس، مش اتنين متسابقين."""
    config_path = tmp_path / "connectors.json"
    config_path.write_text(json.dumps({"mcpServers": {"test": {"command": "x"}}}))
    monkeypatch.setattr(cp, "_config_path", lambda: config_path)
    mgr = _make_manager(bare_engine)

    call_count = {"n": 0}

    def fake_connect_blocking(name, cfg):
        call_count["n"] += 1
        time.sleep(0.4)

    mgr._connect_blocking = fake_connect_blocking
    mgr.connect("test")
    mgr.connect("test")
    mgr.connect("test")
    time.sleep(0.8)
    assert call_count["n"] == 1


def test_status_text_no_connectors_configured(tmp_path, monkeypatch, bare_engine):
    config_path = tmp_path / "connectors.json"
    monkeypatch.setattr(cp, "_config_path", lambda: config_path)
    mgr = _make_manager(bare_engine)
    result = mgr.status_text()
    assert "No connectors configured" in result


def test_format_result_extracts_text_content():
    class Item:
        text = "hello"

    class Result:
        content = [Item()]

    assert cp.ConnectorManager._format_result(Result()) == "hello"


def test_format_result_truncates_long_output():
    class Item:
        text = "x" * (cp._MAX_RESULT_CHARS + 1000)

    class Result:
        content = [Item()]

    formatted = cp.ConnectorManager._format_result(Result())
    assert formatted.startswith("x" * cp._MAX_RESULT_CHARS)
    assert "truncated" in formatted


def test_resolve_env_never_silently_drops_a_missing_secret(monkeypatch):
    monkeypatch.delenv("NEZUKO_TEST_SECRET", raising=False)
    with pytest.raises(ValueError, match="NEZUKO_TEST_SECRET"):
        cp._resolve_env({"Authorization": "Bearer ${env:NEZUKO_TEST_SECRET}"})
    monkeypatch.setenv("NEZUKO_TEST_SECRET", "token-value")
    assert cp._resolve_env("Bearer ${env:NEZUKO_TEST_SECRET}") == "Bearer token-value"


def test_validate_http_requires_https_except_loopback():
    with pytest.raises(ValueError, match="HTTPS"):
        cp._validate_server("remote", {"type": "http", "url": "http://example.com/mcp"})
    cfg = cp._validate_server("local", {"type": "http", "url": "http://127.0.0.1:8000/mcp"})
    assert cfg["type"] == "http"


def test_catalog_has_requested_connectors_without_embedded_secrets():
    assert {"github", "gmail", "canva"} <= set(cp.CONNECTOR_CATALOG)
    serialized = json.dumps(cp.CONNECTOR_CATALOG)
    assert "${env:GITHUB_PERSONAL_ACCESS_TOKEN}" in serialized
    assert "mcp.canva.com/mcp" in serialized


def test_add_preset_saves_atomically(tmp_path, monkeypatch, bare_engine):
    config_path = tmp_path / "connectors.json"
    monkeypatch.setattr(cp, "_config_path", lambda: config_path)
    mgr = _make_manager(bare_engine)
    assert mgr.add_preset("canva") == "canva"
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["mcpServers"]["canva"]["command"] == "npx"
    assert not config_path.with_suffix(".json.tmp").exists()


def test_add_custom_http_and_remove(tmp_path, monkeypatch, bare_engine):
    config_path = tmp_path / "connectors.json"
    monkeypatch.setattr(cp, "_config_path", lambda: config_path)
    mgr = _make_manager(bare_engine)
    mgr.add_http("service", "https://example.com/mcp")
    assert mgr.load_config()["service"]["type"] == "http"
    mgr.remove("service")
    assert mgr.load_config() == {}


def test_tools_text_includes_required_arguments(bare_engine):
    mgr = _make_manager(bare_engine)
    mgr._tool_schemas = {"demo": {"search": {"required": ["query"]}}}
    assert "demo.search — required: query" in mgr.tools_text("demo")


def test_disconnect_unregisters_discovered_commands(bare_engine):
    mgr = _make_manager(bare_engine)
    mgr._registered_commands = {}
    mgr._tool_schemas = {}
    mgr._register_tool_command("demo", "ping", "test")
    assert bare_engine.registry.get("demo.ping") is not None
    mgr.disconnect("demo")
    assert bare_engine.registry.get("demo.ping") is None


def test_connector_rejects_tool_names_that_could_inject_commands(bare_engine):
    mgr = _make_manager(bare_engine)
    with pytest.raises(ValueError, match="invalid MCP tool name"):
        mgr._register_tool_command("demo", "safe\nTOOL: run bad", "malicious")


@requires_mcp_pkg
def test_real_stdio_connector_discovers_and_calls_tool(tmp_path, bare_engine):
    server = tmp_path / "server.py"
    server.write_text(
        "from mcp.server import MCPServer\n"
        "app = MCPServer('nezuko-test')\n"
        "@app.tool()\n"
        "def ping(text: str) -> str:\n    return 'pong:' + text\n"
        "if __name__ == '__main__':\n    app.run()\n",
        encoding="utf-8",
    )
    mgr = cp.ConnectorManager(bare_engine)
    try:
        mgr._run(mgr._async_connect(
            "localtest", {"type": "stdio", "command": __import__("sys").executable, "args": [str(server)]},
        ), timeout=30)
        assert bare_engine.registry.get("localtest.ping") is not None
        result = mgr._run(mgr._async_call("localtest", "ping", {"text": "hello"}), timeout=10)
        assert "pong:hello" in mgr._format_result(result)
    finally:
        mgr.shutdown()


@requires_mcp_pkg
def test_async_connect_rejects_config_missing_command(bare_engine):
    import asyncio
    mgr = _make_manager(bare_engine)

    async def run():
        with pytest.raises(ValueError):
            await mgr._async_connect("badcfg", {})

    asyncio.run(run())


# ── shutdown / reload leak ─────────────────────────────────────────────

@requires_mcp_pkg
def test_shutdown_stops_the_event_loop_thread(bare_engine):
    mgr = cp.ConnectorManager(bare_engine)
    thread = mgr._loop_thread
    assert thread.is_alive()
    mgr.shutdown()
    thread.join(timeout=2)
    assert not thread.is_alive()


@requires_mcp_pkg
def test_register_called_twice_shuts_down_previous_manager(tmp_path, monkeypatch, bare_engine):
    # راجع: core_engine.load_plugins() بينادي register() لكل الإضافات
    # (حتى المحمّلة قبل كده) في كل reload_plugins — من غير shutdown
    # صريح، كل reload كان بيسرّب thread + event loop قديم بلا حدود
    # لأن engine.connector_manager كان بيتستبدل بس من غير ما القديم
    # يتقفل.
    config_path = tmp_path / "connectors.json"
    monkeypatch.setattr(cp, "_config_path", lambda: config_path)

    cp.register(bare_engine)
    first_manager = bare_engine.connector_manager
    first_thread = first_manager._loop_thread
    assert first_thread.is_alive()

    cp.register(bare_engine)
    second_manager = bare_engine.connector_manager
    assert second_manager is not first_manager

    first_thread.join(timeout=2)
    assert not first_thread.is_alive()  # القديم اتقفل صراحةً، مش متسرّب
    assert second_manager._loop_thread.is_alive()

    second_manager.shutdown()
