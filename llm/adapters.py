"""Model adapter layer: a registry of interchangeable LLM backends behind one interface.

TrustGuard is model-independent - generation is fully separated from verification and the release
decision. Any adapter implementing `generate(system, prompt) -> Generation` can be plugged in:

  ollama   - local models via the Ollama server (default; offline-friendly)
  openai   - any OpenAI-compatible /v1/chat/completions endpoint: vLLM, LM Studio, llama.cpp server,
             Ollama's OpenAI shim, OpenRouter, or the OpenAI API itself. Key from env (never hardcoded).
  scripted - deterministic fixed responses (tests / reproducible evaluation)
  failing  - always raises (fault-injection demonstrations)

Select via config:  llm.provider = ollama | openai   (or env TRUSTGUARD_LLM_PROVIDER).
"""
from __future__ import annotations

import logging
import os
import time

import requests

from config.settings import Settings
from core.errors import LLMUnavailableError
from llm.base import FailingLLM, Generation, ScriptedLLM
from llm.ollama_client import OllamaClient

log = logging.getLogger("trustguard.llm")


class OpenAICompatClient:
    """Client for any OpenAI-compatible chat-completions endpoint."""

    def __init__(self, base_url: str, model: str, api_key_env: str = "OPENAI_API_KEY",
                 temperature: float = 0.1, max_tokens: int = 450, connect_timeout_s: float = 5,
                 read_timeout_s: float = 240, technical_retries: int = 1):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = os.environ.get(api_key_env, "")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = (connect_timeout_s, read_timeout_s)
        self.technical_retries = technical_retries

    def generate(self, system: str, prompt: str) -> Generation:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "temperature": self.temperature, "max_tokens": self.max_tokens, "stream": False, "seed": 42,
        }
        last_exc = None
        for attempt in range(self.technical_retries + 1):
            start = time.perf_counter()
            try:
                r = requests.post(f"{self.base_url}/chat/completions", json=payload, headers=headers,
                                  timeout=self.timeout)
                if r.status_code in (401, 403):
                    raise LLMUnavailableError("The OpenAI-compatible endpoint rejected the credentials.")
                r.raise_for_status()
                data = r.json()
                text = data["choices"][0]["message"]["content"].strip()
                if not text:
                    raise LLMUnavailableError("The model returned an empty response.")
                usage = data.get("usage", {})
                return Generation(text=text, model=self.model, latency_ms=(time.perf_counter() - start) * 1000,
                                  prompt_tokens=usage.get("prompt_tokens", 0),
                                  completion_tokens=usage.get("completion_tokens", 0))
            except LLMUnavailableError:
                raise
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                time.sleep(min(2 ** attempt, 4))
            except (requests.HTTPError, ValueError, KeyError) as exc:
                raise LLMUnavailableError(f"OpenAI-compatible endpoint error: {exc}") from exc
        raise LLMUnavailableError(f"OpenAI-compatible endpoint unreachable at {self.base_url} ({last_exc}).")


def build_llm(settings: Settings):
    """Construct the configured LLM adapter. Defaults to Ollama."""
    cfg = settings.llm
    provider = cfg.get("provider", "ollama").lower()
    if provider == "ollama":
        return OllamaClient.from_settings(cfg)
    if provider in ("openai", "openai_compat", "vllm", "lmstudio", "openrouter"):
        return OpenAICompatClient(
            base_url=cfg.get("openai_base_url", cfg["base_url"]), model=cfg["model"],
            api_key_env=cfg.get("api_key_env", "OPENAI_API_KEY"), temperature=cfg["temperature"],
            max_tokens=cfg["max_tokens"], connect_timeout_s=cfg["connect_timeout_s"],
            read_timeout_s=cfg["read_timeout_s"], technical_retries=cfg["technical_retries"])
    if provider == "scripted":
        return ScriptedLLM(["(scripted provider: supply responses in code)"])
    if provider == "failing":
        return FailingLLM()
    raise LLMUnavailableError(f"Unknown LLM provider '{provider}'. Use ollama or openai.")


def available_backends(settings: Settings) -> dict:
    """Report which configured backends are reachable (for /health and the UI)."""
    from llm.ollama_client import list_models
    cfg = settings.llm
    out = {"configured_provider": cfg.get("provider", "ollama")}
    out["ollama_models"] = list_models(cfg["base_url"])
    return out
