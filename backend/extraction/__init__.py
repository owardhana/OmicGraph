"""Literature-extraction pipeline (Feature 2).

Closed-world: entities are linked only to nodes already in the graph; nothing is
minted. Stages (built incrementally):
  dictionary  — gazetteer build from the graph + sentence matching  [scaffold]
  ingest      — PubMed reldate delta via E-utils                     [todo]
  relation    — one cheap LLM verdict per co-mention sentence        [todo]
  stage       — CandidateEdge / CandidateEvidence dedup + write      [todo]

Trust model: docs/adr/0013-literature-extraction-trust-model.md.
Plan: docs/design/feature-2-literature-extraction.md.
"""
