"""
PipelineController — standalone version (no Flask).

Import this into main.py or use it directly for testing.
All fixes applied:
  - self._mode initialized to "site"
  - self._mode_lock created
  - _post_to_server always receives mode argument
  - _convo_url / _site_url properly assigned
  - _check_server uses correct attributes
  - NameError on 'target' removed
  - Mode resets to "site" after each convo turn
  - Retry on STT timeout
"""

import threading
from typing import Optional

import requests

from utils.config_manager import ConfigManager
from utils.Actions import Actions
from services.wake_word_service import WakeWordService
from services.stt_service import STTService
from services.translator_service import TranslatorService
from services.tts_service import TTSService
from services.command_service import CommandService


class PipelineController:

    def __init__(self):
        print("[Pipeline] Initializing...")
        self._cfg     = ConfigManager()
        self._busy    = threading.Event()
        self._running = True
        self._ARDUINO_ENABLED = False

        # ── Mode routing ───────────────────────────────────
        # "site"  = web dashboard request → site_url server
        # "convo" = wake word request     → convo_url server
        # Default is "site". Wake word flips it to "convo" for one turn only.
        self._mode      = "site"
        self._mode_lock = threading.Lock()

        # ── Web mode flag ──────────────────────────────────
        # When True: pipeline ignores transcriptions (web server owns the mic)
        self._web_mode      = False
        self._web_mode_lock = threading.Lock()

        # ── Retry state ────────────────────────────────────
        self._retry_pending = False

        # ── Arduino ────────────────────────────────────────
        motor_controller = Actions.check_the_arduino()
        if motor_controller:
            print("[Pipeline] Arduino Connected")
            self._ARDUINO_ENABLED = True

        # ── Server URLs ────────────────────────────────────
        self._convo_url      = self._cfg.model["convo_url"].rstrip("/")
        self._site_url       = self._cfg.model["site_url"].rstrip("/")
        self._server_timeout = self._cfg.model.get("timeout_seconds", 30)

        print(f"[Pipeline] Convo URL: {self._convo_url}")
        print(f"[Pipeline] Site  URL: {self._site_url}")
        self._check_servers()

        # ── Services ───────────────────────────────────────
        self.translator = TranslatorService(self._cfg)
        self.tts        = TTSService(self._cfg)
        self.command    = CommandService(self._cfg)

        self.stt = STTService(
            self._cfg,
            on_text=self._on_transcription,
            on_timeout=self._on_stt_timeout,
        )
        self.wake = WakeWordService(self._cfg, on_detected=self._on_wake_word)
        self.stt.register_wake_listener(self.wake.feed)

        print("[Pipeline] Ready.")

    @property
    def cfg(self): return self._cfg

    @property
    def busy(self): return self._busy

    # ── Server health checks ───────────────────────────────
    def _check_servers(self):
        for label, url in [("convo", self._convo_url), ("site", self._site_url)]:
            try:
                r    = requests.get(f"{url}/health", timeout=3)
                data = r.json()
                print(f"[Pipeline] {label} server OK — model: {data.get('model', '?')}, "
                      f"mode: {data.get('mode', '?')}")
            except requests.ConnectionError:
                print(f"[Pipeline] WARNING: {label} server not reachable at {url}")
            except Exception as e:
                print(f"[Pipeline] WARNING: {label} health check failed ({e})")

    # ── HTTP to servers ────────────────────────────────────
    def _post_to_server(self, text: str, mode: str = "site") -> dict:
        """
        Post text to the correct server based on mode.
        mode="convo" → convo_url  (wake-word voice conversation)
        mode="site"  → site_url   (web dashboard)
        """
        url = self._convo_url if mode == "convo" else self._site_url
        print(f"[Pipeline] POST → {mode} ({url}): '{text[:60]}'")
        try:
            r = requests.post(
                f"{url}/respond",
                json={"text": text},
                timeout=self._server_timeout,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print(f"[Pipeline] Server error ({mode}): {e}")
            return {"type": "answer", "response": "Sorry, I could not reach my brain right now."}

    # ── Web mode control ───────────────────────────────────
    def enter_web_mode(self):
        """
        Call before /transcribe starts recording.
        Suspends pipeline so it does not steal the transcription.
        Stops any ongoing TTS so the mic stays clean.
        """
        with self._web_mode_lock:
            self._web_mode = True
        self.tts.stop()
        print("[Pipeline] Web mode ON — pipeline suspended.")

    def exit_web_mode(self):
        """Call after /transcribe returns."""
        with self._web_mode_lock:
            self._web_mode = False
        print("[Pipeline] Web mode OFF — pipeline resumed.")

    # ── Lifecycle ──────────────────────────────────────────
    def start(self):
        self.stt.start()
        self.wake.start()
        print("[Pipeline] Running.")

    def stop(self):
        self._running = False
        self.wake.stop()
        self.stt.stop()
        self.tts.stop()

    def arm_stt(self):
        self.stt.arm()

    # ── Pipeline callbacks ─────────────────────────────────
    def _on_wake_word(self):
        # Ignore wake word while web UI owns the mic
        with self._web_mode_lock:
            if self._web_mode:
                return

        # Switch mode to convo BEFORE arming — so the transcription
        # that comes back goes to the right server
        with self._mode_lock:
            self._mode = "convo"

        # Barge-in: interrupt Wall-E if he is currently speaking
        if self._busy.is_set():
            print("[Pipeline] Barge-in — interrupting TTS.")
            self.tts.stop()
            self._busy.clear()

        self._retry_pending = False
        self.stt.arm()

    def _on_stt_timeout(self):
        """
        STT armed but nothing loud enough was detected.
        Retry once, then give up and reset mode to site.
        """
        with self._web_mode_lock:
            if self._web_mode:
                return

        if not self._retry_pending:
            print("[Pipeline] STT timeout — retrying once...")
            self._retry_pending = True
            self.stt.arm()
        else:
            print("[Pipeline] Retry also timed out — resetting to idle.")
            self._retry_pending = False
            with self._mode_lock:
                self._mode = "site"

    def _on_transcription(self, raw_text: str):
        # Drop transcription if web server owns the mic
        with self._web_mode_lock:
            if self._web_mode:
                print(f"[Pipeline] Dropped (web mode): '{raw_text}'")
                return

        # Drop empty strings — Whisper sometimes returns whitespace
        text = raw_text.strip()
        if not text:
            print("[Pipeline] Dropped empty transcription.")
            return

        self._retry_pending = False
        print(f"[Pipeline] Accepted: '{text}'")

        self._busy.set()
        try:
            self.process_text(text)
        finally:
            self._busy.clear()
            # Always reset mode to site after one convo turn completes
            with self._mode_lock:
                self._mode = "site"

    # ── One full pipeline turn ─────────────────────────────
    def process_text(self, raw_text: str, force_mode: Optional[str] = None) -> dict:
        """
        Run one full turn: translate → route → post → speak.

        force_mode: override self._mode for this call only.
                    Pass "site" from web endpoints so wake-word state
                    cannot bleed into dashboard requests.
        """
        lang = self._cfg.language
        print(f"\n[Pipeline] Input  : '{raw_text}'")

        english_input = self.translator.to_english(raw_text)
        print(f"[Pipeline] English: '{english_input}'")

        if force_mode is not None:
            mode = force_mode
        else:
            with self._mode_lock:
                mode = self._mode

        print(f"[Pipeline] Mode   : {mode}")

        result    = self._post_to_server(english_input, mode=mode)
        resp_type = result.get("type", "answer")
        resp_text = result.get("response", "")
        print(f"[Pipeline] Reply  : [{resp_type}] '{resp_text}'")

        if resp_type == "command":
            command_data = result.get("command_data", {})
            print(f"[Pipeline] CMD    : {command_data}")
            # TODO: forward command_data to Arduino via self.command
        else:
            if resp_text.strip():
                final_text = self.translator.to_language(resp_text, lang)
                print(f"[Pipeline] TTS    : '{final_text[:80]}'")
                self.tts.speak(final_text, lang)
            else:
                print("[Pipeline] Empty response — not speaking.")

        return result
