"""Legal-currency checks against the curator-maintained registry (config/legal_currency.yaml)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from core.models import Evidence, LegalRef

ACKNOWLEDGES_RE = re.compile(
    r"struck\s+down|unconstitutional|repeal|no\s+longer|replaced|ceased|invalid|quashed|not\s+in\s+force|"
    r"was\s+(earlier|previously)|formerly|superseded", re.I)


@dataclass
class CurrencyEntry:
    act: str
    section: str
    status: str
    effective: str
    note: str
    authority: str

    def as_evidence(self) -> Evidence:
        ref = "entire Act" if self.section == "*" else f"Section {self.section}"
        return Evidence(chunk_id=f"currency:{self.act}:{self.section}", doc_id="legal-currency-registry",
                        doc_title=f"Legal-currency registry ({self.authority})", act_code=self.act,
                        section="" if self.section == "*" else self.section, ref_type="Section", page_start=0,
                        page_end=0, text=f"{self.note} Authority: {self.authority}.",
                        score=1.0, doc_status="curator-entered", retrievers=["currency_registry"])


@lru_cache(maxsize=4)
def load_registry(path: str) -> tuple[CurrencyEntry, ...]:
    p = Path(path)
    if not p.exists():
        return ()
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return tuple(CurrencyEntry(act=e["act"], section=str(e["section"]), status=e["status"],
                               effective=str(e.get("effective", "")), note=" ".join(str(e["note"]).split()),
                               authority=e.get("authority", "")) for e in data.get("entries", []))


def check_currency(refs: list[LegalRef], claim_text: str, registry_path: str) -> tuple[str, CurrencyEntry | None]:
    """Returns ('ok'|'outdated'|'acknowledged', entry)."""
    for ref in refs:
        for entry in load_registry(registry_path):
            if entry.act == ref.act_code and entry.section in ("*", ref.number):
                if ACKNOWLEDGES_RE.search(claim_text):
                    return "acknowledged", entry
                return "outdated", entry
    return "ok", None
