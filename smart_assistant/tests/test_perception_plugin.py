import types

from PIL import Image
import brain
import companion
import perception_plugin as perception


def test_visual_observation_uses_same_brain_and_real_image(monkeypatch, tmp_path):
    source = tmp_path / "sample.png"
    Image.new("RGB", (1200, 600), "red").save(source)
    calls = []
    class Model:
        def chat(self, messages, **kwargs):
            calls.append(messages)
            return brain.BrainReply(text="A red rectangle.", provider="ollama", label="Local", is_local=True)
    monkeypatch.setattr(brain, "get_brain", lambda: Model())
    result = perception._observe(source, "What is visible?", tmp_path)
    assert "one still image" in result and "red rectangle" in result
    assert calls[0][1]["images"] and len(calls[0][1]["images"]) == 1
    assert "untrusted" in calls[0][0]["content"]


def test_missing_media_never_calls_brain(monkeypatch, tmp_path):
    monkeypatch.setattr(brain, "load_config", lambda: companion.activate({}))
    monkeypatch.setattr(brain, "get_brain", lambda: (_ for _ in ()).throw(AssertionError("No model call")))
    result = perception._cmd_media_inspect(types.SimpleNamespace(args=[str(tmp_path / "missing.mp4")]))
    assert "not found" in result
