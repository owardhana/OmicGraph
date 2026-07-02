# OmniGraph — Agent Definitions

Agents are autonomous processes that read/write the graph or respond to user queries.
Each agent has a defined scope, trigger, and hard constraints.

---

## Agent taxonomy

```
MVP agents (built)
├── CitationAgent    — PubMed PMID enrichment, nightly
├── EmbeddingAgent   — semantic-search embeddings (cron opt-in, default off; run on demand)
├── ChatAgent        — agentic tool-loop over the graph, streaming, per-request
│                      (the query surface; replaced the single-shot Text2Cypher endpoint)
└── ExtractionAgent  — literature -> CandidateEdge proposals (Feature 2 P1 scaffold;
                       OFF by default, admin-gated; staging only, promotion is P2)

v2 agents (post-demo)
├── ValidationAgent  — promotion gate: scores + promotes CandidateEdges (Feature 2 P2)
└── FreshnessAgent   — monitors source DB versions, triggers ETL
```

---

## MVP Agents

> Natural-language → Cypher querying is no longer a standalone agent. The former
> single-shot **QueryAgent** (`POST /api/query`, Text2Cypher) was removed once the
> **ChatAgent** subsumed it: `run_cypher` inside the chat tool-loop does the same
> NL→Cypher job in-context, validator-gated. See ChatAgent below.

### 1. CitationAgent

**Role:** Enrich existing graph edges with supporting PubMed PMIDs. Never creates new edges or nodes.

**Trigger:** Nightly cron (00:00 UTC). Also triggerable manually via `POST /admin/agents/citation/run`.

**Input:** `REGULATES` edges where `pmids = []`, batched 100/run. (Post-ADR-0004
these are `(:Protein)-[:REGULATES]->(:Gene)`; the source's `hgnc_symbol` still
drives the PubMed query, so the flow below is unchanged — only the node-label
match in `_fetch_uncited_edges` moves from `:Gene` to `:Protein`.)

**Flow:**
```
fetch batch of edges with no citations
  → for each edge:
      build PubMed query: "{source.hgnc_symbol} {target.hgnc_symbol} regulation"
      → NCBI E-utilities search (max 10 results)
      → fetch abstracts
      → filter: abstract must mention BOTH entity names
      → optional: Claude API to confirm relevance (1 sentence check)
      → attach validated PMIDs to edge
      → log: edge_id, pmids_added, timestamp
  → update DataSource log node
```

**Output:** PMIDs written to edge property `pmids: [...]`. Run log written to `CitationRun` node.

**Constraints:**
- NEVER creates new edges or nodes
- NEVER stores full text — PMIDs only
- NEVER trusts LLM to assert biological facts — only to confirm entity co-mention
- Rate limit: 3 NCBI requests/second (free tier)
- Skip edge if already has ≥3 PMIDs
- Mark edge `citation_attempted: true` even if 0 results (prevent re-querying)

**Tools:** NCBI E-utilities API, Neo4j driver, OpenRouter API (optional relevance check, haiku model)

**Files:** `backend/agents/citation_agent.py`

---

### 2. ChatAgent

**Role:** Conversational, agentic assistant over the graph. Multi-turn, streaming,
tool-using — the analyst-facing query surface (replaced the former single-shot
Text2Cypher endpoint).

**Trigger:** Per user request (HTTP `POST /api/chat/stream`, Server-Sent Events).

**Flow:**
```
load prior turns (conversational memory) → [system, ...history, user]
  → stream an LLM turn (OpenRouter, SYNTHESIS_MODEL) advertising 5 read-only tools
  → if it requested tools: run them, append results, loop (max 6 iterations)
  → else: the streamed text is the final answer
  → forced final no-tools turn if the tool budget is exhausted
  → persist the user + assistant turns
```

**Tools (all READ-ONLY, no write path):** `search_graph` (resolve name→id, full-text),
`semantic_search` (find entities by meaning — embeds the query, then vector-searches
Gene/Protein/Disease; ADR-0008 — the query-time consumer of the EmbeddingAgent's
vectors), `get_subgraph` (signal-decay neighbourhood), `shortest_path` (explain how two
entities connect), `run_cypher` (read-only aggregations — routed through
`validate_cypher`, a single-MATCH read-only guard).

**Memory:** prior user/assistant *text* turns stored in Neo4j as
`(:ChatSession {id})-[:HAS_TURN]->(:ChatTurn {role, content, seq, ts})`. Tool calls are
ephemeral (re-run on demand), never persisted. Operational nodes, never biological topology.

**Constraints:**
- Never writes to the graph — every tool is read-only; `run_cypher` is validator-gated.
- Tool loop is bounded (`_MAX_TOOL_ITERS`=6); errors surface as a clean event, not a 500.
- Tool results are compacted (trimmed fields, capped lists) to bound context + token cost.

**Tools:** OpenRouter API (streaming + tool-calling), Neo4j driver, Cypher validator.

**Files:** `backend/agents/chat_agent.py`, `backend/agents/tools.py`,
`backend/db/queries/chat.py`, `backend/api/routes/chat.py`.

---

### 3. ExtractionAgent

**Role:** Read PubMed and **propose** node↔node relationships as `CandidateEdge`
staging nodes — the first agent to propose topology. Closed-world (links only to
existing graph nodes), abstracts only, MVP edge types `INTERACTS_WITH` + `IMPLICATED_IN`.

**Trigger:** Manual, **gated** — `POST /admin/agents/extraction/run` returns
`disabled` unless `EXTRACTION_AGENT_ENABLED=true` (spends NCBI + LLM). No cron.

**Flow:** build gazetteer from graph → PubMed reldate delta (E-utils) → per sentence
with ≥2 distinct linked entities → cheap LLM verdict per in-vocab pair (polarity:
affirm/negate/hedge) → `stage_verdict`: enrich existing trusted edge, else upsert a
`CandidateEdge` (+`CandidateEvidence` per PMID; confidence = independent-PMID agreement).

**Constraints (ADR-0013):** NEVER writes trusted topology. Candidates are operational
labels with endpoint ids as **string properties** (not relationships) → invisible to
traversal/search/counts. Promoted edges (P2) will carry `provenance_tier='literature'`.

**Files:** `backend/agents/extraction_agent.py`, `backend/extraction/{dictionary,ingest,relation,stage}.py`,
`backend/llm/prompts/extraction.py`. Design: `docs/design/feature-2-literature-extraction.md`.

---

## v2 Agents (define now, build later)

> **LiteratureAgent is BUILT** as the **ExtractionAgent** (MVP §3 above, Feature 2 P1).
> Its original sketch here is superseded by [ADR-0013](docs/adr/0013-literature-extraction-trust-model.md):
> staging label is `CandidateEdge`/`CandidateEvidence` (not `EdgeCandidate`), and
> promoted edges carry `provenance_tier='literature'` (not `source:agent_extracted`).
> What remains for v2 is the **promotion gate** below.

### ValidationAgent (Feature 2 P2 — promotion gate)

**Role:** Score `CandidateEdge`s from the ExtractionAgent. Auto-promote high-confidence
candidates (with ≥N independent PMIDs), flag borderline for human review. On promote,
mint the real typed edge tagged `provenance_tier='literature'` (ADR-0013).

**Trigger:** After each ExtractionAgent run. Also per-candidate via admin UI.

**Flow:**
```
fetch EdgeCandidates with status=pending_review
  → for each candidate:
      → check: does relationship already exist in graph? (dedup)
      → check: do source entities exist as nodes? (entity resolution)
      → cross-reference: does DoRothEA / ENCODE corroborate? (+score)
      → cross-reference: does any existing PMID on edge overlap? (+score)
      → compute final score (0-1)
      → score ≥ 0.85 → auto-promote to graph (source: agent_extracted)
      → score 0.60-0.84 → flag for human review in admin UI
      → score < 0.60 → discard, log reason
```

**Output:** Edges promoted to graph tagged `source: "agent_extracted"`, `review_status: "auto_approved"`.

**Constraints:**
- Auto-promoted edges must carry: PMID, extracted sentence, agent confidence score, source model version
- Human-reviewed edges tagged `review_status: "human_approved"`
- Disputed edges tagged `review_status: "rejected"` — kept in log, never deleted
- All agent-extracted edges visually distinct in UI (different edge style)

**Files:** `backend/agents/validation_agent.py`

---

### 5. FreshnessAgent

**Role:** Monitor upstream data sources for new versions. Alert when source DB version changes.

**Trigger:** Monthly cron.

**Sources monitored:**
- GENCODE — check latest release vs loaded version
- GTEx — check latest release
- DoRothEA — check GitHub release
- HGNC — monthly diff

**Flow:**
```
for each source:
  → fetch current version from source API/page
  → compare to DataSource node in graph (loaded_version)
  → if newer version available:
      → log FreshnessAlert node
      → send notification (email / webhook)
      → optionally trigger ETL script (manual approval required)
```

**Constraints:**
- Never auto-runs ETL — human approval required
- Notification only — no graph writes except FreshnessAlert log node

**Files:** `backend/agents/freshness_agent.py`

---

## Agent communication pattern

Agents do not call each other directly. Coordination via Neo4j graph nodes:

```
CitationAgent    reads  → (:Edge {pmids: []})
CitationAgent    writes → (:Edge {pmids: [...], citation_attempted: true})

LiteratureAgent  writes → (:EdgeCandidate {status: "pending_review"})
ValidationAgent  reads  → (:EdgeCandidate {status: "pending_review"})
ValidationAgent  writes → (:Edge) or (:EdgeCandidate {status: "rejected"})

FreshnessAgent   writes → (:FreshnessAlert)
ETL scripts      reads  → (:FreshnessAlert) [manual trigger]
```

Graph = shared state / message bus. No inter-agent HTTP calls.

---

## Agent safety rules (all agents)

1. **No hallucinated topology** — agents never assert biological relationships from LLM output alone
2. **Cite everything** — every agent-written property must trace to a PMID or source DB
3. **Idempotent** — re-running any agent produces same result, no duplicate writes
4. **Labeled provenance** — every agent-written edge/node carries `source_agent`, `agent_version`, `run_timestamp`
5. **Fail loud** — agent errors written to `AgentRunLog` node, surfaced in admin UI
6. **Scope locked** — each agent touches only its defined node/edge types, enforced at code level

---

## Admin endpoints (FastAPI)

```
POST /admin/agents/citation/run           → trigger CitationAgent manually
POST /admin/agents/embedding/run          → trigger EmbeddingAgent manually (one batch)
GET  /admin/agents/{citation,embedding}/log → last N run-log nodes
POST /admin/agents/extraction/run         → trigger ExtractionAgent (gated: EXTRACTION_AGENT_ENABLED)
GET  /admin/agents/extraction/candidates  → pending CandidateEdges ≥ confidence floor
GET  /admin/agents/extraction/log         → last N ExtractionRun nodes
POST /admin/candidates/{id}/approve       → promote CandidateEdge (ValidationAgent, P2)
POST /admin/candidates/{id}/reject        → reject CandidateEdge (P2)
GET  /admin/freshness                     → FreshnessAlert nodes (v2)
```
