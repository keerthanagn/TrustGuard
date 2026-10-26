"""Optional structured-output generation: the model returns JSON claims, each with its own citation(s).

Why optional and off by default: TrustGuard's headline property is that verification is INDEPENDENT of
the generating model. The rule-based claim extractor preserves that. This structured path asks the model
to decompose its own answer into atomic claims with self-citations, which can improve claim boundaries
for long answers - but the self-citations are treated as hints only and are RE-VERIFIED independently;
they never influence the verdict. Enable with verification.structured_claims=true.

Robust parsing: models wrap JSON in prose or code fences, so we extract the first balanced JSON object
and validate it with Pydantic; any failure falls back to the rule-based extractor (fail-safe).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

from pydantic import BaseModel, Field, ValidationError

log = logging.getLogger("trustguard.llm")

STRUCTURED_SYSTEM = (
    "You are a legal information assistant for Indian law. Answer ONLY from the supplied evidence passages.\n"
    "Return a single JSON object, and nothing else, with this exact shape:\n"
    '{"abstain": false, "answer": "<full prose answer>", '
    '"claims": [{"text": "<one atomic legal statement>", "cites": ["S1"]}]}\n'
    "Rules:\n"
    "- Each claim is ONE atomic legal fact naming the act and section/article, taken only from the evidence.\n"
    "- `cites` lists the evidence ids (e.g. S1, S2) that support that claim.\n"
    "- Use exact punishments, amounts, durations and conditions from the evidence; invent nothing.\n"
    "- If the evidence does not answer the question, set \"abstain\": true, \"answer\" to the abstention "
    "sentence, and \"claims\": [].\n"
    "- Output must be valid JSON. No markdown, no commentary outside the JSON."
)


class StructuredClaim(BaseModel):
    text: str = Field(min_length=3, max_length=600)
    cites: list[str] = Field(default_factory=list)


class StructuredAnswer(BaseModel):
    abstain: bool = False
    answer: str = ""
    claims: list[StructuredClaim] = Field(default_factory=list)


def _extract_json(text: str) -> Optional[str]:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.I | re.M).strip()
    start = text.find("{")
    if start < 0:
        return None
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            esc = (ch == "\\" and not esc)
            if ch == '"' and not esc:
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def parse_structured(raw: str) -> Optional[StructuredAnswer]:
    blob = _extract_json(raw)
    if not blob:
        return None
    try:
        return StructuredAnswer.model_validate(json.loads(blob))
    except (json.JSONDecodeError, ValidationError) as exc:
        log.info("Structured-output parse failed (%s); falling back to rule-based extraction", exc)
        return None
