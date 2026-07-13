"""ValidationAgent — the promotion gate (Feature 2 P2, ADR-0013).

Promotes a staged CandidateEdge into a REAL typed edge — the one code path that writes
consortium-grade topology — so it is deliberately conservative:

- The promoted edge is permanently tagged ``provenance_tier='literature'`` +
  ``source_db='literature_extracted'`` + its supporting ``pmids`` (so traversal
  discounts it and the UI renders it as "proposed").
- **Auto-promote is UNCALIBRATED and default-OFF** (``VALIDATION_AUTO_PROMOTE_ENABLED``)
  until the precision harness (``RUN_EXTRACTION_EVAL``) produces a number. The safe
  path is manual ``approve``/``reject`` per candidate.
- Re-checks ``trusted_edge_exists`` at promote time (a canonical edge may have appeared
  since staging) — if present, this becomes enrichment (append PMIDs), not a new edge.
- Idempotent: MERGE (not CREATE); re-promotion doesn't duplicate.
"""

import logging

from backend.agents.base_agent import BaseAgent
from backend.config import settings
from backend.db.neo4j_client import get_session
from backend.extraction.stage import (
    _ALLOWED_EDGES,
    _KIND_MAP,
    _SYMMETRIC,
    endpoints_view,
    trusted_edge_exists,
)

logger = logging.getLogger(__name__)


class ValidationAgent(BaseAgent):
    agent_name = "ValidationAgent"
    agent_version = "0.1.0"

    async def _affirming_pmids(self, session, triple_key: str) -> list[str]:
        rows = await (
            await session.run(
                "MATCH (:CandidateEdge {triple_key: $tk})<-[:SUPPORTS]-(ev:CandidateEvidence) "
                "WHERE ev.polarity = 'affirm' RETURN collect(DISTINCT ev.pmid) AS pmids",
                tk=triple_key,
            )
        ).data()
        return rows[0]["pmids"] if rows else []

    async def _promote_one(self, session, ce: dict) -> str:
        """Promote / enrich one candidate. Returns 'promoted' | 'enriched' | 'skipped'."""
        if ce.get("rel_type") not in _ALLOWED_EDGES:
            return "skipped"
        if ce.get("subject_kind") not in _KIND_MAP or ce.get("object_kind") not in _KIND_MAP:
            return "skipped"

        ep = endpoints_view(ce)
        pmids = await self._affirming_pmids(session, ce["triple_key"])
        s_label, s_idf = _KIND_MAP[ce["subject_kind"]]
        o_label, o_idf = _KIND_MAP[ce["object_kind"]]
        arrow = "-" if ce["rel_type"] in _SYMMETRIC else "->"
        params = {
            "tk": ce["triple_key"], "sid": ce["subject_id"], "oid": ce["object_id"],
            "pmids": pmids, "confidence": ce.get("confidence"),
            **self.provenance(),
        }

        if await trusted_edge_exists(session, ep):
            # Canonical edge appeared since staging -> enrich it, don't mint a duplicate.
            # Record the EXACT delta appended (ce.enriched_pmids) so revert removes only
            # what we added and never strips a citation the canonical edge already had
            # (ADR-0014 §2). Delta is computed in the same statement to avoid drift.
            query = (
                f"MATCH (s:{s_label} {{{s_idf}: $sid}})-[r:{ce['rel_type']}]{arrow}"
                f"(o:{o_label} {{{o_idf}: $oid}}) "
                "WITH r, [x IN $pmids WHERE NOT x IN coalesce(r.pmids, [])] AS delta LIMIT 1 "
                "SET r.pmids = coalesce(r.pmids, []) + delta, r.lit_enriched = true "
                "WITH r, delta "
                "MATCH (ce:CandidateEdge {triple_key: $tk}) "
                "SET ce.status = 'promoted', ce.promoted_at = $run_timestamp, "
                "    ce.promotion_kind = 'enrich', ce.enriched_pmids = delta "
                "RETURN count(r) AS n"
            )
            rows = await (await session.run(query, **params)).data()
            return "enriched" if rows and rows[0]["n"] else "skipped"

        # Mint the real typed edge, permanently tiered 'literature'. `r.triple_key` links
        # the edge back to the candidate that produced it (provenance + future deep-link).
        query = (
            f"MATCH (s:{s_label} {{{s_idf}: $sid}}), (o:{o_label} {{{o_idf}: $oid}}) "
            f"MERGE (s)-[r:{ce['rel_type']}]{arrow}(o) "
            "SET r.provenance_tier = 'literature', r.source_db = 'literature_extracted', "
            "    r.pmids = $pmids, r.confidence = $confidence, r.triple_key = $tk, "
            "    r.source_agent = $source_agent, r.agent_version = $agent_version, "
            "    r.run_timestamp = $run_timestamp "
            "WITH r "
            "MATCH (ce:CandidateEdge {triple_key: $tk}) "
            "SET ce.status = 'promoted', ce.promoted_at = $run_timestamp, ce.promotion_kind = 'mint' "
            "RETURN count(r) AS n"
        )
        rows = await (await session.run(query, **params)).data()
        return "promoted" if rows and rows[0]["n"] else "skipped"

    async def _fetch_promotable(self, session) -> list[dict]:
        query = """
        MATCH (ce:CandidateEdge)
        WHERE ce.status = 'pending'
          AND ce.confidence >= $conf
          AND ce.n_affirm >= $min_pmids
          AND coalesce(ce.n_negate, 0) = 0
        RETURN properties(ce) AS props
        """
        rows = await (
            await session.run(
                query,
                conf=settings.VALIDATION_AUTO_PROMOTE_CONFIDENCE,
                min_pmids=settings.VALIDATION_MIN_INDEPENDENT_PMIDS,
            )
        ).data()
        return [r["props"] for r in rows]

    async def run(self) -> dict:
        """Auto-promote pass. No-op unless VALIDATION_AUTO_PROMOTE_ENABLED (uncalibrated)."""
        stats = {"considered": 0, "promoted": 0, "enriched": 0, "skipped": 0,
                 "auto_promote_enabled": settings.VALIDATION_AUTO_PROMOTE_ENABLED}
        if settings.VALIDATION_AUTO_PROMOTE_ENABLED:
            async with get_session() as session:
                candidates = await self._fetch_promotable(session)
                stats["considered"] = len(candidates)
                for ce in candidates:
                    stats[await self._promote_one(session, ce)] += 1
        await self.write_run_log_to_graph("ValidationRun", stats)
        return stats

    async def _fetch_candidate(self, session, triple_key: str) -> dict | None:
        rows = await (
            await session.run(
                "MATCH (ce:CandidateEdge {triple_key: $tk}) RETURN properties(ce) AS props",
                tk=triple_key,
            )
        ).data()
        return rows[0]["props"] if rows else None

    async def approve(self, triple_key: str) -> dict:
        """Manually promote a specific candidate, bypassing the auto-promote threshold."""
        async with get_session() as session:
            ce = await self._fetch_candidate(session, triple_key)
            if ce is None:
                return {"status": "not_found", "triple_key": triple_key}
            if ce.get("status") != "pending":
                return {"status": ce.get("status"), "triple_key": triple_key, "note": "not pending"}
            return {"status": await self._promote_one(session, ce), "triple_key": triple_key}

    async def reject(self, triple_key: str) -> dict:
        """Reject a candidate — kept (flagged, never re-proposed), never deleted."""
        async with get_session() as session:
            rows = await (
                await session.run(
                    "MATCH (ce:CandidateEdge {triple_key: $tk}) "
                    "SET ce.status = 'rejected', ce.rejected_at = $ts "
                    "RETURN count(ce) AS n",
                    tk=triple_key, ts=self.provenance()["run_timestamp"],
                )
            ).data()
        found = bool(rows and rows[0]["n"])
        return {"status": "rejected" if found else "not_found", "triple_key": triple_key}

    async def revert(self, triple_key: str) -> dict:
        """Undo a promotion (ADR-0014 §2) — the one safety net for a mis-clicked approve.

        - MINT  -> delete the promoted edge, guarded on `provenance_tier='literature'` so
          a canonical edge can never be deleted.
        - ENRICH -> remove exactly `ce.enriched_pmids` from the canonical edge's `pmids`
          (the recorded delta; canonical citations survive) and clear `lit_enriched`.

        The candidate is always reset to `pending` (even if the edge match finds nothing),
        so a reverted proposal returns cleanly to the review queue.
        """
        async with get_session() as session:
            ce = await self._fetch_candidate(session, triple_key)
            if ce is None:
                return {"status": "not_found", "triple_key": triple_key}
            if ce.get("status") != "promoted":
                return {"status": ce.get("status"), "triple_key": triple_key,
                        "note": "not promoted"}

            kind = ce.get("promotion_kind")
            s_kind, o_kind = ce.get("subject_kind"), ce.get("object_kind")
            if s_kind in _KIND_MAP and o_kind in _KIND_MAP:
                s_label, s_idf = _KIND_MAP[s_kind]
                o_label, o_idf = _KIND_MAP[o_kind]
                arrow = "-" if ce.get("rel_type") in _SYMMETRIC else "->"
                params = {"sid": ce["subject_id"], "oid": ce["object_id"],
                          "delta": ce.get("enriched_pmids") or []}
                if kind == "mint":
                    await session.run(
                        f"MATCH (s:{s_label} {{{s_idf}: $sid}})"
                        f"-[r:{ce['rel_type']} {{provenance_tier: 'literature'}}]{arrow}"
                        f"(o:{o_label} {{{o_idf}: $oid}}) DELETE r",
                        **params,
                    )
                elif kind == "enrich":
                    await session.run(
                        f"MATCH (s:{s_label} {{{s_idf}: $sid}})-[r:{ce['rel_type']}]{arrow}"
                        f"(o:{o_label} {{{o_idf}: $oid}}) WITH r LIMIT 1 "
                        "SET r.pmids = [x IN coalesce(r.pmids, []) WHERE NOT x IN $delta], "
                        "    r.lit_enriched = null",
                        **params,
                    )

            await session.run(
                "MATCH (ce:CandidateEdge {triple_key: $tk}) "
                "SET ce.status = 'pending', ce.promoted_at = null, "
                "    ce.promotion_kind = null, ce.enriched_pmids = null",
                tk=triple_key,
            )
        return {"status": "reverted", "triple_key": triple_key, "kind": kind}

    async def recent_runs(self, limit: int = 10) -> list[dict]:
        query = """
        MATCH (n:ValidationRun)
        RETURN properties(n) AS props
        ORDER BY n.run_timestamp DESC
        LIMIT $limit
        """
        async with get_session() as session:
            rows = await (await session.run(query, limit=limit)).data()
        return [r["props"] for r in rows]


validation_agent = ValidationAgent()
