"""Atomic claim extraction from generated legal answers (rule-based, deterministic, LLM-independent)."""
from __future__ import annotations

import re

from core.models import Claim
from retrieval.legal_refs import extract_refs
from verification.numeric import extract_punishments, extract_quantities

_ABBREV = ["Sec", "Secs", "s", "ss", "No", "Nos", "Rs", "i.e", "e.g", "etc", "viz", "Art", "Arts", "v", "vs",
           "Govt", "Ltd", "Dr", "Mr", "Mrs", "Ms", "St", "cl", "Cl", "sub-s", "Para", "para", "Ch", "Pvt", "Hon'ble"]
_ABBREV_RE = re.compile(r"\b(" + "|".join(re.escape(a) for a in _ABBREV) + r")\.", re.I)
_PLACEHOLDER = "․"  # one-dot leader, restored after splitting

ABSTAIN_RE = re.compile(
    r"(sources?|evidence|passages?|documents?|knowledge base)\s+(provided\s+)?(do|does)\s+not\s+(address|contain|cover|mention|specify|state)"
    r"|cannot\s+(answer|be\s+answered)|not\s+able\s+to\s+(answer|find)|no\s+information\s+(is\s+)?(available|provided)", re.I)
NON_MATERIAL_RE = re.compile(
    r"(consult|speak\s+(to|with)|contact|seek\s+advice\s+from)\s+(a|an|your)?\s*(qualified\s+)?(lawyer|advocate|legal|attorney)"
    r"|not\s+(legal\s+advice|a\s+lawyer)|for\s+informational\s+purposes|i\s+hope\s+this|let\s+me\s+know|please\s+note\s+that\s+this", re.I)
LEGAL_TERMS_RE = re.compile(
    r"\b(section|article|act|sanhita|constitution|punish\w*|imprison\w*|fine|offen[cs]e\w*|liable|penalt\w*|court|"
    r"right|law|legal|illegal|crime|criminal|guilty|convict\w*|arrest\w*|bail|cognizable|accused|shall|state|"
    r"government|parliament|citizen|prohibit\w*|permit\w*|entitled|deemed|jurisdiction|compensation|repeal\w*|"
    r"struck\s+down|unconstitutional|amend\w*)\b", re.I)
CONDITION_RE = re.compile(r"\b(if|unless|provided\s+that|except|where|when|only\s+if|subject\s+to|in\s+case)\b", re.I)
JURIS_RE = re.compile(r"\b(in\s+India|beyond\s+India|outside\s+India|Union\s+territor\w+|State\s+Government|"
                      r"Central\s+Government|Supreme\s+Court|High\s+Courts?|Magistrate|Parliament)\b", re.I)
DATE_RE = re.compile(r"\b(\d{1,2}(st|nd|rd|th)?\s+(January|February|March|April|May|June|July|August|September|"
                     r"October|November|December),?\s+\d{4}|(19|20)\d{2})\b", re.I)
ABSOLUTE_RE = re.compile(r"\b(always|never|in\s+all\s+cases|without\s+(any\s+)?exception|regardless\s+of|"
                         r"under\s+no\s+circumstances|automatically|in\s+every\s+case|only)\b", re.I)
PRONOUN_START_RE = re.compile(
    r"^(it|this|that|such|these|those|the\s+(punishment|penalty|offence|section|article|provision|act|"
    r"sentence|fine|term|same|accused|offender|law)|he|she|they|in\s+addition|additionally|also|further)\b", re.I)


def _clean(text: str) -> str:
    t = re.sub(r"\[(S\d+|\d+)\]|\((S\d+)\)", "", text)                    # citation markers
    t = re.sub(r"(?m)^\s*(#+|\*|-|•|\d+[.)])\s+", "\n", t)           # markdown bullets/headings
    t = re.sub(r"\*\*|__|`", "", t)
    return t


def split_sentences(text: str) -> list[str]:
    t = _ABBREV_RE.sub(lambda m: m.group(1) + _PLACEHOLDER, _clean(text))
    t = re.sub(r"(\d)\.(\d)", r"\1" + _PLACEHOLDER + r"\2", t)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z(\"'“])|\n+", t)
    out = []
    for p in parts:
        p = p.replace(_PLACEHOLDER, ".").strip(" \t-")
        if len(p) > 3:
            out.append(p)
    return out


def split_compound(sentence: str) -> list[str]:
    """Split independent clauses joined by semicolons or contrastive connectives."""
    pieces = re.split(r";\s+|,?\s+whereas\s+|;\s*however,?\s+|\.\s*Additionally,?\s+", sentence)
    out = []
    for p in pieces:
        p = p.strip(" ,;")
        if len(p.split()) >= 4:
            out.append(p[0].upper() + p[1:] if p else p)
        elif out:
            out[-1] = f"{out[-1]}; {p}"
    return out or [sentence]


def is_abstention(text: str) -> bool:
    return bool(ABSTAIN_RE.search(text))


def build_claim(text: str, claim_id: str, sentence_index: int, prior_refs: list | None = None) -> Claim:
    """Construct one Claim with all independent metadata from a single statement.

    Shared by the rule-based extractor and the optional structured-output path so both yield identical
    claim metadata for verification. `prior_refs` enables reference inheritance across sentences.
    """
    text = text.strip()
    refs = extract_refs(text)
    inherited = False
    if not refs and prior_refs and PRONOUN_START_RE.match(text):
        refs, inherited = list(prior_refs), True
    quantities = extract_quantities(text)
    punishments = extract_punishments(text)
    material = True
    if is_abstention(text) or NON_MATERIAL_RE.search(text):
        material = False
    elif (not refs and not quantities and not punishments and not LEGAL_TERMS_RE.search(text)
          and (len(text.split()) < 6 or not re.search(r"\d|\b(is|are|was|were|has|have)\b", text))):
        material = False  # short filler without any assertion of legal or numeric content
    return Claim(
        claim_id=claim_id, text=text, sentence_index=sentence_index, material=material, refs=refs,
        inherited_refs=inherited, quantities=quantities, punishments=punishments,
        conditions=sorted({m.group(0).lower() for m in CONDITION_RE.finditer(text)}),
        dates=[m.group(0) for m in DATE_RE.finditer(text)],
        jurisdiction=sorted({m.group(0) for m in JURIS_RE.finditer(text)}),
        absolute_terms=sorted({m.group(0).lower() for m in ABSOLUTE_RE.finditer(text)}),
    )


def extract_claims(answer: str, max_claims: int = 12) -> list[Claim]:
    claims: list[Claim] = []
    last_refs: list = []
    for s_idx, sentence in enumerate(split_sentences(answer)):
        for piece in split_compound(sentence):
            text = piece.strip()
            if text.endswith("?"):
                continue
            claim = build_claim(text, f"C{len(claims) + 1}", s_idx, last_refs)
            if claim.refs and not claim.inherited_refs:
                last_refs = claim.refs
            claims.append(claim)
            if len(claims) >= max_claims:
                return claims
    return claims


def claims_from_structured(texts: list[str], max_claims: int = 12) -> list[Claim]:
    """Build claims from an LLM's own atomic-claim decomposition (structured-output path)."""
    claims: list[Claim] = []
    last_refs: list = []
    for i, text in enumerate(texts[:max_claims]):
        claim = build_claim(text, f"C{i + 1}", i, last_refs)
        if claim.refs and not claim.inherited_refs:
            last_refs = claim.refs
        claims.append(claim)
    return claims
