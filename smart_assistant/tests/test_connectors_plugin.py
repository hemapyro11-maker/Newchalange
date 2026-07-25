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
    assert "مفيش" in result


def test_format_result_extracts_text_content():
    class Item:
        text = "hello"

    class Result:
        content = [Item()]

    assert cp.ConnectorManager._format_result(Result()) == "hello"


def test_format_result_truncates_long_output():
    class Item:
        text = "x" * 5000

    class Result:
        content = [Item()]

    formatted = cp.ConnectorManager._format_result(Result())
    assert len(formatted) == 4000


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
