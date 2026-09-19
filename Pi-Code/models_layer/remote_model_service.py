"""
RemoteModelService — runs on the RASPBERRY PI.

Sends English text to the laptop's Flask server via HTTP POST,
returns the AI's English response.

Drop-in replacement for OllamaModelService — same interface,
zero changes to the pipeline.

Configure in config.json:
    "model": {
        "provider":         "remote",
        "remote_url":       "http://192.168.1.42:8000",
        "timeout_seconds":  30
    }

JSON sent to server:
    {
      "text":      "Hello",
      "image_b64": null
    }

JSON received:
    {
      "response": "Beep boop! Hi there."
    }
"""

import requests
from typing import Optional

from utils.config_manager import ConfigManager
from models_layer.model_service import BaseModelService


class RemoteModelService(BaseModelService):

    def __init__(self, cfg: ConfigManager):
        self._url     = cfg.model["remote_url"].rstrip("/")
        self._timeout = cfg.model.get("timeout_seconds", 30)
        print(f"[Model] Remote mode — server: {self._url}")
        self._check_connection()

    def _check_connection(self):
        """Ping the laptop server at startup."""
        try:
            r = requests.get(f"{self._url}/health", timeout=3)
            data = r.json()
            print(f"[Model] Server reachable — provider: {data.get('provider')}, "
                  f"model: {data.get('model')}")
        except requests.ConnectionError:
            print(f"[Model] WARNING: Server not reachable at {self._url}")
            print(f"[Model]   On laptop, run: python server/ai_server.py")
            print(f"[Model]   Make sure firewall allows port 8000")
        except Exception as e:
            print(f"[Model] WARNING: Health check failed ({e})")

    def generate(self, text: str, image_b64: Optional[str] = None) -> str:
        """
        Send text to laptop, return AI response.
        Falls back gracefully on network errors so the pipeline never crashes.
        """
        payload = {
            "text":      text,
            "image_b64": image_b64,
        }

        try:
            r = requests.post(
                f"{self._url}/respond",
                json=payload,
                timeout=self._timeout,
            )
            r.raise_for_status()
            return r.json()["response"]

        except requests.Timeout:
            print(f"[Model] Server timeout (>{self._timeout}s)")
            return "Beep boop... the server took too long to respond."

        except requests.ConnectionError:
            print("[Model] Server unreachable — check network and laptop server.")
            return "Beep boop... I cannot reach my brain right now."

        except requests.HTTPError as e:
            print(f"[Model] Server returned {r.status_code}: {r.text}")
            return "Beep boop... the server gave an error."

        except (KeyError, ValueError) as e:
            print(f"[Model] Invalid response from server: {e}")
            return "Beep boop... I got a strange response."

        except Exception as e:
            print(f"[Model] Unexpected error: {e}")
            return "Beep boop... something went wrong."