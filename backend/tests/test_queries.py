"""Cypher correctness tests against the live graph."""

from backend.db.queries.genes import (
    get_gene_by_symbol,
    get_gene_neighborhood,
)
from backend.db.queries.graph import search_genes


async def test_gene_lookup():
    record = await get_gene_by_symbol("TP53")
    assert record is not None
    props = record["props"]
    assert props["ensembl_id"].startswith("ENSG")
    assert props["hgnc_symbol"] == "TP53"
    assert record["is_tf"] is True  # TP53 has outgoing REGULATES


async def test_neighborhood():
    record = await get_gene_by_symbol("TP53")
    ensembl_id = record["props"]["ensembl_id"]
    graph = await get_gene_neighborhood(ensembl_id, tissue="all", max_hops=1)
    assert len(graph["nodes"]) > 0
    assert len(graph["edges"]) > 0
    # Every REGULATES edge must carry an A/B confidence tier.
    for edge in graph["edges"]:
        if edge["rel_type"] == "REGULATES":
            assert edge["props"]["confidence_tier"] in ("A", "B")


async def test_tissue_filter():
    # ALB (albumin) is the canonical liver-expressed gene.
    record = await get_gene_by_symbol("ALB")
    ensembl_id = record["props"]["ensembl_id"]
    graph = await get_gene_neighborhood(ensembl_id, tissue="liver", max_hops=1)
    produces = [e for e in graph["edges"] if e["rel_type"] == "PRODUCES"]
    # The liver filter must yield only edges above the threshold (0.3).
    assert produces, "ALB should have liver-expressed transcripts"
    for edge in produces:
        assert edge["props"]["tw_liver"] > 0.3


async def test_search():
    results = await search_genes("TP53", limit=10)
    assert results
    assert results[0]["hgnc_symbol"] == "TP53"
