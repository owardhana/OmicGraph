# ADR 0015 — Enrichment data as scored annotations, not new node kinds

Status: Accepted (planned — `feat/omicgraph-next-phase`)

Governs how the next-phase enrichment sources (subcellular localization; pathway /
GO gene-set membership) attach to the graph. Sits alongside the two prior ADRs that
answered the near-identical "new axis" question in **opposite** ways:
[ADR-0006](0006-tissue-as-visual-channel.md) made tissue a *channel*;
[ADR-0007](0007-disease-as-first-class-nodes.md) made disease a *node*.

## Context

OmicGraph's **entity kinds** are a closed set — `gene`, `transcript`, `protein`,
`variant`, `disease`, `metabolite` (see [CONTEXT.md](../../CONTEXT.md)). Two new
annotation axes arrive this phase:

1. **Subcellular localization** — HPA (current) + ComPPI (integrator of LOCATE + HPA
   + 6 more; ~2015 snapshot). Today `Protein.subcellular_loc` is a **single** UniProt
   string (`06_uniprot_enrich.py` → `subcellularLocations[0]`).
2. **Pathway / GO gene-set membership** — Reactome (open, current) + MSigDB C5 (GO
   sets). Today only opaque per-protein `go_terms` (GO **IDs**, not names, not grouped)
   exist. **KEGG-proper is license-barred** (restricted since 2011; MSigDB froze it at
   2017) — `KEGG_MEDICUS` only if ever needed.

Each axis could be modelled as a **new node kind** (`Compartment` / `Pathway` +
membership edges) or a **scored property**. The choice cascades into the MCP surface
and the frontend inspector, so it is settled here first.

## Decision

**Both axes are scored, multi-value *properties* (annotations) — never node kinds.**
`Compartment`, `Pathway`, and `GeneSet` are explicitly **not** entity kinds; the closed
set of six is unchanged.

Rationale:

- **Consistency + precedent.** Follows tissue-as-channel ([ADR-0006](0006-tissue-as-visual-channel.md)):
  a spatial/grouping annotation is a channel, not a traversable node.
- **Identity.** [vision-and-mvp.md](../vision-and-mvp.md) states *"Not a pathway
  browser"* and lists Reactome as a system OmicGraph is *different from*. First-class
  `Pathway` nodes would make OmicGraph the thing it defined itself against.
- **It delivers the actual payload.** ComPPI's value is **compartment-aware PPI** —
  filtering `INTERACTS_WITH` to interactor pairs sharing a compartment. That needs
  localization on *both endpoints*, which a property provides directly; a node adds
  nothing here.
- **Avoids hub explosion + licensing.** A `Compartment`/`Pathway` node accumulates
  thousands of members → needs dense-capping like STRING; and KEGG-as-topology drags
  in the KEGG licence. Annotations sidestep both.

Concretely:

- `subcellular_loc` upgrades **single → multi-value + per-location score**
  (`{location, score, source}[]`). Controlled vocabulary of ~9 major GO-CC compartments
  (nucleus, cytoplasm, mitochondrion, ER, Golgi, plasma membrane, extracellular,
  cytoskeleton, lysosome/peroxisome), **not** ComPPI's 1600-term hierarchy. HPA-primary,
  ComPPI-backfill.
- **GO IDs resolved to readable BP/CC/MF names**; pathway membership stored as a scored
  multi-value property sourced from Reactome + MSigDB C5.
- **Compartment-aware PPI filtering is a real feature** — a shared-compartment gate,
  toggleable, over `INTERACTS_WITH`.
- **Membrane topology (TopDB)** answers a *different* question (transmembrane-segment
  geometry, not "which compartment") — a separate optional property, or deferred. Not
  folded into localization.

## Consequences

- `06_uniprot_enrich.py` and `backend/api/models.py:61` (`subcellular_loc: Optional[str]`)
  change to the multi-value shape; two new ETL scripts (`17_location`, `18_pathways`).
- The frontend **Annotations** inspector tab is where both land
  ([next-phase plan](../design/next-phase-omicgraph.md)).
- Annotations are structured, not free text → **no EmbeddingAgent involvement**.
- Reversible: an annotation can be **promoted** to a node later if a first-class "list
  all proteins in compartment X" query is ever required — the property is a strict
  subset of that capability.
- **Compartment-aware PPI filter — built, but data-limited (task #10).** `COMPARTMENT_PPI_FILTER`
  (env) + a per-request `?compartment_filter` override + MCP param gate `INTERACTS_WITH` on
  shared `subcellular_locs`, in both expansion and display. Verified correct
  (nucleus∩mito → dropped; unknown-loc → kept). **But ComPPI scores cytosol+nucleus highest
  for nearly every protein**, so almost all interacting pairs overlap and the filter rarely
  removes an edge in practice (17_location caps to top-3 and drops the `N/A` pseudo-loc to
  reduce this, but the two dominant compartments remain). Meaningful discrimination needs a
  stricter localization source — **HPA "Main location"** (the raw file is already in
  `data/raw/`) — a data follow-up; the mechanism is done.

## Rejected alternatives

- **`Compartment` / `Pathway` as node kinds.** Rejected — hub explosion, identity drift
  ("pathway browser"), KEGG licensing; the property already delivers compartment-aware PPI.
- **Keep `subcellular_loc` single-value.** Rejected — the current status quo; cannot
  express multi-localization or source scores, and cannot gate PPI by shared compartment.
- **KEGG-proper as a pathway source.** Rejected — license-barred; Reactome + MSigDB C5
  (+ `KEGG_MEDICUS` if needed) cover the need openly.
