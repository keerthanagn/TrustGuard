"""Parsing of statutory references (sections / articles) and act names in free text."""
from __future__ import annotations

import re

from core.models import LegalRef

# Canonical act codes and the surface forms that refer to them.
ACT_ALIASES: dict[str, list[str]] = {
    "BNS": [r"bharatiya\s+nyaya\s+sanhita", r"\bbns\b", r"nyaya\s+sanhita"],
    "ITA": [r"information\s+technology\s+act", r"\bit\s+act\b", r"\bita\b", r"\bitaa\b"],
    "COI": [r"constitution(\s+of\s+india)?", r"\bcoi\b"],
    "IPC": [r"indian\s+penal\s+code", r"\bipc\b"],
    "BNSS": [r"bharatiya\s+nagarik\s+suraksha\s+sanhita", r"\bbnss\b"],
    "BSA": [r"bharatiya\s+sakshya\s+adhiniyam", r"\bbsa\b"],
}
ACT_NAMES = {
    "BNS": "Bharatiya Nyaya Sanhita, 2023",
    "ITA": "Information Technology Act, 2000",
    "COI": "Constitution of India",
    "IPC": "Indian Penal Code, 1860",
    "BNSS": "Bharatiya Nagarik Suraksha Sanhita, 2023",
    "BSA": "Bharatiya Sakshya Adhiniyam, 2023",
}
_ACT_RES = {code: [re.compile(p, re.I) for p in pats] for code, pats in ACT_ALIASES.items()}

# Letter suffixes ("66C", "21A", "243ZA") are case-sensitive so that "103 of" is not read as "103OF".
_NUMCORE = r"\d{1,3}(?-i:[A-Z]{1,3}|\s[A-Z](?![A-Za-z]))?(?![\w])"
_NUM = rf"({_NUMCORE})"
_SUB = r"((?:\s?\(\s?[0-9a-z]{1,4}\s?\))*)"
_REF_RE = re.compile(
    r"\b(sections?|secs?\.?|ss?\.|articles?|arts?\.)\s*" + _NUM + _SUB
    + r"((?:\s*(?:,|and|&|or)\s*" + _NUMCORE + _SUB + r")*)",
    re.I,
)
_EXTRA_NUM_RE = re.compile(_NUM + _SUB)


def normalise_section(num: str) -> str:
    """'66 c' -> '66C', '21a' -> '21A'."""
    return re.sub(r"\s+", "", num).upper()


def section_key(num: str) -> tuple[int, str]:
    m = re.match(r"(\d+)([A-Z]*)", normalise_section(num))
    if not m:
        return (0, "")
    return (int(m.group(1)), m.group(2))


def detect_acts(text: str) -> list[str]:
    found = []
    for code, pats in _ACT_RES.items():
        if any(p.search(text) for p in pats):
            found.append(code)
    # "IT Act" must not be confused with "it act" in prose - require capitalised form
    if "ITA" in found and not re.search(r"Information\s+Technology|IT\s+Act|\bITA\b", text):
        found.remove("ITA")
    if "COI" in found and not re.search(r"Constitution", text):
        found.remove("COI")
    return found


def strip_act_names(text: str) -> str:
    """Remove act names so retrieval matches on substance rather than on the title of the statute."""
    t = text
    for code, pats in _ACT_RES.items():
        for p in pats:
            t = p.sub(" ", t)
    t = re.sub(r",?\s*\b(19|20)\d{2}\b", " ", t)
    t = re.sub(r"\b(under|of|in)\s+the\s*(\?|$)", r"\2", t)
    return re.sub(r"\s{2,}", " ", t).strip()


def _nearest_act(text: str, start: int, end: int) -> str:
    """Pick the act mentioned closest after (preferred) or before a reference."""
    best, best_dist = "", 10**9
    for code, pats in _ACT_RES.items():
        for p in pats:
            for m in p.finditer(text):
                if code == "ITA" and not re.match(r"Information|IT|ITA", m.group(0)):
                    continue
                if code == "COI" and not m.group(0).startswith("Constitution"):
                    continue
                if m.start() >= end:
                    dist = m.start() - end
                else:
                    dist = (start - m.end()) * 2 + 40  # prefer acts named after the reference
                if 0 <= dist < best_dist and dist < 160:
                    best, best_dist = code, dist
    return best


def extract_refs(text: str) -> list[LegalRef]:
    refs: list[LegalRef] = []
    for m in _REF_RE.finditer(text):
        word = m.group(1).lower()
        ref_type = "Article" if word.startswith("art") else "Section"
        act = _nearest_act(text, m.start(), m.end())
        if ref_type == "Article" and not act:
            act = "COI"
        numbers = [(m.group(2), m.group(3))]
        if m.group(4):
            numbers += [(x.group(1), x.group(2)) for x in _EXTRA_NUM_RE.finditer(m.group(4))]
        for num, sub in numbers:
            n = normalise_section(num)
            if not n or not n[0].isdigit():
                continue
            refs.append(LegalRef(ref_type=ref_type, number=n, subsection=re.sub(r"\s", "", sub or ""),
                                 act_code=act, raw=m.group(0).strip()))
    # de-duplicate preserving order
    seen, out = set(), []
    for r in refs:
        key = (r.ref_type, r.number, r.subsection, r.act_code)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def strip_refs(text: str) -> str:
    """Remove reference phrases ("under Section 103(1) of the BNS") so NLI judges the substance."""
    t = re.sub(r"\b(under|as per|in terms of|according to|by virtue of)\s+(the\s+)?" + _REF_RE.pattern
               + r"(\s+of\s+(the\s+)?[A-Z][\w ,]*?(Sanhita|Act|Code|Constitution)(,?\s*\d{4})?)?", " ", text, flags=re.I)
    t = _REF_RE.sub(lambda m: "this provision", t)
    t = re.sub(r"\s+(of|under)\s+(the\s+)?(Bharatiya Nyaya Sanhita|Information Technology Act|IT Act|BNS|IPC|"
               r"Constitution of India|Constitution|Indian Penal Code)(,?\s*\d{4})?", "", t, flags=re.I)
    t = re.sub(r"\((BNS|IT Act|IPC|COI)\)", "", t)
    return re.sub(r"\s{2,}", " ", t).strip(" ,")
