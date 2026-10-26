"""Deterministic extraction and comparison of legal quantities: terms of imprisonment, fines, ages,
time limits, and punishment types. Handles Indian numbering (lakh, crore) and number words."""
from __future__ import annotations

import re

from core.models import Quantity

UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
SCALES = {"hundred": 100, "thousand": 1_000, "lakh": 100_000, "lakhs": 100_000, "lac": 100_000,
          "crore": 10_000_000, "crores": 10_000_000, "million": 1_000_000}

_NUMWORD = r"(?:%s)" % "|".join(sorted(list(UNITS) + list(SCALES), key=len, reverse=True))
_NUMBER = rf"(?:\d[\d,]*(?:\.\d+)?|{_NUMWORD}(?:[\s-]+(?:and\s+)?{_NUMWORD})*)"

_DURATION_RE = re.compile(rf"\b({_NUMBER})[\s-]*(years?|months?|days?|hours?)\b", re.I)
_MONEY_RE = re.compile(
    rf"(?:(?:rs\.?|inr|₹|rupees)\s*({_NUMBER})(?:\s*(lakhs?|crores?|thousand|lac))?"
    rf"|\b({_NUMBER})(?:\s*(lakhs?|crores?|thousand|lac))?\s*rupees"
    rf"|\b({_NUMBER})\s+(lakhs?|crores?)\b)",
    re.I,
)

MAX_CUES = r"(may\s+extend\s+to|extend(?:ing)?\s+to|up\s*to|upto|maximum(?:\s+of)?|not\s+exceeding|not\s+more\s+than|at\s+most|as\s+much\s+as|which\s+may\s+be)"
MIN_CUES = r"(not\s+(?:be\s+)?less\s+than|at\s+least|minimum(?:\s+of)?|mandatory|no\s+less\s+than|a\s+minimum)"

PUNISHMENT_PATTERNS = {
    "death": r"\bdeath\b(?!\s+of)|\bcapital\s+punishment\b|\bdeath\s+penalty\b",
    "life_imprisonment": r"imprisonment\s+for\s+(the\s+remainder\s+of\s+)?(that\s+person'?s\s+natural\s+)?life|life\s+imprisonment",
    "imprisonment": r"\bimprison(ment|ed)\b|\bjail\b|\bsentence[sd]?\s+to\b",
    "fine": r"\bfine[sd]?\b",
    "community_service": r"community\s+service",
    "compensation": r"\bcompensation\b|\bdamages\b",
}


def words_to_number(text: str) -> float | None:
    t = text.lower().replace(",", "").replace("-", " ").strip()
    try:
        return float(t)
    except ValueError:
        pass
    total, current, seen = 0.0, 0.0, False
    prev_unit = None  # last cardinal-unit value added, reset by a scale word
    for tok in t.split():
        if tok == "and":
            continue
        if tok in UNITS:
            val = UNITS[tok]
            # Two adjacent plain units with no scale between (e.g. "two three", a struck-through
            # amendment artifact) are not a valid compound. Treat it as a correction: keep the later value.
            if prev_unit is not None and not (prev_unit % 10 == 0 and prev_unit >= 20 and val < 10):
                current = current - prev_unit + val
            else:
                current += val
            prev_unit = val
            seen = True
        elif tok in SCALES:
            scale = SCALES[tok]
            current = (current or 1) * scale
            if scale >= 1000:
                total += current
                current = 0
            prev_unit = None
            seen = True
        else:
            try:
                current += float(tok)
                prev_unit = None
                seen = True
            except ValueError:
                return None
    return total + current if seen else None


def _qualifier(before: str) -> str:
    window = before[-70:].lower()
    mx = [m.end() for m in re.finditer(MAX_CUES, window)]
    mn = [m.end() for m in re.finditer(MIN_CUES, window)]
    if not mx and not mn:
        return "exact"
    return "max" if (max(mx) if mx else -1) > (max(mn) if mn else -1) else "min"


def _applies_to(text: str, start: int, end: int) -> str:
    before = text[max(0, start - 80):start].lower()
    after = text[end:end + 40].lower()
    if re.match(r"\s*(of\s+age|old|of\s+his\s+age|of\s+her\s+age)", after) or re.search(r"\b(age\s+of|aged)\b", before[-45:]):
        return "age"
    if re.match(r"\s*(of\s+|in\s+)?(imprisonment|jail|prison|rigorous|simple)", after):
        return "imprisonment"
    pos_fine = before.rfind("fine")
    pos_imp = max(before.rfind("imprisonment"), before.rfind("term"), before.rfind("jail"))
    if pos_fine < 0 and pos_imp < 0:
        if re.search(r"\b(within|period|limitation|before|after)\b", before[-30:]):
            return "time_limit"
        return "other"
    return "fine" if pos_fine > pos_imp else "imprisonment"


def extract_quantities(text: str) -> list[Quantity]:
    out: list[Quantity] = []
    spans: list[tuple[int, int]] = []
    for m in _MONEY_RE.finditer(text):
        num = m.group(1) or m.group(3) or m.group(5)
        scale = (m.group(2) or m.group(4) or m.group(6) or "").lower()
        value = words_to_number(num or "")
        if value is None:
            continue
        if scale:
            value *= SCALES.get(scale, 1)
        out.append(Quantity(kind="money", value=value, qualifier=_qualifier(text[:m.start()]),
                            applies_to="fine" if "fine" in text[max(0, m.start() - 80):m.start()].lower()
                            or "fine" in text[m.end():m.end() + 20].lower() else "money",
                            raw=m.group(0).strip()))
        spans.append(m.span())
    for m in _DURATION_RE.finditer(text):
        if any(a <= m.start() < b for a, b in spans):
            continue
        value = words_to_number(m.group(1))
        if value is None:
            continue
        unit = m.group(2).lower()
        years = value if unit.startswith("year") else value / 12 if unit.startswith("month") else \
            value / 365 if unit.startswith("day") else value / 8760
        applies = _applies_to(text, m.start(), m.end())
        kind = "age" if applies == "age" else "duration"
        out.append(Quantity(kind=kind, value=round(years, 6), qualifier=_qualifier(text[:m.start()]),
                            applies_to=applies, raw=m.group(0).strip()))
    return out


def extract_punishments(text: str) -> list[str]:
    found = []
    low = text.lower()
    for name, pat in PUNISHMENT_PATTERNS.items():
        if re.search(pat, low):
            found.append(name)
    if "life_imprisonment" in found and "imprisonment" in found:
        # "imprisonment" is implied by life imprisonment unless a separate term is mentioned
        rest = re.sub(PUNISHMENT_PATTERNS["life_imprisonment"], " ", low)
        if not re.search(PUNISHMENT_PATTERNS["imprisonment"], rest):
            found.remove("imprisonment")
    return found


def same_value(a: float, b: float) -> bool:
    return abs(a - b) <= max(1e-6, 1e-3 * max(abs(a), abs(b)))


def compare_quantity(q: Quantity, evidence_qs: list[Quantity]) -> tuple[str, str]:
    """Compare one claimed quantity with quantities found in evidence.

    Returns (verdict, explanation) where verdict is one of:
      match            same value and compatible qualifier
      qualifier_conflict  same value but claim says minimum where evidence says maximum (or vice versa)
      value_conflict   evidence states a different value for the same kind of quantity
      absent           evidence states no comparable quantity
    """
    comparable = [e for e in evidence_qs if e.kind == q.kind and
                  (q.applies_to in {"other", "money"} or e.applies_to in {"other", "money"} or e.applies_to == q.applies_to)]
    for e in comparable:
        if same_value(e.value, q.value):
            if {q.qualifier, e.qualifier} == {"min", "max"}:
                return "qualifier_conflict", (f"claim states a {'minimum' if q.qualifier == 'min' else 'maximum'} "
                                              f"of '{q.raw}' but the source states a "
                                              f"{'minimum' if e.qualifier == 'min' else 'maximum'} ('{e.raw}')")
            return "match", f"'{q.raw}' matches '{e.raw}' in the source"
    if comparable:
        vals = ", ".join(sorted({e.raw for e in comparable})[:4])
        return "value_conflict", f"claim states '{q.raw}' but the source states {vals}"
    return "absent", f"no source passage states '{q.raw}'"
