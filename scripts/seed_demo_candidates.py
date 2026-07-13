"""Seed / clear MOCK literature-extraction candidates for the admin review dashboard.

Dev-only playground data for Feature 2 P3 (ADR-0014). Every mock node is tagged
``mock: true`` so teardown is one command and never touches real extraction output. The
candidates reference REAL graph nodes (TP53, EGFR, breast carcinoma…) so names resolve in
the UI — but the asserted biology is illustrative, not curated truth.

    PYTHONPATH=. python scripts/seed_demo_candidates.py          # create the mocks
    PYTHONPATH=. python scripts/seed_demo_candidates.py --clear  # remove ALL mocks

Teardown removes mock CandidateEdge/CandidateEvidence AND any literature edge a mock was
promoted into — matched by ``r.triple_key`` (minted edges carry it), so even candidates you
approve/revert in the dashboard are cleaned up. Requires the graph up + the well-known
entities present.
"""

from __future__ import annotations

import asyncio
import sys

from backend.db.neo4j_client import close_driver, get_session

_NOW = "2026-07-03T12:00:00Z"
_MODEL = "anthropic/claude-haiku-4.5"
_SYMMETRIC = {"INTERACTS_WITH"}  # mirrors backend.extraction.stage._SYMMETRIC


def _tk(rel: str, sid: str, oid: str) -> str:
    """Canonical triple_key — mirrors stage.triple_key (symmetric edges sort endpoints)."""
    ids = sorted([sid, oid]) if rel in _SYMMETRIC else [sid, oid]
    return f"{rel}:{ids[0]}|{ids[1]}"


# (rel, subject_sym, subject_kind, object_sym, object_kind, confidence, status, evidence[])
# evidence = (pmid, polarity, sentence_span, model_conf). n_affirm/n_negate derive from it.
_SPECS = [
    ("INTERACTS_WITH", "TP53", "protein", "MDM2", "protein", 0.94, "pending", [
        ("38010001", "affirm", "MDM2 directly binds the TP53 transactivation domain.", 0.93),
        ("38010002", "affirm", "The TP53–MDM2 interaction was confirmed by co-IP in vivo.", 0.9),
        ("38010003", "affirm", "MDM2 physically associates with TP53 to regulate its stability.", 0.88),
    ]),
    ("INTERACTS_WITH", "EGFR", "protein", "KRAS", "protein", 0.71, "pending", [
        ("38020001", "affirm", "EGFR signalling engages KRAS at the membrane.", 0.8),
        ("38020002", "affirm", "A physical EGFR–KRAS complex was detected under EGF stimulation.", 0.74),
        ("38020003", "negate", "No direct EGFR–KRAS binding was observed in our pulldown.", 0.6),
    ]),
    ("INTERACTS_WITH", "MYC", "protein", "AKT1", "protein", 0.52, "pending", [
        ("38030001", "affirm", "AKT1 was reported to interact with MYC in proliferating cells.", 0.7),
    ]),
    ("INTERACTS_WITH", "BRCA1", "protein", "TP53", "protein", 0.36, "pending", [
        ("38040001", "affirm", "A weak BRCA1–TP53 association was noted in one assay.", 0.55),
    ]),
    ("IMPLICATED_IN", "BRCA1", "gene", "breast carcinoma", "disease", 0.88, "pending", [
        ("38050001", "affirm", "BRCA1 loss-of-function is causally implicated in breast carcinoma.", 0.95),
        ("38050002", "affirm", "Germline BRCA1 variants strongly predispose to breast carcinoma.", 0.9),
        ("38050003", "affirm", "BRCA1 is a well-established breast carcinoma susceptibility gene.", 0.92),
    ]),
    ("IMPLICATED_IN", "APOE", "gene", "Alzheimer disease", "disease", 0.83, "pending", [
        ("38060001", "affirm", "APOE ε4 is the strongest genetic risk factor for Alzheimer disease.", 0.94),
        ("38060002", "affirm", "APOE is repeatedly implicated in late-onset Alzheimer disease.", 0.88),
    ]),
    ("IMPLICATED_IN", "KRAS", "gene", "uveal melanoma", "disease", 0.6, "pending", [
        ("38070001", "affirm", "KRAS mutations were associated with uveal melanoma progression.", 0.72),
        ("38070002", "affirm", "KRAS was implicated in a subset of uveal melanoma cases.", 0.66),
    ]),
    ("IMPLICATED_IN", "PTEN", "gene", "type 2 diabetes mellitus", "disease", 0.31, "pending", [
        ("38080001", "affirm", "PTEN was nominally linked to type 2 diabetes in a small study.", 0.5),
    ]),
    # pre-rejected — populates the Rejected tab on first look.
    ("IMPLICATED_IN", "TNF", "gene", "asthma", "disease", 0.44, "rejected", [
        ("38090001", "affirm", "TNF was proposed as an asthma modifier.", 0.6),
        ("38090002", "negate", "TNF blockade did not alter asthma outcomes in the trial.", 0.62),
    ]),
    # pre-promoted (mint) — populates the Promoted tab; mints a real literature edge that
    # teardown removes via r.triple_key. Revert it in the dashboard to see the edge deleted.
    ("INTERACTS_WITH", "EGFR", "protein", "MYC", "protein", 0.9, "promoted", [
        ("38100001", "affirm", "EGFR signalling stabilises MYC via a direct interaction.", 0.9),
        ("38100002", "affirm", "An EGFR–MYC complex was resolved by mass spectrometry.", 0.88),
    ]),
]


async def _resolve(session) -> dict[tuple[str, str], str]:
    """(kind, symbol_or_name) -> canonical id, for every entity the specs reference."""
    want = {(k, s) for rel, sa, ka, sb, kb, *_ in _SPECS for k, s in ((ka, sa), (kb, sb))}
    label_key = {"protein": ("Protein", "uniprot_id", "hgnc_symbol"),
                 "gene": ("Gene", "ensembl_id", "hgnc_symbol"),
                 "disease": ("Disease", "ontology_id", "name")}
    out: dict[tuple[str, str], str] = {}
    for kind in {k for k, _ in want}:
        label, idf, namef = label_key[kind]
        names = [s for k, s in want if k == kind]
        rows = await (await session.run(
            f"MATCH (n:{label}) WHERE n.{namef} IN $names RETURN n.{namef} AS s, n.{idf} AS id",
            names=names)).data()
        for r in rows:
            out[(kind, r["s"])] = r["id"]
    return out


async def seed(session) -> int:
    ids = await _resolve(session)
    created = 0
    for rel, sa, ka, sb, kb, conf, status, ev in _SPECS:
        sid, oid = ids.get((ka, sa)), ids.get((kb, sb))
        if not sid or not oid:
            print(f"  skip {sa}/{sb}: entity not in graph")
            continue
        tk = _tk(rel, sid, oid)
        n_aff = sum(1 for e in ev if e[1] == "affirm")
        n_neg = sum(1 for e in ev if e[1] == "negate")
        await session.run(
            "CREATE (ce:CandidateEdge {mock:true, triple_key:$tk, rel_type:$rel, "
            "subject_id:$sid, subject_kind:$ka, object_id:$oid, object_kind:$kb, "
            "status:$status, confidence:$conf, n_affirm:$na, n_negate:$ne, "
            "provenance_tier:'literature', source_agent:'ExtractionAgent', "
            "agent_version:'0.1.0', first_seen:$now, last_seen:$now})",
            tk=tk, rel=rel, sid=sid, ka=ka, oid=oid, kb=kb, status=status,
            conf=conf, na=n_aff, ne=n_neg, now=_NOW)
        for pmid, pol, span, mc in ev:
            await session.run(
                "MATCH (ce:CandidateEdge {triple_key:$tk}) "
                "CREATE (:CandidateEvidence {mock:true, triple_key:$tk, pmid:$pmid, "
                "polarity:$pol, sentence_span:$span, model_conf:$mc, model:$model, "
                "extracted_at:$now})-[:SUPPORTS]->(ce)",
                tk=tk, pmid=pmid, pol=pol, span=span, mc=mc, model=_MODEL, now=_NOW)

        if status == "promoted":  # mint the real literature edge (carries triple_key)
            arrow = "-" if rel in _SYMMETRIC else "->"
            s_label = "Protein" if ka == "protein" else "Gene"
            s_idf = "uniprot_id" if ka == "protein" else "ensembl_id"
            o_label, o_idf = {"protein": ("Protein", "uniprot_id"), "gene": ("Gene", "ensembl_id"),
                              "disease": ("Disease", "ontology_id")}[kb]
            await session.run(
                f"MATCH (s:{s_label} {{{s_idf}:$sid}}), (o:{o_label} {{{o_idf}:$oid}}) "
                f"MERGE (s)-[r:{rel}]{arrow}(o) "
                "SET r.provenance_tier='literature', r.source_db='literature_extracted', "
                "    r.triple_key=$tk, r.pmids=$pmids, r.confidence=$conf, r.promotion_kind='mint'",
                sid=sid, oid=oid, tk=tk, pmids=[e[0] for e in ev], conf=conf)
            await session.run(
                "MATCH (ce:CandidateEdge {triple_key:$tk}) "
                "SET ce.promotion_kind='mint', ce.promoted_at=$now", tk=tk, now=_NOW)
        created += 1
    return created


async def clear(session) -> int:
    keys = [r["k"] for r in await (await session.run(
        "MATCH (ce:CandidateEdge {mock:true}) RETURN ce.triple_key AS k")).data()]
    # remove any literature edge a mock was promoted into (matched by triple_key). Guarded
    # on keys so we never scan the typed edges when there's nothing to clear.
    if keys:
        await session.run(
            "MATCH ()-[r:INTERACTS_WITH|IMPLICATED_IN]-() WHERE r.triple_key IN $keys DELETE r",
            keys=keys)
    await session.run("MATCH (ev:CandidateEvidence {mock:true}) DETACH DELETE ev")
    n = await (await session.run(
        "MATCH (ce:CandidateEdge {mock:true}) DETACH DELETE ce RETURN count(*) AS n")).data()
    return n[0]["n"] if n else 0


async def main() -> None:
    clearing = "--clear" in sys.argv
    async with get_session() as session:
        if clearing:
            print(f"cleared {await clear(session)} mock candidates (+ evidence, + minted edges)")
        else:
            await clear(session)  # idempotent: wipe any prior mocks first
            print(f"seeded {await seed(session)} mock candidates")
    await close_driver()


if __name__ == "__main__":
    asyncio.run(main())
