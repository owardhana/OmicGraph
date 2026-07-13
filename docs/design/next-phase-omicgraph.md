# Next Phase — OmicGraph

Plan for the phase after the literature-extraction MVP. Developed via a
grill-with-docs session against [CONTEXT.md](../../CONTEXT.md),
[vision-and-mvp.md](../vision-and-mvp.md), and the ADRs. **This document is the plan
only — no ETL/frontend code is built by the planning session.**

Decisions of record surfaced here:
[ADR-0015](../adr/0015-enrichment-as-annotations.md) (enrichment as annotations),
[ADR-0016](../adr/0016-disgenet-curated-gene-disease.md) (DisGeNET),
[ADR-0017](../adr/0017-public-access-model.md) (public access model).

---

## Pillar 0 — Rename OmniGraph → **OmicGraph**

Done first (mechanical unblock). Scope split into four layers; **a–c in, d out**:

| Layer | In? | Notes |
|-------|-----|-------|
| a. GitHub repo `Project_OMNI` → `OmicGraph` | ✅ | GitHub auto-redirects the old URL |
| b. Code identifiers — `package.json`, docker-compose service/container names, backend app title, page `<title>`, README | ✅ | grep-replace, mechanical |
| c. Docs + product name `OmniGraph` → `OmicGraph` (CONTEXT.md, README, docs, ADRs) | ✅ | high-value consistency |
| d. **Local folder** `~/Desktop/Project_OMNI` | ❌ | breaks the auto-memory path (`projects/-Users-…-Project-OMNI/memory/`), scratchpad path, absolute paths; iCloud churn. The *project* is OmicGraph; the *folder* stays `Project_OMNI` |

Git housekeeping (already applied): local `main` fast-forwarded to `origin/main` (was
behind 16; PR #5 had merged the literature branch); new branch `feat/omicgraph-next-phase`.

---

## Pillar 1 — Data enrichment

All three land as **annotations / edges on existing nodes** — no new entity kinds
([ADR-0015](../adr/0015-enrichment-as-annotations.md)). The closed set of six entity kinds
is unchanged.

### 1a. Subcellular localization → scored multi-value property
- **Sources:** HPA (current, direct TSV) primary; **ComPPI** (integrator of LOCATE + HPA +
  6 more) backfill. LOCATE is dead (~2013) — taken only via ComPPI, never standalone.
- **Shape:** `Protein.subcellular_loc` upgrades single-string → `{location, score, source}[]`
  over a ~9-term GO-CC controlled vocabulary. Touches `06_uniprot_enrich.py` +
  `backend/api/models.py:61`. New ETL: `17_location.py`.
- **Feature:** compartment-aware PPI — a toggleable shared-compartment gate over
  `INTERACTS_WITH`.
- **Not this:** TopDB membrane *topology* is a separate optional property (or deferred) —
  not localization.

### 1b. Pathway / GO gene-set membership → scored annotation property
- **Finding:** absent today — only opaque per-protein GO **IDs** exist.
- **Sources:** **Reactome** (open, current) + **MSigDB C5** (GO sets). **KEGG-proper is
  license-barred** — `KEGG_MEDICUS` (free subset) only if ever needed.
- **Cheapest high win:** resolve the existing GO IDs → readable **BP/CC/MF names**.
- New ETL: `18_pathways.py`. Lands in the inspector **Annotations** tab.

### 1c. DisGeNET curated gene-disease → new `GENE_DISEASE_ASSOC` edge
Per [ADR-0016](../adr/0016-disgenet-curated-gene-disease.md): curated tier only; new edge
type (not `IMPLICATED_IN`); **EFO-only reconciliation** (CUI→MONDO→EFO, drop unmapped, no
CUI-keyed nodes). **Gate: a CUI→EFO yield spike runs before committing the ETL.** New ETL:
`19_disgenet.py`. Gives three orthogonal gene→disease evidence classes (GWAS · TCGA · DisGeNET).

---

## Pillar 2 — MCP integration + security

Per [ADR-0017](../adr/0017-public-access-model.md).

- **Website: open + anonymous** (per-IP rate limit). **MCP API: free key** (per-key quota,
  keys hashed at rest, self-serve issuance on the landing page).
- **Public tools:** `search`, `semantic_search`, `subgraph`, `shortest_path`, **bounded
  export** (JSON / CSV / GraphML, ~`TRAVERSAL_MAX_NODES`). **`run_cypher` omitted from all
  public surfaces** — internal validator-gated only.
- **Full-graph download:** separate pre-baked, versioned dump (static link), not a live
  endpoint.
- **Security hardening (audit was clean — no leaked secrets in history):**
  - Admin **fails closed in production** (unset `ADMIN_TOKEN` refuses admin routes) —
    reverses the current empty=open dev default.
  - **⚠ Live action:** verify `ADMIN_TOKEN` is set on the current Oracle host — if empty,
    `#/admin` is exposed right now.
  - Statement timeout on all public queries; Neo4j loopback-bound; backend private; Caddy
    sole ingress; per-IP + per-key rate limits.
  - Transport: remote MCP over HTTP/SSE behind Caddy, same Oracle box.

---

## Pillar 3 — Frontend refinement

Structure agreed; styling driven by the `ui-ux-pro-max` design pass. Keeps the existing
neutral, warm-charcoal, Claude-Code theme — **saturation stays reserved for graph nodes**.

### 3-column app shell
**Left = find** (existing `EntityBrowser`, search + multi-select) · **Center = 3D force
graph** (`GraphViewer3D`) · **Right = inspect** (new tabbed Entity Inspector). Interaction
model unchanged: hover = lightweight tooltip (name + kind); click = pin into the right panel.

### Entity Inspector (OmniPath-style tabs)
Unifies the current `NodeDetailPanel` + `EdgeDetailPanel`. New data maps cleanly onto tabs
— the payoff of settling data-shape first:

| Tab | Content |
|-----|---------|
| Overview | IDs, symbol, layer, subtype, summary, vertical backbone |
| Interactions | `INTERACTS_WITH` + **compartment-aware filter** (1a) |
| Annotations | **subcellular location** (1a), **pathway / GO names** (1b), MW |
| Disease | `ASSOCIATED_WITH` · `IMPLICATED_IN` · **`GENE_DISEASE_ASSOC`** (1c) · `DIFFERENTIALLY_EXPRESSED` |
| Regulation | `REGULATES` (TF↔gene) |
| Metabolism | `CATALYSES` metabolites |
| Literature | PMIDs + "proposed" literature-tier edges |

### Landing page (front door)
Net-new (no landing exists today; app boots straight into the graph). Website is public, so
this is a **front door, not an auth gate**. Pattern = *Product Demo + Features*: hero →
**live canned 3D graph teaser** → feature breakdown → CTA. Carries: "Launch app" (→ open
graph), "Get free MCP key" (devs, self-serve), and a **discreet admin access** input
(retires the need to know the `#/admin` URL). Suggested routing: landing at `/`, graph at
`/app`.

### Visual language (from `ui-ux-pro-max`)
- **Type:** Fira Sans (body/labels) + Fira Code (data/IDs/mono) — the "Dashboard Data"
  pairing, built for data viz. (Alt if a more futuristic feel is wanted: Exo + Roboto Mono.)
- **Chrome:** neutral slate, solid panels, no gradients. One restrained cool accent for
  CTAs / focus rings only — chosen to **avoid the node hues** (green/blue/violet/amber/
  teal/cyan/pink), preserving "saturation = nodes."
- **Motion:** subtle (150–300ms micro-interactions; respect `prefers-reduced-motion`).
- **Data tables** in the inspector: tabular figures, sortable, virtualized for long lists.

---

## Sequencing & dependencies

1. **Pillar 0 rename** (a–c) — first, as one mechanical commit. *(Git sync already done.)*
2. **Pillar 1 data** — data-shape decisions (done) unblock both MCP and frontend tabs.
   Run the **DisGeNET yield spike** before its ETL.
3. **Pillar 2 MCP + security** — depends on Pillar 1 (what's queryable/exportable) + the
   hardening items.
4. **Pillar 3 frontend** — Annotations/Disease tabs consume Pillar 1; landing hosts the
   Pillar 2 key issuance + admin access.

## Doc touch-ups this phase will need
- `CONTEXT.md` — `GENE_DISEASE_ASSOC` + location/pathway annotation notes (**already added**
  in the grill session).
- `data-architecture.md` — new sources (HPA, ComPPI, Reactome, MSigDB, DisGeNET), new ETL
  scripts (17–19), the `subcellular_loc` shape change, `GENE_DISEASE_ASSOC` provenance +
  conductance row.
- `roadmap.md` — move these from "deferred" to "in progress" as built.
- Rename pass — `OmniGraph` → `OmicGraph` across all docs (Pillar 0c).
