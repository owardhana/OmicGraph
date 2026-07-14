# ADR 0016 — Curated gene-disease from Open Targets (EFO-native), a distinct edge

Status: Accepted (planned — `feat/omicgraph-next-phase`).
Supersedes its own first draft (DisGeNET) — see "History" below.

Adds a *curated* gene-disease evidence class without breaking two standing glossary
rules: Disease is EFO-keyed, and `IMPLICATED_IN` is GWAS-specific
([CONTEXT.md](../../CONTEXT.md), [data-architecture §6](../data-architecture.md)).

## Context

The graph already carries two gene→disease evidence classes: `IMPLICATED_IN` (GWAS
statistical roll-up) and `DIFFERENTIALLY_EXPRESSED` (TCGA expression). A third,
*orthogonal* class — **expert/literature-curated** associations — is missing, and it
is exactly the mendelian / rare-disease causal knowledge that neither common-variant
GWAS nor cancer expression captures.

The original plan sourced this from **DisGeNET**, but DisGeNET's curated bulk download
is login/paywall-gated (freemium) and could not be obtained. It also keyed diseases by
**UMLS CUI**, forcing a lossy CUI→EFO crosswalk. **Open Targets Platform** is a strictly
better source for the same need:

- **Open** (CC0), no login — a public bulk download / already-connected GraphQL.
- **EFO/MONDO-native** — disease IDs match existing Disease nodes directly; the
  crosswalk (and its risk) disappears entirely.
- Exposes association evidence **broken down by datasource**, so the curated subset can
  be isolated from the statistical/expression signal already in the graph.

## Decision

1. **New edge type `GENE_DISEASE_ASSOC`** (Gene → Disease), `gda_score` = the Open
   Targets *datasource* score, `source_db='OpenTargets'`, `ot_datasources` = which
   curated sources supported it. **Never** folded into `IMPLICATED_IN`.
2. **Curated datasources only** — `gene2phenotype`, `genomics_england`, `orphanet`,
   `clingen` (+ `uniprot_literature` if wanted). **Not** the aggregate `overall` score,
   which blends GWAS Catalog + ClinVar + Cancer Gene Census + expression that the graph
   *already* has (double-count guard).
3. **EFO-native reconciliation.** Keep associations whose disease EFO id already exists
   as a Disease node; **drop the rest.** No crosswalk, no CUI-keyed nodes — Disease
   stays strictly EFO-keyed. (MONDO ids OT emits are mapped to their EFO xref where the
   Disease node is EFO.)
4. **No yield spike.** It existed to de-risk the lossy CUI→EFO crosswalk; with EFO-native
   matching there is nothing to measure — unmatched simply drop.

## Consequences

- Three orthogonal gene→disease evidence classes converge on the same Disease node —
  **statistical (GWAS) · curated (Open Targets) · expression (TCGA)** — grouped in the
  inspector's **Disease** tab ([next-phase plan](../design/next-phase-omicgraph.md)).
- Acquisition: Open Targets `associationByDatasourceDirect` bulk (open, no login,
  Pattern-1 topology-from-files) → `19_opentargets.py`; the connected OT GraphQL MCP is a
  fallback / spot-check, not the ETL path (topology comes from files — §2).
- `GENE_DISEASE_ASSOC` needs a conductance entry (curated → comparable to a strong
  `IMPLICATED_IN`; exact value in the traversal pass).
- Coverage is bounded to diseases already present (GWAS/EFO-derived) — accepted. ~2,213
  edges from ~19,560 curated pairs (≈88% dropped).
- **Crosswalk investigated and rejected (task #9).** OT curated diseases are MONDO-centric
  (~15k pairs) vs the graph's EFO/OBA Disease set, so a MONDO→EFO crosswalk seemed like it
  would lift coverage. Built one from `efo.json` xrefs and measured: EFO *imports* MONDO as
  its own nodes rather than cross-referencing it, so the map held only ~195 MONDO→EFO
  entries; applying it translated 285/64,150 rows and *reduced* edges (2,213→2,176), because
  translating a graph-present MONDO id to a graph-absent EFO id drops the match. **The real
  ceiling is disease-set overlap, not vocabulary** — OT curated rare/mendelian diseases
  mostly aren't in a GWAS-common-variant graph, and minting them is rejected above. A
  materially better lift would need a different disease-source, not a crosswalk.

## Rejected alternatives

- **DisGeNET.** Rejected — curated bulk is access-gated (could not be downloaded) and
  UMLS-CUI vocab forces a lossy crosswalk. Open Targets is open + EFO-native.
- **Open Targets aggregate (`overall`) score.** Rejected — blends the GWAS/ClinVar/COSMIC/
  expression evidence already in the graph; using it double-counts and destroys the
  "distinct curated class" that is the entire point.
- **Fold into `IMPLICATED_IN`.** Rejected — corrupts a GWAS-specific label; the evidence
  class (curated vs statistical) becomes unrecoverable.
- **Skip curated gene-disease entirely.** Considered (the honest fallback if no open
  source existed) — unnecessary now that Open Targets supplies it cleanly.

## History

First draft sourced DisGeNET (curated tier, CUI→MONDO→EFO crosswalk, yield-spike-gated).
Dropped when the curated bulk proved un-downloadable; Open Targets replaced it and removed
the crosswalk and the spike. The edge shape (`GENE_DISEASE_ASSOC`, distinct from
`IMPLICATED_IN`) and the EFO-only Disease rule are unchanged.
