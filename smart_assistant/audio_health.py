"""Read Windows microphone mute/volume; unmute only on an explicit user action."""
from __future__ import annotations

import os


def _endpoint(selected=""):
    from pycaw.pycaw import AudioUtilities, EDataFlow, DEVICE_STATE
    name = selected.rsplit(" [", 1)[0]
    if name and name not in {"Microsoft Sound Mapper - Input", "Primary Sound Capture Driver"}:
        devices = AudioUtilities.GetAllDevices(EDataFlow.eCapture.value, DEVICE_STATE.ACTIVE.value)
        matches = [d for d in devices if d.FriendlyName == name]
        if len(matches) != 1:
            raise ValueError("Cannot identify the selected Windows microphone endpoint")
        return matches[0]
    return AudioUtilities.CreateDevice(AudioUtilities.GetMicrophone())


def microphone_state(selected="", *, unmute=False):
    if os.name != "nt":
        return {"available": False, "detail": "Windows endpoint checks are unavailable"}
    try:
        import comtypes
    except ImportError:
        return {"available": False, "detail": "Windows audio diagnostic dependency is unavailable"}
    initialized = False
    try:
        comtypes.CoInitialize(); initialized = True
        device = _endpoint(selected)
        volume = device.EndpointVolume
        if unmute:
            volume.SetMute(0, None)
        return {"available": True, "name": device.FriendlyName,
                "muted": bool(volume.GetMute()),
                "volume": round(volume.GetMasterVolumeLevelScalar()*100)}
    except Exception as exc:
        return {"available": False, "detail": str(exc)[:200]}
    finally:
        if initialized:
            comtypes.CoUninitialize()
