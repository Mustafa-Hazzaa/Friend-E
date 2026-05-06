"""
Wall-E Web Interface - Configuration
"""

import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# ── Security ──────────────────────────────────────────────────────────────────
SECRET_KEY    = b'\xccCL\xb2&S\xcb\xfa&\x0e\x90\x03\xe7h5\x0f\x1e\r\xef\xd6 2\x05&'

# ── Server ────────────────────────────────────────────────────────────────────
APP_PORT  = 5000
APP_DEBUG = False
PI_IP = "192.168.43.221"
PI_URL = "http://192.168.43.221:5000"

# ── Hardware ──────────────────────────────────────────────────────────────────
ARDUINO_PORT       = "/dev/ttyACM0"
AUTOSTART_ARDUINO  = True
AUTOSTART_CAM      = True

# # ── Audio ─────────────────────────────────────────────────────────────────────
# SOUND_FOLDER      = os.path.join(BASE_DIR, "static/sounds/")
# SOUND_FORMAT      = "wav"
# AUDIOPLAYER_CMD   = ['aplay']
# ESPEAK_CMD        = ['espeak-ng', '-v', 'en', '-b', '1']

# ── File uploads ──────────────────────────────────────────────────────────────
UPLOAD_FOLDER      = os.path.join(BASE_DIR, "uploads")
MAX_CONTENT_LENGTH = 20 * 1024 * 1024   # 20 MB

# ── Blockly movement constants ────────────────────────────────────────────────
CODEBLOCK_MOTORPOWER = 0.8   # motor power for straight moves (0.0–1.0)
CODEBLOCK_MOTORSPEED = 17    # cm/s at CODEBLOCK_MOTORPOWER
CODEBLOCK_TURNPOWER  = 0.5   # motor power during turns
CODEBLOCK_TURNTIME   = 1.8   # seconds to complete a 90° turn at CODEBLOCK_TURNPOWER