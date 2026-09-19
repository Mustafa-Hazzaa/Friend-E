"""
STTService — microphone → transcribed text.

ONE stream. ONE queue. Routes audio to whoever needs it:
  - WakeWordService  (always, via registered listener)
  - pipeline buffer  (when armed — wake word conversation)

WakeWordService registers itself via register_wake_listener().

── The core timing problem and how we fix it ──────────────────────────────

THE RACE CONDITION (old behaviour):
  transcribe_once() swapped in a temporary _on_text collector, armed STT,
  then called result_q.get(timeout=10). Meanwhile:
    1. Mic hears speech → silence detected → audio sent to Whisper
    2. Whisper takes 3-5s on Pi
    3. result_q.get(timeout=10) expires → returns ""
    4. finally block restores original _on_text
    5. Whisper finishes → calls _on_text → but it is now the PIPELINE callback
    6. Pipeline processes the result as a voice command instead of web input

THE FIX (transcribe_once):
  transcribe_once() registers a result queue on self BEFORE arming.
  The Whisper worker checks _transcribe_active first and delivers results
  to the right place regardless of timing.

THE NON-BLOCKING FIX (arm_for_web):
  arm_for_web(callback) arms the mic and returns immediately.
  When Whisper finishes (however long it takes), it calls callback(text).
  The /start-voice endpoint returns instantly; the result is pushed
  to the site server by the pipeline, not waited for by Flask.
"""

import queue
import threading
from typing import Callable, Optional

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

from utils.config_manager import ConfigManager

_VAD_FRAME_SAMPLES = 480
_STT_RATE          = 16_000


def _load_vad(aggressiveness: int = 1):
    try:
        import webrtcvad
        vad = webrtcvad.Vad(aggressiveness)
        print(f"[STT] VAD: webrtcvad (aggressiveness={aggressiveness})")
        return vad, "webrtcvad"
    except ImportError:
        print("[STT] VAD: energy fallback (webrtcvad not installed)")
        return None, "energy"


def _rms_to_db(audio: np.ndarray) -> float:
    rms = np.sqrt(np.mean(audio.astype(np.float32) ** 2))
    if rms == 0:
        return -float("inf")
    return 20 * np.log10(rms / 32768.0)


class STTService:

    def __init__(self, cfg: ConfigManager,
                 on_text:    Optional[Callable[[str], None]] = None,
                 on_timeout: Optional[Callable] = None):
        self._cfg        = cfg.stt
        self._on_text    = on_text
        self._on_timeout = on_timeout

        # WakeWordService registers here so it gets every audio block
        self._wake_listener: Optional[Callable[[np.ndarray], None]] = None

        # ── Find microphone ────────────────────────────────
        mic_name = "USB2.0 Device"
        self._input_device = None
        for i, dev in enumerate(sd.query_devices()):
            if mic_name in dev["name"] and dev["max_input_channels"] > 0:
                self._input_device = i
                print(f"[STT] Mic '{mic_name}' at device {i}")
                break
        if self._input_device is None:
            raise RuntimeError(f"Microphone '{mic_name}' not found.")

        mic_rate           = self._cfg["sample_rate"]
        self._decimate     = max(1, mic_rate // _STT_RATE)
        self._db_threshold = self._cfg.get("db_threshold", -35)
        self._silence_dur  = self._cfg.get("silence_duration", 1.5)
        print(f"[STT] {mic_rate} Hz → {_STT_RATE} Hz (÷{self._decimate})")
        print(f"[STT] dB gate     : {self._db_threshold} dBFS")
        print(f"[STT] Silence dur : {self._silence_dur}s")

        # ── Raw audio queue — mic callback → router ────────
        self._raw_q: queue.Queue[np.ndarray] = queue.Queue(maxsize=300)

        # ── Pipeline (armed) mode state ────────────────────
        self._armed           = False
        self._audio_buffer    = []
        self._silence_counter = 0.0
        self._heard_loud      = False
        self._lock            = threading.Lock()

        # ── Whisper queue ──────────────────────────────────
        self._whisper_q: queue.Queue[np.ndarray] = queue.Queue()

        # ── transcribe ownership ───────────────────────────
        # Covers both transcribe_once (blocking) and arm_for_web (non-blocking).
        #
        # _transcribe_active    : True while a web caller owns the mic
        # _transcribe_result_q  : set by transcribe_once (blocking path)
        # _transcribe_callback  : set by arm_for_web (non-blocking path)
        # _whisper_busy         : True while Whisper is actively processing audio.
        #                         arm_for_web blocks re-arming until Whisper is
        #                         done to prevent the "double free" crash from
        #                         two Whisper sessions colliding in native code.
        self._transcribe_lock      = threading.Lock()
        self._transcribe_active    = False
        self._transcribe_result_q: Optional[queue.Queue] = None
        self._transcribe_callback: Optional[Callable[[str], None]] = None
        self._whisper_busy         = False

        # ── VAD + Whisper model ────────────────────────────
        aggressiveness        = self._cfg.get("vad_aggressiveness", 1)
        self._vad, self._vad_type = _load_vad(aggressiveness)
        self._model = WhisperModel(
            self._cfg["model_size"],
            device=self._cfg["device"],
            compute_type=self._cfg["compute_type"],
        )

        # ── ONE stream, never closed ───────────────────────
        self._stream = sd.InputStream(
            device=self._input_device,
            samplerate=mic_rate,
            channels=1,
            blocksize=_VAD_FRAME_SAMPLES * self._decimate,
            dtype="int16",
            callback=self._mic_callback,
        )

    # ── Public API ─────────────────────────────────────────

    def register_wake_listener(self, listener: Callable[[np.ndarray], None]):
        """WakeWordService calls this once at startup."""
        self._wake_listener = listener
        print("[STT] WakeWord listener registered.")

    def start(self):
        self._stream.start()
        threading.Thread(target=self._router_worker,
                         daemon=True, name="stt-router").start()
        threading.Thread(target=self._whisper_worker,
                         daemon=True, name="stt-whisper").start()
        print("[STT] Ready — mic stream open.")

    def stop(self):
        self._stream.stop()
        self._stream.close()
        print("[STT] Stopped.")

    def arm(self):
        """Start collecting audio for the next utterance."""
        with self._lock:
            self._armed           = True
            self._audio_buffer    = []
            self._silence_counter = 0.0
            self._heard_loud      = False
        print("[STT] Listening...")

    def feed(self, indata: np.ndarray) -> None:
        """Kept for compatibility — STTService owns the stream now."""
        pass

    def arm_for_web(self, on_result: Callable[[str], None]) -> bool:
        """
        Non-blocking web transcription.

        Arms the mic and returns immediately. When Whisper finishes
        (however long it takes), it calls on_result(text) in a background thread.

        Returns False (and does NOT arm) if Whisper is still processing a
        previous recording — the caller should wait and retry rather than
        firing a new session which would crash native Whisper/sounddevice code.
        Returns True when successfully armed.
        """
        with self._transcribe_lock:
            if self._whisper_busy:
                print("[STT] arm_for_web: rejected — Whisper still busy from previous session")
                return False
            self._transcribe_active   = True
            self._transcribe_result_q = None
            self._transcribe_callback = on_result
        print("[STT] arm_for_web: armed, callback registered.")
        self.arm()
        return True

    def transcribe_once(self, timeout: float = 20.0,
                        language: Optional[str] = None) -> str:
        """
        Record one utterance and return the transcribed text (BLOCKING).
        Used by the web dashboard /transcribe endpoint when a synchronous
        response is acceptable.

        timeout: How long to wait for Whisper to deliver a result.
                 20s is the correct default on Pi:
                   - user speaks (variable)
                   - silence detection fires after ~1s of quiet
                   - Whisper inference takes 3-5s on Pi
                 Don't reduce below 15s unless you benchmark your device.

        Returns "" on timeout or if nothing was heard.
        """
        lang          = language or self._cfg.get("language", "en")
        result_q: queue.Queue[str] = queue.Queue()
        orig_language = self._cfg.get("language", "en")

        # Register BEFORE arming — guarantees no Whisper result slips past
        with self._transcribe_lock:
            self._transcribe_active   = True
            self._transcribe_result_q = result_q
            self._transcribe_callback = None          # non-blocking path not used

        self._cfg["language"] = lang
        self.arm()

        try:
            text = result_q.get(timeout=timeout)
            print(f"[STT] transcribe_once got: '{text}'")
            return text

        except queue.Empty:
            print(f"[STT] transcribe_once timeout after {timeout}s")
            return ""

        finally:
            # Clear ownership FIRST so any subsequent Whisper result
            # (arriving after our timeout) gets discarded, not pipelined
            with self._transcribe_lock:
                self._transcribe_active   = False
                self._transcribe_result_q = None
                self._transcribe_callback = None

            self._cfg["language"] = orig_language

            # Disarm in case silence timer has not fired yet
            with self._lock:
                self._armed           = False
                self._audio_buffer    = []
                self._silence_counter = 0.0
                self._heard_loud      = False

    # ── Internal ───────────────────────────────────────────

    def _mic_callback(self, indata, frames, time_info, status):
        """Sounddevice callback — enqueue raw block and return immediately."""
        mono      = indata[:, 0]
        audio_16k = mono[::self._decimate].copy()
        try:
            self._raw_q.put_nowait(audio_16k)
        except queue.Full:
            pass  # drop frame rather than block the audio thread

    def _router_worker(self):
        """
        Single thread — reads every audio block and routes it:
          1. Always → WakeWordService listener
          2. If armed → pipeline buffer
        """
        while True:
            audio = self._raw_q.get()

            # 1. Wake word always gets every block
            if self._wake_listener is not None:
                try:
                    self._wake_listener(audio)
                except Exception:
                    pass

            # 2. Pipeline mode (armed)
            with self._lock:
                if self._armed:
                    self._route_pipeline(audio)

    def _route_pipeline(self, audio: np.ndarray):
        """Called under self._lock. Accumulates audio, detects silence."""
        db = _rms_to_db(audio)

        if db >= self._db_threshold:
            if not self._heard_loud:
                print(f"[STT] First loud sound ({db:.1f} dB)")
            self._heard_loud = True

        if self._is_speech(audio):
            self._silence_counter = 0.0
        else:
            self._silence_counter += len(audio) / _STT_RATE

        self._audio_buffer.append(audio.copy())

        if self._silence_counter >= self._silence_dur:
            print(f"[STT] Silence reached ({self._silence_dur}s) → finalizing")
            self._armed = False

            if self._heard_loud and len(self._audio_buffer) > 10:
                combined = (np.concatenate(self._audio_buffer)
                            .astype(np.float32) / 32768.0)
                print(f"[STT] Sending {len(combined) / _STT_RATE:.2f}s to Whisper")
                self._whisper_q.put(combined)
            else:
                print("[STT] No loud speech — firing timeout callback")
                self._fire_web_timeout_if_active()
                if self._on_timeout:
                    threading.Thread(target=self._on_timeout, daemon=True).start()

            self._audio_buffer    = []
            self._silence_counter = 0.0
            self._heard_loud      = False

    def _fire_web_timeout_if_active(self):
        """
        If arm_for_web is active and nothing was heard, deliver "" to the
        callback so the caller isn't left hanging indefinitely.
        """
        with self._transcribe_lock:
            if not self._transcribe_active:
                return
            cb = self._transcribe_callback
            q  = self._transcribe_result_q
            self._transcribe_active   = False
            self._transcribe_callback = None
            self._transcribe_result_q = None

        if cb is not None:
            threading.Thread(target=cb, args=("",), daemon=True).start()
        elif q is not None:
            q.put("")

    def _whisper_worker(self):
        """
        Dedicated Whisper thread — never blocks the mic router.
        Sets _whisper_busy for the duration of inference so arm_for_web
        can reject a new session that would collide with running native code.
        """
        while True:
            audio = self._whisper_q.get()
            print("[STT] Whisper processing...")

            with self._transcribe_lock:
                self._whisper_busy = True

            try:
                segments, _ = self._model.transcribe(
                    audio,
                    language=self._cfg.get("language", "en"),
                    no_speech_threshold=self._cfg.get("no_speech_threshold", 0.6),
                    beam_size=self._cfg.get("beam_size", 5),
                )
                text = " ".join(s.text for s in segments).strip()
            except Exception as e:
                print(f"[STT] Whisper error: {e}")
                text = ""
            finally:
                with self._transcribe_lock:
                    self._whisper_busy = False

            print(f"[STT] Whisper result: '{text}'" if text else "[STT] Whisper returned empty")

            # Grab and clear ownership atomically
            with self._transcribe_lock:
                active = self._transcribe_active
                cb     = self._transcribe_callback
                q      = self._transcribe_result_q
                if active:
                    self._transcribe_active   = False
                    self._transcribe_callback = None
                    self._transcribe_result_q = None

            if active:
                # Web caller owns this result
                if cb is not None:
                    # arm_for_web path — always deliver (even empty string)
                    print("[STT] → web callback (arm_for_web)")
                    threading.Thread(target=cb, args=(text,), daemon=True).start()
                elif q is not None:
                    # transcribe_once path
                    if text:
                        print("[STT] → web caller (transcribe_once)")
                        q.put(text)
                    # empty: transcribe_once timeout handles it via queue.Empty
            else:
                # Pipeline owns this result
                if text:
                    print("[STT] → pipeline")
                    if self._on_text:
                        self._on_text(text)
                else:
                    if self._on_timeout:
                        threading.Thread(target=self._on_timeout, daemon=True).start()

    def _is_speech(self, audio: np.ndarray) -> bool:
        """Return True if the audio frame contains speech."""
        if self._vad_type == "webrtcvad":
            if len(audio) > _VAD_FRAME_SAMPLES:
                for i in range(0, len(audio) - _VAD_FRAME_SAMPLES + 1,
                               _VAD_FRAME_SAMPLES):
                    chunk = audio[i:i + _VAD_FRAME_SAMPLES]
                    if len(chunk) == _VAD_FRAME_SAMPLES:
                        if self._vad.is_speech(chunk.tobytes(), _STT_RATE):
                            return True
                return False
            elif len(audio) == _VAD_FRAME_SAMPLES:
                return self._vad.is_speech(audio.tobytes(), _STT_RATE)
            else:
                padded = np.zeros(_VAD_FRAME_SAMPLES, dtype=np.int16)
                padded[:len(audio)] = audio
                return self._vad.is_speech(padded.tobytes(), _STT_RATE)
        else:
            rms = np.sqrt(np.mean(audio.astype(np.float32) ** 2))
            return rms > 300
