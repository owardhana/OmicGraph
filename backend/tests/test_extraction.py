"""Literature-extraction dictionary/matcher tests (Feature 2, P1 foundation).

Pure-offline: a Gazetteer is built from fixture Entry lists, no Neo4j / network.
These lock the closed-world entity-linking behaviour the rest of the pipeline
depends on (alias resolution, longest-match, casing/ambiguity gates).
"""

from backend.extraction.dictionary import Entry, Gazetteer

_ENTRIES = [
    Entry("TP53", "ENSG00000141510", "gene", "TP53"),
    Entry("p53", "ENSG00000141510", "gene", "TP53"),        # alias -> same ENSG
    Entry("EGFR", "ENSG00000146648", "gene", "EGFR"),
    Entry("HLA-A", "ENSG00000206503", "gene", "HLA-A"),
    Entry("type 2 diabetes mellitus", "EFO_0001360", "disease", "type 2 diabetes mellitus"),
    Entry("diabetes mellitus", "EFO_0000400", "disease", "diabetes mellitus"),
    Entry("MET", "ENSG00000105976", "gene", "MET"),          # also an English word
    Entry("cancer", "EFO_0000311", "disease", "cancer"),      # generic — floods prose
    Entry("breast cancer", "EFO_0000305", "disease", "breast cancer"),
]


def _gaz() -> Gazetteer:
    return Gazetteer.from_entries(_ENTRIES)


def _resolved(matches):
    return {(m.surface, m.candidates[0].node_id) for m in matches}


def test_alias_resolves_to_canonical_id():
    hits = _gaz().match("the p53 pathway")
    assert ("p53", "ENSG00000141510") in _resolved(hits)


def test_longest_match_wins():
    # "type 2 diabetes mellitus" must win over the shorter "diabetes mellitus".
    hits = _gaz().match("patients with type 2 diabetes mellitus were enrolled")
    surfaces = {m.surface for m in hits}
    assert "type 2 diabetes mellitus" in surfaces
    assert "diabetes mellitus" not in surfaces


def test_trailing_punctuation_stripped():
    # sentence-final period must not break the multi-word disease match.
    hits = _gaz().match("associated with type 2 diabetes mellitus.")
    assert "type 2 diabetes mellitus" in {m.surface for m in hits}


def test_hyphenated_symbol_matches_whole():
    hits = _gaz().match("HLA-A expression was elevated")
    assert ("HLA-A", "ENSG00000206503") in _resolved(hits)


def test_ambiguous_symbol_requires_exact_case():
    # lowercase 'met' (English word) must NOT match the gene MET...
    assert not _gaz().match("the met receptor tyrosine kinase")
    # ...but uppercase MET must.
    assert "MET" in {m.surface for m in _gaz().match("MET amplification")}


def test_short_symbol_is_case_sensitive():
    # 'egfr' lowercase should not match the 4-char symbol EGFR.
    assert "EGFR" not in {m.surface for m in _gaz().match("egfr was measured")}
    assert "EGFR" in {m.surface for m in _gaz().match("EGFR was measured")}


def test_generic_disease_word_gated_standalone():
    # bare "cancer" must NOT match (floods prose)...
    assert "cancer" not in {m.surface for m in _gaz().match("the risk of cancer rises")}
    # ...but the specific "breast cancer" phrase must (longest-match).
    assert "breast cancer" in {m.surface for m in _gaz().match("associated with breast cancer")}


def test_co_mention_gate_precondition():
    # A sentence with >=2 distinct linked entities is the minimal candidate signal.
    hits = _gaz().match("p53 regulates EGFR")
    ids = {m.candidates[0].node_id for m in hits}
    assert len(ids) >= 2
