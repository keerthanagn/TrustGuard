from verification.claim_extractor import extract_claims, is_abstention, split_sentences


def test_sentence_split_keeps_abbreviations():
    s = split_sentences("Under Sec. 103 of the BNS, murder is punishable. It also attracts a fine.")
    assert len(s) == 2


def test_reference_inheritance():
    answer = ("Under Section 103 of the Bharatiya Nyaya Sanhita, murder is punishable with death. "
              "It also carries a fine.")
    claims = extract_claims(answer)
    assert claims[1].inherited_refs and claims[1].refs[0].number == "103"


def test_non_material_advice_marked():
    claims = extract_claims("Please consult a qualified lawyer for advice.")
    assert not claims[0].material


def test_quantities_and_punishments_attached():
    c = extract_claims("Identity theft is punishable with imprisonment up to three years and a fine.")[0]
    assert c.quantities and c.punishments


def test_abstention_detection():
    assert is_abstention("The provided legal sources do not address this question.")
    assert not is_abstention("Murder is punishable with death under Section 103.")


def test_absolute_terms_flagged():
    c = extract_claims("Causing death is always murder without any exception under the BNS.")[0]
    assert "always" in c.absolute_terms
