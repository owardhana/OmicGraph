# OmniGraph — Project Structure

## Directory tree

```
Project_OMNI/
│
├── AGENTS.md                        ← agent definitions + safety rules
├── 01_vision.md                     ← project vision + full-scope design
├── 02_mvp.md                        ← MVP spec, schema, timeline
├── 03_structure.md                  ← this file
│
├── docker-compose.yml               ← Neo4j + backend + frontend
├── .env.example                     ← env var template (no secrets committed)
├── .gitignore
│
├── data/
│   ├── raw/                         ← downloaded source files (gitignored)
│   │   ├── hgnc_complete_set.txt
│   │   ├── gencode.v46.annotation.gtf.gz
│   │   ├── GTEx_Analysis_v10_eGenes.txt
│   │   └── dorothea_ab.csv
│   ├── processed/                   ← transformed TSVs ready for Neo4j import
│   └── neo4j/                       ← Neo4j data volume (gitignored)
│
├── etl/                             ← data ingestion scripts, run in order
│   ├── 00_download.sh               ← download all raw sources
│   ├── 01_hgnc.py                   ← gene nodes + ID mapping
│   ├── 02_gencode.py                ← gene + transcript nodes, PRODUCES edges
│   ├── 03_gtex.py                   ← tissue weights onto PRODUCES edges
│   ├── 05_proteins.py               ← TF Protein nodes + TRANSLATES_TO/ENCODES (runs before 04)
│   ├── 04_dorothea.py               ← Protein(TF)→Gene REGULATES edges
│   └── utils/
│       ├── neo4j_client.py          ← shared Neo4j connection
│       └── id_mapper.py             ← Ensembl ↔ HGNC ↔ UniProt mapping
│
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py                      ← FastAPI app entry point
│   │
│   ├── api/
│   │   ├── routes/
│   │   │   ├── genes.py             ← GET /gene/{symbol}, /gene/{symbol}/graph
│   │   │   ├── transcripts.py       ← GET /transcript/{id}
│   │   │   ├── search.py            ← GET /search?q=
│   │   │   ├── query.py             ← POST /query (Text2Cypher)
│   │   │   └── admin.py             ← POST /admin/agents/*/run
│   │   └── models.py                ← Pydantic request/response schemas
│   │
│   ├── db/
│   │   ├── neo4j_client.py          ← connection pool, session management
│   │   └── queries/
│   │       ├── genes.py             ← Cypher for gene endpoints
│   │       ├── transcripts.py       ← Cypher for transcript endpoints
│   │       └── graph.py             ← subgraph traversal Cypher
│   │
│   ├── agents/
│   │   ├── base_agent.py            ← shared: logging, retry, provenance
│   │   ├── query_agent.py           ← Text2Cypher + response synthesis
│   │   └── citation_agent.py        ← PubMed enrichment (MVP)
│   │   # v2 additions:
│   │   # ├── literature_agent.py
│   │   # ├── validation_agent.py
│   │   # └── freshness_agent.py
│   │
│   ├── llm/
│   │   ├── client.py                ← Claude API wrapper (anthropic SDK)
│   │   ├── prompts/
│   │   │   ├── text2cypher.py       ← Cypher generation system prompt
│   │   │   ├── synthesis.py         ← answer synthesis prompt
│   │   │   └── citation_check.py   ← abstract relevance check prompt
│   │   └── validators.py            ← Cypher syntax validation
│   │
│   └── config.py                    ← env vars, constants (tissues, thresholds)
│
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── tsconfig.json
│   └── src/
│       ├── App.tsx
│       ├── main.tsx
│       │
│       ├── components/
│       │   ├── GraphViewer3D.tsx     ← react-force-graph-3d, layer planes
│       │   ├── SearchBar.tsx         ← HGNC symbol search + autocomplete
│       │   ├── EdgeDetailPanel.tsx   ← edge info: type, confidence, PMIDs
│       │   ├── NodeDetailPanel.tsx   ← gene/transcript info card
│       │   ├── TissueFilter.tsx      ← blood / liver / brain toggle
│       │   ├── QueryPanel.tsx        ← natural language query + answer display
│       │   └── LayerToggle.tsx       ← show/hide genomics / transcriptomics
│       │
│       ├── hooks/
│       │   ├── useGraph.ts           ← fetch + transform graph data for viz
│       │   ├── useQuery.ts           ← Text2Cypher query state
│       │   └── useSearch.ts          ← search debounce + results
│       │
│       ├── api/
│       │   └── client.ts             ← typed API calls (fetch wrappers)
│       │
│       ├── types/
│       │   └── graph.ts              ← GraphNode, GraphEdge, QueryResult types
│       │
│       └── styles/
│           └── layers.ts             ← layer colors, node colors, edge colors
│
└── docs/
    └── adr/                          ← Architecture Decision Records (when needed)
```

---

## Key design decisions in structure

### ETL lives outside backend
ETL scripts are one-shot ops, not part of the running service. Separate `etl/` dir — no FastAPI dependency, run directly with Python. Shared only via `etl/utils/neo4j_client.py`.

### Agents live inside backend
Agents run as scheduled tasks triggered by FastAPI admin routes or external cron. They share the same Neo4j connection pool + Claude API client as the rest of the backend. No separate service for MVP.

### LLM layer isolated
All Claude API calls go through `backend/llm/`. Prompts in `backend/llm/prompts/` as Python files — not string literals in business logic. Easy to version + swap prompts without touching agent logic.

### Queries as separate module
Cypher strings in `backend/db/queries/` — not inline in route handlers. Makes Cypher testable, reviewable, and maintainable as graph schema evolves.

### Frontend types match backend models
`frontend/src/types/graph.ts` mirrors `backend/api/models.py` Pydantic schemas. Single source of truth = backend. If schema changes, update Pydantic first, then TS types.

---

## What gets gitignored

```gitignore
# source data (large files)
data/raw/
data/processed/
data/neo4j/

# secrets
.env

# python
__pycache__/
*.pyc
.venv/

# node
node_modules/
dist/
```

Raw data downloaded via `etl/00_download.sh` — reproducible, not committed.

---

## Environment variables (.env.example)

```bash
# Neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=changeme

# Claude API
ANTHROPIC_API_KEY=sk-ant-...

# NCBI (optional — higher rate limit with key)
NCBI_API_KEY=

# App
TISSUES=whole_blood,liver,brain_prefrontal_cortex
DOROTHEA_MIN_CONFIDENCE=A,B
TEXT2CYPHER_MODEL=claude-sonnet-4-6
CITATION_AGENT_BATCH_SIZE=100
```

---

## Development setup (local)

```bash
# 1. Start Neo4j
docker compose up neo4j -d

# 2. Load data (one-time, ~30 min total)
cd etl
bash 00_download.sh
python 01_hgnc.py
python 02_gencode.py
python 03_gtex.py
python 04_dorothea.py

# 3. Start backend
cd backend
pip install -r requirements.txt
uvicorn main:app --reload

# 4. Start frontend
cd frontend
npm install
npm run dev
```

---

## Module dependency rules

```
frontend → backend API only (no direct Neo4j)
backend/api → backend/db + backend/agents + backend/llm
backend/agents → backend/db + backend/llm
backend/db → Neo4j only
backend/llm → Claude API only
etl → Neo4j only (via etl/utils/neo4j_client.py)
```

No circular deps. Agents never call API routes. ETL never imports backend modules.
