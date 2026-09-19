"""
WakeWordService — listens for the wake word and fires a callback.

Audio source:
  No longer opens its own mic stream.
  Registers a listener with STTService via register_wake_listener().
  STTService sends every audio block here via that listener.
  This means exactly ONE stream exists system-wide.
"""

import os
import queue
import threading
import time
from typing import Callable

import numpy as np
from openwakeword.model import Model

from utils.config_manager import ConfigManager

_OWW_RATE = 16_000


class WakeWordService:

    def __init__(self, cfg: ConfigManager, on_detected: Callable):
        self._cfg         = cfg.wake_word
        self._on_detected = on_detected
        self._running     = False
        self._last_trigger = 0.0

        model_path = self._cfg.get("model_path", "")
        if model_path and os.path.exists(model_path):
            wakeword_arg         = [model_path]
            self._prediction_key = os.path.splitext(
                                       os.path.basename(model_path))[0]
            print(f"[WakeWord] Loading from file: {model_path}")
        else:
            wakeword_arg         = [self._cfg["model"]]
            self._prediction_key = self._cfg["model"]
            print(f"[WakeWord] Auto-download: '{self._cfg['model']}'")

        self._model = Model(
            wakeword_models=wakeword_arg,
            inference_framework="onnx",
        )

        # Queue bridges audio delivery → inference thread
        self._audio_queue: queue.Queue[np.ndarray] = queue.Queue()

    # ── Public ─────────────────────────────────────────────

    def start(self):
        self._running = True
        threading.Thread(target=self._inference_loop,
                         daemon=True, name="wakeword").start()
        print(f"[WakeWord] Listening for '{self._cfg['model']}'...")

    def stop(self):
        self._running = False

    def feed(self, audio_16k: np.ndarray) -> None:
        """
        Called by STTService's router with every 16kHz audio block.
        audio_16k is already decimated — no further processing needed.
        """
        if not self._running:
            return
        try:
            self._audio_queue.put_nowait(audio_16k)
        except queue.Full:
            pass

    # ── Internal ───────────────────────────────────────────

    def _inference_loop(self):
        while self._running:
            try:
                audio = self._audio_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            prediction = self._model.predict(audio)
            score      = prediction.get(self._prediction_key, 0)
            now        = time.time()

            if (score >= self._cfg["threshold"] and
                    (now - self._last_trigger) > self._cfg["cooldown_seconds"]):
                self._last_trigger = now
                print(f"[WakeWord] Detected! (score={score:.2f})")

                delay = self._cfg.get("post_detect_delay", 0.5)
                if delay > 0:
                    time.sleep(delay)

                self._on_detected()