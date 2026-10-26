"""TrustGuard middleware orchestrator.

Flow per request:
  1. validate + screen the question
  2. generate a draft (initial, then bounded repairs)
  3. retrieve legal evidence
  4. extract atomic claims
  5. verify claims + screen the draft for malicious content
  6. apply the strict release policy
  7. if it fails and is repairable and retries remain -> build a repair prompt and loop
  8. release only a draft whose final attempt passes every mandatory check; otherwise withhold with reasons

Also runs two baselines (base LLM, retrieval-augmented LLM) so the three systems can be compared on the
same questions. Baselines reuse generation + verification for measurement but skip the release policy.
"""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import contextmanager

from config.settings import Settings, get_settings
from core.errors import InputValidationError, LLMUnavailableError, RetrievalError, TrustGuardError
from core.models import (Attempt, Decision, Evidence, SafetyLabel, StageTiming, TrustReport)
from database.db import Database, utcnow
from llm.base import Generation, LLMClient
from llm.ollama_client import OllamaClient
from llm.prompts import (ABSTAIN_TEXT, BASE_SYSTEM, GROUNDED_SYSTEM, base_prompt, grounded_prompt,
                         repair_prompt)
from llm.structured import STRUCTURED_SYSTEM, parse_structured
from middleware.policy import evaluate_policy, is_repairable
from retrieval.index import HybridIndex, registry
from safety.screener import SafetyScreener
from verification.claim_extractor import claims_from_structured, extract_claims, is_abstention
from verification.nli import NLIScorer
from verification.verifier import ClaimVerifier

log = logging.getLogger("trustguard.pipeline")

CATEGORY_EXPLANATIONS = {
    "VERIFIED": "All material legal claims were verified against traceable evidence and safety screening passed.",
    "UNSUPPORTED": "The answer contained legal claims that the available evidence does not support.",
    "CONTRADICTED": "The answer contained legal claims that the evidence contradicts (e.g. a wrong punishment, "
                    "a fabricated section, or outdated law).",
    "UNSAFE": "The drafted answer was withheld by malicious-content screening.",
    "NO_EVIDENCE": "The knowledge base does not contain sufficient relevant, current legal evidence to answer "
                   "this question reliably.",
    "SYSTEM_ERROR": "A component failed while processing this request. The draft is withheld rather than "
                    "released unverified.",
    "QUESTION_BLOCKED": "The question itself requested harmful operational content and was declined.",
}


class TrustGuardPipeline:
    def __init__(self, settings: Settings, db: Database, llm: LLMClient | None = None,
                 index: HybridIndex | None = None, nli: NLIScorer | None = None,
                 screener: SafetyScreener | None = None, fault: str = ""):
        self.settings = settings
        self.db = db
        self.fault = fault
        self._llm = llm
        self._index = index
        self._nli = nli
        self._screener = screener

    # ------------------------------------------------------------------ lazy components
    @property
    def llm(self) -> LLMClient:
        if self._llm is None:
            from llm.adapters import build_llm
            self._llm = build_llm(self.settings)
        return self._llm

    def get_index(self, doc_ids: list[str] | None) -> HybridIndex:
        if self._index is not None:
            return self._index
        return registry.get(self.settings, self.db, doc_ids)

    @property
    def screener(self) -> SafetyScreener:
        if self._screener is None:
            self._screener = SafetyScreener(self.settings, fault=self.fault)
        return self._screener

    def make_verifier(self, index: HybridIndex) -> ClaimVerifier:
        return ClaimVerifier(self.settings, index, nli=self._nli, fault=self.fault)

    # ------------------------------------------------------------------ helpers
    @contextmanager
    def _stage(self, report: TrustReport, name: str, attempt: int = 0):
        start = time.perf_counter()
        try:
            yield
        finally:
            report.timings.append(StageTiming(name, (time.perf_counter() - start) * 1000, attempt))

    def _generate(self, system: str, prompt: str) -> Generation:
        if self.fault == "llm_unavailable":
            raise LLMUnavailableError("Simulated LLM outage (fault injection).")
        return self.llm.generate(system, prompt)

    # ------------------------------------------------------------------ main entry
    def run(self, question: str, doc_ids: list[str] | None = None, mode: str = "trustguard",
            request_id: str | None = None, persist: bool = True) -> TrustReport:
        settings = self.settings
        rid = request_id or f"TG-{uuid.uuid4().hex[:12]}"
        report = TrustReport(request_id=rid, question=question.strip(), created_at=utcnow(),
                             model=getattr(self.llm, "model", settings.llm["model"]),
                             knowledge_base=[], mode=mode,
                             settings_snapshot=self._snapshot())
        t0 = time.perf_counter()
        try:
            self._validate(question)
            index = self.get_index(doc_ids)
            report.knowledge_base = sorted(index.acts())
            if index.degraded_reason:
                report.errors.append(index.degraded_reason)

            # screen the question; only a BLOCK declines outright
            with self._stage(report, "question_safety"):
                report.question_safety = self.screener.screen(report.question, is_question=True)
            if report.question_safety.label == SafetyLabel.BLOCK:
                return self._finalise(report, Decision.WITHHELD, "QUESTION_BLOCKED",
                                      report.question_safety.reasons, t0, persist)

            if mode == "base":
                return self._run_base(report, index, t0, persist)
            if mode == "retrieval":
                return self._run_retrieval(report, index, t0, persist)
            return self._run_trustguard(report, index, t0, persist)

        except InputValidationError as exc:
            report.errors.append(str(exc))
            return self._finalise(report, Decision.WITHHELD, "SYSTEM_ERROR", [str(exc)], t0, persist)
        except (RetrievalError, LLMUnavailableError, TrustGuardError) as exc:
            report.errors.append(f"{type(exc).__name__}: {exc}")
            return self._finalise(report, Decision.WITHHELD, "SYSTEM_ERROR",
                                  [f"A {exc.component} error occurred: {exc}"], t0, persist)
        except Exception as exc:  # pragma: no cover - last-resort guard
            log.exception("Unexpected pipeline failure")
            report.errors.append(f"Unexpected error: {exc}")
            return self._finalise(report, Decision.WITHHELD, "SYSTEM_ERROR",
                                  ["An unexpected error occurred; the answer is withheld."], t0, persist)

    # ------------------------------------------------------------------ TrustGuard mode
    def _run_trustguard(self, report: TrustReport, index: HybridIndex, t0: float, persist: bool) -> TrustReport:
        settings = self.settings
        max_retries = settings.middleware["max_retries"]
        verifier = self.make_verifier(index)

        with self._stage(report, "retrieval"):
            evidence = index.search(report.question, top_k=settings.retrieval["top_k"])
        report.question_evidence = evidence
        min_rel = settings.retrieval["min_relevance"]
        has_relevant = any(e.score >= min_rel for e in evidence)
        from verification.evidence_diag import diagnose
        report.evidence_notes = diagnose(evidence, min_rel)

        previous_text = ""
        previous_verifs = []
        previous_safety_feedback = ""
        previous_failures: list[str] = []

        for attempt_no in range(max_retries + 1):
            kind = "initial" if attempt_no == 0 else "repair"
            attempt = Attempt(attempt=attempt_no, kind=kind, llm_model=report.model)

            # build the prompt
            structured = settings.verification.get("structured_claims", False)
            if attempt_no == 0:
                system = STRUCTURED_SYSTEM if structured else GROUNDED_SYSTEM
                prompt = grounded_prompt(report.question, evidence)
            else:
                system = GROUNDED_SYSTEM  # repairs use the prose path for reliability
                structured = False
                prompt, feedback = repair_prompt(report.question, evidence, previous_text, previous_verifs,
                                                 previous_safety_feedback, previous_failures)
                attempt.prompt_feedback = feedback

            # generate
            try:
                with self._stage(report, "generation", attempt_no):
                    gen = self._generate(system, prompt)
                attempt.draft, attempt.llm_model, attempt.llm_ms = gen.text, gen.model, gen.latency_ms
                report.model = gen.model
            except LLMUnavailableError as exc:
                attempt.error = str(exc)
                attempt.policy_passed = False
                attempt.policy_failures = ["generation_error"]
                report.attempts.append(attempt)
                return self._finalise(report, Decision.WITHHELD, "SYSTEM_ERROR",
                                      [f"The language model was unavailable: {exc}"], t0, persist)

            # claims + verification
            with self._stage(report, "claim_extraction", attempt_no):
                claims = None
                if structured:
                    parsed = parse_structured(attempt.draft)
                    if parsed is not None:
                        # present the prose answer to the user/verifier; decompose via the model's claims
                        attempt.draft = parsed.answer or attempt.draft
                        texts = [c.text for c in parsed.claims] if not parsed.abstain else []
                        claims = claims_from_structured(texts, settings.verification["max_claims"]) if texts \
                            else extract_claims(attempt.draft, settings.verification["max_claims"])
                if claims is None:  # rule-based path (default, and structured fallback)
                    claims = extract_claims(attempt.draft, settings.verification["max_claims"])
            with self._stage(report, "verification", attempt_no):
                attempt.claims = verifier.verify_all(claims, evidence)
            # safety screening of the draft
            with self._stage(report, "answer_safety", attempt_no):
                attempt.safety = self.screener.screen(attempt.draft)

            # policy
            outcome = evaluate_policy(settings, attempt, has_relevant)
            attempt.policy_passed = outcome.passed
            attempt.policy_failures = outcome.failures
            report.attempts.append(attempt)

            if outcome.passed:
                n = len([c for c in attempt.claims if c.claim.material])
                return self._finalise(report, Decision.RELEASED, "VERIFIED",
                                      [f"{n} material claim(s) verified against traceable evidence."], t0, persist,
                                      final_answer=attempt.draft, citations=self._citations(attempt))

            # decide whether to repair
            if attempt_no >= max_retries or not is_repairable(outcome):
                return self._finalise(report, Decision.WITHHELD, outcome.category or "UNSUPPORTED",
                                      outcome.messages, t0, persist)

            previous_text = attempt.draft
            previous_verifs = attempt.claims
            previous_failures = outcome.failures
            previous_safety_feedback = ("; ".join(attempt.safety.reasons)
                                        if attempt.safety and attempt.safety.label != SafetyLabel.SAFE else "")

        # loop exhausted without a pass (should be covered above)
        last = report.attempts[-1]
        out = evaluate_policy(settings, last, has_relevant)
        return self._finalise(report, Decision.WITHHELD, out.category or "UNSUPPORTED", out.messages, t0, persist)

    # ------------------------------------------------------------------ baselines
    def _run_base(self, report: TrustReport, index: HybridIndex, t0: float, persist: bool) -> TrustReport:
        attempt = Attempt(attempt=0, kind="initial", llm_model=report.model)
        try:
            with self._stage(report, "generation"):
                gen = self._generate(BASE_SYSTEM, base_prompt(report.question))
            attempt.draft, attempt.llm_model, attempt.llm_ms = gen.text, gen.model, gen.latency_ms
            report.model = gen.model
        except LLMUnavailableError as exc:
            attempt.error = str(exc)
            report.attempts.append(attempt)
            return self._finalise(report, Decision.WITHHELD, "SYSTEM_ERROR", [str(exc)], t0, persist)
        # measure claims for evaluation but release unconditionally (this is an unguarded baseline)
        attempt.claims = self._measure(report, index, attempt.draft)
        attempt.safety = self.screener.screen(attempt.draft)
        attempt.policy_passed = True
        report.attempts.append(attempt)
        return self._finalise(report, Decision.RELEASED, "BASELINE_BASE", ["Base LLM output (no verification)."],
                              t0, persist, final_answer=attempt.draft, citations=[])

    def _run_retrieval(self, report: TrustReport, index: HybridIndex, t0: float, persist: bool) -> TrustReport:
        attempt = Attempt(attempt=0, kind="initial", llm_model=report.model)
        with self._stage(report, "retrieval"):
            evidence = index.search(report.question, top_k=self.settings.retrieval["top_k"])
        report.question_evidence = evidence
        try:
            with self._stage(report, "generation"):
                gen = self._generate(GROUNDED_SYSTEM, grounded_prompt(report.question, evidence))
            attempt.draft, attempt.llm_model, attempt.llm_ms = gen.text, gen.model, gen.latency_ms
            report.model = gen.model
        except LLMUnavailableError as exc:
            attempt.error = str(exc)
            report.attempts.append(attempt)
            return self._finalise(report, Decision.WITHHELD, "SYSTEM_ERROR", [str(exc)], t0, persist)
        attempt.claims = self._measure(report, index, attempt.draft, evidence)
        attempt.safety = self.screener.screen(attempt.draft)
        attempt.policy_passed = True
        report.attempts.append(attempt)
        return self._finalise(report, Decision.RELEASED, "BASELINE_RETRIEVAL",
                              ["Retrieval-augmented LLM output (no verification gate)."],
                              t0, persist, final_answer=attempt.draft, citations=self._citations(attempt))

    def _measure(self, report: TrustReport, index: HybridIndex, draft: str,
                 evidence: list[Evidence] | None = None) -> list:
        """Verify claims for metric collection only (baselines release regardless)."""
        with self._stage(report, "verification"):
            claims = extract_claims(draft, self.settings.verification["max_claims"])
            return self.make_verifier(index).verify_all(claims, evidence or [])

    # ------------------------------------------------------------------ finalisation
    def _citations(self, attempt: Attempt) -> list[str]:
        seen, out = set(), []
        for cv in attempt.claims:
            for e in cv.supporting:
                if e.citation not in seen and e.doc_id != "legal-currency-registry":
                    seen.add(e.citation)
                    out.append(e.citation)
        return out

    def _finalise(self, report: TrustReport, decision: Decision, category: str, messages: list[str],
                  t0: float, persist: bool, final_answer: str = "", citations: list[str] | None = None) -> TrustReport:
        report.decision = decision
        report.decision_category = category
        report.final_answer = final_answer if decision == Decision.RELEASED else ""
        report.citations = citations or []
        base = CATEGORY_EXPLANATIONS.get(category, "")
        detail = " ".join(m for m in messages if m)
        report.explanation = (base + (" " + detail if detail else "")).strip() or detail
        report.total_ms = (time.perf_counter() - t0) * 1000
        from core.observability import audit
        audit(log, "request_complete", request_id=report.request_id, mode=report.mode, model=report.model,
              decision=decision.value, category=category, retries=report.retries,
              material_claims=len([c for a in report.attempts for c in a.claims if c.claim.material]),
              evidence_notes=[n["kind"] for n in report.evidence_notes], total_ms=round(report.total_ms, 1))
        if persist:
            try:
                self.db.save_report(report, log_queries=self.settings.privacy.get("log_queries", True),
                                     store_drafts=self.settings.privacy.get("store_withheld_drafts", True))
                self.db.apply_retention(self.settings.privacy.get("retention_days", 0))
            except Exception:  # persistence must not break a response
                log.exception("Failed to persist report %s", report.request_id)
        return report

    def _validate(self, question: str) -> None:
        q = (question or "").strip()
        if not q:
            raise InputValidationError("The question is empty.")
        limit = self.settings.limits["max_question_chars"]
        if len(q) > limit:
            raise InputValidationError(f"The question exceeds {limit} characters.")

    def _snapshot(self) -> dict:
        s = self.settings
        return {
            "llm_model": s.llm["model"], "temperature": s.llm["temperature"],
            "top_k": s.retrieval["top_k"], "use_semantic": s.retrieval.get("use_semantic", True),
            "use_reranker": s.retrieval.get("use_reranker", True), "min_relevance": s.retrieval["min_relevance"],
            "entail_threshold": s.verification["entail_threshold"],
            "contradict_threshold": s.verification["contradict_threshold"],
            "max_retries": s.middleware["max_retries"], "withhold_on_review": s.safety.get("withhold_on_review", True),
        }


def build_pipeline(settings: Settings | None = None, db: Database | None = None, **kwargs) -> TrustGuardPipeline:
    settings = settings or get_settings()
    db = db or Database(settings.path("db_path"))
    return TrustGuardPipeline(settings, db, **kwargs)
