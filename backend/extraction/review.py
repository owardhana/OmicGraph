"""Review read-surface for the admin dashboard (Feature 2 P3, ADR-0014).

Read-only shaping over `:CandidateEdge` / `:CandidateEvidence`. Two jobs the raw
`list_candidates` surface doesn't do:

- **Resolve endpoint ids -> names.** Candidates store `subject_id`/`object_id` as raw
  strings (`ENSG…`/`UniProt`/`EFO…`); the reviewer needs "TP53" / "breast cancer".
- **No confidence floor** (ADR-0014 §4). Sub-floor candidates are exactly the ones
  auto-promote will never touch, so they are the whole reason manual review exists —
  confidence is a sort key here, never a gate.

Writes (approve/reject/revert) live on the ValidationAgent; this module only reads.
"""

from __future__ import annotations

from backend.extraction.stage import (
    _KIND_MAP,
    _SYMMETRIC,
    endpoints_view,
    trusted_edge_exists,
)

_STATUSES = {"pending", "promoted", "rejected"}
# sort key -> Cypher ORDER BY clause (allowlist; never interpolate user input raw).
_SORTS = {
    "confidence": "ce.confidence DESC, ce.n_affirm DESC",
    "n_affirm": "ce.n_affirm DESC, ce.confidence DESC",
    "recent": "ce.last_seen DESC",
}
# Surface contradicting evidence first, then support, then hedges (ADR-0014 payload).
_POLARITY_ORDER = {"negate": 0, "affirm": 1, "hedge": 2}


def _endpoint(kind: str, node_id: str, name_map: dict[tuple[str, str], str]) -> dict:
    return {"id": node_id, "kind": kind, "name": name_map.get((kind, node_id), node_id)}


def evidence_sort_key(ev: dict) -> tuple[int, str]:
    """Order evidence so contradicting (negate) rows surface first, then support, then
    hedges; stable by extracted_at within a polarity (ADR-0014 payload — negate shown,
    not just counted)."""
    return (_POLARITY_ORDER.get(ev.get("polarity"), 3), ev.get("extracted_at") or "")


async def _resolve_names(session, refs: list[tuple[str, str]]) -> dict[tuple[str, str], str]:
    """Map (kind, id) -> display name. One query per label (3 max), not per row."""
    by_kind: dict[str, set[str]] = {}
    for kind, node_id in refs:
        if kind in _KIND_MAP and node_id:
            by_kind.setdefault(kind, set()).add(node_id)

    out: dict[tuple[str, str], str] = {}
    for kind, ids in by_kind.items():
        label, idf = _KIND_MAP[kind]
        rows = await (
            await session.run(
                f"MATCH (n:{label}) WHERE n.{idf} IN $ids "
                f"RETURN n.{idf} AS id, coalesce(n.hgnc_symbol, n.name, n.{idf}) AS name",
                ids=list(ids),
            )
        ).data()
        for r in rows:
            out[(kind, r["id"])] = r["name"]
    return out


async def list_for_review(session, status: str = "pending",
                          sort: str = "confidence", limit: int = 100) -> list[dict]:
    """Review queue for one status tab. NOT confidence-gated (ADR-0014 §4)."""
    status = status if status in _STATUSES else "pending"
    order = _SORTS.get(sort, _SORTS["confidence"])
    rows = await (
        await session.run(
            f"MATCH (ce:CandidateEdge) WHERE ce.status = $status "
            f"RETURN properties(ce) AS props ORDER BY {order} LIMIT $limit",
            status=status, limit=limit,
        )
    ).data()
    cands = [r["props"] for r in rows]

    refs = [(c.get("subject_kind"), c.get("subject_id")) for c in cands] + \
           [(c.get("object_kind"), c.get("object_id")) for c in cands]
    names = await _resolve_names(session, refs)

    return [
        {
            "triple_key": c.get("triple_key"),
            "rel_type": c.get("rel_type"),
            "symmetric": c.get("rel_type") in _SYMMETRIC,
            "subject": _endpoint(c.get("subject_kind"), c.get("subject_id"), names),
            "object": _endpoint(c.get("object_kind"), c.get("object_id"), names),
            "status": c.get("status"),
            "confidence": c.get("confidence"),
            "n_affirm": c.get("n_affirm"),
            "n_negate": c.get("n_negate"),
            "first_seen": c.get("first_seen"),
            "last_seen": c.get("last_seen"),
            "promotion_kind": c.get("promotion_kind"),
        }
        for c in cands
    ]


async def _endpoint_context(session, kind: str, node_id: str) -> dict:
    """Existing node's display name, degree, and a short summary snippet — helps the
    reviewer judge the entity. Empty dict if the node isn't found."""
    if kind not in _KIND_MAP or not node_id:
        return {}
    label, idf = _KIND_MAP[kind]
    rows = await (
        await session.run(
            f"MATCH (n:{label} {{{idf}: $id}}) "
            f"RETURN coalesce(n.hgnc_symbol, n.name, $id) AS name, "
            "       coalesce(n.summary_text, n.description, '') AS summary, "
            "       count { (n)--() } AS degree",
            id=node_id,
        )
    ).data()
    if not rows:
        return {}
    r = rows[0]
    summary = r["summary"] or ""
    return {"name": r["name"], "degree": r["degree"],
            "summary": summary[:280] + ("…" if len(summary) > 280 else "")}


async def candidate_detail(session, triple_key: str) -> dict | None:
    """Full review payload for one candidate (ADR-0014 detail shape)."""
    rows = await (
        await session.run(
            "MATCH (ce:CandidateEdge {triple_key: $tk}) RETURN properties(ce) AS props",
            tk=triple_key,
        )
    ).data()
    if not rows:
        return None
    ce = rows[0]["props"]

    ev_rows = await (
        await session.run(
            "MATCH (ce:CandidateEdge {triple_key: $tk})<-[:SUPPORTS]-(ev:CandidateEvidence) "
            "RETURN properties(ev) AS props",
            tk=triple_key,
        )
    ).data()
    evidence = sorted((e["props"] for e in ev_rows), key=evidence_sort_key)

    names = await _resolve_names(
        session,
        [(ce.get("subject_kind"), ce.get("subject_id")),
         (ce.get("object_kind"), ce.get("object_id"))],
    )

    # would_be_action is a meaningful PREVIEW only for a pending candidate. Once promoted,
    # the trusted edge exists (we made it), so a recomputed preview would wrongly read
    # "ENRICH" for something we MINTED — report what actually happened instead.
    would_be_action = None
    if ce.get("status") == "pending":
        would_be_action = "ENRICH" if await trusted_edge_exists(session, endpoints_view(ce)) else "MINT"

    return {
        "proposed_change": {
            "rel_type": ce.get("rel_type"),
            "symmetric": ce.get("rel_type") in _SYMMETRIC,
            "subject": _endpoint(ce.get("subject_kind"), ce.get("subject_id"), names),
            "object": _endpoint(ce.get("object_kind"), ce.get("object_id"), names),
            "would_be_action": would_be_action,
        },
        "scoring": {
            "confidence": ce.get("confidence"),
            "n_affirm": ce.get("n_affirm"),
            "n_negate": ce.get("n_negate"),
            "status": ce.get("status"),
            "first_seen": ce.get("first_seen"),
            "last_seen": ce.get("last_seen"),
            "promotion_kind": ce.get("promotion_kind"),
            "promoted_at": ce.get("promoted_at"),
        },
        "evidence": [
            {
                "pmid": e.get("pmid"),
                "sentence_span": e.get("sentence_span"),
                "polarity": e.get("polarity"),
                "model_conf": e.get("model_conf"),
                "model": e.get("model"),
                "extracted_at": e.get("extracted_at"),
            }
            for e in evidence
        ],
        "endpoint_context": {
            "subject": await _endpoint_context(session, ce.get("subject_kind"), ce.get("subject_id")),
            "object": await _endpoint_context(session, ce.get("object_kind"), ce.get("object_id")),
        },
        "agent_profiling": {
            "source_agent": ce.get("source_agent"),
            "agent_version": ce.get("agent_version"),
            "provenance_tier": ce.get("provenance_tier"),
        },
    }
