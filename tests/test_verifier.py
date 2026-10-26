"""Verifier tests. These load the NLI model; they are slower but exercise the research core."""
import pytest

from core.models import ClaimStatus
from verification.claim_extractor import extract_claims
from verification.verifier import ClaimVerifier


@pytest.fixture(scope="module")
def verifier(settings, index):
    return ClaimVerifier(settings, index)


def verify_first(verifier, text):
    return verifier.verify(extract_claims(text)[0], [])


def test_supported_claim(verifier):
    r = verify_first(verifier, "Under Section 103 of the Bharatiya Nyaya Sanhita, murder is punishable "
                               "with death or imprisonment for life, and shall also be liable to fine.")
    assert r.status == ClaimStatus.SUPPORTED and r.supporting


def test_fabricated_section_contradicted(verifier):
    r = verify_first(verifier, "Section 999 of the Bharatiya Nyaya Sanhita punishes cyber defamation.")
    assert r.status == ClaimStatus.CONTRADICTED


def test_wrong_punishment_contradicted(verifier):
    r = verify_first(verifier, "Under Section 66C of the IT Act, identity theft is punishable with "
                               "imprisonment up to ten years.")
    assert r.status == ClaimStatus.CONTRADICTED


def test_invented_minimum_fine_contradicted(verifier):
    r = verify_first(verifier, "Section 66C of the IT Act prescribes a mandatory minimum fine of five lakh rupees.")
    assert r.status == ClaimStatus.CONTRADICTED


def test_struck_down_law_contradicted(verifier):
    r = verify_first(verifier, "Section 66A of the IT Act punishes sending offensive messages online.")
    assert r.status == ClaimStatus.CONTRADICTED


def test_repealed_law_contradicted(verifier):
    r = verify_first(verifier, "Cheating is currently punishable under Section 420 of the Indian Penal Code.")
    assert r.status == ClaimStatus.CONTRADICTED


def test_out_of_scope_insufficient(verifier):
    r = verify_first(verifier, "The GST rate on gold jewellery is three percent.")
    assert r.status in (ClaimStatus.INSUFFICIENT_EVIDENCE, ClaimStatus.CONTRADICTED)


def test_verifier_error_fails_closed(settings, index):
    v = ClaimVerifier(settings, index, fault="verifier_error")
    r = v.verify(extract_claims("Under Section 103 of the BNS, murder is punishable with death.")[0], [])
    assert r.status == ClaimStatus.VERIFICATION_ERROR and r.error
