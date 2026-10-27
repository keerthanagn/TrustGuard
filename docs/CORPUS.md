# TrustGuard legal corpus inventory

Generated from the live knowledge base and `reports/corpus_import.json`. All documents are seeded as
**unreviewed** (provenance recorded, not yet independently human-verified) and are excluded from current-law
retrieval only when marked **outdated**.

## Indexed documents (current)

| Act | Code | Status | Pages | Chunks | Sections | Source | In force |
|---|---|---|---|---:|---:|---|---|
| Bharatiya Nyaya Sanhita, 2023 (Act 45) | BNS | unreviewed | 102 | 536 | 358 | eGazette 250883 | 2024-07-01 |
| Bharatiya Nagarik Suraksha Sanhita, 2023 (Act 46) | BNSS | unreviewed | 249 | 1038 | 531 | eGazette 250884 | 2024-07-01 |
| Bharatiya Sakshya Adhiniyam, 2023 (Act 47) | BSA | unreviewed | 47 | 241 | 170 | eGazette 250882 | 2024-07-01 |
| Constitution of India (as on 1 May 2024) | COI | unreviewed | 402 | 1047 | 498 | legislative.gov.in | 1950-01-26 |
| Information Technology Act, 2000 (amended 2008) | ITA | unreviewed | 40 | 169 | 112 | Goa Police consolidated | 2000-10-17 |
| Right to Information Act, 2005 (Act 22) | RTI | unreviewed | 25 | 82 | 31 | India Code aa2005 | 2005-10-12 |

## Historical / superseded (excluded from current-law retrieval by default)

| Act | Code | Status | Why |
|---|---|---|---|
| Information Technology Act, 2000 (original) | ITA | outdated | superseded by the 2008 amendment |

## Imported this phase (Phase 2)

Via `python -m scripts.import_corpus` (manifest: `config/corpus_manifest.yaml`). Official sources only
(eGazette / India Code / MHA), tried in priority order with timeouts, retries, and a curl TLS fallback.

**Succeeded:** BNSS (eGazette), BSA (eGazette), RTI (India Code).

**Awaiting retry (official source unreachable at import time):**

| Act | Code | Reason |
|---|---|---|
| Consumer Protection Act, 2019 | CPA | India Code (indiacode.nic.in) returned HTTP 504 on all paths |
| Motor Vehicles Act, 1988 | MVA | India Code returned HTTP 504 |
| Protection of Women from Domestic Violence Act, 2005 | PWDVA | India Code returned HTTP 504 |

India Code was intermittently unreachable during import (it served RTI but 504'd for the three above).
The import is **idempotent and retryable** — re-run `python -m scripts.import_corpus --only CPA MVA PWDVA`
when the source is up; successful documents are not re-imported. No unofficial copy was substituted, and
no Act is marked indexed unless its document and index entries were verified.

## Provenance & review

- Every document stores: `doc_type`, `jurisdiction`, `source_url`, `version`, `effective_date`, `licence`,
  `sha256`, extraction page/chunk/section counts, and `status`.
- Licence: Government of India official public legal documents.
- Review status is **unreviewed** until a curator authenticates the text against the official gazette on
  the Knowledge Base page. "Unreviewed" documents are retrieved and cited, but the UI labels them as not
  independently verified.
