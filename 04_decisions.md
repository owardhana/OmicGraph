# OmniGraph — Finalized Decisions

All decisions locked before MVP build. Reference this before making implementation choices.

---

## Infrastructure

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Deployment (MVP) | Local only | Build + test locally, VPS deploy for demo day |
| Graph DB | Neo4j Community 5.x (Docker) | Mature, Cypher, native full-text search, free |
| Backend | FastAPI (Python 3.11+) | Async, typed, fast to build |
| Frontend | React + TypeScript + Vite | Fast HMR, modern, no SSR constraints |
| Containerization | Docker Compose (Neo4j + backend + frontend) | Single `docker compose up` |

---

## LLM / Agent

| Decision | Choice | Rationale |
|----------|--------|-----------|
| LLM API | OpenRouter (openrouter.ai) | Single key, model swap without code change, OpenAI-compatible |
| Text2Cypher model | `anthropic/claude-sonnet-4-6` | Best structured output + graph reasoning |
| Answer synthesis model | `anthropic/claude-sonnet-4-6` | Consistent voice with query step |
| Citation relevance check | `anthropic/claude-haiku-4-5-20251001` | Simple entity co-mention, 100x cheaper |
| Literature NER (v2) | `google/gemini-2.5-flash` | Fast, cheap, good entity extraction |
| Agent scheduling | APScheduler inside FastAPI | No extra services, nightly cron + manual trigger |
| Citation agent scope | PMID enrichment only — no topology writes | Safety: no hallucinated biology in graph |

OpenRouter client pattern:
```python
from openai import AsyncOpenAI

llm = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY")
)
```

---

## Data

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Gene ID (canonical) | Ensembl (ENSG) | GTEx + GENCODE native, stable |
| Gene ID (display/search) | HGNC symbol | Human-readable, what users type |
| Transcript ID | Ensembl (ENST) | GENCODE native |
| Protein ID (canonical) | UniProt accession | Standard protein identifier; from HGNC `uniprot_ids` (ADR-0004) |
| Protein scope (MVP) | TF slice only (DoRothEA TFs) | Regulatory proteome; full proteome is future |
| TF→gene regulation | Protein(TF) → target Gene (DoRothEA A-B) | Directed, downward, mechanistic, pre-scored (ADR-0004) |
| Transcript→protein source | GENCODE `metadata.SwissProt` (ENST→UniProt) | Existing source family; no new heavyweight dependency |
| Gene-transcript edges | GENCODE structure + GTEx tissue weights | Static topology + dynamic expression |
| Tissues (MVP) | Whole blood, Liver, Brain (PFC) | High sample count + biological diversity |
| Data scope (MVP) | Normal (healthy) only | GTEx = healthy donors. Cancer + perturbation v2+ |
| DoRothEA access | Pre-exported CSV from saezlab/dorothea GitHub | No R installation required |

---

## Graph semantics

| Decision | Choice |
|----------|--------|
| Node kinds | `Gene` (genomics), `Transcript` (transcriptomics), `Protein` (proteomics) — `entity_kind` field; TF = Protein `subtype='transcription_factor'` (ADR-0004) |
| Edge: Protein(TF) → Gene label | `REGULATES` (was Gene→Gene; now protein-sourced, downward — ADR-0004) |
| Edge: Gene → Transcript label | `PRODUCES` |
| Edge: Transcript → Protein label | `TRANSLATES_TO` (primary); `ENCODES` (Gene→Protein) fallback when no transcript |
| REGULATES properties | `mode` (activator/repressor/unknown), `confidence`, `confidence_tier`, `source_db`, `pmids` |
| PRODUCES properties | flat `tw_<tissue>` floats (ADR-0001), `source_db`, `pmids` |
| Tissue filter mechanism | **Frontend opacity, continuous** — backend never removes nodes/edges by tissue; transcript/PRODUCES opacity scales by `tw_<tissue>` (weak = faint, never gone). Tissue removed from traversal conductance. Resolved in [ADR-0006](docs/adr/0006-tissue-as-visual-channel.md) (fixes the "transcripts vanish per tissue" bug). Explicit tissue *queries* still filter. |

---

## Traversal

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Neighborhood bound | **Signal-decay** (confidence-gated spreading activation) + user hard cap | Biology-true: relevance, not hop count, bounds the result (ADR-0005) |
| Signal rule | `signal_next = signal_cur × d × c(edge)` | `d` = global per-hop decay (default 0.7); `c` = edge conductance |
| Edge conductance `c` | REGULATES→confidence; PRODUCES→**structural ~0.9** (tissue-independent, ADR-0006); TRANSLATES_TO/ENCODES→~1.0 | Structural edges near-certain; weak regulation self-prunes; tissue is opacity, not signal |
| Stop condition | `signal < ε` (default 0.05) OR nodes ≥ `max_nodes` (default 150) | User-adjustable; deterministic tie-break (confidence, then ID) |
| Replaces | Fixed `max_hops` API param → `min_signal`, `decay`, `max_nodes` | — |
| Tissue ↔ traversal | Resolved: tissue removed from conductance (ADR-0006) | Weak expression dims (opacity), never prunes — no dependency remains |

---

## Search

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Search type | Prefix + full-text (Neo4j 5 native full-text index) | Covers partial symbols, typos, gene descriptions |
| Search fields indexed | `hgnc_symbol`, `description` | Symbol = primary, description = fallback |
| Results limit | 10 per query | Autocomplete dropdown |

Full-text index creation (Neo4j 5 native syntax):
```cypher
CREATE FULLTEXT INDEX gene_search IF NOT EXISTS
FOR (n:Gene|Transcript) ON EACH [n.hgnc_symbol, n.description]
```
Scope note (post-ADR-0004): the index covers `Gene|Transcript`, **not** `Protein`.
Intended for MVP — searching a symbol finds the gene; its TF protein is one
`ENCODES`/`TRANSLATES_TO` hop away and surfaces in the graph. Add `Protein` to the
index only if direct protein search is needed later.

B-tree indexes (required for query performance — create alongside full-text):
```cypher
CREATE INDEX gene_ensembl_idx IF NOT EXISTS FOR (n:Gene) ON (n.ensembl_id)
CREATE INDEX gene_symbol_idx IF NOT EXISTS FOR (n:Gene) ON (n.hgnc_symbol)
CREATE INDEX transcript_id_idx IF NOT EXISTS FOR (n:Transcript) ON (n.ensembl_tx_id)
```

---

## Frontend UX

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Theme (task #1) | **Neutral Claude-Code-style**: warm charcoal canvas (`~#1a1a18`), solid light off-white panels (`~#faf9f5`, hairline border, soft shadow, no frosted-glass blur), monochrome chrome, **no gradients anywhere**, graphite/near-black for active+selected states | User: modern neutral shades like Claude Code UI, dislikes gradients. Saturated color reserved for graph nodes only. Mechanical styling — no ADR. |
| 3D viz library | react-force-graph-3d (Three.js) | Handles layered layout, directed edges, GPU-accelerated |
| Layer model | Graphite structure — fixed Z per omics layer; **three layers** (genomics, transcriptomics, proteomics-TF) | exact Z coords/spread owned by task #5 |
| Layer planes | Semi-transparent PlaneGeometry in Three.js | Visual separation without occlusion |
| Node colors | Per `entity_kind`/subtype — gene, TF-protein, transcript distinct by color (+ shape per layer); **exact palette owned by task #1 restyle** | Distinct, colorblind-friendly |
| Edge colors | REGULATES activator: green, repressor: red, PRODUCES: purple | Directional semantics |
| Layout / spread (task #5) | Tuned force-directed: stronger charge (~-160), **collision force**, longer links (~60–90), weaker centering, 3-layer Z separation → "web", not clumps. Structural scale measures (aggregation / edge-bundling / LOD) deferred — the signal-decay `max_nodes` cap is the scale guardrail. | User wants web-like spread that holds at scale; cap bounds per-view node count (ADR-0005) |
| On edge | **Click-to-select** (pin edge detail) + subtle link curvature for separability — not hover-only | "Hard to select edges" complaint (task #5) |
| On node click | Open detail panel (right sidebar) + "Expand neighborhood" button | Info without losing graph context |
| On expand click | Load 1-hop neighbors, add to existing graph | User controls graph complexity |
| Default load | TP53 neighborhood pre-loaded | Immediately demonstrates value, famous gene |
| Tissue filter | Toggle buttons (All / Blood / Liver / Brain) | Changes edge opacity by tissue_weights threshold |
| Layer toggle | Show/hide genomics / transcriptomics / proteomics independently | Clean layer exploration. **Fix #4:** toggling a layer must hide its edges *immediately* (today they persist until hover — react-force-graph accessor caching; fix via `refresh()`, same mechanism as ADR-0006 tissue opacity). Note: edges are now all inter-layer, so hiding e.g. proteomics removes every REGULATES edge — correct, not a regression. |
| Query panel | Bottom drawer — text input → POST /api/query → answer + citations | Non-intrusive, expandable |

---

## Testing

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Backend tests | pytest only | Cypher correctness + agent safety rules are highest risk |
| Frontend tests | Manual smoke tests only (pre-demo) | Visual testing not worth time pre-demo |
| CI/CD | None (local MVP) | Add GitHub Actions when moving to cloud |

Test structure:
```
backend/tests/
├── conftest.py           ← Neo4j test connection, fixtures
├── test_queries.py       ← Cypher correctness against live Neo4j
├── test_agents.py        ← citation agent: writes PMIDs only, never new edges/nodes
└── test_text2cypher.py   ← 5 benchmark questions → valid Cypher returned
```

---

## Ports (local dev)

| Service | Port |
|---------|------|
| Neo4j Browser | 7474 |
| Neo4j Bolt | 7687 |
| FastAPI | 8000 |
| React (Vite) | 3000 |

FastAPI CORS: allow `http://localhost:3000` in development.

---

## Environment variables (complete list)

```bash
# OpenRouter
OPENROUTER_API_KEY=sk-or-...

# Neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=changeme

# NCBI
NCBI_API_KEY=                         # optional, raises rate limit 3→10 req/s

# Models
TEXT2CYPHER_MODEL=anthropic/claude-sonnet-4-6
SYNTHESIS_MODEL=anthropic/claude-sonnet-4-6
CITATION_CHECK_MODEL=anthropic/claude-haiku-4-5-20251001

# App config
TISSUES=whole_blood,liver,brain_prefrontal_cortex
DOROTHEA_MIN_CONFIDENCE=A,B
CITATION_AGENT_BATCH_SIZE=100
CITATION_AGENT_CRON_HOUR=0            # midnight UTC
DEFAULT_GENE=TP53                     # pre-loaded on frontend
TISSUE_WEIGHT_THRESHOLD=0.3           # min weight for edge visibility
```
