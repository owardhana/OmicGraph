"""ETL 12 — COSMIC Cancer Gene Census: flag cancer genes on existing Gene nodes.

Bulk-file enrichment (06_data_vision.md Pattern 1 / 09_data_catalog.md row 11).
Reads the COSMIC Cancer Gene Census CSV and SETs ``cancer_gene = true`` plus the
``cosmic_tier`` ("1" or "2") on Gene nodes matched by HGNC symbol. This populates
the ``cancer_gene`` bool that has always been on the Gene model but was never
sourced (it stays null for genes not in the Census — null = "not checked", never
False).

Enrichment, not topology: this script only ever MATCHes existing Gene nodes and
SETs properties on them — it never CREATEs a Gene (symbols absent from the graph
are skipped and counted), matching the discipline of 11_gnomad.py. Provenance
(source_db = COSMIC_CGC, source_version = v99) is recorded on the DataSource node,
not clobbered onto the multi-sourced Gene node.

Format discipline (ADR-0003): required columns are checked against the header and
the script aborts with the columns it DID find rather than silently mis-parsing.

    etl/.venv/bin/python etl/12_cosmic.py
"""

import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils.neo4j_client import close_driver, get_session  # noqa: E402

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
COSMIC_FILE = _PROJECT_ROOT / "data" / "raw" / "cosmic_cancer_gene_census.csv"
REQUIRED_COLUMNS = ["Gene Symbol", "Tier"]
WRITE_BATCH = 5000
SOURCE_DB = "COSMIC_CGC"
SOURCE_VERSION = "v99"

# MATCH only — never CREATE. Returns the count actually matched so we can report
# how many Census symbols were absent from the graph.
SET_QUERY = """
UNWIND $rows AS r
MATCH (g:Gene {hgnc_symbol: r.symbol})
SET g.cancer_gene = true, g.cosmic_tier = r.tier
RETURN count(g) AS c
"""


def main() -> None:
    start = time.time()
    if not COSMIC_FILE.exists():
        raise FileNotFoundError(
            f"{COSMIC_FILE} not found. Run etl/00_download.sh first "
            "(COSMIC may require a manual login download — see 00_download.sh)."
        )

    # The Sanger endpoint serves an HTML login page (not a CSV) to unauthenticated
    # clients; detect that explicitly rather than emitting a confusing pandas error.
    with open(COSMIC_FILE, "rb") as fh:
        head = fh.read(64).lstrip().lower()
    if head.startswith(b"<!doctype") or head.startswith(b"<html"):
        print(f"ABORT: {COSMIC_FILE.name} is an HTML page (a COSMIC login page), "
              "not CSV data. COSMIC requires a free account — download "
              "cancer_gene_census.csv manually into data/raw/ (see 00_download.sh).")
        sys.exit(1)

    header = pd.read_csv(COSMIC_FILE, nrows=0)
    missing = [c for c in REQUIRED_COLUMNS if c not in header.columns]
    if missing:
        print(f"ABORT: COSMIC CGC CSV missing required columns: {missing}")
        print(f"Columns present: {list(header.columns)}")
        sys.exit(1)

    df = pd.read_csv(COSMIC_FILE, dtype=str, usecols=REQUIRED_COLUMNS)

    # One row per gene; dedup on symbol, keeping the strongest (lowest) tier.
    gene_to_tier: dict[str, str] = {}
    for symbol, tier in zip(df["Gene Symbol"], df["Tier"]):
        if not isinstance(symbol, str) or not symbol.strip():
            continue
        symbol = symbol.strip()
        tier = tier.strip() if isinstance(tier, str) and tier.strip() else "1"
        prev = gene_to_tier.get(symbol)
        if prev is None or tier < prev:  # "1" < "2": prefer tier 1
            gene_to_tier[symbol] = tier
    print(f"Cancer Gene Census symbols parsed: {len(gene_to_tier)}")

    rows = [{"symbol": s, "tier": t} for s, t in gene_to_tier.items()]
    flagged = 0
    with get_session() as session:
        for i in range(0, len(rows), WRITE_BATCH):
            rec = session.run(SET_QUERY, rows=rows[i : i + WRITE_BATCH]).single()
            flagged += rec["c"] if rec else 0
        # Provenance + run summary on the DataSource node (no Gene clobbering).
        session.run(
            "MERGE (d:DataSource {name: $name}) "
            "SET d.loaded_at = datetime(), d.source_db = $source_db, "
            "    d.source_version = $source_version, "
            "    d.census_symbols = $census, d.genes_flagged = $flagged",
            name="12_cosmic", source_db=SOURCE_DB, source_version=SOURCE_VERSION,
            census=len(gene_to_tier), flagged=flagged,
        ).consume()

    skipped = len(gene_to_tier) - flagged
    elapsed = time.time() - start
    print(f"{flagged} genes flagged as cancer genes from COSMIC CGC.")
    print(f"Census symbols not present in graph (skipped): {skipped}")
    print(f"Time elapsed: {elapsed:.1f}s")
    close_driver()


if __name__ == "__main__":
    main()
