"""Strict release policy. Decides whether a verified draft may be released, and why not if withheld."""
from __future__ import annotations

from dataclasses import dataclass, field

from config.settings import Settings
from core.models import Attempt, ClaimStatus, SafetyLabel


@dataclass
class PolicyOutcome:
    passed: bool
    failures: list[str] = field(default_factory=list)       # machine-readable codes
    category: str = ""                                       # decision category when failing
    messages: list[str] = field(default_factory=list)       # human-readable explanations


def evaluate_policy(settings: Settings, attempt: Attempt, has_relevant_evidence: bool) -> PolicyOutcome:
    """Apply release conditions to a single attempt. Every condition must hold to release."""
    mw, sf = settings.middleware, settings.safety
    failures: list[str] = []
    messages: list[str] = []
    category = ""

    # system error during generation
    if attempt.error:
        return PolicyOutcome(False, ["generation_error"], "SYSTEM_ERROR",
                             [f"The answer could not be generated: {attempt.error}"])

    # safety must pass
    safety = attempt.safety
    if safety is not None:
        if safety.label == SafetyLabel.BLOCK:
            failures.append("safety_block")
            category = "UNSAFE"
            messages.append("The drafted answer was blocked by safety screening: " + "; ".join(safety.reasons))
        elif safety.label == SafetyLabel.REVIEW and sf.get("withhold_on_review", True):
            failures.append("safety_review")
            category = category or "UNSAFE"
            messages.append("The drafted answer was flagged for review by safety screening: " + "; ".join(safety.reasons))

    material = [c for c in attempt.claims if c.claim.material]
    errors = [c for c in material if c.status == ClaimStatus.VERIFICATION_ERROR]
    contradicted = [c for c in material if c.status == ClaimStatus.CONTRADICTED]
    unsupported = [c for c in material if c.status == ClaimStatus.INSUFFICIENT_EVIDENCE]
    supported = [c for c in material if c.status == ClaimStatus.SUPPORTED]

    # a verification error must never become an approval
    if errors:
        failures.append("verification_error")
        category = category or "SYSTEM_ERROR"
        messages.append(f"{len(errors)} claim(s) could not be verified because a verification component failed; "
                        "the answer is withheld rather than released unverified.")

    if contradicted:
        failures.append("contradicted_claims")
        category = category or "CONTRADICTED"
        messages.append(f"{len(contradicted)} claim(s) are contradicted by the legal evidence.")

    if unsupported:
        failures.append("unsupported_claims")
        category = category or "UNSUPPORTED"
        messages.append(f"{len(unsupported)} material claim(s) are not supported by sufficient evidence.")

    # there must be at least one supported material claim unless the answer is a clean abstention
    is_abstention = len(material) == 0 and len(attempt.claims) > 0
    if not is_abstention and len(supported) < mw.get("min_material_claims", 1):
        if not (contradicted or unsupported or errors):
            failures.append("no_material_claims")
            category = category or "NO_EVIDENCE"
            messages.append("The answer contains no verifiable legal statement supported by the evidence.")

    # citations required for a substantive (non-abstaining) answer
    if mw.get("require_citations", True) and supported and not is_abstention:
        has_citation = any(c.supporting for c in supported)
        if not has_citation:
            failures.append("missing_citations")
            category = category or "NO_EVIDENCE"
            messages.append("No traceable citation is available for the supported statements.")

    if not has_relevant_evidence and not is_abstention and supported:
        failures.append("no_relevant_evidence")
        category = category or "NO_EVIDENCE"
        messages.append("No sufficiently relevant legal evidence was retrieved for this question.")

    return PolicyOutcome(passed=not failures, failures=failures, category=category, messages=messages)


def is_repairable(outcome: PolicyOutcome) -> bool:
    """Repair helps with factual/safety problems; it cannot fix a verifier/LLM system error."""
    repairable = {"safety_block", "safety_review", "contradicted_claims", "unsupported_claims",
                  "no_material_claims", "missing_citations"}
    blocking = {"verification_error", "generation_error"}
    if any(f in blocking for f in outcome.failures):
        return False
    return any(f in repairable for f in outcome.failures)
