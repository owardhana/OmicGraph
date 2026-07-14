"""ETL 17 — Subcellular localization: scored, multi-value property on Protein nodes.

Pillar 1a / ADR-0015 (enrichment as annotations, not node kinds). Upgrades the single
``subcellular_loc`` string (UniProt's first location, set by 06_uniprot_enrich) to a
scored, multi-value compartment set that drives the inspector's Annotations tab and
compartment-aware PPI filtering.

Source: **ComPPI** (comppi--compartments--tax_hsapiens_loc_all). ComPPI is an *integrator*
of 8 localization datasets — including the Human Protein Atlas and LOCATE — and it emits,
per UniProt protein, a "Major Loc With Loc Score" column already normalized to ~6 major
GO-CC compartments with per-compartment confidence scores, e.g. ``cytosol:0.8|nucleus:0.7``.
That is exactly the controlled vocabulary ADR-0015 calls for, keyed by UniProt, scored.

Deviation from ADR-0015 wording ("HPA-primary + ComPPI-backfill"): ComPPI *bundles* HPA and
pre-normalizes to the major-compartment vocab, so it is the practical integrated source
here. The raw HPA file (subcellular_location.tsv, ENSG-keyed, granular terms) stays in
data/raw/ for a future freshness/granularity refinement; a major protein's compartment set
is stable, so the ~2015 ComPPI snapshot is sufficient for this controlled-vocab feature.

Enrichment, not topology (data-architecture §2): only ever MATCHes existing Protein nodes
and SETs properties — never CREATEs a Protein. ComPPI accessions absent from the Swiss-Prot
proteome are skipped and counted.

Neo4j property shape: node properties are primitives or arrays of primitives (no list-of-
maps), so the scored multi-value localization is stored as index-aligned parallel arrays —
the same flat-property discipline as the ``tw_<tissue>`` weights (ADR-0001):
  - ``subcellular_locs``        : [string]  compartment names (the queryable set)
  - ``subcellular_loc_scores``  : [float]   ComPPI confidence, index-aligned
  - ``subcellular_loc_source``  : "ComPPI"

    etl/.venv/bin/python etl/17_location.py
"""

import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils.neo4j_client import close_driver, get_session  # noqa: E402

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = _PROJECT_ROOT / "data" / "raw"
COMPPI_FILE = RAW_DIR / "comppi--compartments--tax_hsapiens_loc_all.txt.gz"

# ComPPI localization is carried on both interaction endpoints (A and B); we read the
# UniProt id + its "Major Loc ... With Loc Score" for each side and dedup per protein.
SIDES = [
    ("Interactor A", "Major Loc A With Loc Score"),
    ("Interactor B", "Major Loc B With Loc Score"),
]
WRITE_BATCH = 1000
SOURCE_DB = "ComPPI"
SOURCE_VERSION = "2.1.1_loc_all"
# ComPPI over-annotates (a protein often lists 5-6 compartments incl. an "N/A"
# pseudo-compartment), which makes the compartment-aware PPI filter (ADR-0015) useless —
# every pair overlaps. Keep only real compartments and the protein's top-scoring few, so
# the stored set reflects confident primary localization.
_NOISE_LOCS = {"n/a", "unknown", "na", ""}
MAX_LOCS_PER_PROTEIN = 3

SET_QUERY = """
UNWIND $rows AS r
MATCH (p:Protein {uniprot_id: r.uniprot})
SET p.subcellular_locs = r.locs,
    p.subcellular_loc_scores = r.scores,
    p.subcellular_loc_source = $source_db
RETURN count(p) AS c
"""


def _parse_locs(cell: object) -> dict[str, float]:
    """Parse ``cytosol:0.8|nucleus:0.7`` -> {'cytosol': 0.8, 'nucleus': 0.7}."""
    out: dict[str, float] = {}
    if not isinstance(cell, str):
        return out
    for part in cell.split("|"):
        part = part.strip()
        if ":" not in part:
            continue
        loc, _, score = part.rpartition(":")
        loc = loc.strip()
        try:
            out[loc] = float(score)
        except ValueError:
            continue
    return out


def main() -> None:
    start = time.time()
    if not COMPPI_FILE.exists():
        print(f"ABORT: {COMPPI_FILE.name} not in {RAW_DIR}. Download the ComPPI "
              "H. sapiens compartments file (comppi.linkgroup.hu/downloads).")
        sys.exit(1)

    needed = [c for pair in SIDES for c in pair]
    df = pd.read_csv(
        COMPPI_FILE, sep="\t", compression="gzip", dtype=str,
        usecols=lambda c: c in needed, low_memory=False,
    )
    missing = [c for c in needed if c not in df.columns]
    if missing:
        print(f"ABORT: ComPPI file missing expected columns {missing}.")
        print(f"Columns present: {list(df.columns)}")
        sys.exit(1)
    print(f"ComPPI rows: {len(df)}")

    # Collapse the interaction table to one localization set per protein, keeping the
    # max score seen per compartment (identical across an endpoint's rows in practice).
    prot_locs: dict[str, dict[str, float]] = {}
    for uid_col, loc_col in SIDES:
        for uid, loc_cell in zip(df[uid_col], df[loc_col]):
            if not isinstance(uid, str) or not uid.strip():
                continue
            locs = _parse_locs(loc_cell)
            if not locs:
                continue
            acc = prot_locs.setdefault(uid.strip(), {})
            for loc, score in locs.items():
                if score > acc.get(loc, 0.0):
                    acc[loc] = score
    print(f"Distinct proteins with a localization: {len(prot_locs)}")

    # Build index-aligned parallel arrays (locs sorted by descending score, then name).
    rows = []
    for uid, locs in prot_locs.items():
        clean = {k: v for k, v in locs.items() if k.strip().lower() not in _NOISE_LOCS}
        ordered = sorted(clean.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_LOCS_PER_PROTEIN]
        if not ordered:
            continue
        rows.append({
            "uniprot": uid,
            "locs": [loc for loc, _ in ordered],
            "scores": [round(score, 3) for _, score in ordered],
        })

    matched = 0
    with get_session() as session:
        for i in range(0, len(rows), WRITE_BATCH):
            rec = session.run(
                SET_QUERY, rows=rows[i : i + WRITE_BATCH], source_db=SOURCE_DB
            ).single()
            matched += rec["c"] if rec else 0
        session.run(
            "MERGE (d:DataSource {name: $name}) "
            "SET d.loaded_at = datetime(), d.source_db = $source_db, "
            "    d.source_version = $source_version, "
            "    d.proteins_with_loc = $parsed, d.proteins_matched = $matched",
            name="17_location", source_db=SOURCE_DB, source_version=SOURCE_VERSION,
            parsed=len(prot_locs), matched=matched,
        ).consume()

    skipped = len(rows) - matched
    elapsed = time.time() - start
    print(f"Proteins localized (subcellular_locs set): {matched}")
    print(f"ComPPI proteins not in the Swiss-Prot graph (skipped): {skipped}")
    print(f"Time elapsed: {elapsed:.1f}s")
    close_driver()


if __name__ == "__main__":
    main()
