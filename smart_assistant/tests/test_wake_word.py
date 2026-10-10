import threading
import numpy as np
import wake_word as wake


def test_spikes_and_repeat_detections_are_filtered():
    gate = wake.TriggerGate()
    assert not gate.accept(0.99, 0)
    assert not gate.accept(0.1, 0.08)
    assert not gate.accept(0.99, 0.16)
    assert gate.accept(0.99, 0.24)
    assert not gate.accept(0.99, 1)
    assert not gate.accept(0.99, 6)
    assert gate.accept(0.99, 6.08)


def test_mic_is_closed_before_wake_callback_and_does_not_rearm(tmp_path):
    fired = threading.Event()
    states, microphone = [], {"open": False}
    class Detector:
        def reset(self):
            pass
        def predict(self, data):
            assert data.dtype == np.int16
            return {"jarvis": 0.9}
    class Stream:
        def __init__(self, **kwargs):
            self.callback = kwargs["callback"]
            assert kwargs["samplerate"] == 16000
        def __enter__(self):
            microphone["open"] = True
            for _ in range(3):
                self.callback(np.zeros(1280, dtype=np.int16).tobytes(), 1280, None, None)
            return self
        def __exit__(self, *args):
            microphone["open"] = False
    def on_wake():
        assert not microphone["open"]
        fired.set()
    listener = wake.WakeListener(tmp_path, on_wake, states.append,
                                 detector_factory=lambda path: Detector(), stream_factory=Stream)
    listener.start()
    listener.allow(True)
    try:
        assert fired.wait(3)
        assert not listener.active.is_set()
        assert listener.released.is_set()
    finally:
        listener.close()
        listener.thread.join(2)
    assert not listener.thread.is_alive()
    assert "detected" in states


def test_disabled_listener_never_opens_microphone(tmp_path):
    loaded = threading.Event()
    calls = []
    listener = wake.WakeListener(tmp_path, lambda: calls.append("wake"), calls.append,
                                 detector_factory=lambda path: loaded.set(),
                                 stream_factory=lambda **kw: calls.append("microphone"))
    listener.start()
    assert loaded.wait(3)
    listener.close()
    listener.thread.join(2)
    assert "microphone" not in calls and "wake" not in calls


def test_invalid_download_is_not_cached(tmp_path, monkeypatch):
    import io
    import pytest
    monkeypatch.setattr(wake.urllib.request, "urlopen", lambda *args, **kw: io.BytesIO(b"bad"))
    with pytest.raises(ValueError, match="Invalid"):
        wake.prepare_models(tmp_path)
    assert not list(tmp_path.iterdir())


def test_cached_models_never_require_network(tmp_path, monkeypatch):
    for name in wake.MODEL_NAMES:
        (tmp_path / name).write_bytes(b"x" * 2048)
    monkeypatch.setattr(wake.urllib.request, "urlopen", lambda *args, **kw: (_ for _ in ()).throw(AssertionError("network")))
    assert wake.prepare_models(tmp_path) == tmp_path
