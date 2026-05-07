
import time

import requests
from flask import current_app


_MIN_LISTEN_TIMEOUT = 20.0
_POLL_INTERVAL      = 0.5   # seconds between /voice-status polls
_WHISPER_HEADROOM   = 120


def speak(text: str, lang: str = "en") -> bool:
    if not text or not text.strip():
        return True

    pi = _pi_url()
    try:
        r = requests.post(
            f"{pi}/speak",
            json={"text": text, "lang": lang},
            timeout=90,
        )
        ok = r.ok
    except requests.RequestException as e:
        current_app.logger.error(f"[Pi] speak failed: {e}")
        ok = False

    try:
        requests.post(f"{pi}/exit-web-mode", timeout=5)
    except requests.RequestException as e:
        current_app.logger.warning(f"[Pi] exit-web-mode failed: {e}")

    return ok


def listen(timeout: float = 90.0, language: str = None) -> str:
    safe_timeout = max(timeout, _MIN_LISTEN_TIMEOUT)
    if safe_timeout != timeout:
        current_app.logger.warning(
            f"[Pi] listen() timeout {timeout}s is too short — "
            f"raised to {safe_timeout}s"
        )

    pi = _pi_url()


    payload = {}
    if language:
        payload["language"] = language

    try:
        r = requests.post(f"{pi}/start-voice", json=payload, timeout=10)
        r.raise_for_status()
        session_id = r.json().get("session_id", "")
        if not session_id:
            current_app.logger.error("[Pi] /start-voice returned no session_id")
            return ""
        current_app.logger.info(f"[Pi] Voice session started: {session_id}")
    except requests.RequestException as e:
        current_app.logger.error(f"[Pi] /start-voice failed: {e}")
        return ""

    poll_deadline = time.monotonic() + safe_timeout + _WHISPER_HEADROOM

    while time.monotonic() < poll_deadline:
        time.sleep(_POLL_INTERVAL)
        try:
            r = requests.get(
                f"{pi}/voice-status",
                params={"session_id": session_id},
                timeout=5,
            )
            r.raise_for_status()
            data   = r.json()
            status = data.get("status", "unknown")

            if status == "done":
                text = data.get("text", "").strip()
                current_app.logger.info(f"[Pi] listen() got: '{text[:80]}'")
                return text

            if status in ("error", "unknown"):
                current_app.logger.error(f"[Pi] Voice session {session_id} ended with status: {status}")
                return ""

            # status == "listening" or "transcribing" → keep polling

        except requests.RequestException as e:
            current_app.logger.warning(f"[Pi] /voice-status poll failed: {e}")

    current_app.logger.error(
        f"[Pi] listen() timed out after {safe_timeout + _WHISPER_HEADROOM}s "
        f"(speech={safe_timeout}s + whisper headroom={_WHISPER_HEADROOM}s, "
        f"session {session_id})"
    )
    return ""


def _pi_url() -> str:
    url = current_app.config.get("PI_URL", "").rstrip("/")
    if not url:
        raise RuntimeError(
            "PI_URL is not set in config. "
            "Add PI_URL = 'http://<PI_IP>:5000' to your site server config."
        )
    return url
