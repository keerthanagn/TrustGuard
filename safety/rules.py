"""Rule layer for malicious-content screening.

Separates operational intent ("how to do X") from legal/educational discussion ("X is an offence under
section Y"). Only operational harmful content drives a BLOCK from rules; discussion is down-weighted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Harm categories with surface patterns. These are deliberately conservative and are combined with an
# intent signal; a pattern alone does not block, because legal answers legitimately name these offences.
CATEGORY_PATTERNS: dict[str, list[str]] = {
    "credential_theft": [
        r"\bphish(ing|e?r)?\b", r"ste[a']?l\s+(the\s+|their\s+|his\s+|her\s+|your\s+|a\s+)?(password|credential|login)",
        r"keylogg", r"fake\s+login\s+page", r"harvest\s+credentials",
        r"capture\s+(the\s+|their\s+|his\s+|her\s+|your\s+|a\s+)?(otp|password|credential)",
    ],
    "malware": [
        r"\b(write|create|build|develop|code|generate)\s+(a\s+)?(virus|worm|trojan|ransomware|malware|rootkit|botnet)\b",
        r"\bransomware\b", r"\bkeylogger\b", r"payload\s+that", r"reverse\s+shell", r"obfuscate\s+(the\s+)?(payload|malware)",
    ],
    "unauthorized_access": [
        r"\b(hack|break)\s+into\b",
        r"\bhack(ing|ed)?\s+(a|an|the|my|your|their|into)?\s*(\w+\s+)?(server|system|account|network|web\s?site|computer|database|device|wi-?fi|portal)\b",
        r"gain\s+unauthori[sz]ed\s+access", r"bypass\s+(the\s+)?(authentication|login|2fa|mfa|paywall)",
        r"crack\s+(the\s+)?(password|wifi|hash)", r"brute[\s-]?force\s+(the\s+)?(login|password)", r"sql\s*injection\s+to",
        r"privilege\s+escalation\s+to", r"exploit\s+to\s+gain",
    ],
    "data_exfiltration": [
        r"exfiltrat", r"dump\s+(the\s+)?(database|db|user\s+data)", r"steal\s+(the\s+)?(data|database|records|files)",
        r"leak\s+(the\s+)?(data|database|customer)", r"scrape\s+and\s+sell",
    ],
    "physical_harm": [
        r"\b(build|make|construct|synthesi[sz]e)\s+(a\s+)?(bomb|explosive|weapon|poison)\b",
        r"how\s+to\s+(kill|murder|poison)\s+(a\s+)?(person|someone|people)",
    ],
    "fraud": [
        r"launder\s+(the\s+)?money", r"evade\s+(tax|taxes)\s+by", r"forge\s+(a\s+)?(document|signature|certificate)",
        r"counterfeit\s+", r"clone\s+(a\s+)?(card|sim)",
    ],
}

OPERATIONAL_CUES = [
    r"step[\s-]?by[\s-]?step", r"\bhere(?:'s| is| are)\b.{0,30}\b(how|steps|code|script|way)\b",
    r"\bhow\s+(to|do\s+i|can\s+i|would\s+i)\b", r"\bfollow\s+these\b", r"first,?\s+you",
    r"\byou\s+(can|should|must|need to|will)\s+\w+", r"```", r"\bimport\s+\w+", r"\bdef\s+\w+\(",
    r"use\s+(the\s+)?following\s+(code|command|script)", r"\brun\s+(the\s+)?(following|this)\b",
    r"\bexecute\s+", r"\bpayload\b", r"instructions?\s+(to|for|on)\b", r"\b\d\.\s+\w+.*\n\s*\d\.\s+",
    r"the\s+process\s+is",
    # imperative requests to produce a harmful artefact
    r"\b(write|create|make|build|generate|draft|compose|provide|give\s+me|send|develop|design|show\s+me)\s+"
    r"(me\s+)?(a|an|the|some|working|me a|detailed)\b",
    r"\bexplain\s+(in\s+detail\s+)?how\b", r"\bteach\s+me\b", r"\bhelp\s+me\s+\w+",
    r"\bwalk\s+(me\s+)?through\b", r"\bguide\s+me\b", r"\bshow\s+me\s+how\b",
    # bare imperative to create a harmful artefact or perform an intrusive action (no article needed)
    r"\b(write|create|build|develop|generate|make|code|program)\s+(me\s+)?(a|an|the|some|working)?\s*"
    r"(malware|ransomware|virus|worm|trojan|spyware|keylogger|rootkit|botnet|exploit|payload|backdoor)\b",
    r"\b(install|deploy|plant|embed|inject|set\s*up)\s+(a|an|the|my|your|their|some|it)?\s*\w+",
]

LEGAL_CONTEXT_CUES = [
    r"\bsection\s+\d", r"\barticle\s+\d", r"\bpunishab", r"\boffen[cs]e\b", r"\billegal\b", r"\bprohibited\b",
    r"\bliable\b", r"\bpenalt", r"\bconvict", r"is\s+a\s+crime", r"against\s+the\s+law", r"\bimprison",
    r"\bfine\b", r"sanhita", r"\bconstitution\b", r"it\s+act", r"\bshall\s+be\s+punished\b", r"\bcognizable\b",
    r"educational\s+purpose", r"for\s+awareness", r"\bcybersecurity\b.{0,20}\b(defen[cs]e|awareness|protect)",
]


@dataclass
class RuleHit:
    category: str
    pattern: str
    snippet: str


def _find(patterns: list[str], text: str) -> list[tuple[str, str]]:
    out = []
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            out.append((p, m.group(0)))
    return out


def analyse(text: str) -> dict:
    """Return rule hits, operational-intent signal and legal-context signal for the text."""
    category_hits: list[RuleHit] = []
    for cat, pats in CATEGORY_PATTERNS.items():
        for pat, snip in _find(pats, text):
            category_hits.append(RuleHit(cat, pat, snip))
    operational = [m for p in OPERATIONAL_CUES for m in [re.search(p, text, re.I)] if m]
    legal = [m for p in LEGAL_CONTEXT_CUES for m in [re.search(p, text, re.I)] if m]
    categories = sorted({h.category for h in category_hits})
    op_count = len(operational)
    legal_count = len(legal)
    # score: harmful category + operational phrasing raises risk; dense legal framing lowers it
    operational_and_harmful = bool(category_hits and op_count >= 1 and op_count > legal_count)
    # explicit artefact cues ("step-by-step", "code", "script") signal a request to *do* harm, not discuss it
    artefact = bool(re.search(r"step[\s-]?by[\s-]?step|\bcode\b|\bscript\b|\bpayload\b|working\s+\w+", text, re.I))
    raw = 0.0
    if category_hits:
        raw = 0.35 + 0.12 * min(len(categories), 3)
        raw += 0.18 * min(op_count, 3)
        raw -= 0.12 * min(legal_count, 4)
        if operational_and_harmful and artefact:
            raw += 0.2
    elif op_count and re.search(r"\b(bomb|malware|ransomware|phish|exploit|hack)\b", text, re.I):
        raw = 0.3 + 0.1 * op_count
    score = max(0.0, min(1.0, raw))
    return {
        "categories": categories,
        "hits": [h.__dict__ for h in category_hits],
        "operational": op_count,
        "legal_context": legal_count,
        "rule_score": round(score, 3),
        "operational_and_harmful": operational_and_harmful,
    }
