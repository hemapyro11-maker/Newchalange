import io
import json
import pytest
import brain


def ndjson(*messages):
    return io.BytesIO(b"\n".join(json.dumps(message).encode() for message in messages))


def test_stream_collects_text_and_native_tool_calls(monkeypatch):
    call = {"function": {"name": "memory_save", "arguments": {"arguments": "a fact"}}}
    monkeypatch.setattr(brain.urllib.request, "urlopen", lambda *a, **k: ndjson(
        {"message": {"content": "Hello "}},
        {"message": {"content": "world", "tool_calls": [call]}},
        {"done": True, "message": {"content": "!"}},
    ))
    previews = []
    result = brain._post_local_stream("http://localhost/api/chat", {"stream": True}, 10, previews.append)
    assert result["message"]["content"] == "Hello world!"
    assert result["message"]["tool_calls"] == [call]
    assert previews[-1] == "Hello world!"


def test_interrupted_stream_is_not_accepted_as_final(monkeypatch):
    monkeypatch.setattr(brain.urllib.request, "urlopen", lambda *a, **k: ndjson({"message": {"content": "partial"}}))
    with pytest.raises(RuntimeError, match="before completion"):
        brain._post_local_stream("http://localhost/api/chat", {}, 10, lambda text: None)


def test_stream_error_is_reported(monkeypatch):
    monkeypatch.setattr(brain.urllib.request, "urlopen", lambda *a, **k: ndjson({"error": "model unavailable"}))
    with pytest.raises(RuntimeError, match="model unavailable"):
        brain._post_local_stream("http://localhost/api/chat", {}, 10, lambda text: None)


def test_preview_listener_is_request_scoped_and_restored_after_failure():
    first, second = lambda text: None, lambda text: None
    with brain.stream_listener(first):
        assert brain._stream_state.callback is first
        with pytest.raises(ValueError):
            with brain.stream_listener(second):
                assert brain._stream_state.callback is second
                raise ValueError()
        assert brain._stream_state.callback is first
    assert brain._stream_state.callback is None


def test_companion_streaming_converts_tools_after_complete_response(monkeypatch):
    monkeypatch.setattr(brain, "load_config", lambda: {"assistant_mode": "companion"})
    captured = {}
    def stream(url, payload, timeout, callback):
        captured.update(payload)
        callback("I'll remember that.")
        return {"message": {"content": "I'll remember that.", "tool_calls": [
            {"function": {"name": "memory_save", "arguments": {"arguments": "channel name"}}}]}}
    monkeypatch.setattr(brain, "_post_local_stream", stream)
    messages = [{"role": "system", "content": "system", "nezuko_tools": [
        {"type": "function", "function": {"name": "memory_save"}}]}, {"role": "user", "content": "remember"}]
    with brain.stream_listener(lambda text: None):
        result = brain._call_ollama(brain.PROVIDERS["ollama"], "qwen3.5:4b", messages, 0.6, 100)
    assert captured["stream"] is True
    assert "nezuko_tools" not in captured["messages"][0]
    assert result.endswith("TOOL: memory_save channel name")
