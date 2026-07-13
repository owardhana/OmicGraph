# ADR 0016 — DisGeNET curated gene-disease as a distinct edge, reconciled to EFO

Status: Accepted (planned — `feat/omicgraph-next-phase`)

Adds DisGeNET's curated gene-disease associations without breaking two standing glossary
rules: Disease is EFO-keyed, and `IMPLICATED_IN` is GWAS-specific
([CONTEXT.md](../../CONTEXT.md), [data-architecture §6](../data-architecture.md)).

## Context

The graph already carries two gene→disease evidence classes: `IMPLICATED_IN` (GWAS
statistical roll-up) and `DIFFERENTIALLY_EXPRESSED` (TCGA expression). **DisGeNET** adds a
third, *orthogonal* class — **expert/literature-curated** associations with a GDA score —
that neither statistical nor expression evidence captures.

Two frictions:

- **Vocabulary.** DisGeNET keys diseases by **UMLS CUI**; OmicGraph Disease nodes are
  **EFO** (`ontology_id`, e.g. `EFO_0001360`). The glossary forbids non-EFO Disease IDs.
- **Label ownership.** `IMPLICATED_IN` is defined as the GWAS Catalog roll-up specifically
  (`source_db=GWAS_Catalog`). Reusing it for DisGeNET corrupts that definition.
- **Access.** DisGeNET is freemium (MedBioinformatics); the academic tier is free but
  requires licence acceptance/registration, and the useful precision is in the **curated**
  tier, not the text-mined (BeFree) tier.

## Decision

1. **New edge type `GENE_DISEASE_ASSOC`** (Gene → Disease), carrying `gda_score`,
   `source_db='DisGeNET'`, `disgenet_source` (the curated sub-source). **Never** folded
   into `IMPLICATED_IN`.
2. **Curated tier only** — drop the text-mined BeFree tier (precision over recall).
3. **EFO-only reconciliation.** Crosswalk **CUI → EFO** (routed via **MONDO**, which
   cross-references both). Keep associations whose disease maps to an **existing** EFO
   Disease node; **drop the unmapped rest.** No CUI-keyed Disease nodes are ever minted —
   Disease stays strictly EFO-keyed.
4. **Yield spike before ETL.** The crosswalk hit-rate against the ~13k existing EFO Disease
   nodes is an empirical unknown. Measure it first; if the mapped yield is low, DisGeNET's
   marginal value over existing GWAS + TCGA gene-disease edges is thin → reconsider inclusion.

## Consequences

- Three orthogonal gene→disease evidence classes now converge on the same Disease node —
  **statistical (GWAS) · curated (DisGeNET) · expression (TCGA)** — grouped in the
  inspector's **Disease** tab ([next-phase plan](../design/next-phase-omicgraph.md)).
- Coverage loss on unmapped CUIs is **accepted** as the price of keeping Disease EFO-clean.
- New ETL script `19_disgenet.py` (curated download → CUI→MONDO→EFO crosswalk → MERGE
  `GENE_DISEASE_ASSOC`), plus a licence-acceptance step in the source registry.
- `GENE_DISEASE_ASSOC` needs a conductance entry in the signal-decay table (curated →
  treat comparably to a strong `IMPLICATED_IN`; exact value TBD in the traversal pass).

## Rejected alternatives

- **Mint CUI-keyed Disease nodes for unmapped associations.** Rejected — dual ID scheme,
  breaks the EFO-only rule, splits the same disease across two nodes.
- **Fold DisGeNET into `IMPLICATED_IN`.** Rejected — corrupts a GWAS-specific label; the
  evidence class (curated vs statistical) becomes unrecoverable.
- **Include the text-mined (BeFree) tier.** Rejected — noise; the curated tier is the
  differentiated signal.
- **Skip DisGeNET entirely.** Held open pending the yield spike — curated associations are
  genuinely orthogonal, but only worth the crosswalk cost if enough map to EFO.
