# OmicGraph — Vision, Scope & Design

Why OmicGraph exists, what it covers, and the durable product/design decisions
behind it. The data model and provenance live in
[`data-architecture.md`](data-architecture.md); current build state and future
work live in [`roadmap.md`](roadmap.md); architectural rationale lives in
[`docs/adr/`](adr/).

---

## What it is

A multi-omics knowledge graph for human biology. Nodes are biological entities
(genes, transcripts, proteins, metabolites, variants, diseases); edges are
directed, typed, evidence-scored relationships. Tissue-segmented. Queryable in
plain English. Literature-cited.

Not a pathway browser. Not a gene lookup tool. A **navigable map of molecular
causality** — from TF binding through transcription, splicing, translation, and
signalling to metabolic output and disease — segmented by tissue, backed by
citations.

## The problem it solves

Biology is multi-layered but its data is siloed: GTEx knows tissue expression,
ENCODE knows TF binding, STRING knows protein interactions, UniProt knows
proteins, PubMed knows the literature. No single system integrates these into a
traversable, cited, queryable graph. Researchers triangulate manually across many
databases, browser tabs, and papers. OmicGraph collapses that into one interface.

## Prior art (and why OmicGraph is different)

| System | What it does | Gap |
|--------|-------------|-----|
| STRING | Protein interactions | No genomics/transcriptomics layer |
| OpenTargets | Gene→disease | No mechanistic traversal |
| Reactome | Pathway diagrams | Static, not queryable as a graph |
| OmniPath | Signalling network | No 3D viz, no RAG, no tissue-specific expression |
| BioGRID | Genetic/protein interactions | No multi-omics |

OmicGraph = unified layers + tissue context + 3D viz + LLM query + agent curation.
No single existing system has all five.

---

## Scope

### Realized
- **Genomics:** Gene (Ensembl ENSG), Variant (rsid / chr:pos).
- **Transcriptomics:** Transcript (Ensembl ENST).
- **Proteomics:** Protein (UniProt) — **full ~20k proteome**; TF is a Protein
  `subtype='transcription_factor'` ([ADR-0004](adr/0004-transcription-factors-as-proteins.md), [ADR-0010](adr/0010-full-proteome.md)).
- **Metabolomics:** Metabolite (HMDB / ChEBI) via Recon3D ([ADR-0009](adr/0009-metabolomics-layer-4.md)).
- **Phenotype:** Disease (EFO) as first-class nodes ([ADR-0007](adr/0007-disease-as-first-class-nodes.md)).
- Edges: `REGULATES`, `PRODUCES`, `TRANSLATES_TO`/`ENCODES`, `INTERACTS_WITH`,
  `IN_GENE`, `ASSOCIATED_WITH`, `IMPLICATED_IN`, `DIFFERENTIALLY_EXPRESSED`,
  `CATALYSES`, `GENE_DISEASE_ASSOC` (curated, Open Targets — ADR-0016).
- **Annotations** (ADR-0015): scored subcellular localization (`subcellular_locs`),
  Reactome pathways, GO:BP terms — surfaced in the inspector's Annotations tab; a
  compartment-aware PPI filter gates `INTERACTS_WITH`.
- **Read-only MCP server** at `/mcp` (ADR-0017) — search / semantic / subgraph /
  shortest-path + bounded export for external agents; no raw Cypher.
- **Public front door:** a landing page (`/`), self-serve developer docs at `#/api`
  (MCP connect config + REST reference), and the `#/admin` literature-review
  dashboard (ADR-0014) with an up-front token gate.
- Signal-decay traversal ([ADR-0005](adr/0005-signal-decay-traversal.md),
  [ADR-0011](adr/0011-backbone-guaranteed-traversal.md)), tissue-as-opacity
  ([ADR-0006](adr/0006-tissue-as-visual-channel.md)), an agentic chat assistant
  (with an NL→Cypher escape hatch), citation
  + embedding agents, semantic (vector) search ([ADR-0008](adr/0008-neo4j-native-vector-indexing.md)),
  3D layered viz, Entity Browser multi-select, shortest-path finder.

### Out of scope (current)
- ENCODE cCREs / `BINDS` / `REGULATES_VIA` — gated on AuraDB migration (see roadmap).
- Perturbation data (DepMap/LINCS), co-expression networks, cell-type resolution.
- Agent topology extraction (new edge proposals) — design session required.
- User accounts / saved queries.

---

## Finalized decisions

Reference these before making implementation choices. Where a decision grew into a
formal record, the ADR is linked.

### Infrastructure
| Decision | Choice | Rationale |
|----------|--------|-----------|
| Graph DB | Neo4j Community 5.x (Docker) | Cypher, native full-text + vector search, free |
| Backend | FastAPI (Python 3.11+) | Async, typed, fast to build |
| Frontend | React + TypeScript + Vite | Fast HMR, modern |
| Containerization | Docker Compose | Single `docker compose up` |
| Deployment | Local (MVP) → AuraDB Professional when ENCODE / production / multi-user RBAC needed | — |

### LLM / Agent
| Decision | Choice | Rationale |
|----------|--------|-----------|
| LLM API | OpenRouter (OpenAI-compatible) | Single key, model swap without code change |
| Chat / synthesis model | `anthropic/claude-sonnet-4.6` | Tool-calling + graph reasoning |
| Citation relevance check | `nvidia/nemotron-3-ultra-550b-a55b:free` | Cheap entity co-mention check — FREE slug so the nightly cron costs $0 (swap to a paid slug for higher precision) |
| Embeddings | `openai/text-embedding-3-small` (1536-dim) | Semantic search |
| Agent scheduling | APScheduler inside FastAPI | No extra services |
| Citation agent scope | PMID enrichment only — no topology writes | Safety: no hallucinated biology |

### Data identity & semantics
| Decision | Choice |
|----------|--------|
| Gene ID | Ensembl ENSG (canonical), HGNC symbol (display/search) |
| Transcript / Protein / Disease / Metabolite IDs | ENST / UniProt / EFO / HMDB(→ChEBI fallback) |
| TF→gene regulation | `REGULATES` is Protein→Gene, downward, DoRothEA A-B (never Gene→Gene — ADR-0004) |
| Transcript→protein | `TRANSLATES_TO` (GENCODE SwissProt) primary; `ENCODES` (HGNC) fallback |
| Tissue | Frontend opacity channel only — never removes nodes/edges, never feeds traversal (ADR-0006). Explicit tissue *queries* still filter. |
| Property storage | Primitive types / arrays of primitives; flat `tw_<tissue>` floats (ADR-0001) |

### Traversal
Signal-decay (confidence-gated spreading activation) with a user hard cap, not a
fixed hop count (ADR-0005). `signal_next = signal_cur × d × c(edge)`; stop at
`signal < ε` or `nodes ≥ max_nodes`; deterministic tie-break. Dense edge types are
capped per node per frontier ring; the seed's own vertical backbone (incl. its
metabolites) is guaranteed via a pre-pass (ADR-0011). Full conductance table in
[`data-architecture.md` §7](data-architecture.md#7-signal-decay-traversal--conductance).

### Search
Neo4j 5 native fulltext (`node_search`) over `hgnc_symbol`, `description`,
`summary_text`, `name`, `formula`; B-tree indexes on every canonical key; native
vector indexes for semantic search (ADR-0008). Full index list in
[`data-architecture.md` §8](data-architecture.md#8-neo4j-index-catalog).

### Testing
pytest for backend (Cypher correctness + agent safety are the highest-risk areas);
manual smoke tests for frontend. `backend/tests/`: `test_queries.py` (Cypher vs
live Neo4j), `test_agents.py` (citation agent writes PMIDs only),
`test_traversal_bridge.py` (ADR-0011/0012 golden traversal values).

### Ports (local dev)
Neo4j Browser 7474 · Neo4j Bolt 7687 · FastAPI 8000 · React (Vite) 3000.
FastAPI CORS allows `http://localhost:3000` in development.

---

## Frontend design

### 3D visualization
- **react-force-graph-3d** (Three.js). Layers are stacked planes at fixed Y per
  omics layer; X/Z free-simulated by a tuned force layout (stronger charge,
  collision force, longer links → a "web", not clumps). The signal-decay
  `max_nodes` cap is the scale guardrail.
- **Colour is the differentiator** (shapes are too hard to read at node sizes):

  | Node | Hex | | Edge | Hex |
  |------|-----|-|------|-----|
  | Gene | `#4ade80` green | | REGULATES activator | `#22c55e` green |
  | Transcript | `#60a5fa` blue | | REGULATES repressor | `#ef4444` red |
  | Protein | `#c084fc` violet | | PRODUCES | `#818cf8` indigo |
  | Protein — TF subtype | `#f59e0b` amber | | TRANSLATES_TO / ENCODES | `#c084fc` violet |
  | Variant | `#2dd4bf` teal | | INTERACTS_WITH | `#64748b` slate |
  | Metabolite | `#22d3ee` cyan | | CATALYSES | `#22d3ee` cyan |
  | Disease | `#f472b6` hot pink | | ASSOCIATED_WITH | `#f472b6` pink |

  (Metabolite/CATALYSES recoloured orange→cyan to deconflict from TF amber.)
- **Theme:** neutral, Claude-Code-style — warm charcoal canvas, solid light panels,
  no gradients; saturated colour reserved for graph nodes. Camera: Orbit (default) /
  Fly toggle via `F`.
- **Edges:** click-to-select (pin detail, rendered in the right dock alongside the
  node inspector — mutually exclusive) with subtle link curvature for separability,
  plus a lightweight hover tooltip. **Nodes:** hover shows a tooltip (name + kind);
  click opens the Entity Inspector + "Expand neighbourhood".

### Left rail: search, browse & ask (unified)
A single left dock (`LeftRail`) holds a pinned "jump to entity" search bar on top
and a **Browse | Ask** mode toggle underneath, replacing what were once three
separate components (`SearchBar`, `EntityBrowser`, `ChatPanel`). Both the Browse
and Ask panes stay **mounted** at all times — hidden via the `hidden` attribute
rather than unmounted — so switching modes or collapsing/reopening the rail never
drops the Browse pane's staged multi-selection or the Ask pane's chat thread.

**Browse pane** (`EntityBrowser`): server-side debounced search via
`GET /api/entities` with a virtualized list — scales to 500k+ nodes. Checkbox per
row; "Load selected (N)" calls `POST /api/graph/multi`. **Additive** merge —
selections add to the current graph; "Clear" resets to empty (not default TP53).
User controls accumulation.

**Ask pane** (`ChatPanel`): the agentic chat assistant, unchanged in behavior —
now just one of the two rail modes instead of its own dock.

### Multi-seed loading & disconnected islands
`POST /api/graph/multi` runs signal-decay traversal from each seed in parallel
(`asyncio.gather`), merges by machine ID (`ensembl_id` / `uniprot_id` / `rsid` /
`ontology_id` / `hmdb_id` / `chebi_id`), returns one `GraphResponse`. If the
selected **seeds** fall into more than one connected component, a banner warns
*"N of M selected entities form separate clusters…"* (counts seed clusters, not
incidental island nodes left by `max_nodes` trimming).

Shortest-path finder: `GET /api/graph/path?from=&to=&max_hops=6` →
`shortestPath((a)-[*..6]-(b))`, hard-capped at 6 hops (longer is biologically
meaningless). Returns `path_quality` direct(1–2) / moderate(3–4) / weak(5–6) /
no_path, never a silent empty result.

---

## The agent layer

OmicGraph cannot be fully curated manually. Two production roles plus one future:
- **Citation agent** (scheduled) — searches PubMed for literature supporting each
  existing edge; attaches PMIDs. Never creates edges.
- **Embedding agent** (scheduled) — embeds node `summary_text`/`description` for
  semantic search. Writes only embedding/provenance properties.
- **Extraction agent** (Feature 2, P1+P2 built, OFF by default) — reads new papers,
  proposes new edges as `:CandidateEdge` (staging, never trusted topology). The
  **ValidationAgent** promotes reviewed candidates to real edges tagged
  `provenance_tier='literature'`. See
  [`docs/design/feature-2-literature-extraction.md`](design/feature-2-literature-extraction.md)
  + [ADR-0013](adr/0013-literature-extraction-trust-model.md).
