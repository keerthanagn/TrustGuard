from retrieval.legal_refs import detect_acts, extract_refs, normalise_section, strip_refs


def test_section_normalisation():
    assert normalise_section("66 c") == "66C"
    assert normalise_section("21a") == "21A"


def test_extract_simple_reference():
    refs = extract_refs("Under Section 103 of the Bharatiya Nyaya Sanhita, 2023, murder is punishable")
    assert len(refs) == 1
    assert refs[0].number == "103" and refs[0].act_code == "BNS" and refs[0].ref_type == "Section"


def test_extract_letter_suffix_not_confused_with_of():
    # "Section 103 of" must not parse as section "103OF"
    refs = extract_refs("Section 103 of the BNS")
    assert refs[0].number == "103"


def test_extract_letter_suffix_kept():
    assert extract_refs("Sec. 66C of the IT Act")[0].number == "66C"
    assert extract_refs("Section 66 A of the IT Act")[0].number == "66A"


def test_article_defaults_to_constitution():
    refs = extract_refs("Article 21 guarantees personal liberty")
    assert refs[0].ref_type == "Article" and refs[0].act_code == "COI"


def test_multiple_references():
    refs = extract_refs("sections 303 and 318 of the BNS")
    assert {r.number for r in refs} == {"303", "318"}


def test_detect_acts():
    assert "BNS" in detect_acts("the Bharatiya Nyaya Sanhita")
    assert "ITA" in detect_acts("the Information Technology Act")
    assert "COI" in detect_acts("the Constitution of India")


def test_strip_refs_removes_citation_phrases():
    out = strip_refs("Under Section 103 of the Bharatiya Nyaya Sanhita, 2023, murder is punishable")
    assert "Section" not in out and "murder is punishable" in out
