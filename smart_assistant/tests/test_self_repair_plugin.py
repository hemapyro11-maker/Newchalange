import ast
from types import SimpleNamespace
import self_repair_plugin as sr


def test_self_repair_registers(bare_engine):
    sr.register(bare_engine)
    assert bare_engine.registry.get("self_repair") is not None


def test_media_smoke_reports_missing_ffmpeg(monkeypatch):
    monkeypatch.setattr(sr.mr, "binary", lambda name: None)
    assert sr._real_media_smoke() == (False, "FFmpeg is unavailable")


def test_choose_openrouter_model_stays_on_free_models():
    provider = sr.brain.PROVIDERS["openrouter"]
    selected = sr._choose_model(provider, ["paid/model", "qwen/qwen3:free"])
    assert selected == "qwen/qwen3:free"


def test_parse_patch_rejects_non_json():
    assert sr._parse_patch("I would change it") is None
    assert sr._parse_patch('{"search":"old","replace":"new","reason":"fix"}')["replace"] == "new"


def test_sensitive_call_scanner_detects_new_subprocess_use():
    safe = ast.parse("def f():\n    return 1\n")
    unsafe = ast.parse("def f():\n    return subprocess.run(['x'])\n")
    assert sr._dangerous_calls(safe) == []
    assert sr._dangerous_calls(unsafe) == ["subprocess.run"]


def test_ai_plugin_patch_is_applied_after_validation(tmp_path, monkeypatch):
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    source = plugins / "demo_plugin.py"
    source.write_text(
        "def answer():\n    return 'broken'\n\ndef register(engine):\n    engine.registry.register('demo', lambda ctx: answer())\n",
        encoding="utf-8",
    )
    reply = sr.brain.BrainReply(text='{"search":"return \'broken\'","replace":"return \'fixed\'","reason":"correct result"}')
    monkeypatch.setattr(sr.brain, "get_brain", lambda: SimpleNamespace(chat=lambda *a, **k: reply))
    class Engine:
        plugin_health = {"demo_plugin": {"status": "loaded"}}
        def load_plugins(self):
            self.plugin_health = {"demo_plugin": {"status": "loaded"}}
    result = sr._tested_ai_plugin_repair(Engine(), f'File "{source}", line 2, in answer')
    assert result.startswith("AI repaired")
    assert "return 'fixed'" in source.read_text(encoding="utf-8")
    assert list((tmp_path / ".nezuko" / "repairs").glob("demo_plugin-*.bak"))
