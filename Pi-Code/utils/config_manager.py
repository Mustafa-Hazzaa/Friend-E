"""
ConfigManager — single source of truth for all settings.

Every service reads from this. To change any setting,
edit config.json — no code changes needed.
"""

import json
import os
from dataclasses import dataclass


CONFIG_PATH = "./utils/config.json"


class ConfigManager:
    """
    Loads config.json and exposes typed sections.

    Usage:
        cfg = ConfigManager()
        print(cfg.language)           # "ar"
        print(cfg.stt["model_size"])  # "base"
    """

    def __init__(self, path: str = CONFIG_PATH):
        self.config_path = path
        with open(path, "r", encoding="utf-8") as f:
            self._raw = json.load(f)

    # ── Top-level ──────────────────────────────────────────
    @property
    def language(self) -> str:
        return self._raw["language"]
    
    @language.setter
    def language(self, value: str) -> None:
        if value not in ('ar', 'en'):
            raise ValueError("Language must be 'ar' or 'en'")
        self._raw["language"] = value

    # ... other properties ...

    def save(self):
        with open(self.config_path, 'w') as f:
            json.dump(self._raw, f,indent=4)

    # ── Section accessors ──────────────────────────────────
    @property
    def audio(self) -> dict:
        return self._raw["audio"]

    @property
    def wake_word(self) -> dict:
        return self._raw["wake_word"]

    @property
    def stt(self) -> dict:
        return self._raw["stt"]

    @property
    def model(self) -> dict:
        return self._raw["model"]

    @property
    def translation(self) -> dict:
        return self._raw["translation"]

    @property
    def tts(self) -> dict:
        return self._raw["tts"]

    @property
    def robot(self) -> dict:
        return self._raw["robot"]
