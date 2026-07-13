"""ETL 18 — Pathway / GO-process membership: annotation properties (not nodes).

Pillar 1b / ADR-0015 (enrichment as annotations; OmicGraph is *not* a pathway browser,
so pathways are a scored/faceted annotation, never a first-class node kind). Two sources,
two annotation properties:

  - **Reactome** (UniProt2Reactome, human only "R-HSA…") -> ``Protein.reactome_pathways``
    : [string] pathway names the protein participates in.
  - **MSigDB C5 GO:BP** (c5.go.bp gene sets, by symbol) -> ``Gene.go_bp_terms``
    : [string] biological-process gene sets the gene belongs to (readable names).

KEGG-proper is deliberately absent (license-barred — ADR-0015); Reactome + MSigDB C5
cover the need openly. Membership is set-valued (no score) — stored as string arrays,
the primitive/array Neo4j discipline.

Enrichment, not topology (data-architecture §2): only MATCHes existing Gene/Protein nodes
and SETs properties; symbols/accessions absent from the graph are skipped and counted.

    etl/.venv/bin/python etl/18_pathways.py
"""

import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils.neo4j_client import close_driver, get_session  # noqa: E402

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = _PROJECT_ROOT / "data" / "raw"
REACTOME_FILE = RAW_DIR / "UniProt2Reactome.txt"
MSIGDB_GMT = RAW_DIR / "c5.go.bp.v2026.1.Hs.symbols.gmt"
WRITE_BATCH = 1000

# UniProt2Reactome is headerless: uniprot, reactome_id, url, pathway_name, evidence, species.
REACTOME_COLS = ["uniprot", "reactome_id", "url", "pathway", "evidence", "species"]
HUMAN = "Homo sapiens"

SET_REACTOME = """
UNWIND $rows AS r
MATCH (p:Protein {uniprot_id: r.key})
SET p.reactome_pathways = r.terms
RETURN count(p) AS c
"""
SET_GOBP = """
UNWIND $rows AS r
MATCH (g:Gene {hgnc_symbol: r.key})
SET g.go_bp_terms = r.terms
RETURN count(g) AS c
"""


def _prettify_gobp(set_name: str) -> str:
    """GOBP_MITOCHONDRIAL_TRANSLATION -> 'mitochondrial translation'."""
    name = set_name[5:] if set_name.startswith("GOBP_") else set_name
    return name.replace("_", " ").lower().strip()


def _reactome_by_protein() -> dict[str, list[str]]:
    df = pd.read_csv(
        REACTOME_FILE, sep="\t", header=None, names=REACTOME_COLS, dtype=str,
        usecols=["uniprot", "reactome_id", "pathway", "species"],
    )
    human = df[df["species"] == HUMAN]
    print(f"Reactome rows total: {len(df)}; human: {len(human)}")
    by_prot: dict[str, list[str]] = {}
    seen: dict[str, set[str]] = {}
    for uid, pathway in zip(human["uniprot"], human["pathway"]):
        if not isinstance(uid, str) or not isinstance(pathway, str):
            continue
        uid = uid.strip()
        s = seen.setdefault(uid, set())
        if pathway not in s:
            s.add(pathway)
            by_prot.setdefault(uid, []).append(pathway.strip())
    return by_prot


def _gobp_by_gene() -> dict[str, list[str]]:
    """Invert the GMT (set -> genes) into gene -> [readable set names]."""
    by_gene: dict[str, list[str]] = {}
    with open(MSIGDB_GMT) as fh:
        n_sets = 0
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            n_sets += 1
            term = _prettify_gobp(parts[0])
            for symbol in parts[2:]:
                symbol = symbol.strip()
                if symbol:
                    by_gene.setdefault(symbol, []).append(term)
    print(f"MSigDB C5 GO:BP gene sets: {n_sets}; genes covered: {len(by_gene)}")
    return by_gene


def _load(session, query: str, mapping: dict[str, list[str]]) -> int:
    rows = [{"key": k, "terms": v} for k, v in mapping.items()]
    matched = 0
    for i in range(0, len(rows), WRITE_BATCH):
        rec = session.run(query, rows=rows[i : i + WRITE_BATCH]).single()
        matched += rec["c"] if rec else 0
    return matched


def main() -> None:
    start = time.time()
    for f in (REACTOME_FILE, MSIGDB_GMT):
        if not f.exists():
            print(f"ABORT: {f.name} not in {RAW_DIR}.")
            sys.exit(1)

    reactome = _reactome_by_protein()
    gobp = _gobp_by_gene()
    print(f"Proteins with a Reactome pathway: {len(reactome)}")

    with get_session() as session:
        prot_matched = _load(session, SET_REACTOME, reactome)
        gene_matched = _load(session, SET_GOBP, gobp)
        session.run(
            "MERGE (d:DataSource {name: $name}) "
            "SET d.loaded_at = datetime(), "
            "    d.reactome_proteins_matched = $pm, d.gobp_genes_matched = $gm, "
            "    d.source_db = 'Reactome+MSigDB_C5', d.source_version = 'UniProt2Reactome;c5.go.bp.v2026.1'",
            name="18_pathways", pm=prot_matched, gm=gene_matched,
        ).consume()

    elapsed = time.time() - start
    print(f"Proteins tagged with Reactome pathways: {prot_matched} "
          f"(skipped, not in graph: {len(reactome) - prot_matched})")
    print(f"Genes tagged with GO:BP terms: {gene_matched} "
          f"(skipped, not in graph: {len(gobp) - gene_matched})")
    print(f"Time elapsed: {elapsed:.1f}s")
    close_driver()


if __name__ == "__main__":
    main()
