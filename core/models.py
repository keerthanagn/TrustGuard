"""Typed records exchanged between TrustGuard components and serialised into reports."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class ClaimStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    VERIFICATION_ERROR = "VERIFICATION_ERROR"


class SafetyLabel(str, Enum):
    SAFE = "SAFE"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"


class Decision(str, Enum):
    RELEASED = "RELEASED"
    WITHHELD = "WITHHELD"


class DocStatus(str, Enum):
    VERIFIED = "verified"        # authenticated against an official source by a reviewer
    UNREVIEWED = "unreviewed"    # uploaded, provenance not independently checked
    OUTDATED = "outdated"        # superseded text, kept for audit only


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    text: str
    page_start: int
    page_end: int
    section: str = ""            # e.g. "103", "66C", "21A"
    ref_type: str = "Section"    # "Section" or "Article"
    heading: str = ""
    act_code: str = ""           # e.g. "BNS", "ITA", "COI"
    ordinal: int = 0
    injection_flag: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Evidence:
    chunk_id: str
    doc_id: str
    doc_title: str
    act_code: str
    section: str
    ref_type: str
    page_start: int
    page_end: int
    text: str
    score: float = 0.0           # fused relevance (0..1)
    doc_status: str = DocStatus.UNREVIEWED.value
    retrievers: list[str] = field(default_factory=list)
    injection_flag: bool = False

    @property
    def citation(self) -> str:
        ref = f"{self.ref_type} {self.section}" if self.section else "unnumbered text"
        if self.page_start <= 0:
            return f"{self.doc_title}, {ref}"
        pages = f"p. {self.page_start}" if self.page_start == self.page_end else f"pp. {self.page_start}-{self.page_end}"
        return f"{self.doc_title}, {ref}, {pages}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["citation"] = self.citation
        return d


@dataclass
class LegalRef:
    ref_type: str                # Section / Article
    number: str                  # "103", "66C"
    subsection: str = ""         # "(2)"
    act_code: str = ""           # BNS / ITA / COI / IPC / ""
    raw: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Quantity:
    kind: str                    # duration | money
    value: float                 # years for duration, rupees for money
    qualifier: str = ""          # max | min | exact
    applies_to: str = ""         # imprisonment | fine | other
    raw: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Claim:
    claim_id: str
    text: str
    sentence_index: int
    material: bool = True
    refs: list[LegalRef] = field(default_factory=list)
    inherited_refs: bool = False
    quantities: list[Quantity] = field(default_factory=list)
    punishments: list[str] = field(default_factory=list)   # death, life, imprisonment, fine, community service
    conditions: list[str] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    jurisdiction: list[str] = field(default_factory=list)
    absolute_terms: list[str] = field(default_factory=list)  # always, never, without exception...

    def to_dict(self) -> dict:
        return {
            **{k: v for k, v in asdict(self).items() if k not in {"refs", "quantities"}},
            "refs": [r.to_dict() for r in self.refs],
            "quantities": [q.to_dict() for q in self.quantities],
        }


@dataclass
class SignalResult:
    name: str                    # nli | lexical | numeric | statutory | relevance | currency
    passed: bool | None          # None = not applicable
    score: float | None = None
    detail: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ClaimVerification:
    claim: Claim
    status: ClaimStatus
    reason: str
    supporting: list[Evidence] = field(default_factory=list)
    contradicting: list[Evidence] = field(default_factory=list)
    signals: list[SignalResult] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "claim": self.claim.to_dict(),
            "status": self.status.value,
            "reason": self.reason,
            "supporting": [e.to_dict() for e in self.supporting],
            "contradicting": [e.to_dict() for e in self.contradicting],
            "signals": [s.to_dict() for s in self.signals],
            "error": self.error,
        }


@dataclass
class SafetyResult:
    label: SafetyLabel
    risk_score: float
    categories: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    classifier_prob: float | None = None
    benign_context: bool = False
    error: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["label"] = self.label.value
        return d


@dataclass
class StageTiming:
    stage: str
    ms: float
    attempt: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Attempt:
    attempt: int                 # 0 = initial generation, 1..n = repairs
    kind: str                    # initial | repair
    draft: str = ""
    prompt_feedback: str = ""    # verification feedback used to build the repair prompt
    claims: list[ClaimVerification] = field(default_factory=list)
    safety: SafetyResult | None = None
    policy_passed: bool = False
    policy_failures: list[str] = field(default_factory=list)
    llm_model: str = ""
    llm_ms: float = 0.0
    error: str = ""

    def to_dict(self, include_draft: bool = True) -> dict:
        return {
            "attempt": self.attempt,
            "kind": self.kind,
            "draft": self.draft if include_draft else "[redacted]",
            "prompt_feedback": self.prompt_feedback,
            "claims": [c.to_dict() for c in self.claims],
            "safety": self.safety.to_dict() if self.safety else None,
            "policy_passed": self.policy_passed,
            "policy_failures": self.policy_failures,
            "llm_model": self.llm_model,
            "llm_ms": round(self.llm_ms, 1),
            "error": self.error,
        }


@dataclass
class TrustReport:
    request_id: str
    question: str
    created_at: str
    model: str
    knowledge_base: list[str]
    decision: Decision = Decision.WITHHELD
    decision_category: str = ""          # VERIFIED | UNSUPPORTED | CONTRADICTED | UNSAFE | NO_EVIDENCE | SYSTEM_ERROR
    final_answer: str = ""               # only set when RELEASED
    explanation: str = ""
    citations: list[str] = field(default_factory=list)
    question_safety: SafetyResult | None = None
    question_evidence: list[Evidence] = field(default_factory=list)
    evidence_notes: list[dict] = field(default_factory=list)
    attempts: list[Attempt] = field(default_factory=list)
    timings: list[StageTiming] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    settings_snapshot: dict = field(default_factory=dict)
    total_ms: float = 0.0
    mode: str = "trustguard"

    @property
    def retries(self) -> int:
        return max(0, len(self.attempts) - 1)

    @property
    def final_attempt(self) -> Attempt | None:
        return self.attempts[-1] if self.attempts else None

    def to_dict(self, include_drafts: bool = True) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "question": self.question,
            "created_at": self.created_at,
            "mode": self.mode,
            "model": self.model,
            "knowledge_base": self.knowledge_base,
            "decision": self.decision.value,
            "decision_category": self.decision_category,
            "final_answer": self.final_answer,
            "explanation": self.explanation,
            "citations": self.citations,
            "question_safety": self.question_safety.to_dict() if self.question_safety else None,
            "question_evidence": [e.to_dict() for e in self.question_evidence],
            "evidence_notes": self.evidence_notes,
            "attempts": [a.to_dict(include_draft=include_drafts) for a in self.attempts],
            "retries": self.retries,
            "timings": [t.to_dict() for t in self.timings],
            "errors": self.errors,
            "settings_snapshot": self.settings_snapshot,
            "total_ms": round(self.total_ms, 1),
        }
