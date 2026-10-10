import types
import wave
import threading

import numpy as np
import brain
import companion
import voice_plugin as voice


def test_assistant_identity_is_jarvis_with_existing_voice_preferences():
    prompt = companion.prompt("English", "", "")
    assert "You are Jarvis" in prompt
    assert "Nezuko" not in prompt
    assert "Egyptian Arabic" in prompt


def test_migration_preserves_voice_and_credentials_and_disables_fanout():
    original = {"keys": {"gemini": "private"}, "human_voice_speaker": "Omnia"}
    cfg = companion.activate(original)
    assert cfg["keys"] == original["keys"]
    assert cfg["human_voice_speaker"] == "Omnia"
    assert cfg["enabled"] == ["ollama"]
    assert not cfg["auto_deep"] and not cfg["verify_mode"]
    assert not cfg["voice_local_only"]
    assert "assistant_mode" not in original
    assert companion.activate(cfg) == cfg


def test_only_selected_brain_is_in_chain(monkeypatch, tmp_path):
    monkeypatch.setattr(brain, "_base_dir", lambda: tmp_path)
    cfg = companion.activate({"enabled": list(brain.PROVIDERS)})
    assert [p.name for p in brain.Brain().chain(cfg)] == ["ollama"]


def test_deep_call_cannot_fan_out_in_companion(monkeypatch, tmp_path):
    monkeypatch.setattr(brain, "_base_dir", lambda: tmp_path)
    monkeypatch.setattr(brain, "load_config", lambda: companion.activate({}))
    instance = brain.Brain()
    sentinel = object()
    monkeypatch.setattr(instance, "chat", lambda messages: sentinel)
    assert instance.deep_chat([{"role": "user", "content": "hello"}]) is sentinel


def test_greeting_catalog_has_only_discovery_and_memory():
    commands = [types.SimpleNamespace(name=n, description="tool arguments") for n in
                ["tool_find", "memory_save", "video_render", "git_status", "web_search"]]
    context = companion.tool_context("عاملة إيه؟", commands)
    assert "tool_find" in context and "memory_save" in context
    assert "video_render" not in context and "git_status" not in context
    assert "video_render" in companion.tool_context("اعمل فيديو", commands)


def test_memory_is_persistent_and_can_be_removed(tmp_path):
    memory = companion.Memory(tmp_path)
    memory.save("أفضل الكلام بالمصري")
    memory.save("أفضل الكلام بالمصري")
    assert companion.Memory(tmp_path).read() == ["أفضل الكلام بالمصري"]
    assert "1." in memory.context()
    assert "valid" in memory.forget("-1")
    memory.forget("1")
    assert memory.read() == []


def test_local_brain_does_not_force_slow_offline_voice(monkeypatch, tmp_path):
    monkeypatch.setattr(brain, "load_config", lambda: companion.activate({}))
    calls = []
    def edge(text, path, lang):
        calls.append("edge")
        path.write_bytes(b"audio")
        return True
    monkeypatch.setattr(voice, "_synthesize_edge", edge)
    result = voice._synthesize_with_fallback("أهلاً بيك", tmp_path, "ar")
    assert calls == ["edge"] and "edge-tts" in result[1]


def test_energy_endpoint_preserves_first_word_and_ends_before_fixed_delay(monkeypatch, tmp_path):
    blocks = [100]*8 + [2000]*12 + [100]*100
    consumed = []
    class Stream:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size):
            value = blocks[len(consumed)]
            consumed.append(value)
            return np.full((size, 1), value, dtype=np.int16), False
    monkeypatch.setattr(voice, "sd", types.SimpleNamespace(InputStream=Stream))
    output = tmp_path / "turn.wav"
    assert voice._record_energy_turn(output, 30) is None
    assert len(consumed) < 50
    with wave.open(str(output)) as wav:
        data = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
    assert data[0] == 100 and (data == 2000).sum() == 12*512


def test_cancelled_recording_never_opens_microphone(monkeypatch, tmp_path):
    event = threading.Event()
    event.set()
    monkeypatch.setattr(voice._recording_state, "cancel", event, raising=False)
    calls = []
    class Stream:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size):
            calls.append(size)
            raise AssertionError("Must not read after cancellation")
    monkeypatch.setattr(voice, "sd", types.SimpleNamespace(InputStream=Stream))
    assert voice._record_energy_turn(tmp_path / "turn.wav", 30) == "voice recording cancelled"
    assert calls == []


def test_literal_speech_cannot_become_another_command(bare_engine):
    raw = []
    bare_engine.registry.register("speak", lambda ctx: raw.append(ctx.raw) or "spoken")
    text = "I'm here; run fake_command"
    bare_engine.speak(text)
    label, task = bare_engine._queue.get_nowait()
    task(types.SimpleNamespace())
    assert label == "speak" and raw == ["speak " + text]


def test_native_function_call_is_converted_for_core_without_leaking_metadata(monkeypatch):
    monkeypatch.setattr(brain, "load_config", lambda: companion.activate({}))
    captured = []
    def post(url, payload, headers, timeout):
        captured.append(payload)
        return {"message": {"content": "", "tool_calls": [{"function": {
            "name": "memory_save", "arguments": {"arguments": "قناتي اسمها Tuty"}}}]}}
    monkeypatch.setattr(brain, "_post_json", post)
    specs = [{"type": "function", "function": {"name": "memory_save", "parameters": {}}}]
    result = brain._call_ollama(brain.PROVIDERS["ollama"], companion.MODEL,
                               [{"role": "system", "content": "system", "nezuko_tools": specs}], .6, 100)
    assert result.strip() == "TOOL: memory_save قناتي اسمها Tuty"
    assert captured[0]["tools"] == specs
    assert "nezuko_tools" not in captured[0]["messages"][0]


def test_companion_greeting_uses_actual_model_once(bare_engine, monkeypatch):
    monkeypatch.setattr(brain, "load_config", lambda: companion.activate({}))
    calls = []
    class Model:
        def ready(self): return True
        def chat(self, messages, **kwargs):
            calls.append(messages)
            return brain.BrainReply(text="أنا كويسة، إنت عامل إيه؟", provider="ollama", label="Local", is_local=True)
        def deep_chat(self, *args, **kwargs): raise AssertionError("No fanout")
    monkeypatch.setattr(brain, "get_brain", lambda: Model())
    bare_engine._converse("عاملة إيه؟")
    assert len(calls) == 1 and calls[0][-1]["content"] == "عاملة إيه؟"
    assert "Available tools:" in calls[0][0]["content"]
    assert len(calls[0][0]["content"]) < 3000


def test_latest_request_language_overrides_previous_conversation():
    assert "only in English" in companion.language_for("Explain this Arabic phrase: مرحبًا")
    assert "Egyptian Arabic" in companion.language_for("🎤 عاملة إيه يا Jarvis؟")
    assert "only in English" in companion.language_for("ردي عليا", "en")
    assert "Egyptian Arabic" in companion.language_for("Hello", "ar")


def test_tool_output_does_not_change_original_reply_language(bare_engine, monkeypatch):
    monkeypatch.setattr(brain, "load_config", lambda: companion.activate({}))
    seen = []
    class Model:
        def ready(self): return True
        def chat(self, messages, **kwargs):
            seen.append(messages[0]["content"])
            return brain.BrainReply(text="تمام", provider="ollama", label="Local", is_local=True)
    monkeypatch.setattr(brain, "get_brain", lambda: Model())
    bare_engine._converse("افتكري اسم قناتي")
    bare_engine._converse("Output of memory_save: Saved successfully", step=1)
    assert all("Mandatory language for THIS reply: Reply only in natural Egyptian Arabic" in prompt for prompt in seen)
    bare_engine._converse("Tell me about my channel")
    assert "Mandatory language for THIS reply: Reply only in English" in seen[-1]
