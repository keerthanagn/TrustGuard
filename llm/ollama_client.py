"""Ollama HTTP client with bounded timeouts and bounded technical retries."""
from __future__ import annotations

import logging
import time

import requests

from core.errors import LLMUnavailableError
from llm.base import Generation

log = logging.getLogger("trustguard.llm")


class OllamaClient:
    def __init__(self, base_url: str, model: str, temperature: float = 0.1, max_tokens: int = 450,
                 connect_timeout_s: float = 5, read_timeout_s: float = 240, technical_retries: int = 1):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = (connect_timeout_s, read_timeout_s)
        self.technical_retries = technical_retries

    @classmethod
    def from_settings(cls, llm_cfg: dict) -> "OllamaClient":
        return cls(llm_cfg["base_url"], llm_cfg["model"], llm_cfg["temperature"], llm_cfg["max_tokens"],
                   llm_cfg["connect_timeout_s"], llm_cfg["read_timeout_s"], llm_cfg["technical_retries"])

    def generate(self, system: str, prompt: str) -> Generation:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": self.temperature, "num_predict": self.max_tokens, "seed": 42},
        }
        last_exc: Exception | None = None
        for attempt in range(self.technical_retries + 1):
            start = time.perf_counter()
            try:
                r = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout)
                if r.status_code == 404:
                    raise LLMUnavailableError(
                        f"Model '{self.model}' is not available in Ollama. Run: ollama pull {self.model}")
                r.raise_for_status()
                data = r.json()
                text = (data.get("message") or {}).get("content", "").strip()
                if not text:
                    raise LLMUnavailableError("The model returned an empty response.")
                return Generation(text=text, model=self.model, latency_ms=(time.perf_counter() - start) * 1000,
                                  prompt_tokens=data.get("prompt_eval_count", 0),
                                  completion_tokens=data.get("eval_count", 0))
            except LLMUnavailableError:
                raise
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                log.warning("Ollama request failed (attempt %d): %s", attempt + 1, exc)
                time.sleep(min(2 ** attempt, 4))
            except (requests.HTTPError, ValueError) as exc:
                raise LLMUnavailableError(f"Ollama returned an error: {exc}") from exc
        raise LLMUnavailableError(f"Ollama is unreachable at {self.base_url} ({last_exc}). Start it with: ollama serve")


def list_models(base_url: str, timeout: float = 3) -> list[str]:
    try:
        r = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=timeout)
        r.raise_for_status()
        return sorted(m["name"] for m in r.json().get("models", []))
    except (requests.RequestException, ValueError):
        return []
