"""
WALL-E Pi App — runs on the RASPBERRY PI.

Mic-sharing rule:
    STTService owns the single mic stream.
    In normal mode: wake word → sets mode to "convo" → pipeline processes.
    In web mode:    /start-voice arms mic non-blocking.
                    When Whisper finishes it pushes result to site server.
                    Pipeline suspends _on_transcription so it doesn't steal audio.

Mode routing:
    "convo" — triggered by wake word → goes to convo_url server
    "site"  — triggered by web dashboard → goes to site_url server
    Default is "site". Wake word switches it to "convo" for one turn,
    then it resets back to "site" automatically.

Voice transcription flow (non-blocking):
    1. Site calls POST /start-voice   → Pi arms mic, returns immediately
    2. User speaks, Whisper transcribes (however long it takes)
    3. Pi POSTs result to site_url/voice-result automatically
    4. Site can also poll GET /voice-status to check progress

Config checklist (set in config.py or local_config.py):
    model.convo_url  — URL of the AI conversation server (e.g. http://LAPTOP_IP:5001)
    model.site_url   — URL of the AI site/education server (e.g. http://LAPTOP_IP:5002)
    model.timeout_seconds — how long to wait for AI response (default 30)

    IMPORTANT: convo_url and site_url must NOT point to this Pi app itself
    (port 5000). They must point to your AI server running on the laptop.
    If you see "404 NOT FOUND for /respond" it means the URL is wrong.
"""

import threading
import time
import uuid
from typing import Optional
import os
import requests
from flask import Flask, request, jsonify

from utils.config_manager import ConfigManager
from services.wake_word_service import WakeWordService
from services.stt_service import STTService
from services.translator_service import TranslatorService
from services.tts_service import TTSService
from services.command_service import ArduinoDevice
# from picamera2_stream import PiCameraStreamer


# ============================================================================
# PIPELINE CONTROLLER
# ============================================================================

class PipelineController:

    def __init__(self):
        print("[Pipeline] Initializing...")
        self._cfg     = ConfigManager()
        self._busy    = threading.Event()
        self._ARDUINO_ENABLED = False

        # ── Mode routing ───────────────────────────────────
        self._mode      = "site"
        self._mode_lock = threading.Lock()

        # ── camera ───────────────────────────────────
        # camera: PiCameraStreamer = PiCameraStreamer()
        
        # ── Web mode flag ──────────────────────────────────
        self._web_mode      = False
        self._web_mode_lock = threading.Lock()

        # ── Retry state ────────────────────────────────────
        self._retry_pending = False

        # ── Voice session state ────────────────────────────
        # Tracks the current non-blocking voice transcription request.
        # session_id: unique ID returned to the caller so they can poll.
        # status: "listening" | "transcribing" | "done" | "error" | "idle"
        # result: the transcribed text (set when status == "done")
        self._voice_lock       = threading.Lock()
        self._voice_session_id: Optional[str] = None
        self._voice_status     = "idle"   # idle | listening | transcribing | done | error
        self._voice_result     = ""

        # ── Arduino ────────────────────────────────────────
        # motor_controller = Actions.check_the_arduino()
        # if motor_controller:
        #     print("[Pipeline] Arduino Connected")
        #     self._ARDUINO_ENABLED = True

        # ── Server URLs ────────────────────────────────────
        self._convo_url      = self._cfg.model["convo_url"].rstrip("/")
        self._site_url       = self._cfg.model["site_url"].rstrip("/")
        self._server_timeout = self._cfg.model.get("timeout_seconds", 30)

        print(f"[Pipeline] Convo URL : {self._convo_url}")
        print(f"[Pipeline] Site  URL : {self._site_url}")
        self._validate_urls()
        self._check_servers()

        # ── Services ───────────────────────────────────────
        self.translator = TranslatorService(self._cfg)
        self.tts        = TTSService(self._cfg)
        self.commands = ArduinoDevice()

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

    # ── Config validation ──────────────────────────────────
    def _validate_urls(self):
        for label, url in [("convo_url", self._convo_url),
                            ("site_url",  self._site_url)]:
            if ":5000" in url:
                print(f"[Pipeline] ⚠️  WARNING: {label} = '{url}' contains port 5000.")
                print(f"[Pipeline] ⚠️  Port 5000 is THIS Pi app. It has no /respond endpoint.")
                print(f"[Pipeline] ⚠️  {label} should point to your AI server on the laptop.")
                print(f"[Pipeline] ⚠️  Example: http://LAPTOP_IP:8000")

    # ── Server health checks ───────────────────────────────
    def _check_servers(self):
        for label, url in [("convo", self._convo_url), ("site", self._site_url)]:
            try:
                r    = requests.get(f"{url}/health", timeout=3)
                data = r.json()
                print(f"[Pipeline] {label} server OK — {data}")
            except requests.ConnectionError:
                print(f"[Pipeline] WARNING: {label} server not reachable at {url}")
            except Exception as e:
                print(f"[Pipeline] WARNING: {label} health check failed ({e})")

    # ── HTTP to servers ────────────────────────────────────
    def _post_to_server(self, text: str, mode: str = "site") -> dict:
        url = self._convo_url if mode == "convo" else self._site_url
        print(url)
        print(f"[Pipeline] POST → {mode} ({url}): '{text[:60]}'")
        try:
            r = requests.post(
                f"{url}/respond",
                json={"text": text},
                timeout=self._server_timeout,
            )
            r.raise_for_status()
            return r.json()
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response else "?"
            print(f"[Pipeline] HTTP {status} from {mode} server: {e}")
            if status == 404:
                print(f"[Pipeline] ⚠️  404 means '{url}/respond' does not exist.")
            return {"type": "answer", "response": "Sorry, I could not reach my brain right now."}
        except Exception as e:
            print(f"[Pipeline] Server error ({mode}): {e}")
            return {"type": "answer", "response": "Sorry, I could not reach my brain right now."}

    # ── Web mode control ───────────────────────────────────
    def enter_web_mode(self):
        with self._web_mode_lock:
            self._web_mode = True
        self.tts.stop()
        print("[Pipeline] Web mode ON — pipeline suspended.")

    def exit_web_mode(self):
        with self._web_mode_lock:
            self._web_mode = False
        print("[Pipeline] Web mode OFF — pipeline resumed.")

    # ── Non-blocking voice transcription ──────────────────
    def start_voice_session(self, language: Optional[str] = None) -> str:
        """
        Start a non-blocking voice transcription.

        Returns a session_id immediately. The caller can either:
          - Poll GET /voice-status?session_id=<id>  (simple)
          - Implement POST /voice-result on the site server (push, faster)

        When transcription is complete the pipeline automatically:
          1. Updates internal status to "done"
          2. Pushes result to site_url/voice-result
        """
        # Only one session at a time
        with self._voice_lock:
            if self._voice_status in ("listening", "transcribing"):
                return self._voice_session_id  # return existing session

            sid                    = str(uuid.uuid4())[:8]
            self._voice_session_id = sid
            self._voice_status     = "listening"
            self._voice_result     = ""

        if language:
            self._cfg.stt["language"] = language

        self.enter_web_mode()

        def on_result(text: str):
            """
            Called by STTService in a background thread when Whisper finishes.
            text is "" if nothing was heard or Whisper returned empty.

            The Pi's job here is ONLY to transcribe. The site server
            (pdf.py / pi_bridge.py) owns what happens with the text —
            it polls /voice-status and handles the AI call itself.
            """
            print(f"[Pipeline] Voice session {sid} result: '{text}'")

            with self._voice_lock:
                if self._voice_session_id != sid:
                    print(f"[Pipeline] Session {sid} result discarded (superseded).")
                    return
                self._voice_status = "done"
                self._voice_result = text

            # Do NOT exit web mode here.
            # The site server still needs to call /speak after getting the
            # transcription. Web mode stays ON until the full interaction
            # is done — exited explicitly via POST /exit-web-mode from
            # pi_bridge after speak() completes.

        # Wait for any previous Whisper session to finish before arming.
        # arm_for_web returns False if Whisper is still running — retrying
        # immediately would cause a native crash ("double free or corruption").
        max_wait = 120  # seconds
        interval = 1.0
        waited   = 0.0
        while not self.stt.arm_for_web(on_result):
            if waited >= max_wait:
                print(f"[Pipeline] Voice session {sid} aborted — Whisper still busy after {max_wait}s")
                with self._voice_lock:
                    self._voice_status = "error"
                self.exit_web_mode()
                return sid
            print(f"[Pipeline] Waiting for Whisper to finish ({waited:.0f}s)...")
            time.sleep(interval)
            waited += interval

        print(f"[Pipeline] Voice session {sid} started.")
        return sid

    def get_voice_status(self, session_id: str) -> dict:
        """Return the current status of a voice session (for polling)."""
        with self._voice_lock:
            if self._voice_session_id != session_id:
                return {"session_id": session_id, "status": "unknown"}
            return {
                "session_id": session_id,
                "status":     self._voice_status,
                "text":       self._voice_result,
            }

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
        with self._web_mode_lock:
            if self._web_mode:
                return

        with self._mode_lock:
            self._mode = "convo"

        if self._busy.is_set():
            print("[Pipeline] Barge-in — interrupting TTS.")
            self.tts.stop()
            self._busy.clear()

        self._retry_pending = False
        self.stt.arm()

    def _on_stt_timeout(self):
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
        with self._web_mode_lock:
            if self._web_mode:
                print(f"[Pipeline] Dropped (web mode): '{raw_text}'")
                return

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
            with self._mode_lock:
                self._mode = "site"

    # ── One full pipeline turn ─────────────────────────────
    def process_text(self, raw_text: str, force_mode: Optional[str] = None) -> dict:
        """
        Run one full turn: translate → route → post → speak.

        force_mode: override self._mode for this call only.
                    Web endpoints pass force_mode="site" so wake-word
                    state cannot bleed into dashboard requests.
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
            command_data = result.get("data", {})
            print(f"[Pipeline] CMD    : {command_data}") 

            
            cmd = [f"{d['Action']}{d['value']}" for d in command_data]
            print(cmd)  # ['R100', 'R0', 'R100', 'R0']
            
            if cmd:
                print(f"[Pipeline] Sending to Arduino: {cmd}")
                for val in cmd:
                    self.commands.send_command(val)
        else:
            if resp_text.strip():
                final_text = self.translator.to_language(resp_text, lang)
                print(f"[Pipeline] TTS    : '{final_text[:80]}'")
                self.tts.speak(final_text, lang)
            else:
                print("[Pipeline] Empty response — not speaking.")

        return result


# ============================================================================
# FLASK APP
# ============================================================================

pipeline = PipelineController()
app      = Flask(__name__)


@app.route("/health", methods=["GET"])
def health():
    with pipeline._mode_lock:
        current_mode = pipeline._mode
    with pipeline._voice_lock:
        voice_status = pipeline._voice_status
    return jsonify({
        "status":       "ok",
        "language":     pipeline.cfg.language,
        "busy":         pipeline.busy.is_set(),
        "mode":         current_mode,
        "voice_status": voice_status,
    })


@app.route("/ask", methods=["POST"])
def ask():
    """
    Web dashboard sends text here.
    Always routed to the site server — never convo.
    """
    data = request.get_json(silent=True) or {}
    text = data.get("text", "").strip()

    if not text:
        return jsonify({"error": "Missing or empty 'text'"}), 400

    if pipeline.busy.is_set():
        return jsonify({"error": "Pipeline busy"}), 503

    holder = {}

    def run():
        holder["r"] = pipeline.process_text(text, force_mode="site")

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout=60)

    return jsonify(holder.get("r", {
        "type": "answer",
        "response": "Pipeline timed out.",
    }))


@app.route("/arm", methods=["POST"])
def arm():
    """Manually arm STT (for testing without wake word)."""
    if pipeline.busy.is_set():
        return jsonify({"error": "Pipeline busy"}), 503
    pipeline.arm_stt()
    return jsonify({"status": "armed"})


# ── NEW: non-blocking voice endpoints ─────────────────────────────────────

@app.route("/start-voice", methods=["POST"])
def start_voice():
    """
    Start a non-blocking voice transcription session.

    Returns immediately with a session_id. The pipeline will:
      1. Listen for speech (no timeout — waits as long as needed)
      2. Run Whisper when silence is detected
      3. POST the result to site_url/voice-result  (push)
         AND store it for GET /voice-status polling

    Request body (optional):
        { "language": "ar" }    # default: config language

    Response:
        { "session_id": "abc12345", "status": "listening" }
    """

    data     = request.get_json(silent=True) or {}
    language = data.get("language")

    sid = pipeline.start_voice_session(language=language)
    return jsonify({"session_id": sid, "status": "listening"})


@app.route("/exit-web-mode", methods=["POST"])
def exit_web_mode():
    """
    Called by pi_bridge after speak() completes to release the mic
    back to the wake-word pipeline.
    """
    pipeline.exit_web_mode()
    return jsonify({"status": "ok"})


@app.route("/voice-status", methods=["GET"])
def voice_status():
    """
    Poll the status of a voice session.

    Query param: session_id

    Response:
        {
            "session_id": "abc12345",
            "status":     "listening" | "transcribing" | "done" | "error" | "idle",
            "text":       "what the user said"   # only set when status == "done"
        }
    """
    sid = request.args.get("session_id", "")
    try:
        return jsonify(pipeline.get_voice_status(sid))
    except Exception :
        print("get voice status failed")    


# ── LEGACY: blocking transcribe (kept for backward compat) ─────────────────

@app.route("/transcribe", methods=["POST"])
def transcribe():

    data     = request.get_json(silent=True) or {}
    timeout  = float(data.get("timeout", 20.0))
    language = data.get("language")

    pipeline.enter_web_mode()

    try:
        print(f"[API] /transcribe START (timeout={timeout}s)")
        text = pipeline.stt.transcribe_once(timeout=timeout, language=language)
        print(f"[API] /transcribe RESULT: '{text}'")
        return jsonify({"text": text})

    except Exception as e:
        print(f"[API] /transcribe ERROR: {e}")
        return jsonify({"error": str(e), "text": ""}), 500

    finally:
        pipeline.exit_web_mode()
        print("[API] /transcribe END")


@app.route("/tts", methods=["POST"])
def tts():
    return _do_speak()


@app.route("/speak", methods=["POST"])
def speak():
    return _do_speak()


def _do_speak():
    """Speak arbitrary text — used by the operator 'Say this' input."""
    data = request.get_json(silent=True) or {}
    text = data.get("text", "").strip()

    if not text:
        return jsonify({"error": "Missing or empty 'text'"}), 400

    lang = data.get("lang", pipeline.cfg.language)

    print(f"[TTS] Speaking: '{text[:60]}'")
    pipeline.tts.speak(text, lang)
    print(f"[TTS] Done.")

    return jsonify({"status": "spoken", "text": text, "lang": lang})

@app.route('/motor', methods=['POST'])
def motor():
    stickX = request.form.get('stickX')
    stickY = request.form.get('stickY')

    if stickX is None or stickY is None:
        return jsonify({'status': 'Error', 'msg': 'Missing data'})

    xVal = int(float(stickX) * 100)
    yVal = int(float(stickY) * 100)

    if pipeline.commands.is_connected():
        pipeline.commands.send_command("X" + str(xVal))
        pipeline.commands.send_command("Y" + str(yVal))
        return jsonify({'status': 'OK'})

    return jsonify({'status': 'Error', 'msg': 'Arduino not connected'})

@app.route('/servoControl', methods=['POST'])
def servoControl():

    servo = request.form.get('servo')
    value = request.form.get('value')

    if servo is None or value is None:
        return jsonify({'status': 'Error', 'msg': 'Missing data'})

    if pipeline.commands.is_connected():
        pipeline.commands.send_command(servo + value)
        return jsonify({'status': 'OK'})

    return jsonify({'status': 'Error', 'msg': 'Arduino not connected'})

@app.route('/settings', methods=['POST'])
def settings():

    try:

        setting_type = request.form.get('type')
        val = request.form.get('val')

        # ───────── LANGUAGE ─────────

        if setting_type == "language":

            pipeline.cfg.language = val
            pipeline.cfg.save()

            return jsonify({
                'status': 'OK'
            })


        # ───────── VOLUME ─────────

        if setting_type == "volume":

            volume = int(val)

            pipeline.cfg.volume = volume

            os.system(f"amixer set Master {volume * 10}%")

            pipeline.cfg.save()

            return jsonify({
                'status': 'OK'
            })


        return jsonify({
            'status': 'Error',
            'msg': 'Unknown setting type'
        })

    except Exception as e:

        return jsonify({
            'status': 'Error',
            'msg': str(e)
        })
        



if __name__ == "__main__":
    print("[Main] Connecting Arduino...")

    try:
        if pipeline.commands.connect(port=0):
            print("[Main] Arduino connected")
        else:
            print("[Main] Arduino not found (continuing without it)")
    except Exception as e:
        print(f"[Main] Arduino error: {e}")

    pipeline.start()

    print("=" * 60)
    print("  WALL-E Pi App running on port 5000")
    print("=" * 60)

    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)