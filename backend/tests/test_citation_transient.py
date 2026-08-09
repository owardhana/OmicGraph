"""CitationAgent transient-failure discipline (unit — all NCBI/Neo4j/LLM I/O mocked).

Regression for the free-model switch (haiku → free Nemotron, which 502-storms): a
transient LLM failure must NOT mark an edge ``citation_attempted`` (the fetch query
excludes attempted edges, so that would drop it *permanently*). A clean pass — including
a genuine "no relevant abstract" — must still mark it so it isn't re-queried forever.
Mirrors the backfill principle: throttling costs time, not data.
"""

from backend.agents.citation_agent import citation_agent


def _stub_io(monkeypatch, *, abstracts, is_relevant):
    """Wire the agent's I/O to in-memory stubs; return the list of _write_pmids calls.

    ``abstracts`` maps pmid -> abstract text; ``is_relevant(abstract)`` returns a bool or
    raises (to simulate a transient LLM 502/timeout for that abstract)."""
    writes: list[tuple[str, list[str]]] = []

    async def fake_fetch(batch_size):
        return [{"eid": "e1", "src": "AAA", "tgt": "BBB"}]

    async def fake_esearch(http, src, tgt):
        return list(abstracts.keys())

    async def fake_efetch(http, pmids):
        return dict(abstracts)

    async def fake_is_relevant(abstract, src, tgt):
        return is_relevant(abstract)

    async def fake_write(eid, pmids):
        writes.append((eid, list(pmids)))

    async def fake_log(label, props):
        return None

    monkeypatch.setattr(type(citation_agent), "_request_delay", 0.0)
    monkeypatch.setattr(citation_agent, "_fetch_uncited_edges", fake_fetch)
    monkeypatch.setattr(citation_agent, "_esearch", fake_esearch)
    monkeypatch.setattr(citation_agent, "_efetch_abstracts", fake_efetch)
    monkeypatch.setattr(citation_agent, "_is_relevant", fake_is_relevant)
    monkeypatch.setattr(citation_agent, "_write_pmids", fake_write)
    monkeypatch.setattr(citation_agent, "write_run_log_to_graph", fake_log)
    return writes


async def test_transient_llm_failure_leaves_edge_pending(monkeypatch):
    def boom(_abstract):
        raise RuntimeError("Upstream error from Nvidia: ResourceExhausted (32/32) 502")

    writes = _stub_io(monkeypatch, abstracts={"111": "text"}, is_relevant=boom)
    summary = await citation_agent.run(batch_size=1)
    assert writes == []  # edge NOT marked attempted → a healthy run can retry it
    assert summary["edges_skipped"] == 1
    assert summary["edges_processed"] == 0


async def test_clean_no_hit_marks_attempted(monkeypatch):
    writes = _stub_io(monkeypatch, abstracts={"111": "text"}, is_relevant=lambda _a: False)
    summary = await citation_agent.run(batch_size=1)
    assert writes == [("e1", [])]  # genuine "nothing relevant" still marks attempted
    assert summary["edges_processed"] == 1
    assert summary["edges_skipped"] == 0


async def test_partial_success_records_found_pmids(monkeypatch):
    def mixed(abstract):
        if abstract == "bad":
            raise RuntimeError("502")
        return True

    writes = _stub_io(
        monkeypatch, abstracts={"111": "bad", "222": "good"}, is_relevant=mixed
    )
    summary = await citation_agent.run(batch_size=1)
    assert writes == [("e1", ["222"])]  # found pmid kept despite a transient error on another
    assert summary["edges_processed"] == 1
    assert summary["edges_skipped"] == 0
