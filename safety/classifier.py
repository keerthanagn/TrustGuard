"""Zero-shot safety classifier reusing the NLI cross-encoder.

A genuine ML signal independent of the keyword rules: the text is scored for entailment against a set of
hypotheses describing operational harmful content versus benign legal/educational discussion. This treats
the detector as fallible - its probability is one input to the decision, combined with the rule layer and
evaluated on a labelled set in the evaluation module.
"""
from __future__ import annotations

import logging

import numpy as np

from core.resources import get_cross_encoder

log = logging.getLogger("trustguard.safety")

HARM_HYPOTHESES = [
    "This text gives step-by-step instructions to carry out a cyberattack or other crime.",
    "This text explains how to steal passwords, hack a system, or create malware.",
    "This text provides operational instructions to cause harm or break the law.",
]
BENIGN_HYPOTHESES = [
    "This text explains what the law says about an offence, citing sections or punishments.",
    "This text is general legal or educational information and gives no instructions to commit a crime.",
    "This text describes the legal consequences of an activity without explaining how to do it.",
]


class SafetyClassifier:
    def __init__(self, model_name: str):
        self.model = get_cross_encoder(model_name)
        labels = {v.lower(): k for k, v in self.model.config.id2label.items()}
        self.entail_idx = labels.get("entailment", 1)

    def harm_probability(self, text: str) -> float:
        premise = text[:1800]
        pairs = [(premise, h) for h in HARM_HYPOTHESES + BENIGN_HYPOTHESES]
        probs = np.atleast_2d(self.model.predict(pairs, apply_softmax=True, show_progress_bar=False))
        entail = probs[:, self.entail_idx]
        harm = float(entail[: len(HARM_HYPOTHESES)].max())
        benign = float(entail[len(HARM_HYPOTHESES):].max())
        # normalise the two competing maxima into a single probability
        return round(harm / (harm + benign + 1e-9), 3)
