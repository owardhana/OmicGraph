# ADR 0014 — Literature review dashboard (human-gate, not author)

Status: Accepted + Implemented (2026-07-03)

Governs the admin review surface for [Feature 2](../design/feature-2-literature-extraction.md)
(literature extraction). Extends the trust firewall of
[ADR-0013](0013-literature-extraction-trust-model.md): that ADR fixed how candidates are
*stored* and *weighted*; this one fixes how a human *acts* on them.

## Context

Auto-promotion is uncalibrated and default-OFF (`VALIDATION_AUTO_PROMOTE_ENABLED`), so
**manual review is currently the only safe promotion path** — yet there is no surface for
it. The `ValidationAgent.approve/reject` endpoints exist; today they are only reachable by
`curl`. Building the review UI raises three decisions that are **hard to reverse once the
dashboard is minting trusted topology**, and that a future reader would question. They are
recorded here; the mechanical spec (endpoints, payload, layout) lives in the
[design doc](../design/feature-2-literature-extraction.md#admin-review-dashboard-p3).

## Decision

### 1. The reviewer *gates* biology; it never *authors* it — no edit-before-approve

The dashboard offers exactly three verbs: **approve**, **reject**, **revert**. There is
**no "edit the proposal then approve"** — a reviewer cannot change a candidate's endpoints,
edge type, or direction and then promote it.

Editing-then-approving would make a human the *author* of graph topology through the same
write path the agent uses, with none of the agent's provenance (no PMID, no evidence span,
no confidence derivation). That reintroduces exactly the "a person asserted biology from
memory" failure the firewall exists to prevent. If a proposal is wrong, the correct action
is **reject** — the biology it claims is simply not admitted. Hand-authored curation, if
ever wanted, is a separate deliberate feature with its own provenance, not a side effect of
the review queue.

### 2. Revert is fully reversible by recording the exact promotion delta (option A)

Promotion has two branches (`_promote_one`): **MINT** a new literature-tier edge, or
**ENRICH** an existing canonical edge by appending PMIDs. Revert must undo either **without
corrupting canonical data** — the ENRICH branch appends only PMIDs *not already present*, so
a naive "strip the candidate's affirming PMIDs" would delete a citation that legitimately
belongs to the canonical edge (concrete risk: P3 adds `REGULATES`, which `CitationAgent`
already cites → shared PMIDs).

Decision: **promotion records the exact set it changed**, and revert removes exactly that
set.

- **ENRICH:** promotion writes `ce.enriched_pmids = [x IN affirming WHERE NOT x IN existing]`
  — the precise delta added. Revert removes exactly `ce.enriched_pmids` from the canonical
  edge's `pmids[]` (and clears `lit_enriched` iff no literature PMIDs remain), then resets
  the candidate to `pending`. The canonical edge, its `source_db`, and its pre-existing
  citations are untouched.
- **MINT:** revert deletes the promoted edge **iff `provenance_tier='literature'`** (a guard
  that makes it structurally impossible to delete a canonical edge), then resets the
  candidate to `pending`.

Rejected the simpler "revert is MINT-only, ENRICH is not revertible": recording the delta is
cheap, and leaving a whole class of promotions un-undoable is a worse floor for a
trusted-topology tool.

### 3. Access is a single admin token, not a user/RBAC system

The dashboard writes trusted topology, so it cannot sit open in the public graph viewer —
but full user-accounts/RBAC is out of scope ([vision-and-mvp](../vision-and-mvp.md)). The
review surface is gated by a single `ADMIN_TOKEN` (header-checked), the `/admin` route is
hidden without it, and **all** write routes keep the existing `EXTRACTION_AGENT_ENABLED`
master gate. On the public Oracle host, Caddy basic-auth sits in front as a second layer.

### 4. The review list is not confidence-gated

`list_candidates` bakes in `WHERE confidence >= EXTRACTION_CONFIDENCE_FLOOR` (it was a
"strongest first" convenience surface). The review dashboard must **not** inherit that gate:
the sub-floor candidates are precisely the ones auto-promote will never touch, so they are
the whole reason manual review exists. On the admin surface confidence is a **sortable /
filterable column, never a hard cutoff.**

## Consequences

- `stage.py` gains two persisted evidence fields (`model`, `extracted_at`) so the panel can
  profile *which model/version proposed this, when* (design-doc schema already promised them).
- `_promote_one` (ENRICH branch) gains `ce.enriched_pmids` bookkeeping; a new `revert` verb
  joins `approve`/`reject` on the `ValidationAgent`.
- A new read endpoint resolves candidate endpoint **ids → names** (they are stored as raw
  `ENSG…`/`EFO…` strings) and returns the `:CandidateEvidence` chain — the dashboard's core
  payload.
- `would_be_action` (MINT vs ENRICH) is shown as an **advisory preview**; `_promote_one`
  re-checks `trusted_edge_exists` at click time, which remains authoritative (a canonical
  edge appearing between view and click flips MINT→ENRICH correctly).

## Rejected alternatives

- **Edit-before-approve.** Rejected — see Decision 1 (human becomes an un-provenanced author).
- **Revert as MINT-only, ENRICH irreversible.** Rejected — see Decision 2 (delta bookkeeping
  is cheap; a half-revertible tool is a poor trust floor).
- **Full user accounts / RBAC for the dashboard.** Rejected for MVP — a single admin token +
  the existing master gate + Caddy basic-auth is proportionate for a personal/admin tool;
  RBAC returns only with multi-user (the same trigger as the AuraDB migration).
- **Reuse `list_candidates` as-is for the queue.** Rejected — its confidence floor hides the
  exact candidates manual review is for (Decision 4).
