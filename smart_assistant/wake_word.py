"""Local ONNX wake detection; release the microphone before notifying the UI.

Only the three official openWakeWord inference models are downloaded on first
enable. Waiting audio is never saved, transcribed or sent to an AI provider.
"""
from __future__ import annotations

import pathlib
import queue
import threading
import time
import urllib.request

MODEL_NAMES = ("melspectrogram.onnx", "embedding_model.onnx", "hey_jarvis_v0.1.onnx")
MODEL_RELEASE = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/"


def prepare_models(folder: pathlib.Path):
    folder.mkdir(parents=True, exist_ok=True)
    for name in MODEL_NAMES:
        target = folder / name
        if target.is_file() and target.stat().st_size > 1024:
            continue
        temporary = target.with_suffix(".download")
        try:
            with urllib.request.urlopen(MODEL_RELEASE + name, timeout=30) as response, temporary.open("wb") as output:
                size = 0
                while chunk := response.read(65536):
                    size += len(chunk)
                    if size > 64 * 1024 * 1024:
                        raise ValueError("Wake model exceeds download limit")
                    output.write(chunk)
            if size <= 1024:
                raise ValueError("Invalid wake model download")
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    return folder


def load_detector(folder):
    from openwakeword.model import Model
    prepare_models(folder)
    return Model(wakeword_models=[str(folder / MODEL_NAMES[2])], inference_framework="onnx",
                 melspec_model_path=str(folder / MODEL_NAMES[0]),
                 embedding_model_path=str(folder / MODEL_NAMES[1]), ncpu=1)


class TriggerGate:
    """Configurable evidence window with a cooldown between utterances."""
    def __init__(self, threshold=0.5, frames=1, cooldown=5.0):
        self.threshold, self.frames, self.cooldown = threshold, frames, cooldown
        self.count, self.next_allowed = 0, 0.0

    def accept(self, score, now):
        if now < self.next_allowed:
            self.count = 0
            return False
        self.count = self.count + 1 if score >= self.threshold else 0
        if self.count < self.frames:
            return False
        self.count = 0
        self.next_allowed = now + self.cooldown
        return True


class WakeListener:
    def __init__(self, folder, on_wake, on_status, *, detector_factory=load_detector, stream_factory=None,
                 device=None, threshold=0.5, frames=1, on_metrics=None):
        self.folder, self.on_wake, self.on_status = pathlib.Path(folder), on_wake, on_status
        self.detector_factory, self.stream_factory = detector_factory, stream_factory
        self.device = device
        self.threshold = max(0.1, min(0.95, float(threshold)))
        self.frames = max(1, min(3, int(frames)))
        self.on_metrics = on_metrics or (lambda metrics: None)
        self.active = threading.Event()
        self.stopped = threading.Event()
        self.released = threading.Event()
        self.released.set()
        self.thread = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stopped.clear()
        self.thread = threading.Thread(target=self._run, name="nezuko-wake-word", daemon=True)
        self.thread.start()

    def allow(self, enabled):
        self.active.set() if enabled else self.active.clear()

    def close(self):
        self.active.clear()
        self.stopped.set()

    def _run(self):
        try:
            import numpy as np
            import sounddevice as sd
            self.on_status("loading")
            detector = self.detector_factory(self.folder)
            stream_factory = self.stream_factory or sd.RawInputStream
            gate = TriggerGate(self.threshold, self.frames)
            last_metrics, peak_score = 0.0, 0.0
            while not self.stopped.is_set():
                if not self.active.wait(0.2):
                    continue
                if self.stopped.wait(max(0, gate.next_allowed - time.monotonic())):
                    break
                if not self.active.is_set():
                    continue
                detector.reset()
                audio = queue.Queue(maxsize=8)
                def receive(data, frames, timing, status):
                    if status:
                        # Don't infer across a discontinuity or queued old audio.
                        while not audio.empty():
                            try:
                                audio.get_nowait()
                            except queue.Empty:
                                break
                    try:
                        audio.put_nowait(bytes(data))
                    except queue.Full:
                        pass
                fired = False
                self.released.clear()
                try:
                    device_args = {"device": self.device} if self.device is not None else {}
                    with stream_factory(samplerate=16000, blocksize=1280, channels=1,
                                        **device_args,
                                        dtype="int16", callback=receive):
                        self.on_status("waiting")
                        while self.active.is_set() and not self.stopped.is_set():
                            try:
                                chunk = audio.get(timeout=0.1)
                            except queue.Empty:
                                continue
                            samples = np.frombuffer(chunk, dtype=np.int16)
                            scores = detector.predict(samples)
                            score = float(max(scores.values(), default=0))
                            now = time.monotonic()
                            peak_score = max(peak_score, score)
                            accepted = gate.accept(score, now)
                            if now - last_metrics >= 0.25 or accepted:
                                last_metrics = now
                                self.on_metrics({"rms": float(np.sqrt(np.mean(samples.astype(np.float32)**2)))
                                                 if samples.size else 0.0,
                                                 "score": score, "peak_score": peak_score,
                                                 "threshold": self.threshold})
                            if accepted:
                                fired = True
                                self.active.clear()
                                break
                finally:
                    self.released.set()
                # Stream is closed here: normal recording can own the device.
                if fired and not self.stopped.is_set():
                    self.on_status("detected")
                    self.on_wake()
                else:
                    self.on_status("paused")
        except Exception as exc:
            self.on_status("error:" + type(exc).__name__ + ": " + str(exc)[:240])
        finally:
            self.active.clear()


def input_devices():
    """Stable names distinguish the same microphone under different host APIs."""
    import sounddevice as sd
    hosts = sd.query_hostapis()
    return [(f"{device['name']} [{hosts[device['hostapi']]['name']}]", index)
            for index, device in enumerate(sd.query_devices()) if device['max_input_channels'] > 0]


def configured_input(cfg):
    """Resolve by name on each run: Windows device indices can change after reboot."""
    name = cfg.get("microphone_device", "")
    if not name:
        return None
    for label, index in input_devices():
        if label == name:
            return index
    raise ValueError("Selected microphone is disconnected. Select another microphone in Settings.")


def play_acknowledgement(language="ar"):
    """Use a pre-rendered human voice; no network/model inference on wake."""
    import ctypes
    import os
    import sys
    if os.name != "nt":
        return False
    base = pathlib.Path(getattr(sys, "_MEIPASS", pathlib.Path(__file__).resolve().parent))
    path = base / "assets" / ("wake-en.wav" if language == "en" else "wake-ar.wav")
    return path.is_file() and bool(ctypes.WinDLL("winmm").PlaySoundW(
        ctypes.c_wchar_p(str(path)), None, 0x00020002))
