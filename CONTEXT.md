# OmniGraph

Domain language for OmniGraph — a tissue-segmented, multi-omics knowledge graph
of human molecular biology. This file is a glossary, not a spec: it defines what
each term **is**, not how it is implemented.

## Language

### Entities

**Entity kind**:
The omics class of a node — one of `gene`, `transcript`, or `protein`. The single
source of truth for what a node *is*. Replaces the older derived `is_tf` flag,
which now demotes to a protein subtype.

**Gene**:
A genomic locus that can be transcribed. Lives in the **genomics layer**. Machine
ID = Ensembl gene ID (ENSG). Display name = HGNC symbol (e.g. `TP53`).
_Avoid_: locus, ORF (too narrow).

**Transcript**:
An RNA isoform produced from a gene. Lives in the **transcriptomics layer**.
Machine ID = Ensembl transcript ID (ENST). Display name = symbol + isoform number
(e.g. `TP53-201`).
_Avoid_: mRNA (excludes non-coding), isoform (use for the biological concept, not the node).

**Protein**:
A polypeptide translated from a transcript. Lives in the **proteomics layer**.
Machine ID = UniProt accession (e.g. `P04637`). Display name = symbol + kind tag
(e.g. `TP53 (protein)`).

**Transcription factor (TF)**:
A **protein subtype** — a protein that regulates the expression of genes. NOT its
own node kind; a TF is a `protein` whose subtype is transcription-factor. It is
the source of `REGULATES` edges.
_Avoid_: regulator (too broad), "TF node" / "TF layer" (there is no separate TF
node kind or layer — TFs live in the proteomics layer).

**Protein subtype**:
A finer classification of a protein (e.g. transcription-factor, enzyme,
structural). Distinguished visually by **color**, not by layer. Only the
transcription-factor subtype exists today; the field is open for growth.

### Layers

**Layer** (omics layer):
A horizontal plane in the stacked model, one per omics level. Bottom to top:
**genomics → transcriptomics → proteomics** (metabolomics is future). A node
belongs to exactly one layer, fixed by its **entity kind**.

**Genomics layer**: holds **gene** nodes.
**Transcriptomics layer**: holds **transcript** nodes.
**Proteomics layer**: holds **protein** nodes (TFs included).

### Relationships

**Regulates**:
A **protein** (transcription-factor subtype) acting on a **gene** to activate or
repress its expression. Directed, runs *downward* proteomics → genomics. The
biology of TF→DNA binding.
_Avoid_: "gene regulates gene" — the regulator is the TF protein, not its gene.

**Produces**:
A **gene** giving rise to a **transcript**. Directed, genomics → transcriptomics.
Carries tissue context.

**Translates to**:
A **transcript** giving rise to a **protein**. Directed, transcriptomics →
proteomics. The biologically exact, stepwise link up the stack — preferred
whenever the protein's canonical transcript is in the graph.

**Encodes**:
A **gene** giving rise to a **protein**, directed genomics → proteomics. The
**fallback** link used only when the protein's transcript is absent, so a protein
is never left disconnected from its molecule. Together, `TRANSLATES_TO` (primary)
and `ENCODES` (fallback) are what make `TP53 (protein)` recognizably the same
molecule as gene `TP53`.

### Identity & disambiguation

The same molecule appears once per layer (gene `TP53`, transcript `TP53-201`,
protein `TP53 (protein)`), all derived from each other. They are kept distinct by:

1. **Machine ID** — layer-specific and collision-free: ENSG (gene), ENST
   (transcript), UniProt (protein). A node's identity never clashes across layers.
2. **Display name** — symbol plus a kind cue, shown on *every* surface (3D label,
   search, query answers, edge panels): `TP53` / `TP53-201` / `TP53 (protein)`.
3. **Visual channels** in 3D — **layer** (position) + **color** (subtype) +
   **shape** (per layer). Redundant on purpose.

The vertical `ENCODES` (and future translation) edges show that the separate
nodes are the same underlying molecule.

## Flagged ambiguities

- **"TP53"** alone is ambiguous — it names a gene, its transcripts, and its
  protein. Always qualify by **entity kind** (display name carries the cue).
- **"TF"** is not a node kind and not a layer. It is a **protein subtype** living
  in the proteomics layer. The old `is_tf` derived flag is superseded by
  `entity_kind = protein` + subtype = transcription-factor.
- **"Regulation"** is protein→gene, never gene→gene. The earlier model collapsed
  the TF protein into its gene; that conflation is retired.
- **Traversal terms** ("signal", "conductance", "decay", "signal floor") are
  *algorithm* vocabulary, not domain language — see
  [ADR-0005](docs/adr/0005-signal-decay-traversal.md). They are deliberately kept
  out of this glossary.

## Example dialogue

> **Dev:** When I query TP53, why do I see it twice?
> **Bio:** Because you're seeing two entities. The **gene** TP53 in the genomics
> layer — that's the locus other TFs regulate. And the **protein** `TP53 (protein)`
> in the proteomics layer — that's the transcription factor regulating *other*
> genes. The vertical **ENCODES** edge between them says "same molecule."
> **Dev:** So the `REGULATES` edges always start from the protein?
> **Bio:** Right. A TF is a protein subtype. It regulates genes by binding DNA, so
> `REGULATES` runs down from proteomics to genomics. A gene never regulates
> another gene directly — that was shorthand we've now made explicit.
> **Dev:** And `TP53-201`?
> **Bio:** That's a transcript — one RNA isoform of the TP53 gene, in the middle
> layer. Gene **produces** transcript, transcript **translates to** protein
> (or gene **encodes** protein, if the transcript isn't loaded).
