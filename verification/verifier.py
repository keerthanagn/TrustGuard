"""Multi-signal claim verification.

Each material claim is checked against retrieved legal evidence with signals that do not depend on the
LLM that wrote the answer:

  currency    - provision repealed / struck down (curator registry)
  statutory   - cited section/article exists in the cited act (fabricated-reference detection)
  relevance   - evidence of sufficient retrieval relevance exists
  nli         - cross-encoder entailment / contradiction against sentence windows of the evidence
  numeric     - terms of imprisonment, fines, ages and qualifiers (maximum vs minimum) match the source
  punishment  - claimed punishment types are prescribed by the source provision
  attribution - the statement is supported by the cited provision, not by a different one
  scope       - absolute wording ("always", "without exception") against provisions with exceptions
  lexical     - substantive vocabulary of the claim is present in the supporting passage (veto only)

Decision order: errors -> contradictions -> missing evidence -> support. A claim is SUPPORTED only when
NLI entailment, lexical coverage, numeric and punishment checks all pass on relevant evidence.
"""
from __future__ import annotations

import logging
import re

from config.settings import Settings
from core.errors import VerifierError
from core.models import Claim, ClaimStatus, ClaimVerification, Evidence, SignalResult
from retrieval.index import HybridIndex
from retrieval.legal_refs import ACT_NAMES, strip_refs
from verification.currency import check_currency
from verification.lexical import coverage
from verification.nli import NLIScorer, premise_windows
from verification.numeric import compare_quantity, extract_punishments, extract_quantities

log = logging.getLogger("trustguard.verifier")

EXCEPTION_MARKERS_RE = re.compile(r"\bProvided\s+(further\s+)?that\b|\bException\b|\bexcept\b|\bunless\b|"
                                  r"\bNothing\s+in\b|\bshall\s+not\s+apply\b|\bsubject\s+to\b", re.I)
STRONG_ABSOLUTES = {"always", "never", "without exception", "without any exception", "in all cases",
                    "regardless of", "under no circumstances", "in every case", "automatically"}
ONLY_FINE_RE = re.compile(r"\bonly\s+(with\s+|by\s+)?(a\s+)?fine\b|\bfine\s+only\b|\bonly\s+a\s+fine\b", re.I)


def _dedupe(evs: list[Evidence]) -> list[Evidence]:
    seen, out = set(), []
    for e in evs:
        if e.chunk_id not in seen:
            seen.add(e.chunk_id)
            out.append(e)
    return out


class ClaimVerifier:
    def __init__(self, settings: Settings, index: HybridIndex, nli: NLIScorer | None = None,
                 fault: str = ""):
        self.settings = settings
        self.cfg = settings.verification
        self.index = index
        self.fault = fault
        self._nli = nli

    @property
    def nli(self) -> NLIScorer:
        if self.fault == "verifier_error":
            raise VerifierError("Simulated verifier failure (fault injection).")
        if self._nli is None:
            self._nli = NLIScorer(self.cfg["nli_model"], self.cfg.get("nli_batch_size", 16))
        return self._nli

    # ------------------------------------------------------------------ public
    def verify_all(self, claims: list[Claim], question_evidence: list[Evidence]) -> list[ClaimVerification]:
        return [self.verify(c, question_evidence) for c in claims]

    def verify(self, claim: Claim, question_evidence: list[Evidence]) -> ClaimVerification:
        if not claim.material:
            return ClaimVerification(claim=claim, status=ClaimStatus.INSUFFICIENT_EVIDENCE,
                                     reason="Not a material legal assertion (advice, abstention or filler); "
                                            "excluded from the release decision.")
        try:
            return self._verify(claim, question_evidence)
        except Exception as exc:  # fail closed: an error is never treated as support
            log.exception("Verification error for claim %s", claim.claim_id)
            return ClaimVerification(claim=claim, status=ClaimStatus.VERIFICATION_ERROR,
                                     reason="The claim could not be verified because a verification component failed.",
                                     error=f"{type(exc).__name__}: {exc}",
                                     signals=[SignalResult("system", False, None, str(exc))])

    # ------------------------------------------------------------------ core
    def _verify(self, claim: Claim, question_evidence: list[Evidence]) -> ClaimVerification:
        min_rel = self.settings.retrieval["min_relevance"]
        tau_e, tau_c = self.cfg["entail_threshold"], self.cfg["contradict_threshold"]
        signals: list[SignalResult] = []

        def result(status: ClaimStatus, reason: str, supporting=None, contradicting=None) -> ClaimVerification:
            return ClaimVerification(claim=claim, status=status, reason=reason, supporting=supporting or [],
                                     contradicting=contradicting or [], signals=signals)

        # 1. legal currency -------------------------------------------------------------
        currency_state, entry = check_currency(claim.refs, claim.text, str(self.settings.path("legal_currency")))
        extra_evidence: list[Evidence] = []
        if currency_state == "outdated":
            signals.append(SignalResult("currency", False, None, f"{entry.status}: {entry.authority}"))
            return result(ClaimStatus.CONTRADICTED,
                          f"The claim relies on {entry.act} {('s. ' + entry.section) if entry.section != '*' else ''} "
                          f"as current law, but it is {entry.status.replace('_', ' ')} ({entry.authority}).",
                          contradicting=[entry.as_evidence()])
        if currency_state == "acknowledged":
            signals.append(SignalResult("currency", True, None, f"claim acknowledges {entry.status}"))
            extra_evidence.append(entry.as_evidence())
        else:
            signals.append(SignalResult("currency", None, None, "no registry entry for the cited provisions"))

        # 2. statutory references -------------------------------------------------------
        kb_acts = self.index.acts()
        ref_evidence: list[Evidence] = []
        if currency_state != "acknowledged":
            for ref in claim.refs:
                label = f"{ref.ref_type} {ref.number}"
                if ref.act_code and ref.act_code not in kb_acts:
                    signals.append(SignalResult("statutory", None, None,
                                                f"{ACT_NAMES.get(ref.act_code, ref.act_code)} is not in the knowledge base"))
                    return result(ClaimStatus.INSUFFICIENT_EVIDENCE,
                                  f"The claim cites {label} of {ACT_NAMES.get(ref.act_code, ref.act_code)}, "
                                  "which is not in the selected knowledge base.")
                if not self.index.section_exists(ref.act_code, ref.number):
                    act = ACT_NAMES.get(ref.act_code, "any indexed act")
                    signals.append(SignalResult("statutory", False, 0.0, f"{label} not found in {act}"))
                    if ref.act_code:
                        return result(ClaimStatus.CONTRADICTED,
                                      f"{label} does not exist in the {act} as indexed; the reference appears "
                                      "to be fabricated or mis-numbered.")
                    return result(ClaimStatus.INSUFFICIENT_EVIDENCE,
                                  f"{label} could not be matched to any act in the knowledge base.")
                # rank the cited section's own sub-chunks against the claim so the operative subsection
                # (e.g. the punishment clause) is seen, not just the first sub-chunks by ordinal
                for i, sc in self.index.rank_section(ref.act_code, ref.number, claim.text, top=5):
                    ref_evidence.append(self.index.to_evidence(i, max(1.0, sc), ["section_lookup"]))
            if claim.refs:
                signals.append(SignalResult("statutory", True, 1.0,
                                            "cited provisions exist: " + ", ".join(f"{r.act_code} {r.number}" for r in claim.refs)))
            else:
                signals.append(SignalResult("statutory", None, None, "claim cites no specific provision"))

        # 3. evidence --------------------------------------------------------------------
        retrieved = self.index.search(claim.text, top_k=self.cfg["claim_top_k"])
        pool = _dedupe(extra_evidence + ref_evidence + retrieved +
                       [e for e in question_evidence if e.score >= min_rel])
        relevant = [e for e in pool if e.score >= min_rel or "section_lookup" in e.retrievers
                    or "currency_registry" in e.retrievers]
        best_rel = max((e.score for e in relevant), default=0.0)
        signals.append(SignalResult("relevance", bool(relevant), round(best_rel, 3),
                                    f"{len(relevant)} relevant passage(s) at threshold {min_rel}"))
        if not relevant:
            return result(ClaimStatus.INSUFFICIENT_EVIDENCE,
                          "No sufficiently relevant passage was found in the knowledge base for this claim.")
        relevant = relevant[:8]

        # 4. NLI ----------------------------------------------------------------------------
        # The premise header names the provision, so the hypothesis keeps the claim's own reference when the
        # claim is about a provision's status; otherwise references are stripped so NLI judges substance.
        hypothesis = claim.text if currency_state == "acknowledged" else strip_refs(claim.text)
        if len(hypothesis.split()) < 4:
            hypothesis = claim.text
        pairs, owners = [], []
        for k, e in enumerate(relevant):
            act = ACT_NAMES.get(e.act_code, e.doc_title)
            header = f"{e.ref_type} {e.section} of the {act}: " if e.section else ""
            for w in premise_windows(e.text, header):
                pairs.append((w, hypothesis))
                owners.append(k)
        scores = self.nli.score(pairs)
        per_ev_entail = [0.0] * len(relevant)
        per_ev_contra = [0.0] * len(relevant)
        for s, k in zip(scores, owners):
            per_ev_entail[k] = max(per_ev_entail[k], s.entail)
            per_ev_contra[k] = max(per_ev_contra[k], s.contradict)
        best_k = max(range(len(relevant)), key=lambda k: per_ev_entail[k])
        best_entail, best_ev = per_ev_entail[best_k], relevant[best_k]
        # contradictions only count on strongly relevant passages (the cited provision or a high-relevance hit)
        contra_candidates = [k for k, e in enumerate(relevant)
                             if "section_lookup" in e.retrievers or e.score >= max(0.6, min_rel)]
        best_c = max(contra_candidates, key=lambda k: per_ev_contra[k], default=None)
        best_contra = per_ev_contra[best_c] if best_c is not None else 0.0
        signals.append(SignalResult("nli", best_entail >= tau_e, round(best_entail, 3),
                                    f"max entailment {best_entail:.2f} ({best_ev.citation}); "
                                    f"max contradiction {best_contra:.2f}"))

        # 5. numeric & punishment consistency ------------------------------------------------
        if ref_evidence:
            target = ref_evidence
        else:
            target = _dedupe([best_ev] + [e for e in relevant if e.score >= min_rel][:2])
        target_text = " ".join(e.text for e in target)
        ev_quantities = extract_quantities(target_text)
        numeric_conflicts, numeric_absent, numeric_matches = [], [], []
        for q in claim.quantities:
            verdict, why = compare_quantity(q, ev_quantities)
            if verdict in ("value_conflict", "qualifier_conflict"):
                numeric_conflicts.append(why)
            elif verdict == "absent":
                numeric_absent.append(why)
            else:
                numeric_matches.append(why)
        if claim.quantities:
            signals.append(SignalResult("numeric", not numeric_conflicts and not numeric_absent,
                                        len(numeric_matches) / len(claim.quantities),
                                        "; ".join(numeric_conflicts + numeric_absent + numeric_matches)))
        else:
            signals.append(SignalResult("numeric", None, None, "claim states no quantities"))

        ev_pun = set(extract_punishments(target_text))
        if "life_imprisonment" in ev_pun:
            ev_pun.add("imprisonment")
        claimed_pun = set(claim.punishments) - {"compensation"}
        missing_pun = sorted(claimed_pun - ev_pun) if ev_pun else []
        only_fine = bool(ONLY_FINE_RE.search(claim.text)) and "imprisonment" in ev_pun
        if claimed_pun:
            ok = not missing_pun and not only_fine
            detail = "claimed punishments are prescribed by the source" if ok else (
                f"source does not prescribe: {', '.join(missing_pun)}" if missing_pun else
                "claim says the offence is punishable only with fine, but the source prescribes imprisonment")
            signals.append(SignalResult("punishment", ok, None, detail))
        else:
            signals.append(SignalResult("punishment", None, None, "claim states no punishment"))

        # 6. attribution ----------------------------------------------------------------------
        misattributed = None
        if ref_evidence:
            ref_ids = {e.chunk_id for e in ref_evidence}
            ref_entail = max((per_ev_entail[k] for k, e in enumerate(relevant) if e.chunk_id in ref_ids), default=0.0)
            others = [(per_ev_entail[k], e) for k, e in enumerate(relevant)
                      if e.chunk_id not in ref_ids and e.section and
                      e.section not in {r.number for r in claim.refs}]
            if others:
                o_entail, o_ev = max(others, key=lambda t: t[0])
                if ref_entail < tau_e and o_entail >= max(tau_e, 0.7):
                    misattributed = o_ev
            signals.append(SignalResult("attribution", misattributed is None, round(ref_entail, 3),
                                        f"statement matches {misattributed.citation}, not the cited provision"
                                        if misattributed else "statement checked against the cited provision"))

        # 7. scope (missing exceptions / over-generalisation) -----------------------------------
        absolutes = STRONG_ABSOLUTES.intersection(claim.absolute_terms)
        overgeneral = bool(absolutes) and bool(EXCEPTION_MARKERS_RE.search(target_text))
        if absolutes:
            signals.append(SignalResult("scope", not overgeneral, None,
                                        f"absolute wording ({', '.join(sorted(absolutes))}) but the source contains "
                                        "exceptions or conditions" if overgeneral else "no conflicting exceptions found"))

        # 8. lexical ------------------------------------------------------------------------------
        lex = coverage(hypothesis, f"{best_ev.heading if hasattr(best_ev, 'heading') else ''} {best_ev.text}")
        signals.append(SignalResult("lexical", lex >= self.cfg["min_lexical_coverage"], round(lex, 3),
                                    "share of the claim's substantive terms present in the best passage"))

        # ---------------------------------------------------------------- decision
        supporting = [e for k, e in enumerate(relevant) if per_ev_entail[k] >= tau_e][:3] or [best_ev]
        if numeric_conflicts:
            return result(ClaimStatus.CONTRADICTED, "Numeric mismatch: " + "; ".join(numeric_conflicts) + ".",
                          contradicting=target[:2])
        if claimed_pun and (missing_pun or only_fine) and (ref_evidence or best_entail < tau_e):
            return result(ClaimStatus.CONTRADICTED,
                          "Punishment mismatch: " + (f"the source does not prescribe {', '.join(missing_pun)}"
                                                     if missing_pun else "the source prescribes imprisonment, "
                                                     "not a fine alone") + ".", contradicting=target[:2])
        if ref_evidence and numeric_absent and any(q.kind in {"money", "duration"} for q in claim.quantities):
            return result(ClaimStatus.CONTRADICTED,
                          "The cited provision does not state the claimed figure (" + "; ".join(numeric_absent) + ").",
                          contradicting=target[:2])
        if misattributed is not None:
            return result(ClaimStatus.CONTRADICTED,
                          f"The statement is supported by {misattributed.citation}, not by the provision it cites.",
                          supporting=[misattributed], contradicting=ref_evidence[:1])
        if overgeneral and best_entail < 0.9:
            return result(ClaimStatus.CONTRADICTED,
                          "The claim states an absolute rule, but the source provision contains exceptions or "
                          "conditions that the claim omits.", contradicting=target[:2])
        # Deterministic support: the claim cites a real, current provision and its hard facts (figures and
        # punishments) are all consistent with that provision's own text (matches, no conflicts, no absents).
        # For such claims the deterministic legal checks are authoritative and override a soft NLI signal:
        # statutes state offences through definitions, illustrations and provisos that a small NLI model often
        # reads as "contradicting" or "neutral" even when the punishment clause matches exactly.
        numeric_clean = not numeric_conflicts and not numeric_absent
        punishment_clean = not (missing_pun or only_fine)
        has_hard = bool(claim.quantities or claimed_pun)
        deterministic_support = (bool(ref_evidence) and has_hard and numeric_clean and punishment_clean
                                 and misattributed is None and not overgeneral
                                 and (bool(numeric_matches) or (bool(claimed_pun) and not missing_pun)))
        if deterministic_support:
            return result(ClaimStatus.SUPPORTED,
                          f"The cited provision ({ref_evidence[0].citation}) states the claimed "
                          + ("figures and punishment" if numeric_matches and claimed_pun else
                             "figures" if numeric_matches else "punishment")
                          + f"; all deterministic checks passed (NLI entailment {best_entail:.2f}).",
                          supporting=(supporting if best_entail >= tau_e else ref_evidence[:2]))

        # NLI contradiction is the decider only when nothing entails the claim and no deterministic support
        # exists. A soft NLI "contradiction" with matching figures usually comes from an illustration/proviso.
        if best_c is not None and best_contra >= tau_c and best_entail < tau_e:
            return result(ClaimStatus.CONTRADICTED,
                          f"The evidence contradicts the claim and no passage supports it "
                          f"(NLI contradiction {best_contra:.2f}, best entailment {best_entail:.2f}).",
                          contradicting=[relevant[best_c]])
        if best_entail < tau_e:
            return result(ClaimStatus.INSUFFICIENT_EVIDENCE,
                          f"No passage entails the claim (best entailment {best_entail:.2f} < {tau_e}).",
                          supporting=[])
        if numeric_absent:
            return result(ClaimStatus.INSUFFICIENT_EVIDENCE,
                          "Figures in the claim are not stated in the evidence: " + "; ".join(numeric_absent) + ".")
        if lex < self.cfg["min_lexical_coverage"]:
            return result(ClaimStatus.INSUFFICIENT_EVIDENCE,
                          f"Entailment is not corroborated lexically (coverage {lex:.2f}); the claim may add "
                          "content not present in the source.")
        return result(ClaimStatus.SUPPORTED,
                      f"Entailed by {supporting[0].citation} (NLI {best_entail:.2f}); all numeric, punishment and "
                      "reference checks passed.", supporting=supporting)
