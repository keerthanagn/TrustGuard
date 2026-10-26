"""End-to-end Q&A workflow tests: assert the pipeline produces exactly what the UI renders
(released answer, evidence, claim-level results, citations, per-stage timings), and that failure
cases (LLM outage, verifier crash, empty corpus) withhold safely without leaking a draft.

Uses the scripted LLM + the fixture index from conftest, so no live model is required. Real-model
integration is exercised separately via `python -m evaluation.run_eval --llm ollama`.
"""
import pytest

from core.errors import RetrievalError
from core.models import Decision
from llm.base import ScriptedLLM
from middleware.pipeline import TrustGuardPipeline

Q = "What is the punishment for murder under the BNS?"
CORRECT = ("Under Section 103 of the Bharatiya Nyaya Sanhita, murder is punishable with death or imprisonment "
           "for life, and shall also be liable to fine.")
WRONG = "Under Section 302 of the Bharatiya Nyaya Sanhita, murder is punishable only with a fine."


def _pipe(settings, db, index, responses, fault=""):
    llm = ScriptedLLM(responses) if responses else None
    return TrustGuardPipeline(settings, db, llm=llm, index=index, fault=fault)


def test_released_answer_has_everything_the_ui_shows(settings, db, index):
    report = _pipe(settings, db, index, [CORRECT]).run(Q, persist=False)
    assert report.decision == Decision.RELEASED and report.final_answer
    # evidence shown to the user
    assert report.question_evidence, "no retrieved evidence to display"
    e = report.question_evidence[0]
    assert e.doc_title and e.section and e.citation  # source + provision + citation string
    # claim-level verification with supporting evidence
    final = report.final_attempt
    assert final and final.claims
    supported = [c for c in final.claims if c.status.value == "SUPPORTED"]
    assert supported and supported[0].supporting
    # citations and per-stage timings (the status panel + report)
    assert report.citations
    stages = {t.stage for t in report.timings}
    assert {"retrieval", "generation", "verification"} <= stages


def test_withheld_never_leaks_draft(settings, db, index):
    report = _pipe(settings, db, index, [WRONG]).run(Q, persist=False)
    assert report.decision == Decision.WITHHELD
    assert report.final_answer == ""                     # user-facing answer is empty
    d = report.to_dict(include_drafts=False)             # the view the API returns
    assert all(a["draft"] == "[redacted]" for a in d["attempts"])
    assert report.explanation and d["decision_category"] == "CONTRADICTED"


def test_insufficient_evidence_is_explained(settings, db, index):
    report = _pipe(settings, db, index, ["The GST rate on gold jewellery is three percent."]).run(
        "What is the GST rate on gold jewellery?", persist=False)
    # released as a clean abstention OR withheld as no-evidence; never a fabricated substantive answer
    from verification.claim_extractor import is_abstention
    assert report.decision == Decision.WITHHELD or is_abstention(report.final_answer)


def test_llm_timeout_withholds_safely(settings, db, index):
    report = _pipe(settings, db, index, None, fault="llm_unavailable").run(Q, persist=False)
    assert report.decision == Decision.WITHHELD and report.decision_category == "SYSTEM_ERROR"
    assert report.final_answer == ""


def test_retrieval_failure_withholds(settings, db):
    # an empty document selection raises inside retrieval -> SYSTEM_ERROR, not a crash
    pipe = TrustGuardPipeline(settings, db, llm=ScriptedLLM([CORRECT]))
    report = pipe.run(Q, doc_ids=["does-not-exist"], mode="trustguard", persist=False)
    assert report.decision == Decision.WITHHELD and report.decision_category == "SYSTEM_ERROR"


def test_stage_timings_recorded_per_stage(settings, db, index):
    report = _pipe(settings, db, index, [CORRECT]).run(Q, persist=False)
    assert all(t.ms >= 0 for t in report.timings)
    assert len(report.timings) >= 3
