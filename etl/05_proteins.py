"""ETL 05 — Mint transcription-factor Protein nodes + link them to genomics.

Runs AFTER 01-04 (it migrates the REGULATES edges 04 created). Steps:

1. Take the distinct TF symbols straight from the graph's existing REGULATES
   edges (the TFs that are actually wired). For each symbol that resolves to a
   UniProt accession (HGNC ``uniprot_ids``), MERGE a (:Protein {uniprot_id}) with
   entity_kind='protein', subtype='transcription_factor'.
2. Tie each protein down to its molecule:
     - (:Transcript)-[:TRANSLATES_TO]->(:Protein)  primary, from the GENCODE
       SwissProt metadata (ENST -> UniProt), for transcripts present in the graph.
     - (:Gene)-[:ENCODES]->(:Protein)              fallback, only when the protein
       got no transcript link, so a protein is never orphaned from its molecule.
3. Migrate REGULATES from gene-sourced to protein-sourced, PRESERVING edge
   properties (incl. citation work): for each (g:Gene)-[r:REGULATES]->(target),
   where g's protein p exists (matched by hgnc_symbol), MERGE
   (p)-[:REGULATES]->(target) copying r's props, then delete r.

Idempotent: TF symbols are read from REGULATES regardless of whether the source
is still a Gene (pre-migration) or already a Protein (post-migration); MERGE makes
re-mints no-ops; the migration only ever finds Gene-sourced edges. No pyreadr /
DoRothEA file read needed — 04 already encoded the TF set into the graph.

See docs/adr/0004-transcription-factors-as-proteins.md.

    etl/.venv/bin/python etl/05_proteins.py
"""

import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils.id_mapper import IdMapper, strip_version  # noqa: E402
from utils.neo4j_client import close_driver, get_session  # noqa: E402

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = _PROJECT_ROOT / "data" / "raw"
SWISSPROT_FILE = RAW_DIR / "gencode.v46.metadata.SwissProt.gz"
BATCH_SIZE = 2000


def load_swissprot_map() -> dict[str, list[str]]:
    """uniprot accession -> list of unversioned ENST ids (from GENCODE metadata)."""
    if not SWISSPROT_FILE.exists():
        raise FileNotFoundError(
            f"{SWISSPROT_FILE} not found. Run etl/00_download.sh first."
        )
    # 3 columns: versioned ENST, UniProt accession, versioned UniProt.
    df = pd.read_csv(
        SWISSPROT_FILE, sep="\t", header=None,
        names=["enst", "uniprot", "uniprot_v"], dtype=str, compression="gzip",
    )
    out: dict[str, list[str]] = {}
    for enst, uniprot in zip(df["enst"], df["uniprot"]):
        if not isinstance(enst, str) or not isinstance(uniprot, str):
            continue
        out.setdefault(uniprot.strip(), []).append(strip_version(enst.strip()))
    return out


def main() -> None:
    start = time.time()
    mapper = IdMapper()

    with get_session() as session:
        # 0. Distinct TF symbols from the graph's REGULATES (source is Gene
        #    pre-migration or Protein post-migration; both carry hgnc_symbol).
        tf_symbols = [
            r["sym"]
            for r in session.run(
                "MATCH (s)-[:REGULATES]->() WHERE s.hgnc_symbol IS NOT NULL "
                "RETURN DISTINCT s.hgnc_symbol AS sym"
            ).data()
        ]
        print(f"Distinct TF symbols wired in REGULATES: {len(tf_symbols)}")

        # Resolve symbol -> (uniprot, ensembl). Skip (and log) misses.
        rows: list[dict] = []
        no_uniprot: list[str] = []
        for sym in tf_symbols:
            uniprot = mapper.hgnc_to_uniprot(sym)
            ensembl = mapper.hgnc_to_ensembl(sym)
            if not uniprot or not ensembl:
                no_uniprot.append(sym)
                continue
            rows.append({"symbol": sym, "uniprot": uniprot, "ensembl": ensembl})
        print(f"TFs resolved to UniProt: {len(rows)}  (no UniProt: {len(no_uniprot)})")

        swissprot = load_swissprot_map()

        # 1. Mint Protein nodes.
        for i in range(0, len(rows), BATCH_SIZE):
            session.run(
                """
                UNWIND $rows AS row
                MERGE (p:Protein {uniprot_id: row.uniprot})
                SET p.hgnc_symbol = row.symbol,
                    p.entity_kind = 'protein',
                    p.subtype = 'transcription_factor'
                """,
                rows=rows[i : i + BATCH_SIZE],
            ).consume()

        # 2a. TRANSLATES_TO from transcripts present in the graph.
        translates_links = [
            {"uniprot": r["uniprot"], "enst": enst}
            for r in rows
            for enst in swissprot.get(r["uniprot"], [])
        ]
        translates_created = 0
        for i in range(0, len(translates_links), BATCH_SIZE):
            rec = session.run(
                """
                UNWIND $links AS link
                MATCH (p:Protein {uniprot_id: link.uniprot})
                MATCH (t:Transcript {ensembl_tx_id: link.enst})
                MERGE (t)-[rel:TRANSLATES_TO]->(p)
                ON CREATE SET rel.source_db = 'GENCODE_SwissProt'
                RETURN count(rel) AS c
                """,
                links=translates_links[i : i + BATCH_SIZE],
            ).single()
            translates_created += rec["c"] if rec else 0

        # 2b. ENCODES fallback for proteins with NO transcript link.
        encodes_rec = session.run(
            """
            UNWIND $rows AS row
            MATCH (p:Protein {uniprot_id: row.uniprot})
            WHERE NOT ( (:Transcript)-[:TRANSLATES_TO]->(p) )
            MATCH (g:Gene {ensembl_id: row.ensembl})
            MERGE (g)-[rel:ENCODES]->(p)
            ON CREATE SET rel.source_db = 'HGNC'
            RETURN count(rel) AS c
            """,
            rows=rows,
        ).single()
        encodes_created = encodes_rec["c"] if encodes_rec else 0

        # 3. Migrate REGULATES: Gene-sourced -> Protein-sourced, preserving props.
        migrate_rec = session.run(
            """
            MATCH (g:Gene)-[r:REGULATES]->(target:Gene)
            MATCH (p:Protein {hgnc_symbol: g.hgnc_symbol})
            MERGE (p)-[r2:REGULATES]->(target)
            SET r2 += properties(r)
            DELETE r
            RETURN count(r2) AS migrated
            """
        ).single()
        migrated = migrate_rec["migrated"] if migrate_rec else 0

        leftover = session.run(
            "MATCH (:Gene)-[r:REGULATES]->(:Gene) RETURN count(r) AS c"
        ).single()["c"]

    elapsed = time.time() - start
    print(f"Proteins (TF) in graph after merge: {len(rows)}")
    print(f"TRANSLATES_TO edges: {translates_created}")
    print(f"ENCODES (fallback) edges: {encodes_created}")
    print(f"REGULATES migrated to Protein source: {migrated}")
    print(f"REGULATES still Gene->Gene (TF lacked a protein): {leftover}")
    if no_uniprot:
        print(f"TF symbols with no UniProt (first 20): {no_uniprot[:20]}")
    print(f"Time elapsed: {elapsed:.1f}s")
    close_driver()


if __name__ == "__main__":
    main()
