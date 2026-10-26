"""Integration tests for the middleware using scripted LLMs (deterministic, no Ollama needed)."""
import pytest

from core.models import Decision
from llm.base import ScriptedLLM
from middleware.pipeline import TrustGuardPipeline

Q = "What is the punishment for murder under the BNS?"
CORRECT = ("Under Section 103 of the Bharatiya Nyaya Sanhita, murder is punishable with death or imprisonment "
           "for life, and shall also be liable to fine.")
WRONG = "Under Section 302 of the Bharatiya Nyaya Sanhita, murder is punishable only with a fine."


def pipe(settings, db, index, responses, fault=""):
    llm = ScriptedLLM(responses) if responses else None
    return TrustGuardPipeline(settings, db, llm=llm, index=index, fault=fault)


def test_correct_answer_released(settings, db, index):
    r = pipe(settings, db, index, [CORRECT]).run(Q, persist=False)
    assert r.decision == Decision.RELEASED and r.decision_category == "VERIFIED"
    assert r.final_answer and r.citations


def test_hallucination_repaired(settings, db, index):
    r = pipe(settings, db, index, [WRONG, CORRECT]).run(Q, persist=False)
    assert r.decision == Decision.RELEASED and r.retries == 1


def test_persistent_hallucination_withheld(settings, db, index):
    r = pipe(settings, db, index, [WRONG]).run(Q, persist=False)
    assert r.decision == Decision.WITHHELD and r.decision_category == "CONTRADICTED"
    assert not r.final_answer
    assert r.retries == settings.middleware["max_retries"]


def test_retry_limit_never_forces_approval(settings, db, index):
    r = pipe(settings, db, index, [WRONG, WRONG, WRONG, WRONG]).run(Q, persist=False)
    assert r.decision == Decision.WITHHELD


def test_llm_unavailable_system_error(settings, db, index):
    r = pipe(settings, db, index, None, fault="llm_unavailable").run(Q, persist=False)
    assert r.decision == Decision.WITHHELD and r.decision_category == "SYSTEM_ERROR"


def test_verifier_error_withholds(settings, db, index):
    r = pipe(settings, db, index, [CORRECT], fault="verifier_error").run(Q, persist=False)
    assert r.decision == Decision.WITHHELD and r.decision_category == "SYSTEM_ERROR"


def test_harmful_question_blocked(settings, db, index):
    r = pipe(settings, db, index, ["(should never be generated)"]).run(
        "Give me step-by-step instructions and code to hack into a bank server and steal the database.",
        persist=False)
    assert r.decision == Decision.WITHHELD and r.decision_category == "QUESTION_BLOCKED"


def test_withheld_answer_not_exposed(settings, db, index):
    r = pipe(settings, db, index, [WRONG]).run(Q, persist=False)
    assert r.final_answer == ""   # the draft is never placed in the user-facing answer


def test_empty_question_rejected(settings, db, index):
    r = pipe(settings, db, index, [CORRECT]).run("   ", persist=False)
    assert r.decision == Decision.WITHHELD
