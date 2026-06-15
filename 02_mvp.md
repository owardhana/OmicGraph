# OmniGraph — MVP Specification

## Goal

Working demo for computational biology collaborators at ~3 months.
Success = user queries a gene, sees 3D graph of TF regulators + transcripts across 3 tissues, clicks an edge and sees citations.

---

## Scope

### In scope (MVP)

- Gene nodes (Ensembl ID, HGNC symbol, description)
- Transcript nodes (Ensembl TX ID, biotype)
- TF → Gene edges (DoRothEA A-B confidence, directed, regulatory)
- Gene → Transcript edges (GENCODE structure + GTEx tissue weights)
- 3 tissues: whole blood, liver, brain (prefrontal cortex)
- 3D layered visualization (genomics layer Z=0, transcriptomics Z=1)
- Gene/TF search by HGNC symbol
- Neighborhood traversal (1-2 hops)
- Edge detail panel (type, confidence, tissue weights, PMIDs)
- Text2Cypher query (natural language → Cypher → result)
- Citation agent (PubMed PMID attachment to existing edges)

### Out of scope (MVP)

- Protein / metabolite layers
- Cancer or perturbation data
- New edge extraction by agent (topology creation)
- Vector RAG
- User accounts / saved queries
- API access for programmatic queries
- Cell-type resolution

---

## Data sources

| Source | Data loaded | Format | Script |
|--------|------------|--------|--------|
| HGNC | Gene symbols + ID mapping | TSV (download) | `etl/01_hgnc.py` |
| GENCODE v46 | Gene + transcript structure | GTF | `etl/02_gencode.py` |
| GTEx v10 | Tissue expression weights (blood/liver/brain) | median TPM TSV | `etl/03_gtex.py` |
| DoRothEA A-B | TF → target edges + confidence | CSV (R export) | `etl/04_dorothea.py` |
| PubMed (citation agent) | PMIDs for edge enrichment | API | `agents/citation_agent.py` |

Load order: HGNC → GENCODE → GTEx → DoRothEA (dependencies in that order).

---

## Graph schema (Neo4j)

### Node: Gene
```cypher
(:Gene {
  ensembl_id: "ENSG00000139618",   // canonical key
  hgnc_symbol: "BRCA2",            // display + search
  hgnc_id: "HGNC:1101",
  description: "BRCA2 DNA repair...",
  chromosome: "13",
  biotype: "protein_coding"
})
```

### Node: Transcript
```cypher
(:Transcript {
  ensembl_tx_id: "ENST00000380152",
  hgnc_symbol: "BRCA2-201",
  biotype: "protein_coding",
  length_bp: 10257
})
```

### Edge: REGULATES (TF → Gene)
```cypher
(:Gene)-[:REGULATES {
  mode: "activator" | "repressor" | "unknown",
  confidence: 0.92,               // DoRothEA score
  confidence_tier: "A",           // A or B
  source_db: "DoRothEA",
  source_version: "v1.0",
  pmids: ["12345678", "23456789"]
}]->(:Gene)
```

### Edge: PRODUCES (Gene → Transcript)
```cypher
(:Gene)-[:PRODUCES {
  tissue_weights: {
    whole_blood: 0.73,
    liver: 0.45,
    brain_prefrontal_cortex: 0.88
  },
  source_db: "GENCODE+GTEx",
  gencode_version: "v46",
  gtex_version: "v10",
  pmids: []
}]->(:Transcript)
```

### Node: DataSource (metadata)
```cypher
(:DataSource {
  name: "DoRothEA",
  version: "v1.0",
  loaded_at: "2026-06-15",
  record_count: 47823
})
```

---

## Tech stack

```
Frontend:   React + TypeScript + Vite + react-force-graph-3d (Three.js)
Backend:    FastAPI (Python 3.11+)
Graph DB:   Neo4j Community 5.x (self-hosted, Docker)
LLM:        OpenRouter API (OpenAI-compatible) — Text2Cypher + citation agent
ETL:        Python scripts (pandas, neo4j driver)
```

### Docker compose (local dev)
```yaml
services:
  neo4j:
    image: neo4j:5
    ports: ["7474:7474", "7687:7687"]
    environment:
      NEO4J_AUTH: neo4j/password
      NEO4J_PLUGINS: '["apoc"]'
    volumes: ["./data/neo4j:/data"]

  api:
    build: ./backend
    ports: ["8000:8000"]
    depends_on: [neo4j]

  frontend:
    build: ./frontend
    ports: ["3000:3000"]
    depends_on: [api]
```

---

## 3D Visualization

### Layer structure (graphite model)
```
Z = 1.0  ┌─────────────────────────────┐
          │   TRANSCRIPTOMICS LAYER      │  ← Transcript nodes
          │   (blue, semi-transparent)   │
Z = 0.0  └─────────────────────────────┘
          │   GENOMICS LAYER             │  ← Gene / TF nodes
          │   (green, semi-transparent)  │
          └─────────────────────────────┘
```

Node color:
- Gene (non-TF): `#4ade80` (green)
- TF: `#f59e0b` (amber)
- Transcript: `#60a5fa` (blue)

Edge color:
- REGULATES (activator): `#22c55e`
- REGULATES (repressor): `#ef4444`
- PRODUCES: `#a78bfa`

Layer planes rendered as transparent `PlaneGeometry` in Three.js.
Node Z-position fixed by type, X/Y free-simulated (force layout within layer).

### Tissue filter
Dropdown: All / Blood / Liver / Brain
Filters edge opacity by `tissue_weights[selected]` threshold (>0.3 = visible).

---

## Backend API

```
GET  /api/gene/{hgnc_symbol}          → gene node + neighbors (1 hop)
GET  /api/gene/{hgnc_symbol}/graph    → subgraph (2 hops, tissue filter)
GET  /api/transcript/{ensembl_tx_id}  → transcript node
GET  /api/search?q={symbol}           → fuzzy HGNC symbol search
POST /api/query                       → { "question": "..." } → Text2Cypher result
GET  /api/edge/{id}                   → edge detail + pmids
```

---

## Text2Cypher (RAG layer)

### Flow
```
User: "What TFs repress TP53 in liver?"
  ↓
System prompt: schema description + Cypher examples
  ↓
Claude API → generates Cypher
  ↓
FastAPI validates + executes against Neo4j
  ↓
Result formatted → Claude API synthesizes natural language answer
  ↓
Citations (PMIDs) attached to response
```

### Cypher generation prompt (skeleton)
```
You are a Neo4j Cypher expert for a multi-omics knowledge graph.

Schema:
- (:Gene {ensembl_id, hgnc_symbol, biotype})
- (:Transcript {ensembl_tx_id, hgnc_symbol, biotype})
- (:Gene)-[:REGULATES {mode, confidence, tissue_weights, pmids}]->(:Gene)
- (:Gene)-[:PRODUCES {tissue_weights, pmids}]->(:Transcript)

Rules:
- Always filter by confidence_tier IN ['A','B'] for REGULATES edges
- Use hgnc_symbol for gene lookup
- Return pmids on edges
- For tissue queries, check tissue_weights[tissue] > 0.3

Question: {user_question}
Return only the Cypher query, no explanation.
```

---

## Citation Agent

### Trigger
Runs nightly (cron). Processes edges with `pmids: []`.

### Flow
```python
for edge in graph.get_edges_without_citations(limit=100):
    entity_a = edge.source.hgnc_symbol
    entity_b = edge.target.hgnc_symbol
    pmids = pubmed_search(f"{entity_a} {entity_b} regulation", max_results=5)
    validated = [p for p in pmids if abstract_mentions_both(p, entity_a, entity_b)]
    graph.attach_pmids(edge.id, validated)
```

### PubMed search
- API: NCBI E-utilities (free, no key needed for low volume)
- Validate: fetch abstract, check both entity names appear in title/abstract
- Store: PMID list only — no full text, no LLM-generated claims

---

## ETL pipeline

### Run order
```bash
python etl/01_hgnc.py          # ~2 min, loads gene ID mapping
python etl/02_gencode.py       # ~10 min, loads gene + transcript nodes
python etl/03_gtex.py          # ~15 min, loads tissue weights onto PRODUCES edges
python etl/04_dorothea.py      # ~5 min, loads TF→gene REGULATES edges
```

### Idempotency
All scripts use `MERGE` (not `CREATE`) in Cypher — safe to re-run on updates.
Each run logs to `DataSource` node with timestamp + record count.

---

## Build timeline

### Month 1 — Data foundation
- Week 1: Neo4j Docker setup + schema design
- Week 2: ETL scripts (HGNC + GENCODE)
- Week 3: ETL scripts (GTEx + DoRothEA)
- Week 4: FastAPI skeleton + basic graph queries working

### Month 2 — Backend + LLM
- Week 1: REST API endpoints
- Week 2: Text2Cypher integration (Claude API)
- Week 3: Citation agent (PubMed E-utilities)
- Week 4: Query testing + edge case handling

### Month 3 — Frontend + demo polish
- Week 1: React scaffold + react-force-graph-3d basic render
- Week 2: Graphite layer viz (fixed Z positions, layer planes)
- Week 3: Search UI + edge detail panel + tissue filter
- Week 4: Demo polish + collaborator testing

---

## MVP success criteria

- [ ] Graph loads: >40k gene nodes, >200k transcript nodes, >50k TF→gene edges
- [ ] Query "TP53" → 3D graph renders in <3s
- [ ] Tissue filter changes edge visibility correctly
- [ ] Text2Cypher answers 5 benchmark questions correctly
- [ ] Each edge shows at least 1 PMID (citation agent)
- [ ] Demo walkthrough <10 min for new user

---

## Known risks

| Risk | Mitigation |
|------|-----------|
| DoRothEA A-B edges sparse for some TFs | Add B-tier, lower threshold if needed |
| react-force-graph-3d slow >10k nodes | Implement node culling + LOD |
| Text2Cypher generates invalid Cypher | Validate + retry loop, fallback error message |
| GTEx tissue weights missing for some transcripts | Null-safe edge properties, show "no data" in UI |
| Neo4j Community memory limits | Index only queried properties, use APOC for bulk ops |

---

## v2 roadmap (post-demo)

- Protein layer (UniProt + STRING PPIs)
- Cancer data scope (TCGA differential expression)
- Vector RAG (hybrid query mode)
- Agent topology extraction (new edge proposals + validation queue)
- API access for programmatic queries
- Cell-type resolution (CellxGene integration)
- Metabolomics layer (KEGG/Recon3D)
