"""Layered malicious-content screener: rules + zero-shot classifier -> SAFE / REVIEW / BLOCK."""
from __future__ import annotations

import logging

from config.settings import Settings
from core.errors import SafetyError
from core.models import SafetyLabel, SafetyResult
from safety import rules
from safety.classifier import SafetyClassifier

log = logging.getLogger("trustguard.safety")

CATEGORY_LABELS = {
    "credential_theft": "credential theft", "malware": "malware/spyware",
    "unauthorized_access": "unauthorized system access", "data_exfiltration": "data exfiltration",
    "physical_harm": "instructions for physical harm", "fraud": "financial fraud",
    "surveillance": "covert surveillance", "tampering": "records/evidence tampering",
}


class SafetyScreener:
    def __init__(self, settings: Settings, classifier: SafetyClassifier | None = None, fault: str = ""):
        self.settings = settings
        self.cfg = settings.safety
        self.fault = fault
        self._clf = classifier

    @property
    def classifier(self) -> SafetyClassifier | None:
        if self.fault == "safety_error":
            raise SafetyError("Simulated safety-classifier failure (fault injection).")
        if self._clf is None:
            try:
                self._clf = SafetyClassifier(self.settings.verification["nli_model"])
            except Exception as exc:
                log.warning("Safety classifier unavailable (%s); using rules only", exc)
                self._clf = None
        return self._clf

    def screen(self, text: str, is_question: bool = False) -> SafetyResult:
        try:
            return self._screen(text, is_question)
        except SafetyError as exc:
            # fail safe: a screening error routes to REVIEW (strict mode withholds), never to SAFE
            return SafetyResult(label=SafetyLabel.REVIEW, risk_score=1.0, categories=["screening_error"],
                                reasons=[f"Safety screening could not complete: {exc}. Routed to REVIEW."],
                                error=str(exc))

    def _screen(self, text: str, is_question: bool) -> SafetyResult:
        analysis = rules.analyse(text)
        categories = [CATEGORY_LABELS.get(c, c) for c in analysis["categories"]]
        reasons: list[str] = []
        rule_score = analysis["rule_score"]
        benign_context = analysis["legal_context"] > analysis["operational"] and bool(analysis["categories"])

        clf_prob = None
        clf = self.classifier
        if clf is not None:
            clf_prob = clf.harm_probability(text)

        if analysis["categories"]:
            reasons.append("Rule layer flagged: " + ", ".join(categories) + ".")
        if analysis["operational_and_harmful"]:
            reasons.append("Operational phrasing (step-by-step / code / direct instructions) accompanies the flagged content.")
        if benign_context:
            reasons.append("Content appears in a legal/educational context (sections, punishments or defensive framing).")
        if clf_prob is not None:
            reasons.append(f"Classifier harm probability: {clf_prob:.2f}.")

        has_category = bool(analysis["categories"])
        # the classifier is noisy on legal text, so it only raises risk when operational phrasing or a
        # harmful-category rule hit is also present; on its own it cannot flag a pure legal statement.
        clf_contributes = (clf_prob is not None and not benign_context
                           and (analysis["operational"] >= 1 or has_category))
        risk = max(rule_score, clf_prob if clf_contributes else 0.0)

        block_rules = analysis["operational_and_harmful"] and rule_score >= self.cfg["rule_block_score"]
        block_clf = (clf_prob is not None and clf_prob >= self.cfg["block_threshold"]
                     and analysis["operational"] >= 1 and not benign_context)

        if block_rules or block_clf:
            label = SafetyLabel.BLOCK
            if not reasons:
                reasons.append("High-confidence operational harmful content.")
        elif (has_category and not benign_context) or (clf_contributes and risk >= self.cfg["review_threshold"]):
            label = SafetyLabel.REVIEW
        else:
            label = SafetyLabel.SAFE
            if not reasons:
                reasons.append("No harmful operational content detected.")

        return SafetyResult(label=label, risk_score=round(risk, 3), categories=categories, reasons=reasons,
                            classifier_prob=clf_prob, benign_context=benign_context)
