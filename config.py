import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

SECRET_KEY    = b'\xccCL\xb2&S\xcb\xfa&\x0e\x90\x03\xe7h5\x0f\x1e\r\xef\xd6 2\x05&'

APP_PORT  = 5000
APP_DEBUG = False
PI_IP = "192.168.43.221"
PI_URL = "http://192.168.43.221:5000"



ARDUINO_PORT       = "/dev/ttyACM0"
AUTOSTART_ARDUINO  = True
AUTOSTART_CAM      = True



UPLOAD_FOLDER      = os.path.join(BASE_DIR, "uploads")
MAX_CONTENT_LENGTH = 20 * 1024 * 1024

CODEBLOCK_MOTORPOWER = 0.8
CODEBLOCK_MOTORSPEED = 17
CODEBLOCK_TURNTIME   = 1.8