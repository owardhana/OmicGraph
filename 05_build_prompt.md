# OmniGraph — Fable 5 Build Prompt

Copy everything between the triple-backtick fences into a new Claude Code session
opened at /Users/oliverwardhana/Desktop/Project_OMNI, then run /loop.

```
/loop

You are building OmniGraph — a multi-omics graph knowledge base for biology.

Read these files in full before writing any code:
- 01_vision.md
- 02_mvp.md
- AGENTS.md
- 03_structure.md
- 04_decisions.md   ← all finalized tech decisions live here

04_decisions.md is the ground truth for all tech choices. When in doubt, check it first.

---

KEY DECISIONS SUMMARY (details in 04_decisions.md):

Stack: Neo4j 5 + FastAPI (Python 3.11) + React + TypeScript + Vite + react-force-graph-3d
LLM: OpenRouter API (OpenAI-compatible client, base_url=https://openrouter.ai/api/v1)
  - Text2Cypher + synthesis: anthropic/claude-sonnet-4-6
  - Citation relevance check: anthropic/claude-haiku-4-5-20251001
Scheduling: APScheduler inside FastAPI (no Celery, no Redis)
Search: Neo4j 5 native full-text index on hgnc_symbol + description (CREATE FULLTEXT INDEX, not APOC)
Graph UX: TP53 pre-loaded on page load, click node = detail panel + expand button
Testing: pytest backend only (test_queries, test_agents, test_text2cypher)
Ports: Neo4j 7474/7687, FastAPI 8000, Vite 3000

---

Work through the MVP in this exact order. Complete each phase fully — all files working,
all tests passing — before moving to the next. After each phase: run /code-review high
on all files written in that phase, fix every finding, then proceed.

---

PHASE 1 — Project scaffold

Files to create:
- docker-compose.yml
    Neo4j 5 (ports 7474, 7687), backend (port 8000), frontend (port 3000)
    Neo4j env: NEO4J_AUTH, NEO4J_PLUGINS=["apoc"], volume ./data/neo4j:/data
- .env.example (all vars from 04_decisions.md environment section)
- .gitignore (data/raw/, data/neo4j/, .env, __pycache__, node_modules, dist, .venv)
- backend/requirements.txt
    fastapi, uvicorn, "neo4j>=5.0", openai, "APScheduler>=3.10,<4.0", httpx, pydantic, pydantic-settings, pytest, pytest-asyncio, python-dotenv
    NOTE: APScheduler must be <4.0 — v4 has a completely different async API. AsyncIOScheduler lives in APScheduler 3.x.

- etl/requirements.txt
    neo4j, pandas, httpx, python-dotenv
- backend/config.py
    Load all env vars with pydantic BaseSettings. Expose TISSUES as list, DOROTHEA_MIN_CONFIDENCE as list.
- backend/db/neo4j_client.py
    Async Neo4j driver, connection pool, async context manager for sessions.
    Include: create_indexes() function that creates all indexes on startup:
      - FULLTEXT INDEX gene_search IF NOT EXISTS FOR (n:Gene|Transcript) ON EACH [n.hgnc_symbol, n.description]
      - INDEX gene_ensembl_idx IF NOT EXISTS FOR (n:Gene) ON (n.ensembl_id)
      - INDEX gene_symbol_idx IF NOT EXISTS FOR (n:Gene) ON (n.hgnc_symbol)
      - INDEX transcript_id_idx IF NOT EXISTS FOR (n:Transcript) ON (n.ensembl_tx_id)
    All use Neo4j 5 native syntax (CREATE FULLTEXT INDEX / CREATE INDEX), not APOC procedures.
- etl/utils/neo4j_client.py
    Sync Neo4j driver for ETL scripts (separate from async backend client).
- etl/utils/id_mapper.py
    Load HGNC mapping file. Provide: ensembl_to_hgnc(ensembl_id), hgnc_to_ensembl(symbol).

After phase 1: docker compose up neo4j -d, verify Neo4j browser accessible at localhost:7474.

---

PHASE 2 — ETL pipeline

Files to create:
- etl/00_download.sh
    Download to data/raw/:
    - HGNC: https://ftp.ebi.ac.uk/pub/databases/genenames/hgnc/tsv/hgnc_complete_set.txt
    - GENCODE v46 GTF: https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_human/release_46/gencode.v46.annotation.gtf.gz
    - GTEx v10 median TPM: https://storage.googleapis.com/adult-gtex/bulk-gex/v10/rna-seq/GTEx_Analysis_v10_RNASeQCv2.4.2_gene_median_tpm.gct.gz
    - DoRothEA A-B: https://raw.githubusercontent.com/saezlab/dorothea/master/inst/extdata/dorothea_hs.csv
    Print download progress. Skip files already present.

- etl/01_hgnc.py
    Parse hgnc_complete_set.txt. MERGE (:Gene) nodes with:
      ensembl_id (from ensembl_gene_id column), hgnc_symbol (symbol column),
      hgnc_id, description (name column), chromosome (chromosome column), biotype="protein_coding" default.
    Filter: only rows with valid ensembl_gene_id. Create fulltext index after load.
    Print: nodes created, nodes merged, time elapsed.

- etl/02_gencode.py
    Parse gencode.v46.annotation.gtf.gz (streaming, do not load full file to memory).
    MERGE (:Transcript) nodes for transcript features:
      ensembl_tx_id (transcript_id, strip version), hgnc_symbol (transcript_name), biotype (transcript_type), length_bp.
    MERGE (:Gene)-[:PRODUCES {tissue_weights: {}, source_db: "GENCODE", gencode_version: "v46", pmids: [], citation_attempted: false}]->(:Transcript)
    Match Gene by ensembl_id (strip version from gene_id). Skip transcripts with no matching Gene node.
    Print: transcripts created, PRODUCES edges created.

- etl/03_gtex.py
    Parse GTEx_Analysis_v10_RNASeQCv2.4.2_gene_median_tpm.gct.gz.
    GCT format: skip first 2 header lines, third line = column names.
    Exact GTEx v10 column names to map (case-sensitive):
      "Whole Blood"                        → whole_blood
      "Liver"                              → liver
      "Brain - Frontal Cortex (BA9)"       → brain_prefrontal_cortex
    If exact column not found, print available columns and abort — do not guess.
    For each gene: find PRODUCES edges from that Gene node, SET tissue_weights property.
    Normalize TPM to 0-1 scale per tissue (divide by 99th percentile of that tissue's values).
    Match genes by ensembl_id (strip version from "Name" column e.g. ENSG00000139618.19 → ENSG00000139618).
    Skip genes not in graph. Print: edges updated, genes not found (should be <5%).

- etl/04_dorothea.py
    Parse dorothea_hs.csv. Columns: tf, target, mor, likelihood, confidence.
    Filter: confidence IN ['A', 'B'].
    MERGE (:Gene)-[:REGULATES {
      mode: mor column (1→"activator", -1→"repressor", 0→"unknown"),
      confidence: 1.0 for tier A / 0.85 for tier B,
      confidence_tier: confidence column,
      source_db: "DoRothEA",
      source_version: "v1.0",
      pmids: [],
      citation_attempted: false
    }]->(:Gene)
    Match both source (tf column) and target by hgnc_symbol. Skip if either node missing.
    Print: edges created, edges merged, symbols not found.

After phase 2:
- Run all 4 scripts in order.
- Verify in Neo4j browser:
  MATCH (g:Gene) RETURN count(g)          → expect >40,000
  MATCH (t:Transcript) RETURN count(t)    → expect >200,000
  MATCH ()-[r:PRODUCES]->() RETURN count(r) → expect >200,000
  MATCH ()-[r:REGULATES]->() RETURN count(r) → expect >30,000
- Fix any script that fails counts before proceeding.

---

PHASE 3 — Backend API

Files to create:
- backend/db/queries/genes.py
    get_gene_by_symbol(symbol) → Gene node dict
    get_gene_neighborhood(ensembl_id, tissue, max_hops=1) → {nodes, edges}
    get_gene_subgraph(ensembl_id, tissue, max_hops=2) → {nodes, edges}
    All queries: filter REGULATES by confidence_tier IN ['A','B'].
    Tissue filter: include PRODUCES edge if tissue_weights[tissue] > 0.3, or no filter if tissue="all".
    All returned Gene nodes must include is_tf: bool — true if node has any outgoing REGULATES edges.
    Add to Cypher: OPTIONAL MATCH (g)-[:REGULATES]->() WITH g, count(*) > 0 AS is_tf

- backend/db/queries/transcripts.py
    get_transcript_by_id(ensembl_tx_id) → Transcript node dict
    get_transcript_neighborhood(ensembl_tx_id) → {nodes, edges}

- backend/db/queries/graph.py
    search_genes(query, limit=10) → list of Gene nodes
      Use: CALL db.index.fulltext.queryNodes("gene_search", $q) YIELD node, score RETURN node ORDER BY score DESC LIMIT $limit
      This is Neo4j built-in procedure (not APOC) — works after CREATE FULLTEXT INDEX.
    get_edge_detail(source_id, target_id, rel_type) → edge properties + pmids

- backend/api/models.py
    Pydantic models: GeneNode, TranscriptNode, GraphEdge, GraphResponse,
    SearchResult, QueryRequest, QueryResponse, EdgeDetail.

- backend/api/routes/genes.py
    GET /api/gene/{hgnc_symbol} → GeneNode
    GET /api/gene/{hgnc_symbol}/graph?tissue=all&hops=1 → GraphResponse

- backend/api/routes/transcripts.py
    GET /api/transcript/{ensembl_tx_id} → TranscriptNode

- backend/api/routes/search.py
    GET /api/search?q={query}&limit=10 → list[SearchResult]

- backend/api/routes/admin.py
    POST /admin/agents/citation/run → trigger CitationAgent immediately
    GET  /admin/agents/citation/log → last 10 CitationRun log entries

- backend/main.py
    FastAPI app. CORS: allow origins ["http://localhost:3000", "http://127.0.0.1:3000"].
    Register all routers. On startup: call create_indexes(), start APScheduler.
    APScheduler: AsyncIOScheduler, add_job(citation_agent.run, "cron", hour=settings.CITATION_AGENT_CRON_HOUR).
    APScheduler must be started AFTER app startup event (use @app.on_event("startup")).

After phase 3: uvicorn backend.main:app --reload
Test every endpoint with curl:
  curl localhost:8000/api/search?q=TP53
  curl localhost:8000/api/gene/TP53
  curl localhost:8000/api/gene/TP53/graph?tissue=liver
All must return valid JSON with nodes + edges. Fix failures before proceeding.

---

PHASE 4 — LLM layer + agents

Files to create:
- backend/llm/client.py
    AsyncOpenAI client pointed at OpenRouter.
    Async wrapper: async def complete(model, messages, **kwargs) → str
    Include: model constants from config (TEXT2CYPHER_MODEL, etc.)

- backend/llm/prompts/text2cypher.py
    System prompt string. Include:
    - Full Neo4j schema (Gene, Transcript, REGULATES, PRODUCES with all properties)
    - 5 worked examples: question → Cypher (cover: TF regulators, tissue filter, transcript lookup, multi-hop, repressor query)
    - Rules: always filter confidence_tier IN ['A','B'], use hgnc_symbol for lookup, return pmids

- backend/llm/prompts/synthesis.py
    System prompt for answer synthesis from Cypher results. Include citation formatting rules.

- backend/llm/prompts/citation_check.py
    System prompt for abstract relevance check. Input: abstract text + two entity names.
    Output: JSON {relevant: bool, reason: str}

- backend/llm/validators.py
    validate_cypher(query: str) → bool
    Use neo4j driver EXPLAIN to dry-run. Return False + log if invalid.
    Block: any Cypher containing MERGE, CREATE, DELETE, SET (read-only enforcement).

- backend/agents/base_agent.py
    BaseAgent class: run_with_logging(), write_run_log_to_graph(), retry(n=2).
    Provenance tagging: source_agent, agent_version, run_timestamp on all writes.

- backend/agents/query_agent.py
    QueryAgent.query(question, tissue, max_hops) → QueryResponse
    Flow: question → text2cypher prompt → LLM → validate_cypher → execute → synthesis prompt → LLM → return
    On invalid Cypher after 2 retries: return structured error, not hallucinated answer.
    Max Neo4j execution time: 10s timeout.

- backend/agents/citation_agent.py
    CitationAgent.run(batch_size=100)
    Fetch edges where pmids=[] AND citation_attempted!=true.
    For each: NCBI E-utilities search "{source.hgnc_symbol} {target.hgnc_symbol} regulation".
    Fetch abstracts. Filter via citation_check LLM prompt (haiku model).
    Write validated PMIDs to edge. Set citation_attempted=true.
    Rate limit: 3 req/s without NCBI key, 10/s with key.
    Write CitationRun log node to graph after each batch.

- backend/api/routes/query.py
    POST /api/query → QueryRequest → QueryAgent.query() → QueryResponse

- backend/tests/conftest.py
    pytest fixtures: neo4j_session (connects to live Neo4j at NEO4J_URI from .env),
    sample_gene fixture (fetch TP53 node), sample_edge fixture (one REGULATES edge).

- backend/tests/test_queries.py
    test_gene_lookup: get_gene_by_symbol("TP53") returns node with ensembl_id + hgnc_symbol
    test_neighborhood: get_gene_neighborhood returns nodes + edges, all edges have confidence_tier
    test_tissue_filter: tissue="liver" returns only edges where tissue_weights.liver > 0.3
    test_search: search_genes("TP53") returns TP53 as first result

- backend/tests/test_agents.py
    test_citation_agent_no_new_nodes: run CitationAgent on 5 edges, assert node count unchanged
    test_citation_agent_no_new_edges: run CitationAgent, assert REGULATES + PRODUCES count unchanged
    test_citation_agent_sets_attempted: after run, edges have citation_attempted=true
    test_citation_agent_pmids_are_strings: all written PMIDs are strings, not ints or dicts

- backend/tests/test_text2cypher.py
    For each of the 5 benchmark questions: call QueryAgent, assert response.cypher is non-empty string,
    assert response.answer is non-empty string, assert no Cypher write keywords (MERGE/CREATE/DELETE/SET).

After phase 4:
- Test QueryAgent with 5 benchmark questions:
  1. "What transcription factors regulate TP53?"
  2. "What transcripts does BRCA2 produce in liver?"
  3. "Which TFs repress MYC?"
  4. "What are the most confident TF regulators of EGFR in brain?"
  5. "Show me transcripts of TP53 with high expression in blood"
  All must return valid Cypher + synthesized answer + citations list.
- Run CitationAgent manually: POST /admin/agents/citation/run
  Verify: 10+ edges now have pmids populated. Verify no new nodes/edges created.
- Run pytest backend/tests/ — all tests must pass.

---

PHASE 5 — Frontend

Files to create:
- frontend/ (Vite scaffold: npm create vite@latest frontend -- --template react-ts)
- frontend/src/types/graph.ts
    TypeScript interfaces matching backend Pydantic models exactly:
    GeneNode, TranscriptNode, GraphEdge, GraphResponse, SearchResult, QueryRequest, QueryResponse

- frontend/.env
    VITE_API_URL=http://localhost:8000
    (Vite only reads VITE_-prefixed vars. This file is separate from root .env.)

- frontend/src/api/client.ts
    Typed fetch wrappers for all backend endpoints. Base URL from import.meta.env.VITE_API_URL.

- frontend/src/styles/layers.ts
    Layer config: { genomics: { z: 0, color: '#f59e0b', label: 'Genomics' },
                    transcriptomics: { z: 300, color: '#60a5fa', label: 'Transcriptomics' } }
    Node colors: TF (Gene with outgoing REGULATES) = '#f59e0b' amber,
                 Gene (no outgoing REGULATES) = '#4ade80' green,
                 Transcript = '#60a5fa' blue
    Edge colors: REGULATES activator '#22c55e', repressor '#ef4444', PRODUCES '#a78bfa'
    Node sizes: TF 12, Gene 8, Transcript 6

- frontend/src/hooks/useGraph.ts
    Fetch gene subgraph from /api/gene/{symbol}/graph. Transform to react-force-graph-3d format.
    Fix node Z position by layer (Gene Z=0, Transcript Z=300). Free X/Y simulation within layer.

- frontend/src/hooks/useSearch.ts
    Debounced search (300ms) against /api/search. Return SearchResult list.

- frontend/src/hooks/useQuery.ts
    POST /api/query state management. Loading, error, result states.

- frontend/src/components/GraphViewer3D.tsx
    react-force-graph-3d component.
    Layer planes: two semi-transparent PlaneGeometry rectangles at Z=0 and Z=300.
    Node render: colored sphere by type (TF=amber #f59e0b, Gene=green #4ade80, Transcript=blue #60a5fa). Size by connection count.
    Determine if Gene is a TF: check if node has `is_tf: true` property (set by backend when node has outgoing REGULATES edges).
    Edge render: directed arrows, colored by REGULATES mode or PRODUCES.
    On node click: call onNodeClick(node) prop → parent opens detail panel.
    On background click: deselect.
    nodeZVal: fixed by node.layer_z (prevent Z-axis force simulation).
    On mount: load TP53 neighborhood as default (DEFAULT_GENE from env).

- frontend/src/components/SearchBar.tsx
    Input field, autocomplete dropdown from useSearch results.
    On select: trigger graph load for selected gene. Clear on Escape.

- frontend/src/components/TissueFilter.tsx
    Four toggle buttons: All / Blood / Liver / Brain.
    On change: re-fetch graph with tissue param. Active button highlighted.

- frontend/src/components/EdgeDetailPanel.tsx
    Shows on edge hover (not click). Displays: type, mode, confidence, tissue weights bar chart,
    PMID list as clickable links (https://pubmed.ncbi.nlm.nih.gov/{pmid}).

- frontend/src/components/NodeDetailPanel.tsx
    Right sidebar. Shows on node click.
    Gene panel: symbol, description, chromosome, biotype, "Expand Neighborhood" button.
    Transcript panel: id, biotype, length, parent gene link.
    Expand button: calls onExpand(node) → adds 1-hop neighbors to graph.

- frontend/src/components/LayerToggle.tsx
    Two checkboxes: Genomics / Transcriptomics. Toggle node visibility by layer.

- frontend/src/components/QueryPanel.tsx
    Collapsible bottom drawer. Text input + submit.
    Shows: answer text, Cypher query (collapsible code block), citation list with PubMed links.
    Loading spinner during query. Error state if query fails.

- frontend/src/App.tsx
    Layout: full-screen GraphViewer3D, SearchBar top-left, TissueFilter top-right,
    LayerToggle top-center, NodeDetailPanel right sidebar (slides in on click),
    QueryPanel bottom drawer (toggle button bottom-right).
    State: selectedNode, activeTissue, visibleLayers, graphData.
    On mount: load TP53 subgraph.

After phase 5: npm run dev (keep running), then run /verify to confirm all 8 checks pass in the live app:
  1. Page loads → TP53 graph visible in 3D with two layers
  2. Search "BRCA2" → graph updates to BRCA2 neighborhood
  3. Tissue filter "Liver" → edge opacity changes
  4. Click a Gene node → detail panel opens with expand button
  5. Click expand → neighbor nodes added to graph
  6. Open query panel → type "What TFs regulate TP53?" → answer appears with citations
  7. Toggle off Transcriptomics layer → transcript nodes disappear
  8. Hover edge → edge detail panel shows confidence + PMIDs
All 8 checks must pass. If /verify finds failures, fix them before declaring done.

---

KNOWN RISKS (handle if encountered):
- GTEx v10 URL may have changed — if download fails, check gtexportal.org for current median TPM file URL
- DoRothEA CSV URL may have moved — if fails, check github.com/saezlab/dorothea releases for dorothea_hs.csv
- ETL scripts must use python3.11 explicitly (system may default to 3.9): run as `python3.11 etl/01_hgnc.py`
- ETL venv: create with `python3.11 -m venv etl/.venv && source etl/.venv/bin/activate && pip install -r etl/requirements.txt`
- Frontend env: VITE_API_URL goes in frontend/.env (not root .env), Vite only reads prefixed VITE_ vars

RULES (non-negotiable):
- No placeholder code or TODOs — every file complete and functional
- All ETL uses MERGE (idempotent), never CREATE alone
- All agent writes carry: source_agent, agent_version, run_timestamp
- validate_cypher() blocks MERGE/CREATE/DELETE/SET — enforced before every LLM Cypher execution
- No new graph topology from LLM — PMIDs only from CitationAgent
- After each phase: /code-review high, fix all findings before next phase
- After phase 5: /verify to confirm all 8 smoke test checks pass in the live app
- If smoke test or /verify fails and cause is unclear: run /diagnose before trying random fixes
- If smoke test fails: debug and fix, do not skip and move on
- OpenRouter client (not Anthropic SDK) — base_url=https://openrouter.ai/api/v1
```
