"""
TranslatorService — bidirectional translation.

Public interface (what the pipeline calls):
    to_english(text)              — any input → English for the model
    to_language(text, lang)       — English → target language for TTS

The pipeline never decides HOW to translate — it just says what direction.
Internal routing (opus-mt vs google) is hidden here.
"""

import functools
import os
import re
from typing import Optional

from utils.config_manager import ConfigManager

ARABIC_PATTERN = re.compile(r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]+')


def _has_internet() -> bool:
    import socket
    try:
        socket.setdefaulttimeout(2)
        socket.create_connection(("8.8.8.8", 53))
        return True
    except OSError:
        return False


def _is_arabic(text: str) -> bool:
    return bool(ARABIC_PATTERN.search(text))


def _is_mixed(text: str) -> bool:
    return bool(ARABIC_PATTERN.search(text)) and bool(re.search(r'[a-zA-Z]', text))


class _OpusMTModel:
    def __init__(self, model_path: str):
        self._ready = False
        self._tokenizer = None
        self._model = None
        if not os.path.exists(model_path):
            print(f"[Translate] Not found: {model_path}")
            return
        try:
            from transformers import MarianMTModel, MarianTokenizer
            self._tokenizer = MarianTokenizer.from_pretrained(model_path)
            self._model     = MarianMTModel.from_pretrained(model_path)
            self._model.eval()
            self._ready = True
            print(f"[Translate] Loaded {model_path}")
        except Exception as e:
            print(f"[Translate] Load failed ({model_path}): {e}")

    @property
    def ready(self) -> bool:
        return self._ready

    def run(self, text: str) -> str:
        import torch
        inputs = self._tokenizer(
            [text], return_tensors="pt",
            padding=True, truncation=True, max_length=512,
        )
        with torch.no_grad():
            out = self._model.generate(**inputs)
        return self._tokenizer.decode(out[0], skip_special_tokens=True)


class TranslatorService:
    """
    Pipeline calls only two methods:
        to_english(text)            — for feeding the AI model
        to_language(text, lang)     — for feeding TTS
    """

    def __init__(self, cfg: ConfigManager):
        t = cfg.translation
        self._ar_en = _OpusMTModel(t["ar_to_en_model_path"])
        self._en_ar = _OpusMTModel(t["en_to_ar_model_path"])

    # ── Pipeline-facing API ───────────────────────────────
    def to_english(self, text: str) -> str:
        """
        Convert any STT output to English for the AI.
        English input passes through unchanged at zero cost.
        """
        return self._arabic_to_english(text)

    def to_language(self, text: str, lang: str) -> str:
        """
        Convert English AI response to the target language.
        English target passes through unchanged.
        """
        if lang == "ar":
            return self._english_to_arabic(text)
        return text   # already English

    # ── Internal translation ──────────────────────────────
    @functools.lru_cache(maxsize=512)
    def _arabic_to_english(self, text: str) -> str:
        text = text.strip()
        if not text or not _is_arabic(text):
            return text  # already English

        if self._ar_en.ready:
            try:
                result = self._translate_mixed(text) if _is_mixed(text) \
                         else self._ar_en.run(text)
                print(f"[AR→EN] done.")
                return result
            except Exception as e:
                print(f"[AR→EN] local failed ({e})")

        return self._google(text, target="en")

    @functools.lru_cache(maxsize=512)
    def _english_to_arabic(self, text: str) -> str:
        text = text.strip()
        if not text:
            return text

        if self._en_ar.ready:
            try:
                result = self._en_ar.run(f">>ara<< {text}")
                print(f"[EN→AR] done.")
                return result
            except Exception as e:
                print(f"[EN→AR] local failed ({e})")

        return self._google(text, target="ar")

    def _translate_mixed(self, text: str) -> str:
        parts   = ARABIC_PATTERN.split(text)
        matches = ARABIC_PATTERN.findall(text)
        result  = []
        mi      = 0
        for part in parts:
            if part:
                result.append(part)
            if mi < len(matches):
                try:
                    result.append(self._ar_en.run(matches[mi]))
                except Exception:
                    result.append(matches[mi])
                mi += 1
        return re.sub(r'\s+', ' ', " ".join(result)).strip()

    @staticmethod
    def _google(text: str, target: str) -> str:
        if not _has_internet():
            print("[Translate] Offline — returning original.")
            return text
        try:
            from deep_translator import GoogleTranslator
            result = GoogleTranslator(source="auto", target=target).translate(text)
            print(f"[Translate] Google ({target}) ✓")
            return result
        except Exception as e:
            print(f"[Translate] Google failed ({e})")
            return text