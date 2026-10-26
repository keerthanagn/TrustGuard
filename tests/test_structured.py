from llm.structured import parse_structured
from verification.claim_extractor import claims_from_structured


def test_parse_valid_json():
    raw = '{"abstain": false, "answer": "Under s.103 BNS murder is punishable with death.", ' \
          '"claims": [{"text": "Under Section 103 of the BNS, murder is punishable with death.", "cites": ["S1"]}]}'
    out = parse_structured(raw)
    assert out and not out.abstain and len(out.claims) == 1 and out.claims[0].cites == ["S1"]


def test_parse_json_in_code_fence_and_prose():
    raw = 'Sure, here is the JSON:\n```json\n{"abstain": true, "answer": "No info.", "claims": []}\n```\nThanks!'
    out = parse_structured(raw)
    assert out and out.abstain and out.claims == []


def test_parse_invalid_returns_none():
    assert parse_structured("this is not json at all") is None
    assert parse_structured('{"answer": 123, "claims": "bad"}') is None  # schema violation


def test_claims_from_structured_build_metadata():
    claims = claims_from_structured(["Under Section 66C of the IT Act, identity theft is punishable with "
                                     "imprisonment up to three years and a fine up to one lakh rupees."])
    assert claims[0].refs and claims[0].refs[0].number == "66C"
    assert claims[0].quantities and claims[0].punishments
