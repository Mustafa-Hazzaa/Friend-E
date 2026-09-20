# Friend-E

**A bilingual, voice-driven Wall-E robot that tutors kids from their own PDFs — running local speech models on a Raspberry Pi.**

[![Repository](https://img.shields.io/badge/GitHub-Mustafa--Hazzaa%2FFriend--E-181717?logo=github)](https://github.com/Mustafa-Hazzaa/Friend-E)
[![Python](https://img.shields.io/badge/Python-3.10-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.1.3-000000?logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![Raspberry Pi](https://img.shields.io/badge/Raspberry%20Pi-5-A22846?logo=raspberrypi&logoColor=white)](https://www.raspberrypi.com/)
[![Arduino](https://img.shields.io/badge/Arduino-Nano%20ATmega328-00979D?logo=arduino&logoColor=white)](https://www.arduino.cc/)
[![Whisper](https://img.shields.io/badge/STT-faster--whisper-5A29E4)](https://github.com/SYSTRAN/faster-whisper)
[![openWakeWord](https://img.shields.io/badge/Wake%20Word-openWakeWord-FF6F00)](https://github.com/dscripka/openWakeWord)
[![Ollama](https://img.shields.io/badge/LLM-Ollama%20%7C%20qwen3%3A14b-000000)](https://ollama.com/)
[![Status](https://img.shields.io/badge/status-active%20development-yellow)]()

---

## Overview

Friend-E is a physical Wall-E robot that a child can talk to in Arabic or English, drive around with a gamepad, program with drag-and-drop blocks, and — the part that actually matters — hand a PDF to and get taught from it.

The robot says its own name back to you, listens for a wake word, transcribes what you said locally, sends it to an LLM, translates the reply back to your language, runs it through a filter chain that makes it sound like a small anxious robot, and plays it out of a USB speaker. No cloud STT. No cloud TTS for English. The only network dependency in the core loop is the LLM host, which can be a laptop on the same Wi-Fi.

The tutoring side reads a PDF, builds an embedding index over it, and drives four distinct study modes — summarize, quiz, Q&A, and teachback — all spoken out loud, all in the robot's voice. Every session gets written to disk as JSON, and a separate password-gated parent portal runs an LLM pass over that history to produce behavioural charts: curiosity score, emotional split, topic interests, and flagged concerns.

It's built as three cooperating processes — a Flask app server, a Flask runtime on the Pi, and an Arduino Nano holding the servos — because the Pi can run Whisper *or* be responsive, but not both while also driving seven servos on a timer.

---

## System Architecture

Three tiers, each with a hard boundary and a dumb protocol between them. This is deliberate: the Pi should never be blocked on the LLM, and the Arduino should never be blocked on anything.

```
┌──────────────────────────────────────────────────────────────────────┐
│  BROWSER                                                             │
│  Dashboard · PDF Tutor · Blockly · Parent Monitor · Gamepad          │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ HTTP + form posts / fetch
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│  APP SERVER  —  web_interface/  ·  Flask  ·  :5001                   │
│                                                                      │
│   auth.py      Flask-Login + SQLAlchemy (SQLite)                     │
│   pdf.py       4 tutor modes, RAG cache, session history writer      │
│   rag.py       MiniLM embeddings + in-memory cosine retrieval        │
│   website_AI.py Ollama client (qwen3:14b) + all system prompts       │
│   monitor.py   Parent portal, behavioural analysis, JSON cache       │
│   control.py   Motor / servo / TTS proxy → Pi                        │
│   pi_bridge.py speak() + listen() over the Pi's HTTP API             │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ HTTP  (PI_URL, default :5000)
                                │ /speak /start-voice /voice-status
                                │ /motor /servoControl /settings
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│  PI RUNTIME  —  Pi-Code/  ·  Flask  ·  :5000  ·  Python 3.10         │
│                                                                      │
│   stt_service.py       ONE mic stream → router → Whisper thread      │
│   wake_word_service.py openWakeWord ONNX, fed from that same stream  │
│   tts_service.py       Edge/Piper (AR) · Sherpa-ONNX (EN) · ffmpeg   │
│   translator_service.py MarianMT opus-mt ar⇄en, Google fallback      │
│   command_service.py   Queued serial writer, 115200 baud             │
│   picamera2_stream.py  MJPEG stream on :8080                         │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ USB serial · 115200 · "<char><number>\n"
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│  FIRMWARE  —  Pi-Code/wall-e/  ·  Arduino Nano ATmega328             │
│  7 servos via Adafruit PCA9685 · 2 DC motors · animation queue       │
└──────────────────────────────────────────────────────────────────────┘
```

Separately, the Pi posts transcribed English to a conversation server at `POST /respond` (see [The `/respond` contract](#the-respond-contract)).

### Tech Stack

| Layer | Technology | Version | Where |
|---|---|---|---|
| **Wake word** | openWakeWord (ONNX runtime) | 0.6.0 | `services/wake_word_service.py` |
| **STT** | faster-whisper (CTranslate2) | 1.2.1 / ct2 4.7.1 | `services/stt_service.py` |
| **VAD** | webrtcvad-wheels, energy-RMS fallback | 2.0.14 | `services/stt_service.py` |
| **TTS (English)** | sherpa-onnx VITS, fully offline | 1.13.0 | `services/tts_service.py` |
| **TTS (Arabic, online)** | edge-tts, voice `ar-SA-HamedNeural` | 7.2.8 | `services/tts_service.py` |
| **TTS (Arabic, offline)** | Piper, `arabic-emirati-female-model.onnx` | 1.4.2 | `services/tts_service.py` |
| **Arabic diacritization** | Mishkal (+ qalsadi, PyArabic, Tashaphyne) | 0.4.1 | `services/tts_service.py` |
| **Voice character** | ffmpeg `asetrate` + `atempo` + `aecho` | system | `services/tts_service.py` |
| **Translation** | MarianMT `opus-mt-ar-en` / `opus-mt-en-ar` | transformers 5.8.0 | `services/translator_service.py` |
| **Translation fallback** | deep-translator (Google), online only | — | `services/translator_service.py` |
| **LLM (tutor)** | Ollama · `qwen3:14b` · temp 0.3 · ctx 8192 | — | `web_interface/website_AI.py` |
| **LLM (conversation)** | Configurable: ollama / api / remote / mock | — | `models_layer/model_service.py` |
| **Embeddings** | sentence-transformers `all-MiniLM-L6-v2`, vendored | — | `web_interface/rag.py` |
| **Vector search** | NumPy in-memory, normalized dot product | numpy 2.2.6 | `web_interface/rag.py` |
| **PDF parsing** | PyMuPDF (`fitz`) | — | `web_interface/extract.py` |
| **Web framework** | Flask + Jinja2, blueprint-per-domain | 3.1.3 | `web_interface/` |
| **Auth** | Flask-Login, Werkzeug PBKDF2 hashing | — | `web_interface/auth.py` |
| **Database** | SQLite via Flask-SQLAlchemy | — | `web_interface/models.py` |
| **Block programming** | Blockly (Zelos renderer) + JS-Interpreter | bundled | `static/js/blockly/` |
| **Gamepad** | joypad.js over the Gamepad API | bundled | `static/js/main.js` |
| **Charts** | Chart.js | 4.4.1 (CDN) | `templates/monitor.html` |
| **UI** | Bootstrap 5, jQuery 3.7.1 | bundled | `templates/base.html` |
| **Serial** | pyserial, queued writer thread | 3.5 | `services/command_service.py` |
| **Firmware** | Arduino + Adafruit PWM Servo Driver | ^2.4.1 | `wall-e/src/wall-e.ino` |
| **Camera** | Picamera2 → MJPEG on `:8080` | — | `Pi-Code/picamera2_stream (2).py` |

### Why the mic stream is shared

The single most important design constraint on the Pi: **there is exactly one `sd.InputStream` in the whole system.**

An earlier version had `WakeWordService` and `STTService` each opening their own stream. On a Pi that produces device contention and, when Whisper is mid-inference, native-level crashes (`double free or corruption`). The fix is that `STTService` owns the stream and `WakeWordService` registers itself as a listener:

```python
self.stt  = STTService(cfg, on_text=self._on_transcription, on_timeout=self._on_stt_timeout)
self.wake = WakeWordService(cfg, on_detected=self._on_wake_word)
self.stt.register_wake_listener(self.wake.feed)
```

A router thread pulls every 16 kHz block off a queue and fans it out — always to the wake-word model, and additionally into the utterance buffer when STT is armed. The mic callback itself does nothing but decimate and enqueue, so the audio thread never blocks.

`arm_for_web()` returns `False` while Whisper is still busy rather than arming a second session, and `PipelineController.start_voice_session()` polls that for up to 120 s before giving up. That guard is what keeps the native crash from coming back.

---

## Feature Deep-Dive

### AI & Voice

**Wake word.** openWakeWord runs the ONNX inference framework over the shared audio stream. It ships with `hey_jarvis_v0.1.onnx`, but the robot's name is not hardcoded anywhere — `WakeWordService` prefers a local `model_path` and only falls back to a named auto-download:

```python
model_path = self._cfg.get("model_path", "")
if model_path and os.path.exists(model_path):
    wakeword_arg         = [model_path]
    self._prediction_key = os.path.splitext(os.path.basename(model_path))[0]
else:
    wakeword_arg         = [self._cfg["model"]]
    self._prediction_key = self._cfg["model"]
```

To rename the robot, train a model with openWakeWord's custom-model training notebook, drop the `.onnx` into `Pi-Code/models/`, and point `wake_word.model_path` at it. Detection is gated by `threshold` (default 0.3) and a `cooldown_seconds` window so a single utterance can't retrigger. See [Renaming the robot](#renaming-the-robot).

**Barge-in.** If the wake word fires while the robot is mid-sentence, `_on_wake_word` calls `tts.stop()` and clears the busy flag, so you can interrupt it instead of waiting for it to finish.

**Speech-to-text.** faster-whisper (`medium`, `int8`, CPU) behind a webrtcvad gate. The mic runs at 48 kHz and is decimated to 16 kHz for both the wake model and Whisper. An utterance ends when VAD reports `silence_duration` seconds of quiet *and* an RMS gate (`db_threshold`, default −35 dBFS) confirms something loud actually happened — that second check is what stops fan noise from being sent to Whisper as a 4-second empty clip.

**Dual-language handling.** Friend-E thinks in English and speaks in whatever you spoke. `TranslatorService` exposes exactly two methods and hides the routing:

```python
english_input = self.translator.to_english(raw_text)   # AR → EN before the model
...
final_text = self.translator.to_language(resp_text, lang)  # EN → AR before TTS
```

Arabic is detected by Unicode range (`\u0600–\u06FF` and friends), so English input passes through at zero cost. Mixed-script input is split on the Arabic runs and translated piecewise, preserving the Latin parts in place. Both directions run local MarianMT models with `functools.lru_cache(maxsize=512)` on top, falling back to Google via deep-translator only when the local model failed to load *and* the network is up.

**The Wall-E voice.** The robotic character isn't a voice model — it's a deterministic ffmpeg filter chain applied after synthesis, so it works identically across all three TTS backends:

```python
# English
"asetrate=22050*1.15,aresample=22050,atempo=0.70,aecho=0.7:0.6:60:0.15"
# Arabic (sr = 24000 online / 22050 offline)
f"asetrate={sr}*1.33,aresample={sr},atempo=0.75,aecho=0.7:0.6:100:0.15"
```

`asetrate` pitches it up, `atempo` drags it back below real time, and `aecho` adds the small-speaker-in-a-metal-box tail. Set `tts.effect` to `false` in `config.json` to hear the raw voice.

**Arabic synthesis** tries edge-tts first (checked with a 2-second DNS probe to `8.8.8.8:53`) and falls back to Piper offline. Before Piper runs, text goes through Mishkal `tashkeel` to add diacritics — undiacritized Arabic makes Piper mispronounce almost everything. Mishkal uses SQLite internally and SQLite connections can't cross threads, so instances are created lazily per thread via `threading.local()`. Long Arabic strings are split on sentence punctuation and conjunctions (`و`, `أو`, `ثم`, `لكن`, `حيث`) into ≤12-word chunks with 150 ms of silence between them, because Piper degrades badly on long inputs.

**Personality.** All prompts share a `BASE_PERSONA` block in `website_AI.py` that pins the character: short bouncy sentences, analogies drawn from toys and animals, technical terms always named and then immediately explained, no markdown, and a hard rule that an Arabic document gets an Arabic response.

### Educational AI Tutor

Upload a PDF at `/pdf` and four modes light up. PyMuPDF extracts per-page text, control characters get stripped, hyphenated line breaks are rejoined, and pages with zero extractable words are flagged (scanned PDFs raise a clear error — there's no OCR yet).

The retrieval layer is deliberately small. `RAGStore` groups pages into ~400-word chunks, encodes them with `all-MiniLM-L6-v2` (vendored at `web_interface/models/`, loaded with `local_files_only=True`), and stores a single normalized NumPy matrix. Because embeddings are L2-normalized, cosine similarity is just a dot product:

```python
scores      = self.embeddings @ query_vec
top_indices = np.argsort(scores)[::-1][:top_k]
```

No external vector database, no Chroma, no FAISS. For a single textbook chapter on a laptop this is the right call — the whole index is a few hundred KB and rebuilding it is cheaper than managing a server. Stores are cached per filename in `_rag_cache`, and `POST /pdf/clear` evicts one.

| Mode | Endpoint (text / voice) | Retrieval | Behaviour |
|---|---|---|---|
| **Summarize** | `/pdf/summarize` | Map-reduce, *not* top-k | ≤1500 words goes to the model whole. Longer documents are summarized chunk-by-chunk (1–2 sentences each), combined, then retold in character in ≤10 sentences. |
| **Quiz** | `/pdf/quiz/generate` · `/pdf/quiz/run` | Full chunk sweep | Batches of 2 chunks, 2 questions per chunk, `format="json"` at temperature 0, deduplicated by question text, shuffled, truncated to the requested count. 1–20 questions, easy/medium/hard. |
| **Q&A** | `/pdf/qa` · `/pdf/qa/run` | `top_k=4` | Answers strictly from retrieved excerpts; prompt forces an in-character "I couldn't find that one" rather than inventing an answer. |
| **Teachback** | `/pdf/teachback` · `/pdf/teachback/run` | `top_k=7` | Child explains the material back; model returns praise, corrections, and encouragement in ≤7 sentences, with follow-up questions explicitly banned so the loop closes. |

The `/run` variants are the interesting ones: they drive the whole exchange through the robot. `/pdf/quiz/run` speaks each question, calls `listen(timeout=30.0)`, grades the spoken answer, speaks a randomly chosen reaction, reads the explanation, and finally announces the score — all server-side, with the browser just kicking it off.

**Answer grading** is a two-stage cascade that avoids paying for an LLM call on the easy cases:

```python
sim = float(emb_student @ emb_correct)
if sim >= 0.90: return "MATCH"
if sim <= 0.70: return "NO_MATCH"
# ambiguous band → ask the LLM twice, require agreement
r1 = self._call(CONSISTENCY_SYSTEM_PROMPT, prompt)
r2 = self._call(CONSISTENCY_SYSTEM_PROMPT, prompt)
return r1.strip() if r1.strip() == r2.strip() else "NO_MATCH"
```

Only the 0.70–0.90 band reaches the model, and a disagreement between the two passes resolves to `NO_MATCH` rather than a coin flip.

Every mode writes a timestamped JSON record into `uploads/history/` through `save_pdf_session()`. That directory is the sole input to the parent portal.

### Robotics Control

**Dashboard** (`/dashboard`) shows the live MJPEG feed from `http://<PI_IP>:8080/stream.mjpg` alongside the drive and servo controls.

**Driving.** The virtual joystick and the gamepad both converge on the same path: the browser posts `stickX`/`stickY` in the range −1.0…1.0 to `/control/motor`, the app server forwards to the Pi with a deliberately tight `timeout=0.2` (a stale steering packet is worse than a dropped one), and the Pi scales to ±100 and emits two serial commands:

```python
pipeline.commands.send_command("X" + str(xVal))   # turn
pipeline.commands.send_command("Y" + str(yVal))   # drive
```

`ArduinoDevice` never writes to the port from the request thread. Commands go onto a `Queue` and a daemon thread drains it, so a wedged USB device can't stall Flask.

**Servos.** Seven channels on a PCA9685, addressed by a single letter: `G` head rotation, `T` neck top, `B` neck bottom, `E` eye left, `U` eye right, `L` arm left, `R` arm right. Values are 0–100 and the firmware maps them onto per-servo calibration pairs, so mechanical trim lives in `wall-e.ino` and nowhere else:

```cpp
int preset[][2] = {{410,120},   // head rotation
                   {532,178},   // neck top
                   {120,310},   // neck bottom
                   {465,271},   // eye right
                   {278,479},   // eye left
                   {340,135},   // arm left
                   {150,360}};  // arm right
```

Any explicit servo command sets `autoMode = false` and clears the animation queue, so manual input always wins over an idle animation mid-playback.

**Block programming** (`/programming`) is Blockly with the Zelos renderer and a dark theme. Generated JavaScript runs inside JS-Interpreter rather than the page, stepped by a timer, with `STATEMENT_PREFIX` wired to `highlightBlock` so the executing block lights up as it runs. The sandbox only exposes four functions — `blockMoveMotor`, `blockServo`, `playTTS`, `blockAudio`, plus `waitForSeconds` — which is the whole security model: a child's program can't touch the DOM or the network directly.

Distance and turn blocks are time-based, not encoder-based. `move` divides the requested centimetres by `CODEBLOCK_MOTORSPEED` to get a duration; `turn` uses `CODEBLOCK_TURNTIME` for 90° and half that for 45°. Both constants live in `config.py` and want calibrating against your own floor surface.

**Firmware.** `wall-e.ino` parses `<char><number>\n` off the serial line (max 5 characters per token) and dispatches on the first character. Motion commands scale to PWM by `× 2.55`; servo commands interpolate into the calibration table. Animations are queued as `{timer, servos[7]}` structs in a 40-slot ring buffer, and servos power down via `SERVO_ENABLE_PIN` after `SERVO_OFF_TIME` (6 s) of inactivity to stop them buzzing and cooking themselves.

### Parent & Safety Portal

`/monitor` is gated behind a second password prompt — the parent re-enters the account password, `check_password_hash` verifies it, and `session["monitor_active"]` is set. Every data endpoint checks that flag independently and returns 401 without it, so the child can't reach the reports by typing the URL.

| Endpoint | Method | Purpose |
|---|---|---|
| `/monitor-login` | POST | Verify parent password, set the session flag |
| `/sign-out-monitor` | POST | Drop the flag |
| `/get-sessions` | GET | All sessions, newest first, with message counts |
| `/get-session/<filename>` | GET | Full transcript of one session |
| `/analyze-child` | GET | Last cached report (`uploads/last_analysis.json`) |
| `/analyze-child-fresh` | POST | Re-run the analysis over all history |

The analysis pass is prompted to emit chart-ready numbers rather than prose, and the schema is enforced hard in the system prompt (arrays must be arrays, never null, never omitted):

```json
{
  "summary": "...",
  "curiosity_level": 0,
  "emotion":            { "positive": 0, "neutral": 0, "confused": 0 },
  "interests":          { "topic": 0 },
  "behavioral_metrics": { "repetition_level": 0, "engagement_level": 0, "learning_depth": 0 },
  "concerns": [],
  "recommendations": []
}
```

Chart.js renders the emotional split, weighted interests, and the three behavioural metrics. `concerns` is the safety-relevant field: the prompt asks the model to flag confusion loops, repetition, frustration signals, low engagement, and anything a child shouldn't be asking about. If the model returns unparseable JSON, `analyze_child` degrades to a plain-text summary with empty arrays instead of raising.

Reports are cached to disk so opening the portal doesn't trigger a fresh multi-thousand-token pass every time; `/analyze-child-fresh` is the explicit refresh. User messages are concatenated and truncated to 6000 characters before analysis.

---

## Getting Started

### Prerequisites

**Hardware**

| Part | Notes |
|---|---|
| Raspberry Pi 4 / 5 | 4 GB minimum. Whisper `medium` at `int8` is the constraint; drop to `small` or `base` on a Pi 4. |
| Arduino Nano (ATmega328) | Any Nano clone. Upload speed is set to 57600 for the old bootloader. |
| Adafruit PCA9685 | 16-channel PWM driver, 7 channels used. |
| 2 × DC motors + driver | Wired to the pins in `wall-e.ino`. |
| 7 × servos | Head rotation, neck top/bottom, both eyes, both arms. |
| USB microphone | Matched by the substring `"USB2.0 Device"`. |
| USB speaker | Matched by the substring `"USB PnP Sound Device"`. |
| Pi Camera | Optional, drives the MJPEG feed. |
| A laptop | Runs the app server and the LLM. The Pi does not run the LLM. |

> **The device-name match is literal.** `stt_service.py` and `tts_service.py` scan `sd.query_devices()` for those exact substrings and raise `RuntimeError` at startup if nothing matches. Run
> `python -c "import sounddevice as sd; print(sd.query_devices())"`
> and edit `mic_name` / `self._output_device_name` to match your hardware before first run.

**Software**

- Python 3.10 on the Pi (`Pi-Code/.python-version` pins 3.10.0)
- Python 3.10+ on the laptop
- `ffmpeg` on the Pi — the voice effect shells out to it, and without it every `speak()` raises
- `espeak-ng` data, already vendored at `Pi-Code/models/espeak-ng-data`
- [Ollama](https://ollama.com/) on the laptop, with `ollama pull qwen3:14b`
- [PlatformIO](https://platformio.org/) for the firmware
- ALSA dev headers for `sounddevice`: `sudo apt install libportaudio2 portaudio19-dev`

### 1. Clone

```bash
git clone https://github.com/Mustafa-Hazzaa/Friend-E.git
cd Friend-E
```

> Heads-up: the repository currently has `Pi-Code/venv310/` committed, which is most of its ~26,000 files. Add it to `.gitignore` and `git rm -r --cached Pi-Code/venv310` before you do any serious work in here.

### 2. App server (laptop)

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install flask flask-sqlalchemy flask-login werkzeug \
            ollama sentence-transformers PyMuPDF numpy requests
```

There is no `requirements.txt` yet. That list is what `web_interface/` actually imports.

### 3. Pi runtime

```bash
cd Pi-Code
python3.10 -m venv venv310
source venv310/bin/activate

pip install flask numpy scipy sounddevice soundfile \
            faster-whisper webrtcvad-wheels openwakeword \
            piper-tts sherpa-onnx edge-tts mishkal \
            transformers torch sentencepiece sacremoses \
            deep-translator pyserial requests
```

### 4. Firmware

```bash
cd Pi-Code/wall-e
pio run -t upload
```

Confirm it's alive at 115200 baud — the sketch echoes every command it parses back over serial, so typing `G50` should print `G50` and centre the head.

### Configuration

Two files, one per tier. There is no `.env` loader wired up today, so treat `config.py` as the app-server config and `config.json` as the Pi config.

#### `config.py` — app server

```python
SECRET_KEY = b'...'                            # see the security note below
APP_PORT   = 5000
APP_DEBUG  = False

PI_IP  = "192.168.43.221"                      # ← your Pi's LAN address
PI_URL = "http://192.168.43.221:5000"          # ← must match PI_IP

ARDUINO_PORT      = "/dev/ttyACM0"
AUTOSTART_ARDUINO = True
AUTOSTART_CAM     = True

UPLOAD_FOLDER      = os.path.join(BASE_DIR, "uploads")
MAX_CONTENT_LENGTH = 20 * 1024 * 1024          # 20 MB PDF ceiling

CODEBLOCK_MOTORPOWER = 0.8                     # Blockly move/turn calibration
CODEBLOCK_MOTORSPEED = 17                      # cm per second
CODEBLOCK_TURNTIME   = 1.8                     # seconds for 90°
```

> **Security.** `create_app()` reads the session key from the environment and only falls back to a literal default:
> ```python
> app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")
> ```
> The `SECRET_KEY` in `config.py` is loaded into `app.config` but does **not** become the session key. Always export a real one before running anything reachable from outside localhost:
> ```bash
> export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
> ```
> And rotate the committed literal in `config.py` — it's in the public git history.

#### `Pi-Code/utils/config.json` — Pi runtime

```jsonc
{
  "language": "en",                             // "en" | "ar", flipped from /settings
  "wake_word": {
    "model": "hey_jarvis",
    "model_path": "models/hey_jarvis_v0.1.onnx", // ← point here to rename the robot
    "threshold": 0.3,                            // lower = more sensitive, more false fires
    "cooldown_seconds": 1.0,
    "post_detect_delay": 0.5
  },
  "stt": {
    "model_size": "medium",                      // "base"/"small" on a Pi 4
    "device": "cpu",
    "compute_type": "int8",
    "sample_rate": 48000,                        // mic rate, decimated to 16 kHz
    "silence_duration": 1.0,
    "vad_aggressiveness": 1,                     // 0–3
    "db_threshold": -35,                         // RMS gate, dBFS
    "beam_size": 5
  },
  "model": {
    "provider": "remote",                        // remote | ollama | api | mock
    "convo_url": "http://<LAPTOP_IP>:5001",      // wake-word conversations
    "site_url":  "http://<LAPTOP_IP>:5001",      // dashboard-initiated turns
    "timeout_seconds": 1000
  },
  "translation": {
    "ar_to_en_model_path": "models/opus-mt-ar-en",
    "en_to_ar_model_path": "models/opus-mt-en-ar"
  },
  "tts": {
    "edge_voice_ar": "ar-SA-HamedNeural",
    "piper_ar_model": "models/arabic-emirati-female-model.onnx",
    "sherpa_en_model": "models/model.onnx",
    "sherpa_en_tokens": "models/tokens.txt",
    "sherpa_en_data_dir": "models/espeak-ng-data",
    "sample_rate": 48000,
    "effect": true                               // false = no Wall-E voice filter
  }
}
```

> `convo_url` and `site_url` must **not** point at port 5000 — that's the Pi app itself, which has no `/respond`. `PipelineController._validate_urls()` prints a loud warning if you do it anyway, and `_check_servers()` pings `/health` on both at startup.

#### `web_interface/rag.py` — remove the hardcoded cache path

Line 4 pins the Hugging Face cache to a Windows user directory:

```python
os.environ["HF_HOME"] = r"C:\Users\musta\.cache\huggingface"
```

Delete it or set `HF_HOME` in your environment. The MiniLM model is vendored and loaded with `local_files_only=True`, so nothing is downloaded — but this line still breaks on Linux and macOS.

### Running it

Three terminals, in this order.

**1 — LLM host (laptop)**
```bash
ollama serve
ollama run qwen3:14b       # first run pulls ~9 GB
```

**2 — App server (laptop)**
```bash
export SECRET_KEY="..."
python main.py             # http://0.0.0.0:5001
```

**3 — Pi runtime (Pi)**
```bash
cd Pi-Code
source venv310/bin/activate
python main.py             # http://0.0.0.0:5000
```

Then open `http://<LAPTOP_IP>:5001`, create an account, and you land on the dashboard.

Check the wiring before anything else:

```bash
curl http://<PI_IP>:5000/health
# {"status":"ok","language":"en","busy":false,"mode":"site","voice_status":"idle"}

curl http://<LAPTOP_IP>:5001/health
# good
```

### The `/respond` contract

The Pi posts transcribed, translated-to-English text to `{convo_url|site_url}/respond` and expects a small JSON envelope back. **That conversation server is not in this repository yet** — `Pi-Code/main.py` documents the contract and warns on 404, but you need to stand it up yourself (or set `"provider": "mock"` in `config.json` to exercise the full wake-word → STT → TTS loop without it).

Request:
```json
{ "text": "how far away is the moon", "image_b64": null }
```

Answer response — spoken through the robot:
```json
{ "type": "answer", "response": "Ooooh! The moon is really really far..." }
```

Command response — forwarded to the Arduino as `<Action><value>` tokens:
```json
{ "type": "command",
  "data": [ { "Action": "Y", "value": 100 }, { "Action": "Y", "value": 0 } ] }
```

The server should also expose `GET /health` so the Pi's startup check succeeds.

---

## Controls & Modes Guide

### Voice

| Action | How |
|---|---|
| Start a conversation | Say the wake word. Mode flips to `convo` for one turn, then resets to `site`. |
| Interrupt the robot | Say the wake word again — `tts.stop()` fires immediately. |
| Switch language | `/settings` → English / Arabic. Persists to `config.json` via `cfg.save()`. |
| Adjust volume | `/settings` slider, 0–10. Shells out to `amixer set Master <n*10>%`. |
| No speech detected | STT retries once, then resets to idle. |

### Renaming the robot

1. Train a model with [openWakeWord's custom model notebook](https://github.com/dscripka/openWakeWord) — synthetic samples are enough for a two-syllable name.
2. Copy the `.onnx` into `Pi-Code/models/`.
3. Set `wake_word.model_path` to it. The prediction key is derived from the filename, so `friend_e.onnx` must be the model that predicts `friend_e`.
4. Tune `threshold`. Start at 0.5 and walk it down until it triggers reliably; below ~0.3 expect false fires from background speech.
5. Restart the Pi runtime.

### Gamepad

Connect any controller and press a button — the browser fires `gamepadconnected` and `joypad.js` takes over. Axis deadzone is 0.2 and movement is pushed at 100 ms intervals. Disconnecting sends a zero-movement packet so the robot stops rather than coasting.

| Input | Action |
|---|---|
| Left stick | Drive and turn |
| A / Cross | Sad eyes |
| B / Circle | Eyes right |
| X / Square | Eyes left |
| Y / Triangle | Eyes neutral |
| LB / RB | Raise left / right arm |
| LT / RT | Lower left / right arm |
| L3 | Arms back to neutral |
| R3 | Head back to neutral |
| Back / Share | Toggle automatic servo animation mode |
| D-pad left | Random sound |
| D-pad right | Random servo animation |

### Block programming

Open `/programming`. Drag blocks under **Start**, then run. Available blocks:

| Block | Generates | Notes |
|---|---|---|
| Move | `blockMoveMotor(0.0, ±power)` + wait + stop | Distance in cm ÷ `CODEBLOCK_MOTORSPEED` |
| Turn | `blockMoveMotor(±power, 0.0)` + wait + stop | 90° or 45°, timed by `CODEBLOCK_TURNTIME` |
| Servo | `blockServo('<code>', angle)` | One of `G T B L R E U`, 0–100 |
| Servo Presets | `blockServo('<preset>', 0)` | Head up/down/neutral, arms, eyes, sad eyes |
| Speak | `playTTS(text)` | Routed through `/control/tts` → Pi → speaker |
| Audio | `blockAudio(clip)` | Plays a named clip |
| Wait | `waitForSeconds(n)` | 0–600 s |
| Stop | `blockMoveMotor(0.0, 0.0)` | Halt |

Programs save and load as `.xml` workspace files through the file picker.

### AI Tutor

1. Go to `/pdf` and upload. The response reports how many chunks were indexed — if it's 0, the PDF is scanned and you'll need OCR first.
2. Four buttons become active:
   - **Summarize** — speaks a summary of the whole document.
   - **Quiz** — opens a modal: pick 1–20 questions and easy / medium / hard, then the robot asks each one aloud, listens for 30 s, grades, and reads the explanation.
   - **Q&A** — the robot says it's ready, listens for 90 s, and answers from the document only.
   - **Teachback** — the robot asks you to explain what you learned, listens for 90 s, then gives specific praise and corrections.
3. Everything lands in `uploads/history/` as timestamped JSON.

`POST /pdf/clear` with `{"filename": "..."}` drops a cached index if you've replaced a file with the same name.

### Parent portal

Open `/monitor`, enter the account password, and you get session history plus the generated report. Hit refresh to re-run the analysis over everything in `uploads/history/`; otherwise the cached `uploads/last_analysis.json` is served.

---

## Known Issues

Honest list, current as of this commit.

- **`rag.py` never imports `SentenceTransformer` at module scope.** The import sits inside the `if __name__ == "__main__"` block, so `_get_model()` raises `NameError` on first call. Move `from sentence_transformers import SentenceTransformer` to the top of the file.
- **History path casing.** `pdf.py` writes to `<UPLOAD_FOLDER>/history`, `monitor.py` reads `uploads/History`. This works on Windows and silently returns nothing on Linux and macOS. Pick one spelling — and make `monitor.py` use `current_app.config["UPLOAD_FOLDER"]` instead of a relative path.
- **`ConfigManager` has no `volume` property.** `/settings` sets `pipeline.cfg.volume`, which lands on the instance rather than in `_raw`, so `cfg.save()` never persists it. The `amixer` call still works; only persistence is missing.
- **`web_interface/arduino.py` is a mock** that does `from venv import logger`. Real serial goes through the Pi (`Pi-Code/services/command_service.py`); the app server never opens a port. The mock's hardcoded `battery_level = "75"` is what the UI displays.
- **Legacy routes in `main.js`.** `/arduinoConnect`, `/arduinoStatus`, `/animate`, and `/audio` are called by the frontend but not implemented on the app server — leftovers from the upstream interface. Those buttons fail silently.
- **Root-level `AI.py`, `STT.py`, `wake_word.py`** are early standalone prototypes, superseded by `Pi-Code/services/`. `train.py` is a two-line CUDA check. Safe to delete.
- **`uploads/` and `*.db` are gitignored**, so history and accounts are local to each install. There's no backup or migration path yet.
- **No CSRF protection** on the form posts, and `/monitor`'s view route isn't `@login_required` (its data endpoints are individually guarded, so nothing leaks, but the page renders for anonymous visitors).

## Roadmap

Not built yet — listed so nobody goes looking for them in the code:

- **Interactive spoken games.** The tutor covers study modes; guessing games, riddles, and story play are next.
- **Multi-profile support.** The `User` model is a single flat account (`username`, `email`, `password_hash`, `avatar`). Sibling profiles with per-child history and separate parent accounts need a schema change and a `child_id` on every history record.
- **Wake-word UI.** Renaming the robot works today, but only by editing `config.json`. It belongs in `/settings`.
- **OCR for scanned PDFs.** `extract.py` raises a clear error; wiring in Tesseract would close the gap.
- **The conversation server.** The `/respond` contract is documented above but the implementation lives outside this repo.
- **`requirements.txt` / `pyproject.toml`** for both tiers.

## Contributing

Issues and pull requests are welcome, particularly on the items above.

1. Fork and branch off `main`.
2. Keep the tier boundaries intact — the app server talks to the Pi over HTTP, the Pi talks to the Arduino over serial, and neither reaches across.
3. New settings go in `config.py` or `config.json`, not inlined in code.
4. New LLM providers subclass `BaseModelService`, implement `generate()`, and get a case in `ModelServiceFactory.create()`. Nothing in the pipeline should change.
5. If you touch the audio path, test wake word, dashboard voice, and a full `/pdf/quiz/run` — the mic-sharing logic is where the subtle bugs live.
6. Note your hardware in the PR. Servo calibration and motor timing are rig-specific.

## License

No license file is present in the repository, which means default copyright applies and others have no rights to use, modify, or redistribute the code. If you intend this to be open source, add a `LICENSE` — MIT is the usual choice for a project like this, and it's compatible with the bundled components below.

## Acknowledgements

- **[Simon Bluett](https://wired.chillibasket.com/3d-printed-wall-e/)** — the original Wall-E robot build, firmware, and web interface. `wall-e.ino`, `MotorController.hpp`, `Queue.hpp`, and `joystick.js` derive from that project.
- **dkrey** — the Blockly integration (`automation.js`, `automation_blocks.js`, `automation_toolbox.js`), February 2024.
- **[openWakeWord](https://github.com/dscripka/openWakeWord)** by David Scripka.
- **[faster-whisper](https://github.com/SYSTRAN/faster-whisper)** by SYSTRAN, on CTranslate2.
- **[Piper](https://github.com/rhasspy/piper)** and **[sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)** for offline synthesis.
- **[Mishkal](https://github.com/linuxscout/mishkal)** by Taha Zerrouki, for Arabic diacritization.
- **Helsinki-NLP** for the [opus-mt](https://huggingface.co/Helsinki-NLP) translation models.
- **[Blockly](https://developers.google.com/blockly)** and **JS-Interpreter** by Neil Fraser.
