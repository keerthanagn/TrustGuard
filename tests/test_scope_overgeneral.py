"""Regression for final_test_v3 finding H11: an over-generalised constitutional-rights claim
("Article 20 protects from all prosecution without exception") was released SUPPORTED because NLI
entailed the broad claim at 0.96 and the scope check was suppressed by a best_entail < 0.9 gate.

The scope decision must now fire whenever the claim uses strong absolute wording AND the cited
provision's own text contains exceptions/provisos, regardless of NLI entailment — while a genuinely
absolute provision (no exception markers) must NOT be falsely contradicted.
"""
from core.models import ClaimStatus
from verification.claim_extractor import extract_claims
from verification.verifier import ClaimVerifier


def _verify(index, settings, text):
    return ClaimVerifier(settings, index).verify(extract_claims(text)[0], [])


def test_overgeneral_rights_claim_contradicted(settings, index):
    r = _verify(index, settings,
                "Under Article 20 of the Constitution, a person is protected from all prosecution and "
                "punishment in every circumstance without exception.")
    assert r.status == ClaimStatus.CONTRADICTED, f"expected CONTRADICTED, got {r.status} ({r.reason})"
    scope = next((s for s in r.signals if s.name == "scope"), None)
    assert scope is not None and scope.passed is False


def test_scope_guard_requires_exception_marker_in_source():
    # the fix only flags over-generalisation when the CITED provision's own text contains an exception/
    # proviso marker; a genuinely absolute provision (no such marker) must not trip the scope flag,
    # so it can never be contradicted via the scope path. This pins the guard independent of NLI.
    from verification.verifier import EXCEPTION_MARKERS_RE, STRONG_ABSOLUTES
    art20 = ("No person shall be convicted of any offence except for violation of a law in force; and no "
             "person shall be prosecuted and punished for the same offence more than once.")
    art17 = ("Untouchability is abolished and its practice in any form is forbidden; its enforcement shall "
             "be an offence punishable in accordance with law.")
    assert EXCEPTION_MARKERS_RE.search(art20)        # has 'except' -> over-general claim can be flagged
    assert not EXCEPTION_MARKERS_RE.search(art17)    # no exception marker -> scope path cannot fire
    assert "without exception" in STRONG_ABSOLUTES


def test_faithful_article20_claim_supported(settings, index):
    # an accurate (non-over-generalised) Article 20 claim must still be SUPPORTED
    r = _verify(index, settings,
                "Under Article 20 of the Constitution, no person shall be prosecuted and punished for the same "
                "offence more than once.")
    assert r.status == ClaimStatus.SUPPORTED
