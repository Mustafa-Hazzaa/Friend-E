"""
TTSService — text → spoken audio.

Arabic:  Edge TTS (online) → Piper (offline fallback)
English: Sherpa-ONNX (always local)

SQLite / Mishkal thread fix:
  Mishkal uses SQLite internally. SQLite connections cannot be shared
  across threads. The fix is threading.local() — each thread that calls
  _get_mishkal() gets its own Mishkal instance created in that thread.
"""

import asyncio
import io
import re
import socket
import subprocess
import threading
import wave

import numpy as np
import sounddevice as sd
import soundfile as sf
import scipy.signal as sps

from utils.config_manager import ConfigManager


# ── Thread-local Mishkal ──────────────────────────────────
# Each thread that calls _get_mishkal() gets its own instance.
# This prevents the SQLite cross-thread ProgrammingError.
_thread_local = threading.local()


def _get_mishkal():
    """Get or create a Mishkal instance for the current thread."""
    if not hasattr(_thread_local, "vocalizer"):
        try:
            import mishkal.tashkeel
            _thread_local.vocalizer = mishkal.tashkeel.TashkeelClass()
            print(f"[TTS] Mishkal initialised on thread {threading.current_thread().name}")
        except Exception as e:
            print(f"[TTS] Mishkal unavailable: {e}")
            _thread_local.vocalizer = None
    return _thread_local.vocalizer


def _has_internet() -> bool:
    try:
        socket.setdefaulttimeout(2)
        socket.create_connection(("8.8.8.8", 53))
        return True
    except OSError:
        return False


def _chunk_arabic(text: str, max_words: int = 12) -> list[str]:
    parts = [p.strip() for p in re.split(r'[.!?؟،]+', text) if p.strip()]
    chunks = []
    for p in parts:
        words = p.split()
        if len(words) <= max_words:
            chunks.append(p)
            continue
        subs = [s.strip() for s in re.split(r'\s+(?:و|أو|ثم|لكن|حيث)\s+', p)
                if s.strip()]
        for s in subs:
            sw = s.split()
            if len(sw) <= max_words:
                chunks.append(s)
            else:
                for i in range(0, len(sw), max_words):
                    chunks.append(" ".join(sw[i:i + max_words]))
    return chunks


def _resample(samples: np.ndarray, sr: int, target_sr: int) -> np.ndarray:
    """Resample samples from sr to target_sr. No-op if rates already match."""
    if sr == target_sr:
        return samples
    num_samples = int(round(len(samples) * target_sr / sr))
    return sps.resample(samples, num_samples).astype(np.float32)


class TTSService:
    """
    Public interface:
        speak(text, lang)  — synthesize and play (blocks until done)
        stop()             — interrupt playback immediately
    """

    def __init__(self, cfg: ConfigManager):
        self._cfg  = cfg.tts

        # ── Find output device ─────────────────────────────
        self._output_device_name = "USB PnP Sound Device"
        self._output_device      = None
        for i, dev in enumerate(sd.query_devices()):
            if (self._output_device_name in dev["name"]
                    and dev["max_output_channels"] > 0):
                self._output_device = i
                print(f"[TTS] Speaker '{self._output_device_name}' at device {i}")
                break
        if self._output_device is None:
            raise RuntimeError(f"Speaker '{self._output_device_name}' not found.")

        # Rate the output device accepts — all audio is resampled to this
        self._device_rate = self._cfg["sample_rate"]
        print(f"[TTS] Output device rate: {self._device_rate} Hz")

        self._ar_voice = None
        self._en_tts   = None
        # NOTE: Mishkal is NOT initialised here — created lazily per-thread.
        self._load_models()

    def _load_models(self):
        try:
            from piper import PiperVoice
            self._ar_voice = PiperVoice.load(self._cfg["piper_ar_model"])
            print("[TTS] Piper Arabic loaded.")
        except Exception as e:
            print(f"[TTS] Piper Arabic unavailable: {e}")

        try:
            import sherpa_onnx
            self._en_tts = sherpa_onnx.OfflineTts(
                sherpa_onnx.OfflineTtsConfig(
                    model=sherpa_onnx.OfflineTtsModelConfig(
                        vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                            model=self._cfg["sherpa_en_model"],
                            lexicon="",
                            tokens=self._cfg["sherpa_en_tokens"],
                            data_dir=self._cfg["sherpa_en_data_dir"],
                        ),
                    ),
                )
            )
            print("[TTS] Sherpa-ONNX English loaded.")
        except Exception as e:
            print(f"[TTS] Sherpa-ONNX unavailable: {e}")

    # ── Public API ─────────────────────────────────────────

    def speak(self, text: str, lang: str):
        """Synthesize text and play it. Blocks until playback finishes."""
        text = text.strip()
        if not text:
            return

        if lang == "ar":
            samples, sr, online = self._synthesize_arabic(text)
        else:
            samples, sr = self._synthesize_english(text)
            online = False

        if self._cfg.get("effect", True):
            samples, sr = self._apply_effect(samples, sr, lang, online)

        samples = _resample(samples, sr, self._device_rate)

        sd.play(samples, self._device_rate, device=self._output_device)
        sd.wait()

    def stop(self):
        """Interrupt any currently playing audio immediately."""
        sd.stop()

    # ── Arabic synthesis ──────────────────────────────────

    def _synthesize_arabic(self, text: str) -> tuple[np.ndarray, int, bool]:
        if _has_internet():
            try:
                raw = self._edge_tts(text)
                samples, sr = sf.read(io.BytesIO(raw), dtype="float32")
                if samples.ndim == 2:
                    samples = samples.mean(axis=1)
                return samples, sr, True
            except Exception as e:
                print(f"[TTS] Edge TTS failed ({e}) — Piper fallback")
        return *self._piper_tts(text), False

    def _edge_tts(self, text: str) -> bytes:
        import edge_tts

        async def _fetch():
            communicate = edge_tts.Communicate(text, voice=self._cfg["edge_voice_ar"])
            chunks = []
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    chunks.append(chunk["data"])
            return b"".join(chunks)

        return asyncio.run(_fetch())

    def _piper_tts(self, text: str) -> tuple[np.ndarray, int]:
        sr = self._cfg["sample_rate"]

        # _get_mishkal() creates the instance ON THIS THREAD if needed.
        vocalizer = _get_mishkal()
        if vocalizer:
            try:
                text = vocalizer.tashkeel(text.replace("\u0640", "").strip())
            except Exception as e:
                print(f"[TTS] Mishkal tashkeel failed ({e}) — using raw text")

        if not text.endswith((".", "!", "؟")):
            text += "."

        chunks  = _chunk_arabic(text)
        silence = np.zeros(int(sr * 150 / 1000), dtype=np.float32)
        pieces  = []
        for chunk in chunks:
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                self._ar_voice.synthesize_wav(chunk, wf)
            buf.seek(0)
            s, _ = sf.read(buf, dtype="float32")
            if s.ndim == 2:
                s = s.mean(axis=1)
            pieces.append(s)
            pieces.append(silence)

        combined = np.concatenate(pieces[:-1]) if pieces else np.zeros(1, np.float32)
        return combined, sr

    # ── English synthesis ─────────────────────────────────

    def _synthesize_english(self, text: str) -> tuple[np.ndarray, int]:
        audio = self._en_tts.generate(text)
        return np.asarray(audio.samples, dtype=np.float32), audio.sample_rate

    # ── Effect chain ──────────────────────────────────────

    @staticmethod
    def _effect_chain(lang: str, online: bool) -> str:
        if lang == "ar":
            sr = 24000 if online else 22050
            return (f"asetrate={sr}*1.33,aresample={sr},"
                    "atempo=0.75,aecho=0.7:0.6:100:0.15")
        return ("asetrate=22050*1.15,aresample=22050,"
                "atempo=0.70,aecho=0.7:0.6:60:0.15")

    def _apply_effect(self, samples: np.ndarray, sr: int,
                      lang: str, online: bool) -> tuple[np.ndarray, int]:
        buf = io.BytesIO()
        sf.write(buf, samples, sr, format="WAV", subtype="PCM_16")
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error",
             "-i", "pipe:0", "-filter:a", self._effect_chain(lang, online),
             "-f", "wav", "pipe:1"],
            input=buf.getvalue(), capture_output=True, check=True,
        )
        out, out_sr = sf.read(io.BytesIO(proc.stdout), dtype="float32")
        if out.ndim == 2:
            out = out.mean(axis=1)
        return out, out_sr
