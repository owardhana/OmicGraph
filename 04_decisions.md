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
| Gene-gene edges | TF → target (DoRothEA A-B only) | Directed, mechanistic, pre-scored |
| Gene-transcript edges | GENCODE structure + GTEx tissue weights | Static topology + dynamic expression |
| Tissues (MVP) | Whole blood, Liver, Brain (PFC) | High sample count + biological diversity |
| Data scope (MVP) | Normal (healthy) only | GTEx = healthy donors. Cancer + perturbation v2+ |
| DoRothEA access | Pre-exported CSV from saezlab/dorothea GitHub | No R installation required |

---

## Graph semantics

| Decision | Choice |
|----------|--------|
| Edge: TF → Gene label | `REGULATES` |
| Edge: Gene → Transcript label | `PRODUCES` |
| REGULATES properties | `mode` (activator/repressor/unknown), `confidence`, `confidence_tier`, `source_db`, `pmids` |
| PRODUCES properties | `tissue_weights: {whole_blood, liver, brain_prefrontal_cortex}`, `source_db`, `pmids` |
| Tissue filter mechanism | Edge opacity by `tissue_weights[tissue] > 0.3` threshold |

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
| 3D viz library | react-force-graph-3d (Three.js) | Handles layered layout, directed edges, GPU-accelerated |
| Layer model | Graphite structure — fixed Z per omics layer | Genomics Z=0, Transcriptomics Z=1, future layers above |
| Layer planes | Semi-transparent PlaneGeometry in Three.js | Visual separation without occlusion |
| Node colors | Gene/TF: amber (#f59e0b), Transcript: blue (#60a5fa) | Distinct, colorblind-friendly |
| Edge colors | REGULATES activator: green, repressor: red, PRODUCES: purple | Directional semantics |
| On node click | Open detail panel (right sidebar) + "Expand neighborhood" button | Info without losing graph context |
| On expand click | Load 1-hop neighbors, add to existing graph | User controls graph complexity |
| Default load | TP53 neighborhood pre-loaded | Immediately demonstrates value, famous gene |
| Tissue filter | Toggle buttons (All / Blood / Liver / Brain) | Changes edge opacity by tissue_weights threshold |
| Layer toggle | Show/hide genomics / transcriptomics independently | Clean layer exploration |
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
