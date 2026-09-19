"""
ModelService — AI model abstraction layer.

The pipeline only ever calls:
    service.generate(text) -> str

History is managed INSIDE the model service — the pipeline
never touches it. Swapping providers = change config.json only.

Adding a new provider:
  1. Subclass BaseModelService
  2. Implement generate()
  3. Add a case in ModelServiceFactory.create()
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Dict, Any, Optional

from utils.config_manager import ConfigManager


# ─────────────────────────────────────────────────────────
# Abstract base
# ─────────────────────────────────────────────────────────
class BaseModelService(ABC):
    """
    Every provider implements this single method.
    History is the provider's responsibility, not the pipeline's.
    """

    @abstractmethod
    def generate(self, text: str, image_b64: Optional[str] = None) -> str:
        """
        Args:
            text:      Current user message (always English).
            image_b64: Optional base64-encoded image.
        Returns:
            English response string.
        """


# ─────────────────────────────────────────────────────────
# Ollama provider
# ─────────────────────────────────────────────────────────
class OllamaModelService(BaseModelService):

    def __init__(self, cfg: ConfigManager):
        self._cfg     = cfg.model
        self._history: List[Dict[str, str]] = []   # owned here, not in pipeline
        self._client  = None
        self._connect()

    def _connect(self):
        try:
            from ollama import Client
            self._client = Client(host=self._cfg["ollama_host"])
            print(f"[Model] Ollama connected at {self._cfg['ollama_host']}")
        except Exception as e:
            print(f"[Model] Ollama unavailable ({e})")
            self._client = None

    def generate(self, text: str, image_b64: Optional[str] = None) -> str:
        if self._client is None:
            return "Beep boop! I'm offline right now."

        # Inject time if user asks about it
        if any(kw in text.lower() for kw in ["time", "date", "now", "today"]):
            text += f"\n\n[Current date/time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]"

        messages = [{"role": "system", "content": self._cfg["system_prompt"]}]
        messages.extend(self._history)
        user_msg: Dict[str, Any] = {"role": "user", "content": text}
        if image_b64:
            user_msg["images"] = [image_b64]
        messages.append(user_msg)

        response = ""
        for attempt in range(self._cfg["max_retries"]):
            try:
                r = self._client.chat(
                    model=self._cfg["model_name"],
                    messages=messages,
                    options={"temperature": self._cfg["temperature"]},
                )
                response = r.get("message", {}).get("content", "").strip()
                break
            except Exception as e:
                print(f"[Model] Attempt {attempt+1} failed: {e}")
                response = "Beep boop… something went wrong."

        # History managed here — pipeline never sees it
        self._history.append({"role": "user",      "content": text})
        self._history.append({"role": "assistant",  "content": response})

        return response


# ─────────────────────────────────────────────────────────
# Remote API provider
# ─────────────────────────────────────────────────────────
class APIModelService(BaseModelService):

    def __init__(self, cfg: ConfigManager):
        self._cfg     = cfg.model
        self._history: List[Dict[str, str]] = []

    def generate(self, text: str, image_b64: Optional[str] = None) -> str:
        import requests

        messages = [{"role": "system", "content": self._cfg["system_prompt"]}]
        messages.extend(self._history)
        messages.append({"role": "user", "content": text})

        try:
            r = requests.post(
                self._cfg["api_url"],
                json={"model": self._cfg["model_name"],
                      "messages": messages,
                      "temperature": self._cfg["temperature"]},
                headers={"Authorization": f"Bearer {self._cfg['api_key']}",
                         "Content-Type": "application/json"},
                timeout=15,
            )
            r.raise_for_status()
            response = r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"[Model] API error: {e}")
            response = "Beep boop… the API didn't respond."

        self._history.append({"role": "user",      "content": text})
        self._history.append({"role": "assistant",  "content": response})
        return response


# ─────────────────────────────────────────────────────────
# Mock provider — use while testing pipeline without AI
# ─────────────────────────────────────────────────────────
class MockModelService(BaseModelService):
    """
    Returns a canned response instantly.
    Use this to test the full pipeline (wake word → STT → TTS)
    without needing Ollama, an API, or the laptop server.

    Set in config.json:
        "model": { "provider": "mock" }
    """

    def generate(self, text: str, image_b64: Optional[str] = None) -> str:
        print(f"[Model] MOCK received: '{text}'")
        return f"Beep boop! You said: {text}. I am a mock robot response."


# ─────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────
class ModelServiceFactory:
    @staticmethod
    def create(cfg: ConfigManager) -> BaseModelService:
        provider = cfg.model.get("provider", "ollama").lower()
        if provider == "ollama":
            return OllamaModelService(cfg)
        elif provider == "api":
            return APIModelService(cfg)
        elif provider == "remote":
            from models_layer.remote_model_service import RemoteModelService
            return RemoteModelService(cfg)
        elif provider == "mock":
            return MockModelService()
        raise ValueError(f"Unknown provider: '{provider}'")