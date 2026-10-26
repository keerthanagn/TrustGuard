"""LLM client interface plus deterministic clients used for tests, evaluation and fault injection."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Protocol

from core.errors import LLMUnavailableError


@dataclass
class Generation:
    text: str
    model: str
    latency_ms: float
    prompt_tokens: int = 0
    completion_tokens: int = 0


class LLMClient(Protocol):
    model: str

    def generate(self, system: str, prompt: str) -> Generation: ...


class ScriptedLLM:
    """Returns pre-written answers in order (or computed by a function). Used to inject known
    hallucinations into the middleware so its behaviour can be measured independently of a live model."""

    def __init__(self, responses: list[str] | Callable[[str, str, int], str], model: str = "scripted"):
        self.responses = responses
        self.model = model
        self.calls: list[tuple[str, str]] = []

    def generate(self, system: str, prompt: str) -> Generation:
        start = time.perf_counter()
        n = len(self.calls)
        self.calls.append((system, prompt))
        if callable(self.responses):
            text = self.responses(system, prompt, n)
        else:
            text = self.responses[min(n, len(self.responses) - 1)]
        return Generation(text=text, model=self.model, latency_ms=(time.perf_counter() - start) * 1000)


class FailingLLM:
    """Simulates an unavailable LLM backend (technical-failure demonstration)."""

    def __init__(self, model: str = "unavailable"):
        self.model = model

    def generate(self, system: str, prompt: str) -> Generation:
        raise LLMUnavailableError("Simulated LLM outage: the generation service did not respond.")
