"""Phase 1E regression: a general offence query must prefer the base provision over an aggravated
variant, so TrustGuard does not treat a special provision as the general punishment for every offence.
This is enforced generally (heading affinity), not by hardcoding any offence or section."""


def _sections(index, query, k=5):
    return [(e.act_code, e.section) for e in index.search(query, top_k=k)]


def test_general_theft_prefers_base_provision(index):
    # general "theft" question -> base s.303 (3 yrs) must rank above aggravated s.307 (10 yrs)
    ordered = _sections(index, "What is the punishment for theft?")
    assert ("BNS", "303") in ordered, f"base theft provision not retrieved: {ordered}"
    pos_303 = ordered.index(("BNS", "303"))
    pos_307 = ordered.index(("BNS", "307")) if ("BNS", "307") in ordered else 99
    assert pos_303 < pos_307, f"aggravated s.307 ranked above general s.303: {ordered}"


def test_heading_affinity_is_general_not_hardcoded():
    from retrieval.index import HybridIndex
    # a heading fully covered by the query scores ~1.0; a qualified variant scores much lower
    base = HybridIndex._heading_affinity({"punishment", "theft"}, "Theft")
    qualified = HybridIndex._heading_affinity(
        {"punishment", "theft"}, "Theft after preparation made for causing death, hurt or restraint")
    assert base == 1.0 and qualified < 0.3


def test_specific_queries_still_resolve(index):
    # the base-provision boost must not break targeted queries
    assert ("BNS", "103") in _sections(index, "What is the punishment for murder under the BNS?")
    assert ("ITA", "66C") in _sections(index, "punishment for identity theft under the IT Act")
    assert ("COI", "21") in _sections(index, "Can a person be deprived of personal liberty?")
