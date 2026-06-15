# OmniGraph — Vision

## What it is

Multi-omics knowledge graph for human biology. Nodes = biological entities (genes, transcripts, proteins, metabolites). Edges = directional, typed, evidence-scored relationships. Tissue-segmented. Queryable in plain English. Literature-cited.

Not a pathway browser. Not a gene lookup tool. A **navigable map of molecular causality** — from TF binding through transcription, splicing, translation, signaling, to metabolic output — segmented by tissue, backed by citations.

## The problem it solves

Biology is multi-layered. The data is siloed:

- GTEx knows what genes express in which tissue
- ENCODE knows what TFs bind what promoters
- STRING knows what proteins interact
- UniProt knows what proteins exist
- PubMed knows what the literature says

No single system integrates these layers into a traversable, cited, queryable graph. Researchers triangulate manually across 6 databases, 10 browser tabs, and 50 papers. OmniGraph collapses this into one interface.

## The layered model

Visualized as stacked planes (graphite structure):

```
[ Metabolomics ]   ← layer 4 (future)
[ Proteomics   ]   ← layer 3 (future)
[ Transcriptomics ]← layer 2 (MVP)
[ Genomics     ]   ← layer 1 (MVP)
```

Intra-layer edges = horizontal (e.g. TF → target gene, within genomics layer)
Inter-layer edges = vertical (e.g. gene → transcript, crossing layers)

Each node and edge carries tissue context. Same gene, different behavior in liver vs brain vs blood — the graph shows both.

## Node types (full vision)

| Layer | Node type | ID system | Example |
|-------|-----------|-----------|---------|
| Genomics | Gene | Ensembl (ENSG) | TP53, BRCA2 |
| Transcriptomics | Transcript | Ensembl (ENST) | TP53-201, TP53-202 |
| Proteomics | Protein | UniProt | P04637 |
| Metabolomics | Metabolite | HMDB / ChEBI | Pyruvate |
| Regulatory | Transcription Factor | Ensembl (ENSG) | SP1, GATA1 |

## Edge types (full vision)

| Edge | Meaning | Direction | Source |
|------|---------|-----------|--------|
| TF → Gene | Regulatory binding, activates/represses | Directed | DoRothEA, ENCODE |
| Gene → Transcript | Splicing, produces isoform | Directed | GENCODE, GTEx |
| Transcript → Protein | Translation | Directed | UniProt, Ribo-seq |
| Protein → Protein | Binding, signaling, phosphorylation | Directed/undirected | STRING, PhosphoSitePlus |
| Protein → Metabolite | Enzymatic reaction | Directed | KEGG, Recon3D |
| Gene ~ Gene | Co-expression (labeled separately) | Undirected | GTEx, TCGA |

Every edge carries:
- `type` — what the relationship is
- `direction` — activates / represses / binds / produces / phosphorylates
- `confidence` — numeric score (source-specific)
- `tissue_weights` — {blood: 0.8, liver: 0.3, brain: 0.9}
- `pmids` — list of supporting PubMed IDs
- `source_db` — originating database + version

## Tissue segmentation

Initial tissues: **whole blood, liver, brain (prefrontal cortex)**
Source: GTEx v10

Tissue context stored as edge properties (not separate graph copies). Query filters by tissue at runtime. Future: cell-type resolution (single-cell RNA-seq via CellxGene integration).

## Data scopes (full vision)

| Scope | Includes | Source |
|-------|---------|--------|
| **Normal** | Healthy tissue expression | GTEx, Human Protein Atlas |
| **Cancer** | Tumor vs normal differential | TCGA, CCLE |
| **Perturbation** | CRISPR KO, drug treatment | DepMap, LINCS |

MVP = normal only. Cancer + perturbation = v2+.

## The agent layer

OmniGraph cannot be fully curated manually. Two agent roles:

**1. Citation Agent**
Runs on schedule. For each edge in graph, searches PubMed for supporting literature. Extracts PMID + supporting sentence. Attaches to edge. Never creates new edges — only enriches existing ones.

**2. Extraction Agent (v2)**
Reads new papers (bioRxiv, PubMed). Proposes new edges as candidates with evidence. Human/rule validation gate. High-confidence candidates enter graph with `source: agent_extracted` label.

## The query layer

Users query in plain English. Two modes:

**Structured (Text2Cypher)**
"What TFs regulate TP53 in liver?" → Cypher → graph result → formatted answer + citations

**Open-ended RAG (v2)**
"What is known about TP53 splicing in neurodegeneration?" → vector search over graph summaries + PubMed abstracts → synthesized answer + citations

## Why this matters now

The multiomics era is here:
- GTEx v10 (2023) — 54 tissues, 1000 donors
- ENCODE 4 (2024) — 10,000+ experiments
- AlphaFold 3 — protein structure at scale
- Single-cell atlases — Human Cell Atlas, CellxGene

The data exists. The integration layer does not. OmniGraph is that layer.

## Prior art (and why OmniGraph is different)

| System | What it does | Gap |
|--------|-------------|-----|
| STRING | Protein interactions | No genomics/transcriptomics layer |
| OpenTargets | Gene→disease | No mechanistic traversal |
| Reactome | Pathway diagrams | Static, not queryable as graph |
| OmniPath | Signaling network | No 3D viz, no RAG, no tissue-specific expression |
| BioGRID | Genetic/protein interactions | No multi-omics |
| KG-Hub | KG builder toolkit | No viz, no query interface |

OmniGraph = unified layers + tissue context + 3D viz + LLM query + agent curation. No single system has all five.
