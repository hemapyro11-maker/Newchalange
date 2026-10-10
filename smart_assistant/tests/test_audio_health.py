import types

import audio_health


class Volume:
    def __init__(self):
        self.muted = True
        self.changes = []
    def GetMute(self): return self.muted
    def GetMasterVolumeLevelScalar(self): return 1.0
    def SetMute(self, value, context):
        self.changes.append(value); self.muted = bool(value)


def test_diagnosis_never_unmutes_without_an_explicit_action(monkeypatch):
    if audio_health.os.name != "nt":
        return
    volume = Volume()
    monkeypatch.setattr(audio_health, "_endpoint", lambda selected: types.SimpleNamespace(
        FriendlyName="Realtek", EndpointVolume=volume))
    assert audio_health.microphone_state()["muted"] is True
    assert volume.changes == []
    assert audio_health.microphone_state(unmute=True)["muted"] is False
    assert volume.changes == [0]


def test_disconnected_endpoint_returns_a_diagnostic_without_crashing(monkeypatch):
    if audio_health.os.name != "nt":
        return
    def missing(selected): raise ValueError("Disconnected microphone")
    monkeypatch.setattr(audio_health, "_endpoint", missing)
    state = audio_health.microphone_state("Old microphone")
    assert not state["available"]
    assert "Disconnected" in state["detail"]
