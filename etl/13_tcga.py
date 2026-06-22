"""ETL 13 — TCGA differential expression: DIFFERENTIALLY_EXPRESSED edges.

Topology from bulk files (06_data_vision.md Pattern 1 / 09_data_catalog.md rows
12). Computes a per-gene, per-tumor-type differential-expression signal from the
UCSC Xena TCGA Pan-Cancer FPKM matrix, using the GTEx whole-blood tissue weight
already in the graph as a *proxy normal*, and MERGEs:

  (:Gene {ensembl_id})-[:DIFFERENTIALLY_EXPRESSED {tumor_type}]->(:Disease {ontology_id})
      log2fc, direction ("up"/"down"), source_db, source_version, loaded_at

This is a deliberately simplified proxy (KNOWN RISKS, 08_phase3_build_prompt.md):
real differential expression needs DESeq2/edgeR on count data with matched
normals. Here ``log2fc = log2((tumor_median + 0.01) / (gtex_proxy + 0.01))`` gives
a directional signal sufficient for the graph. Threshold |log2fc| >= TCGA_MIN_LOG2FC.

Both endpoints (Gene and Disease) must already exist — genes from 01_hgnc, EFO
Disease nodes from 08_gwas. Genes/diseases absent from the graph are skipped and
counted (never created here).

Format discipline (ADR-0003): every input file is checked for a usable set of
columns and the script aborts (printing the columns it DID find) rather than
silently mis-parsing the (release-variable) Xena layout.

    etl/.venv/bin/python etl/13_tcga.py
"""

import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils.neo4j_client import close_driver, get_session  # noqa: E402

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_RAW = _PROJECT_ROOT / "data" / "raw"
EXPR_FILE = _RAW / "tcga_pancan_expression.tsv.gz"
PHENO_FILE = _RAW / "tcga_pancan_phenotype.tsv.gz"
EFO_MAP_FILE = _RAW / "tcga_efo_mapping.tsv"

MIN_SAMPLES = 10  # a tumor type needs >= this many samples to be processed
EDGE_BATCH = 2000
SOURCE_DB = "TCGA_XENA"
SOURCE_VERSION = "pancan_2023"

# The Xena phenotype layout has changed across releases; accept the first present
# of each candidate set, abort if none match (ADR-0003 discipline).
SAMPLE_COL_CANDIDATES = ["sample", "sampleID", "submitter_id.samples", "bcr_sample_barcode"]
TYPE_COL_CANDIDATES = [
    "cancer type abbreviation", "cancer_type_abbreviation",
    "project_id", "_primary_disease", "disease_code", "acronym",
]


def _strip_ensembl_version(eid: str) -> str:
    return eid.split(".")[0] if isinstance(eid, str) else eid


def _first_present(columns, candidates):
    for c in candidates:
        if c in columns:
            return c
    return None


def _tumor_code(raw: str) -> str | None:
    """Normalise a phenotype value to a bare TCGA code (e.g. 'TCGA-LUAD' -> 'LUAD')."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    s = raw.strip()
    if s.upper().startswith("TCGA-"):
        s = s[5:]
    return s.upper() if s else None


def _load_efo_mapping() -> dict[str, str]:
    """{TCGA code -> EFO ontology id} from the cttv tcga_efo_mapping TSV.

    The file is a 2+ column TSV; the first column is the TCGA code, a later column
    holds the EFO URI/id. The ontology id is the last path segment (EFO_0000123).
    """
    df = pd.read_csv(EFO_MAP_FILE, sep="\t", dtype=str, header=None, comment="#")
    if df.shape[1] < 2:
        print(f"ABORT: {EFO_MAP_FILE.name} needs >=2 columns; found {df.shape[1]}.")
        sys.exit(1)
    mapping: dict[str, str] = {}
    for code_raw, efo_raw in zip(df.iloc[:, 0], df.iloc[:, 1]):
        code = _tumor_code(code_raw)
        if code is None or not isinstance(efo_raw, str) or not efo_raw.strip():
            continue
        oid = efo_raw.rstrip("/").split("/")[-1].strip()
        if oid and oid.lower() != "nan":
            mapping[code] = oid
    return mapping


def _load_gtex_proxy() -> dict[str, float]:
    """{ensembl_id -> max tw_whole_blood across its PRODUCES edges} as proxy normal."""
    query = """
    MATCH (g:Gene)-[r:PRODUCES]->(:Transcript)
    WHERE r.tw_whole_blood IS NOT NULL
    RETURN g.ensembl_id AS eid, max(r.tw_whole_blood) AS proxy
    """
    proxy: dict[str, float] = {}
    with get_session() as session:
        for row in session.run(query).data():
            if row["eid"] is not None and row["proxy"] is not None:
                proxy[_strip_ensembl_version(row["eid"])] = float(row["proxy"])
    return proxy


def _graph_gene_ids() -> set[str]:
    with get_session() as session:
        rows = session.run("MATCH (g:Gene) RETURN g.ensembl_id AS eid").data()
    return {_strip_ensembl_version(r["eid"]) for r in rows if r["eid"]}


def _graph_disease_ids() -> set[str]:
    with get_session() as session:
        rows = session.run("MATCH (d:Disease) RETURN d.ontology_id AS oid").data()
    return {r["oid"] for r in rows if r["oid"]}


def _batched(session, query: str, rows: list[dict], size: int) -> None:
    for i in range(0, len(rows), size):
        session.run(query, rows=rows[i : i + size]).consume()


MERGE_QUERY = """
UNWIND $rows AS row
MATCH (g:Gene {ensembl_id: row.ensembl_id})
MATCH (d:Disease {ontology_id: row.efo_id})
MERGE (g)-[r:DIFFERENTIALLY_EXPRESSED {tumor_type: row.tumor_type}]->(d)
SET r.log2fc = row.log2fc,
    r.direction = row.direction,
    r.source_db = $source_db,
    r.source_version = $source_version,
    r.loaded_at = timestamp()
"""


def main() -> None:
    start = time.time()
    for f in (EXPR_FILE, PHENO_FILE, EFO_MAP_FILE):
        if not f.exists():
            raise FileNotFoundError(f"{f} not found. Run etl/00_download.sh first.")

    threshold = float(os.getenv("TCGA_MIN_LOG2FC", "1.0"))
    print(f"TCGA |log2FC| threshold: >= {threshold}")

    # --- 1. sample -> tumor_type from phenotype ---
    pheno = pd.read_csv(PHENO_FILE, sep="\t", dtype=str, low_memory=False)
    sample_col = _first_present(pheno.columns, SAMPLE_COL_CANDIDATES)
    type_col = _first_present(pheno.columns, TYPE_COL_CANDIDATES)
    if sample_col is None or type_col is None:
        print("ABORT: TCGA phenotype missing a usable sample/type column.")
        print(f"  sample candidates {SAMPLE_COL_CANDIDATES} -> {sample_col}")
        print(f"  type   candidates {TYPE_COL_CANDIDATES} -> {type_col}")
        print(f"Columns present: {list(pheno.columns)}")
        sys.exit(1)
    sample_to_type: dict[str, str] = {}
    for s, t in zip(pheno[sample_col], pheno[type_col]):
        code = _tumor_code(t)
        if isinstance(s, str) and s.strip() and code:
            sample_to_type[s.strip()] = code
    print(f"Samples with a tumor type: {len(sample_to_type)} "
          f"(cols: sample='{sample_col}', type='{type_col}')")

    # --- 2. EFO mapping; only mapped tumor types are processed ---
    efo = _load_efo_mapping()
    print(f"TCGA->EFO mappings: {len(efo)}")

    # --- 3. expression matrix (rows=genes, cols=samples) ---
    expr = pd.read_csv(EXPR_FILE, sep="\t", index_col=0, low_memory=False)
    print(f"Expression matrix shape (genes x samples): {expr.shape}")
    expr.index = [_strip_ensembl_version(g) for g in expr.index]

    graph_genes = _graph_gene_ids()
    graph_diseases = _graph_disease_ids()
    gtex_proxy = _load_gtex_proxy()
    print(f"Graph: {len(graph_genes)} genes, {len(graph_diseases)} diseases, "
          f"{len(gtex_proxy)} GTEx whole-blood proxies")

    # group expression columns by tumor type (only mapped types with enough samples)
    type_to_cols: dict[str, list[str]] = {}
    for col in expr.columns:
        ttype = sample_to_type.get(col)
        if ttype and ttype in efo:
            type_to_cols.setdefault(ttype, []).append(col)

    unmapped = sorted({t for t in sample_to_type.values() if t not in efo})
    if unmapped:
        print(f"Unmapped tumor types (no EFO id, skipped): {unmapped}")

    edges: list[dict] = []
    per_type_counts: dict[str, int] = {}
    skipped_genes = skipped_diseases = 0

    for ttype, cols in sorted(type_to_cols.items()):
        if len(cols) < MIN_SAMPLES:
            print(f"  {ttype}: {len(cols)} samples < {MIN_SAMPLES}, skipped")
            continue
        efo_id = efo[ttype]
        if efo_id not in graph_diseases:
            skipped_diseases += 1
            print(f"  {ttype}: EFO {efo_id} not in graph, skipped")
            continue
        # median log2(FPKM+1) per gene across this tumor type's samples.
        # Xena FPKM is already log2(fpkm+1); guard either way by clipping negatives.
        sub = expr[cols].apply(pd.to_numeric, errors="coerce")
        tumor_median = sub.median(axis=1, skipna=True)
        n_edges = 0
        for eid, tmed in tumor_median.items():
            if eid not in graph_genes:
                skipped_genes += 1
                continue
            if pd.isna(tmed):
                continue
            proxy = gtex_proxy.get(eid)
            if proxy is None:
                continue
            tumor_lin = max(float(tmed), 0.0)
            log2fc = float(np.log2((tumor_lin + 0.01) / (proxy + 0.01)))
            if abs(log2fc) < threshold:
                continue
            edges.append({
                "ensembl_id": eid,
                "efo_id": efo_id,
                "tumor_type": ttype,
                "log2fc": round(log2fc, 4),
                "direction": "up" if log2fc > 0 else "down",
            })
            n_edges += 1
        per_type_counts[ttype] = n_edges
        print(f"  {ttype}: {len(cols)} samples -> {n_edges} edges (EFO {efo_id})")

    print(f"Total DIFFERENTIALLY_EXPRESSED edges to write: {len(edges)}")
    print(f"Skipped (gene not in graph): {skipped_genes}; "
          f"(disease not in graph): {skipped_diseases}")

    with get_session() as session:
        for i in range(0, len(edges), EDGE_BATCH):
            session.run(
                MERGE_QUERY, rows=edges[i : i + EDGE_BATCH],
                source_db=SOURCE_DB, source_version=SOURCE_VERSION,
            ).consume()
        session.run(
            "MERGE (ds:DataSource {name: $name}) "
            "SET ds.loaded_at = datetime(), ds.source_db = $source_db, "
            "    ds.source_version = $source_version, "
            "    ds.edges_written = $edges, ds.per_tumor_type = $per_type",
            name="13_tcga", source_db=SOURCE_DB, source_version=SOURCE_VERSION,
            edges=len(edges),
            per_type=[f"{k}={v}" for k, v in sorted(per_type_counts.items())],
        ).consume()

    elapsed = time.time() - start
    print(f"DIFFERENTIALLY_EXPRESSED edges merged: {len(edges)}")
    print(f"Time elapsed: {elapsed:.1f}s")
    close_driver()


if __name__ == "__main__":
    main()
