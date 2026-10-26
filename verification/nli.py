"""Natural Language Inference scoring with a cross-encoder (independent of the generating LLM)."""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

from core.errors import VerifierError
from core.resources import get_cross_encoder


@dataclass
class NLIScore:
    entail: float
    contradict: float
    neutral: float
    premise: str


def premise_windows(text: str, header: str = "", max_windows: int = 8) -> list[str]:
    """Whole passage plus 1-2 sentence windows: short premises make entailment decisions sharper."""
    sents = [s.strip() for s in re.split(r"(?<=[.;:])\s+(?=[A-Z(])", re.sub(r"\s+", " ", text)) if len(s.strip()) > 20]
    windows = [text]
    for i in range(len(sents)):
        windows.append(sents[i])
        if i + 1 < len(sents):
            windows.append(f"{sents[i]} {sents[i + 1]}")
    seen, out = set(), []
    for w in windows:
        w = f"{header}{w}" if header else w
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out[: max_windows + 1]


class NLIScorer:
    def __init__(self, model_name: str, batch_size: int = 16):
        try:
            self.model = get_cross_encoder(model_name)
        except Exception as exc:
            raise VerifierError(f"NLI model '{model_name}' could not be loaded: {exc}") from exc
        labels = {v.lower(): k for k, v in self.model.config.id2label.items()}
        try:
            self.idx = (labels["entailment"], labels["contradiction"], labels["neutral"])
        except KeyError as exc:
            raise VerifierError(f"NLI model has unexpected labels {self.model.config.id2label}") from exc
        self.batch_size = batch_size

    def score(self, pairs: list[tuple[str, str]]) -> list[NLIScore]:
        if not pairs:
            return []
        try:
            probs = self.model.predict(pairs, batch_size=self.batch_size, apply_softmax=True,
                                       show_progress_bar=False)
        except Exception as exc:
            raise VerifierError(f"NLI inference failed: {exc}") from exc
        probs = np.atleast_2d(probs)
        e, c, n = self.idx
        return [NLIScore(float(p[e]), float(p[c]), float(p[n]), pairs[i][0]) for i, p in enumerate(probs)]
