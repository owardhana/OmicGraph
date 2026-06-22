"""ETL 14 — Metabolomics: Metabolite nodes + CATALYSES edges from Recon3D (ADR-0009).

Topology from a bulk file (06_data_vision.md Pattern 1 / 09_data_catalog.md rows
13-14). Parses the Recon3D human metabolic reconstruction (SBML, FBC package) to
extract:
  - (:Metabolite {hmdb_id|chebi_id, name, formula, charge})   from <species>
  - (:Protein {uniprot_id})-[:CATALYSES {role, reaction_id}]->(:Metabolite)
        role = "substrate" (reactant) | "product"

Gene -> Protein mapping uses the HGNC/UniProt topology already in the graph
(ENCODES / PRODUCES+TRANSLATES_TO), so we never create proteins here — only MATCH
existing ones (08_phase3_build_prompt.md: "Map Ensembl gene IDs -> UniProt via the
existing mappings in Neo4j"). Proteins absent from the graph are skipped.

Metabolite key: hmdb_id (primary) with chebi_id fallback (ADR-0009); a species
with neither resolvable identifier is discarded.

METABOLOMICS_MIN_REACTIONS env var (default 1) drops metabolites appearing in
fewer than N reactions after load.

Requires python-libsbml (etl/requirements.txt) — the FBC package carries the gene
associations, charge, and chemical formula that plain XML parsing would miss.

    etl/.venv/bin/python etl/14_metabolomics.py
"""

import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils.neo4j_client import close_driver, get_session  # noqa: E402

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
RECON_FILE = _PROJECT_ROOT / "data" / "raw" / "Recon3D.xml"
NODE_BATCH = 5000
EDGE_BATCH = 2000
GENE_LOOKUP_BATCH = 500
SOURCE_DB = "Recon3D"
SOURCE_VERSION = "3.04"

_HMDB_RE = re.compile(r"(HMDB\d{5,})", re.IGNORECASE)
_CHEBI_RE = re.compile(r"(CHEBI:\d+)", re.IGNORECASE)
_ENSG_RE = re.compile(r"(ENSG\d{11})")


def _import_libsbml():
    try:
        import libsbml  # noqa: WPS433
    except ImportError as exc:  # pragma: no cover - environment guard
        raise ImportError(
            "python-libsbml is required for 14_metabolomics.py. "
            "Install it: etl/.venv/bin/pip install python-libsbml"
        ) from exc
    return libsbml


def _resource_uris(sbase) -> list[str]:
    """All MIRIAM resource URIs annotated on an SBML element (via CV terms)."""
    uris: list[str] = []
    for i in range(sbase.getNumCVTerms()):
        cv = sbase.getCVTerm(i)
        for j in range(cv.getNumResources()):
            uris.append(cv.getResourceURI(j))
    return uris


def _parse_ids(sbase) -> tuple[str | None, str | None]:
    """(hmdb_id, chebi_id) from a species' MIRIAM annotation, else (None, None)."""
    blob = " ".join(_resource_uris(sbase))
    hmdb = _HMDB_RE.search(blob)
    chebi = _CHEBI_RE.search(blob)
    hmdb_id = hmdb.group(1).upper() if hmdb else None
    # Normalise to the canonical "CHEBI:<n>" form regardless of source casing.
    chebi_id = "CHEBI:" + chebi.group(1).split(":")[-1] if chebi else None
    return hmdb_id, chebi_id


def _collect_gene_products(association, libsbml) -> list[str]:
    """Recursively collect all geneProduct ids referenced by an association tree
    (GeneProductRef / FbcAnd / FbcOr). Returns geneProduct ids (FBC ids)."""
    out: list[str] = []
    if association is None:
        return out
    if isinstance(association, libsbml.GeneProductRef):
        out.append(association.getGeneProduct())
    elif isinstance(association, (libsbml.FbcAnd, libsbml.FbcOr)):
        for k in range(association.getNumAssociations()):
            out.extend(_collect_gene_products(association.getAssociation(k), libsbml))
    return out


def _map_genes_to_uniprot(ensembl_ids: set[str]) -> dict[str, str]:
    """{ensembl_id -> uniprot_id} via existing graph topology, batched.

    One UniProt per gene (first match) — a per-eid CALL subquery so the LIMIT is
    scoped to each gene, not the whole batch."""
    query = """
    UNWIND $eids AS eid
    CALL {
      WITH eid
      MATCH (g:Gene {ensembl_id: eid})-[:ENCODES|PRODUCES|TRANSLATES_TO*1..2]->(p:Protein)
      RETURN p.uniprot_id AS uniprot_id LIMIT 1
    }
    RETURN eid AS ensembl_id, uniprot_id
    """
    mapping: dict[str, str] = {}
    ids = list(ensembl_ids)
    with get_session() as session:
        for i in range(0, len(ids), GENE_LOOKUP_BATCH):
            for row in session.run(query, eids=ids[i : i + GENE_LOOKUP_BATCH]).data():
                if row["uniprot_id"]:
                    mapping[row["ensembl_id"]] = row["uniprot_id"]
    return mapping


def main() -> None:
    start = time.time()
    if not RECON_FILE.exists():
        raise FileNotFoundError(f"{RECON_FILE} not found. Run etl/00_download.sh first.")
    libsbml = _import_libsbml()

    doc = libsbml.readSBMLFromFile(str(RECON_FILE))
    model = doc.getModel()
    if model is None:
        print("ABORT: Recon3D SBML has no <model> element.")
        sys.exit(1)
    fbc_model = model.getPlugin("fbc")

    # --- gene products: FBC id -> label (Ensembl/Entrez) ---
    gp_to_ensembl: dict[str, str] = {}
    if fbc_model is not None:
        for gp in fbc_model.getListOfGeneProducts():
            label = gp.getLabel() or gp.getId()
            m = _ENSG_RE.search(label or "")
            if m:
                gp_to_ensembl[gp.getId()] = m.group(1)

    # --- species -> metabolite props ---
    species_meta: dict[str, dict] = {}  # species id -> {key, props}
    for sp in model.getListOfSpecies():
        hmdb_id, chebi_id = _parse_ids(sp)
        if not hmdb_id and not chebi_id:
            continue
        spfbc = sp.getPlugin("fbc")
        formula = spfbc.getChemicalFormula() if spfbc else None
        charge = spfbc.getCharge() if (spfbc and spfbc.isSetCharge()) else None
        key = hmdb_id if hmdb_id else chebi_id
        species_meta[sp.getId()] = {
            "key_field": "hmdb_id" if hmdb_id else "chebi_id",
            "key": key,
            "hmdb_id": hmdb_id,
            "chebi_id": chebi_id,
            "name": sp.getName() or key,
            "formula": formula or None,
            "charge": int(charge) if charge is not None else None,
        }
    print(f"Species with HMDB/ChEBI id: {len(species_meta)}")

    # --- reactions -> (gene set, reactants, products) ---
    all_ensembl: set[str] = set()
    reactions: list[dict] = []
    unparsed = 0
    for rxn in model.getListOfReactions():
        rfbc = rxn.getPlugin("fbc")
        gpa = rfbc.getGeneProductAssociation() if rfbc else None
        gp_ids = _collect_gene_products(
            gpa.getAssociation() if gpa else None, libsbml
        ) if gpa else []
        ensembl = {gp_to_ensembl[g] for g in gp_ids if g in gp_to_ensembl}
        if not ensembl:
            unparsed += 1
            continue
        reactants = [sr.getSpecies() for sr in rxn.getListOfReactants()]
        products = [sr.getSpecies() for sr in rxn.getListOfProducts()]
        all_ensembl.update(ensembl)
        reactions.append({
            "rxn_id": rxn.getId(),
            "ensembl": ensembl,
            "reactants": reactants,
            "products": products,
        })
    print(f"Reactions with a resolvable gene association: {len(reactions)} "
          f"(unparsed/no-gene: {unparsed})")

    # --- map genes -> uniprot via graph ---
    gene_to_uniprot = _map_genes_to_uniprot(all_ensembl)
    print(f"Genes mapped to a graph Protein: {len(gene_to_uniprot)} / {len(all_ensembl)}")

    # --- build metabolite nodes + CATALYSES edges ---
    used_species: set[str] = set()
    edges: dict[tuple[str, str, str], dict] = {}  # (uniprot, met_key, role) -> edge
    reaction_count: dict[str, int] = {}
    for rxn in reactions:
        uniprots = {gene_to_uniprot[e] for e in rxn["ensembl"] if e in gene_to_uniprot}
        if not uniprots:
            continue
        for role, species_list in (("substrate", rxn["reactants"]), ("product", rxn["products"])):
            for sid in species_list:
                meta = species_meta.get(sid)
                if not meta:
                    continue
                used_species.add(sid)
                reaction_count[meta["key"]] = reaction_count.get(meta["key"], 0) + 1
                for uni in uniprots:
                    edges[(uni, meta["key"], role)] = {
                        "uniprot_id": uni,
                        "met_key": meta["key"],
                        "key_field": meta["key_field"],
                        "role": role,
                        "rxn_id": rxn["rxn_id"],
                    }

    metabolite_rows = [
        species_meta[sid] for sid in used_species
    ]
    # dedup metabolites by canonical key
    by_key: dict[str, dict] = {}
    for m in metabolite_rows:
        by_key.setdefault(m["key"], m)
    metabolite_rows = list(by_key.values())
    edge_rows = list(edges.values())
    print(f"Metabolite nodes: {len(metabolite_rows)}; CATALYSES edges: {len(edge_rows)}")

    with get_session() as session:
        _write_metabolites(session, metabolite_rows)
        _write_catalyses(session, edge_rows)
        deleted = _apply_min_reactions(session)
        session.run(
            "MERGE (ds:DataSource {name: $name}) "
            "SET ds.loaded_at = datetime(), ds.source_db = $source_db, "
            "    ds.source_version = $source_version, "
            "    ds.metabolites = $mets, ds.catalyses_edges = $edges, "
            "    ds.pruned_low_reaction = $deleted",
            name="14_metabolomics", source_db=SOURCE_DB, source_version=SOURCE_VERSION,
            mets=len(metabolite_rows), edges=len(edge_rows), deleted=deleted,
        ).consume()

    elapsed = time.time() - start
    print(f"Metabolite nodes merged: {len(metabolite_rows)}")
    print(f"CATALYSES edges merged: {len(edge_rows)}")
    print(f"Time elapsed: {elapsed:.1f}s")
    close_driver()


# Two explicit MERGE queries — metabolites are keyed on hmdb_id (primary) or, when
# HMDB is absent, on chebi_id (fallback). The MERGE key must be a fixed property,
# so the two key fields need two statements; the crosslink id is SET either way.
_MERGE_BY_HMDB = """
UNWIND $rows AS m
MERGE (met:Metabolite {hmdb_id: m.hmdb_id})
  ON CREATE SET met.created_at = timestamp()
SET met.chebi_id = m.chebi_id, met.name = m.name, met.formula = m.formula,
    met.charge = m.charge, met.node_type = 'metabolite', met.layer_z = 900,
    met.source_db = $source_db, met.source_version = $source_version
"""
_MERGE_BY_CHEBI = """
UNWIND $rows AS m
MERGE (met:Metabolite {chebi_id: m.chebi_id})
  ON CREATE SET met.created_at = timestamp()
SET met.hmdb_id = m.hmdb_id, met.name = m.name, met.formula = m.formula,
    met.charge = m.charge, met.node_type = 'metabolite', met.layer_z = 900,
    met.source_db = $source_db, met.source_version = $source_version
"""


def _write_metabolites(session, rows: list[dict]) -> None:
    hmdb_rows = [r for r in rows if r["key_field"] == "hmdb_id"]
    chebi_rows = [r for r in rows if r["key_field"] == "chebi_id"]
    for query, batch in ((_MERGE_BY_HMDB, hmdb_rows), (_MERGE_BY_CHEBI, chebi_rows)):
        for i in range(0, len(batch), NODE_BATCH):
            session.run(query, rows=batch[i : i + NODE_BATCH],
                        source_db=SOURCE_DB, source_version=SOURCE_VERSION).consume()


def _write_catalyses(session, rows: list[dict]) -> None:
    query = """
    UNWIND $rows AS e
    MATCH (p:Protein {uniprot_id: e.uniprot_id})
    MATCH (met:Metabolite)
      WHERE (e.key_field = 'hmdb_id'  AND met.hmdb_id  = e.met_key)
         OR (e.key_field = 'chebi_id' AND met.chebi_id = e.met_key)
    MERGE (p)-[r:CATALYSES {role: e.role, reaction_id: e.rxn_id}]->(met)
      ON CREATE SET r.source_db = $source_db, r.source_version = $source_version
    """
    for i in range(0, len(rows), EDGE_BATCH):
        session.run(query, rows=rows[i : i + EDGE_BATCH],
                    source_db=SOURCE_DB, source_version=SOURCE_VERSION).consume()


def _apply_min_reactions(session) -> int:
    """Delete metabolites appearing in fewer than METABOLOMICS_MIN_REACTIONS
    reactions (distinct reaction_id on incident CATALYSES edges). Default 1 keeps
    all loaded metabolites."""
    min_reactions = int(os.getenv("METABOLOMICS_MIN_REACTIONS", "1"))
    if min_reactions <= 1:
        return 0
    rec = session.run(
        "MATCH (m:Metabolite) "
        "OPTIONAL MATCH (m)<-[r:CATALYSES]-() "
        "WITH m, count(DISTINCT r.reaction_id) AS rxns "
        "WHERE rxns < $min "
        "DETACH DELETE m "
        "RETURN count(m) AS deleted",
        min=min_reactions,
    ).single()
    return rec["deleted"] if rec else 0


if __name__ == "__main__":
    main()
