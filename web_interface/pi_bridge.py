import requests
from flask import current_app




def speak(text: str, lang: str = "en") -> bool:
    """
    Send text to the Pi's TTS and BLOCK until it finishes speaking.
    The Pi /speak endpoint must be synchronous (wait for eSpeak to finish)
    for the listen() call after it to work correctly.
    """
    try:
        r = requests.post(
            f"{_pi_url()}/speak",
            json={"text": text, "lang": lang},
            timeout=60,   # eSpeak on a long sentence can take a few seconds
        )
        return r.ok
    except requests.RequestException as e:
        current_app.logger.error(f"[Pi] speak failed: {e}")
        return False


def listen(timeout: float = 15.0, language: str = None) -> str:
    """
    Arm the Pi's STT and wait for one utterance.

    timeout    — how long (seconds) to wait for the child to speak.
                 Passed to the Pi so it knows when to give up.
    http_wait  — we give the HTTP connection (timeout + 10) seconds,
                 which is always longer than the STT timeout so the
                 connection never dies before the Pi replies.
    """
    payload = {"timeout": timeout}
    if language:
        payload["language"] = language

    http_wait = timeout + 10   # always longer than STT timeout

    try:
        r = requests.post(
            f"{_pi_url()}/transcribe",
            json=payload,
            timeout=http_wait,
        )
        return r.json().get("text", "")
    except requests.RequestException as e:
        current_app.logger.error(f"[Pi] listen failed: {e}")
        return ""


def _pi_url() -> str:
    return current_app.config["PI_URL"].rstrip("/")
