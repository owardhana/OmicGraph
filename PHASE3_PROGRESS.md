# Phase 3 Build — Progress Tracker

Durable state for the `/loop` autonomous build of Phase 3 (TCGA + Metabolomics +
ENCODE). Each loop iteration reads this first to resume. Status legend:
`TODO` · `IN_PROGRESS` · `CODE_COMPLETE` (written, statically checked, but a live-graph
gate is unrun) · `DONE` (code + verification gates passed) · `BLOCKED` · `GATED`.

Branch: `phase-3-hpc-singularity` (name is stale from prior HPC work; the
uncommitted Metabolite glossary in CONTEXT.md confirms this is the Phase-3 line).

## Environment facts (re-confirm each session)
- Neo4j: started via `docker compose up neo4j -d` (named volume `neo4j_data`). LIVE.
- Node count at start: **601,558** (Variant 325k, Transcript 221k, Gene 42k,
  Disease 13k, **Protein only 117**). → verify-as-you-go for backend.
- Backend venv: `backend/.venv/bin/python` (has fastapi/neo4j/pydantic).
- etl venv: `etl/.venv/bin/python` (has pandas/numpy; libsbml NOT installed).
- ⚠ Protein=117 (not ~20k "full proteome"). Phase-6 CATALYSES will be SPARSE and
  the LDHA gate will likely fail even with Recon3D data → user must re-run the
  Phase-2 proteome ETL (05_proteins/06_uniprot_enrich) for a full proteome.
- ⚠ Total nodes 601k already > the Phase-9 migration trigger (500k). Phase 9 still
  HARD-GATED on user-driven AuraDB migration — do NOT attempt on Community.

## ⚠ DATA BLOCKER (user action required)
Every Phase-3 source URL in 00_download.sh is dead or auth-gated (verified):
- COSMIC CGC → returns an HTML login page (Sanger requires a free account login).
- TCGA Xena expression + phenotype → HTTP 403 (S3 path wrong/changed).
- tcga_efo_mapping.tsv (opentargets/cttv_mappings) → 404 (path moved).
- Recon3D.xml (vmh.life) → 404 (path moved; try BiGG: bigg.ucsd.edu/static/models/Recon3D.xml).
- HMDB zip → 403 (supplementary only; Recon3D SBML carries hmdb/chebi ids directly).
Until working URLs / manual downloads land in data/raw/, ETL phases 2/3/6 cannot
run, so their graph gates stay UNRUN (the scripts abort cleanly via column guards).

## Phase status
| Phase | Scope | Status |
|-------|-------|--------|
| 1 | downloads (00_download.sh) | CODE_COMPLETE — URLs dead/gated (BLOCKED on data) |
| 2 | COSMIC flags (12_cosmic.py) + DAG | CODE_COMPLETE — BLOCKED on COSMIC data |
| 3 | TCGA DE (13_tcga.py) + DAG | CODE_COMPLETE — BLOCKED on TCGA data |
| 4 | Backend TCGA models+traversal+/cancer | DONE (live-verified; data gate UNRUN) |
| 5 | ADR-0009 | DONE |
| 6 | Metabolomics ETL (14_metabolomics.py) + DAG + libsbml | CODE_COMPLETE — BLOCKED on Recon3D |
| 7 | Backend metabolite models+Z shift+indexes+API | DONE (live-verified; data gate UNRUN) |
| 8 | Frontend metabolomics layer + Z shift + UI polish | 8a+8b DONE (typecheck+build pass); 8c (UI polish) TODO |
| 9 | ENCODE cCREs | GATED (do not start) |
| 10 | Tests | DONE for backend (layer-z PASS; data tests SKIP-when-absent) |

## Verification ledger
- Phase 4 conductance: PASS (DE |log2fc|=2→0.5, =8→1.0 cap, none→0.25; CATALYSES 0.7).
- Phase 4 dense-cap: PASS (DIFFERENTIALLY_EXPRESSED capped; CATALYSES not).
- Phase 7 layer-Z: PASS (METABOLITE=900, DISEASE=1200; test_five_layer_z, test_layer_z_no_overlap).
- Phase 7 Pydantic union: PASS (MetaboliteNode resolves via discriminator).
- Phase 7 index DDL: PASS (create_indexes() applied node_search widen + metabolite idxs).
- Phase 4/7 endpoints: PASS no-crash on live graph (/cancer→[], metabolite lookup→None).
- Regression: PASS (15 existing query tests; search + TP53 traversal intact).
- Phase 2 gate (cancer_gene>0): UNRUN — COSMIC data blocked.
- Phase 3 gate (DE edges>1000): UNRUN — TCGA data blocked.
- Phase 6 gate (metabolites>1000, CATALYSES>5000, LDHA→lactate): UNRUN — Recon3D blocked + Protein=117.
- `= 900` audit: PASS backend (only via METABOLITE_LAYER_Z constant) + frontend
  (only intended metabolomics y:600 / phenotype y:900; DISEASE_LAYER_Z now 1200).
- Phase 8a/8b (commit 33d27ed): PASS tsc -b + vite build (both green; dist built).
  Dev server loads with NO console errors; live graph confirms disease nodes
  target Y=900 (Z-shift) and the 5-layer toggle renders (genomics/transcriptomics/
  proteomics/metabolomics/phenotype). Checks 1,4 PASS; checks 2,3,6 (metabolite +
  CATALYSES/DIFFERENTIALLY_EXPRESSED render) UNRUN — no Recon3D/TCGA data.
  NOTE: production `tsc -b` was already RED on HEAD pre-Phase-8 (hgnc_symbol on
  FGNode union, d3-force-3d types) — fixed those too to get a green build.
- Phase 8c (UI polish): TODO — fonts(Inter/JetBrains Mono), glass-morphism panels,
  bottom status bar, hover tooltip, collapsible legend (add Metabolite swatch —
  the static legend currently omits it), ? shortcut overlay, skeleton loaders,
  unified error banners, entity-browser pin/badge/pulse, searchbar chips/arrows/clear.
  Dev server running on :3000 (serverId from preview_start) — reuse next turn.

## Notes / decisions
- "agent writes carry source_agent/agent_version/run_timestamp" applies to
  backend/agents (LLM processes), NOT deterministic ETL scripts — ETL uses
  source_db/source_version (matches existing 08_gwas.py, 11_gnomad.py).
</content>
</invoke>
