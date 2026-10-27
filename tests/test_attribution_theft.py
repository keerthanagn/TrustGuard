"""Regression for the 'what is the punishment for theft' failure (report TG-15e78ed2adcf):

A correct claim about BNS s.303 second/subsequent-conviction punishment was wrongly marked CONTRADICTED
because BNS s.295 shares the identical generic 'second or subsequent conviction ... not less than one
year ... five years' boilerplate and out-scored s.303 on NLI, so the attribution signal declared the
s.303 claim 'misattributed' to s.295 and even displayed s.295 as its supporting evidence.

Root cause: the attribution check must not fire when the cited provision's own numeric + punishment
already match the claim. These tests pin that behaviour and ensure genuine misattribution is still caught.
"""
from core.models import ClaimStatus
from verification.claim_extractor import extract_claims
from verification.verifier import ClaimVerifier

C2_SECOND_CONVICTION = (
    "Under Section 303 of the Bharatiya Nyaya Sanhita, 2023, in case of second or subsequent conviction of a "
    "person under this section, he shall be punished with rigorous imprisonment for a term which shall not be "
    "less than one year but which may extend to five years and with fine.")
C1_BASE = ("Under Section 303 of the Bharatiya Nyaya Sanhita, 2023, whoever commits theft shall be punished "
           "with imprisonment of either description for a term which may extend to three years, or with fine, "
           "or with both.")


def _verify(index, settings, text):
    return ClaimVerifier(settings, index).verify(extract_claims(text)[0], [])


def test_s303_second_conviction_not_misattributed_to_s295(settings, index):
    r = _verify(index, settings, C2_SECOND_CONVICTION)
    assert r.status == ClaimStatus.SUPPORTED, f"expected SUPPORTED, got {r.status} ({r.reason})"
    # supporting evidence must be the cited section, never the unrelated s.295 boilerplate match
    supporting_sections = {(e.act_code, e.section) for e in r.supporting}
    assert ("BNS", "303") in supporting_sections
    assert ("BNS", "295") not in supporting_sections, "s.295 wrongly shown as support for an s.303 claim"
    attribution = next((s for s in r.signals if s.name == "attribution"), None)
    assert attribution is None or attribution.passed


def test_s303_base_theft_supported(settings, index):
    r = _verify(index, settings, C1_BASE)
    assert r.status == ClaimStatus.SUPPORTED
    assert all(e.section == "303" for e in r.supporting)


def test_genuine_misattribution_still_detected(settings, index):
    # a claim whose cited section does NOT contain its figures must still fail (no false SUPPORTED)
    bad = ("Under Section 303 of the Bharatiya Nyaya Sanhita, theft is punishable with death or imprisonment "
           "for life.")
    r = _verify(index, settings, bad)
    assert r.status == ClaimStatus.CONTRADICTED
