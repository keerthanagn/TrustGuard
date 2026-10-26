"""Lexical consistency: how much of a claim's substantive vocabulary is present in the evidence.

This is a supporting signal only. It can veto support (low coverage) but can never establish it.
"""
from __future__ import annotations

import re

_STOP = set("""a an the of and or in on to for by with is are be been being shall may can will would could
should any such that this which who whom whose as at from it its into under than other has have had not no
nor if so do does did also same said provision section article act sanhita constitution code india indian
person persons whoever one either both there their they he she his her them under per mentioned""".split())


def _stem(tok: str) -> str:
    for suf in ("ments", "ment", "ings", "ing", "ies", "ed", "es", "s"):
        if tok.endswith(suf) and len(tok) - len(suf) >= 4:
            return tok[: -len(suf)]
    return tok


def content_tokens(text: str) -> set[str]:
    return {_stem(t) for t in re.findall(r"[a-z]+", text.lower()) if t not in _STOP and len(t) > 2}


SYNONYMS = {
    "jail": "imprison", "prison": "imprison", "imprisonment": "imprison", "punishable": "punish",
    "punished": "punish", "penalty": "punish", "life": "life", "rupee": "rupe", "lakh": "lakh",
}


def coverage(claim: str, evidence: str) -> float:
    c = {SYNONYMS.get(t, t) for t in content_tokens(claim)}
    if not c:
        return 1.0
    e = {SYNONYMS.get(t, t) for t in content_tokens(evidence)}
    e |= {t[:5] for t in e}
    hit = sum(1 for t in c if t in e or t[:5] in e)
    return hit / len(c)
