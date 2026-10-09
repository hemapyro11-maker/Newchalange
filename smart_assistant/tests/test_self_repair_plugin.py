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


def test_functional_probe_requires_a_real_chat_completion(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        sr.brain, "_call_provider",
        lambda provider, model, messages, temperature, max_tokens:
            captured.update(model=model, messages=messages, max_tokens=max_tokens) or "OK",
    )
    out = sr._functional_probe(sr.brain.PROVIDERS["ollama"], "llama3.2:1b")
    assert out == "OK"
    assert captured["model"] == "llama3.2:1b"
    assert captured["max_tokens"] == 8


def test_repair_does_not_claim_healthy_when_real_chat_probe_failed(make_ctx, monkeypatch):
    monkeypatch.setattr(sr, "_repair_external_providers", lambda: (
        [], ["Groq: API key rejected (403); replace the key",
             "AI engines answering real prompts: 0/1"],
    ))
    monkeypatch.setattr(sr, "_real_media_smoke", lambda: (True, "portable H.264 render passed"))
    monkeypatch.setattr(sr, "_tested_ai_plugin_repair", lambda *a, **k: None)
    result = sr._cmd_self_repair(make_ctx("self_repair", []))
    assert "❌ Groq: API key rejected" in result
    assert "No repairable fault remains" not in result


def test_parse_patch_rejects_non_json():
    assert sr._parse_patch("I would change it") is None
    assert sr._parse_patch('{"search":"old","replace":"new","reason":"fix"}')["replace"] == "new"


def test_companion_repair_preserves_selected_brain(monkeypatch):
    cfg = {"assistant_mode": "companion", "primary": "ollama",
           "enabled": ["ollama", "groq"], "models": {"ollama": "qwen3.5:4b"}}
    inspected = []
    monkeypatch.setattr(sr.brain, "load_config", lambda: cfg)
    monkeypatch.setattr(sr.brain, "is_local_alive", lambda *a, **k: True)
    monkeypatch.setattr(sr, "_models_for", lambda p: inspected.append(p.name) or ["llama3.2:1b"])
    monkeypatch.setattr(sr.brain, "save_config", lambda c: (_ for _ in ()).throw(AssertionError("changed brain")))
    monkeypatch.setattr(sr, "_functional_probe", lambda *a: (_ for _ in ()).throw(AssertionError("wrong model probe")))
    fixed, reports = sr._repair_external_providers()
    assert inspected == ["ollama"]
    assert fixed == []
    assert cfg["models"]["ollama"] == "qwen3.5:4b"
    assert any("ollama pull qwen3.5:4b" in report for report in reports)
    assert "AI engines answering real prompts: 0/1" in reports


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
