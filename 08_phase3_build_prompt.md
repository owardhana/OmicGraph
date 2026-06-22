# OmniGraph — Phase 3 Build Prompt

> Copy everything between the triple-backtick fences into a new Claude Code session
> opened at `/Users/oliverwardhana/Desktop/Project_OMNI` on the
> `phase-3-tcga-metabolomics-encode` branch, then run `/loop`.

```
/loop

You are extending OmniGraph — a multi-omics knowledge graph of human biology.
Phase 1 (MVP) and Phase 2 (full proteome, STRING PPIs, Variant/Disease nodes,
semantic search, entity browser) are complete on `main`. You are on
`phase-3-tcga-metabolomics-encode`.

Read these files IN FULL before writing any code:
- CONTEXT.md                ← domain glossary (update it at Phase 5 to add Metabolite)
- 01_vision.md              ← layered model + node/edge status table
- 06_data_vision.md         ← data engineering map, Phase 3 backlog section
- 04_decisions.md           ← all finalized decisions
- AGENTS.md                 ← agent safety rules (never violated)
- backend/api/models.py     ← current node models + layer Z constants
- frontend/src/styles/layers.ts ← current layer Y coords + node colors
- docs/adr/0005-signal-decay-traversal.md
- docs/adr/0007-disease-as-first-class-nodes.md
- docs/adr/0008-neo4j-native-vector-indexing.md

04_decisions.md and CONTEXT.md are ground truth for all domain choices.
When in doubt, check them first.

---

KEY CONTEXT:

Phase 3 adds three biological expansions and one infrastructure upgrade:

1. TCGA cancer differential expression — which genes are up/down in each tumor
   type vs normal, using UCSC Xena pan-cancer data. New edge type:
   DIFFERENTIALLY_EXPRESSED (Gene → Disease). New Cancer Gene Census flags
   (COSMIC) update the existing `cancer_gene` bool on Gene nodes.

2. Metabolomics — new Layer 4 between proteomics and phenotype. Metabolite
   nodes (HMDB/ChEBI/KEGG IDs) + CATALYSES edges (Protein → Metabolite) from
   the Recon3D human metabolic reconstruction. Disease shifts to Layer 5.
   Frontend Y-coordinates shift: metabolomics Y=600, phenotype Y=900.

3. ENCODE cCREs (gated — Phase 9) — 1.7M regulatory element nodes in the
   genomics layer. ONLY begins after AuraDB migration. Neo4j Community Edition
   cannot hold this volume. Do not start Phase 9 until the migration is done.

4. Frontend UI polish — across all phases, the UI should become more
   professional and functional. Phase 8 is a dedicated UI polish pass.

New env vars (all must have defaults in .env.example):
  TCGA_MIN_LOG2FC=1.0           # absolute log2FC threshold for DIFFERENTIALLY_EXPRESSED edges
  TCGA_MAX_ADJ_PVALUE=0.05      # adjusted p-value cutoff
  METABOLOMICS_MIN_REACTIONS=1  # minimum reactions a metabolite must appear in to be loaded
  ENCODE_BATCH_SIZE=5000        # cCRE nodes per Cypher UNWIND (Phase 9)

ETL patterns (non-negotiable — same as Phase 2):
  Topology (new nodes/edges) → bulk file download via 00_download.sh + local pandas parse
  Enrichment (add properties to existing nodes) → REST API calls, batched, rate-limited
  Never call an API to discover which nodes to create.
  All ETL uses MERGE (idempotent), never CREATE alone.
  All agent writes carry: source_agent, agent_version, run_timestamp.

Signal-decay conductance (extend traversal.py):
  DIFFERENTIALLY_EXPRESSED: min(1.0, abs(log2fc) / 4.0) — stronger fold-change = higher conductance
  CATALYSES: 0.7 — enzymatic link (moderately confident structural)
  BINDS (ENCODE, Phase 9): chip_score (0–1) from ENCODE signal p-value

---

Work through phases in exact order. Complete each phase fully — all scripts
working, all verification checks passing — before moving to the next.
After each phase: /code-review high on every file written in that phase.
Fix every finding. Then proceed.

---

PHASE 1 — TCGA + COSMIC data downloads

Files to modify:
- etl/00_download.sh
    Add downloads:
    # TCGA Pan-Cancer gene expression (UCSC Xena public, no auth required)
    XENA_BASE="https://tcga-xena-hub.s3.us-east-1.amazonaws.com/download"
    curl -C - -o data/raw/tcga_pancan_expression.tsv.gz \
      "$XENA_BASE/TCGA-PANCAN.htseq_fpkm.tsv.gz"
    curl -C - -o data/raw/tcga_pancan_phenotype.tsv.gz \
      "$XENA_BASE/TCGA-PANCAN.GDC_phenotype.tsv.gz"
    # COSMIC Cancer Gene Census (v99, public tier — no auth for TSV)
    curl -C - -o data/raw/cosmic_cancer_gene_census.csv \
      "https://cancer.sanger.ac.uk/cosmic/file_download/GRCh38/cosmic/v99/cancer_gene_census.csv"
    # TCGA cancer type → EFO mapping (from EMBL-EBI GWAS Catalog mappings)
    curl -C - -o data/raw/tcga_efo_mapping.tsv \
      "https://raw.githubusercontent.com/opentargets/cttv_mappings/master/tcga_efo_mapping.tsv"
    # Recon3D SBML (human metabolic reconstruction, ~60MB)
    curl -C - -o data/raw/Recon3D.xml \
      "https://www.vmh.life/files/reconstructions/Recon/3D.04/Recon3D_301.xml"
    # HMDB metabolite identifiers (minimal download — just IDs + names)
    curl -C - -o data/raw/hmdb_metabolites.zip \
      "https://hmdb.ca/system/downloads/current/hmdb_metabolites.zip"

After Phase 1 verify:
  - All files present and non-zero in data/raw/.
  - Print file sizes: `ls -lh data/raw/tcga_* data/raw/cosmic_* data/raw/Recon3D.xml data/raw/hmdb_*`

---

PHASE 2 — COSMIC cancer gene flags

Files to create:
- etl/12_cosmic.py
    Purpose: read cosmic_cancer_gene_census.csv and SET cancer_gene=true on Gene
    nodes whose HGNC symbol appears in the Census. This populates the existing
    cancer_gene bool that was always on the Gene model but never sourced.

    Steps:
    1. Read data/raw/cosmic_cancer_gene_census.csv (pandas).
       Print column names and abort with a clear error if expected columns absent
       (same discipline as ADR-0003 / GTEx column guard).
       Expected columns: "Gene Symbol", "Tier" (COSMIC tiers 1+2).
    2. MERGE (:Gene {hgnc_symbol: row["Gene Symbol"]})
       SET g.cancer_gene = true, g.cosmic_tier = row["Tier"]
       source_db = "COSMIC_CGC", source_version = "v99"
    3. Log count of genes updated to DataSource node.

    Only SET existing Gene nodes — never CREATE. Skip symbols not in graph.
    Print: "N genes flagged as cancer genes from COSMIC CGC."

- etl/run_pipeline.py
    Add 12_cosmic to the DAG after 11_gnomad:
    11_gnomad → 12_cosmic

After Phase 2 verify:
  MATCH (g:Gene {cancer_gene: true}) RETURN count(g)
  Should be > 0 (COSMIC v99 has ~750 tier-1+2 genes).

---

PHASE 3 — TCGA differential expression ETL

Files to create:
- etl/13_tcga.py
    Purpose: compute gene-level differential expression for each TCGA tumor type
    vs GTEx normals, then create DIFFERENTIALLY_EXPRESSED edges from Gene to Disease.

    Steps:
    1. Load data/raw/tcga_pancan_expression.tsv.gz (rows=genes, cols=samples).
       Rows are Ensembl IDs (ENSG). Print shape and abort on column guard failure.
    2. Load data/raw/tcga_pancan_phenotype.tsv.gz to get sample → tumor_type mapping.
       TCGA codes: LUAD, BRCA, COAD, PRAD, KIRC, LIHC, STAD, BLCA, HNSC, etc.
    3. Load data/raw/tcga_efo_mapping.tsv → dict {tcga_code: efo_id}.
       Only process tumor types that map to a known EFO ID. Log unmapped types.
    4. For each tumor type with ≥ 10 samples:
       a. Compute median log2(FPKM+1) per gene in tumor samples.
       b. Use preloaded GTEx whole_blood tissue weights from graph as proxy normal
          (exact: query Neo4j for tw_whole_blood on PRODUCES edges, use as relative
          expression rank). NOTE: This is a simplified proxy — real DESeq2 needs
          count data. Use paired log2FC = log2((tumor_median+0.01)/(gtex_proxy+0.01)).
       c. Filter: abs(log2fc) >= TCGA_MIN_LOG2FC env var (default 1.0)
                  AND this is a meaningful biological signal.
    5. For each passing (gene, tumor_type, log2fc) triple:
       MATCH (g:Gene {ensembl_id: $ensembl_id})
       MATCH (d:Disease {ontology_id: $efo_id})
       MERGE (g)-[r:DIFFERENTIALLY_EXPRESSED {tumor_type: $tumor_type}]->(d)
       SET r.log2fc = $log2fc,
           r.direction = CASE WHEN $log2fc > 0 THEN 'up' ELSE 'down' END,
           r.source_db = 'TCGA_XENA',
           r.source_version = 'pancan_2023',
           r.loaded_at = timestamp()
    6. Log total edges created per tumor type to DataSource node.

    Tunable env vars used:
      TCGA_MIN_LOG2FC (default 1.0)

    IMPORTANT: DIFFERENTIALLY_EXPRESSED is a Gene→Disease edge. The Disease node
    must already exist (loaded by 08_gwas.py in Phase 2). Skip genes or diseases
    not in graph — log count of skipped.

- etl/run_pipeline.py
    Add 13_tcga to the DAG after 12_cosmic:
    12_cosmic → 13_tcga

After Phase 3 verify:
  MATCH (:Gene)-[r:DIFFERENTIALLY_EXPRESSED]->(:Disease) RETURN count(r)
  Should be > 1000 (expect ~50k-200k edges across all tumor types).
  MATCH (:Gene)-[r:DIFFERENTIALLY_EXPRESSED {direction:'up'}]->(:Disease)
    WHERE r.tumor_type = 'LUAD' RETURN count(r)
  Should be > 0.

---

PHASE 4 — Backend: TCGA models + traversal + API

Files to modify:
- backend/api/models.py
    Update GraphEdge comment: add DIFFERENTIALLY_EXPRESSED to rel_type list.
    Add fields to GraphEdge:
      log2fc: Optional[float] = None          # DIFFERENTIALLY_EXPRESSED
      direction: Optional[str] = None          # "up" | "down"
      tumor_type: Optional[str] = None         # TCGA cancer code
    Update edge_from_raw() to pass these from props.

- backend/db/queries/traversal.py
    Add "DIFFERENTIALLY_EXPRESSED" to _TRAVERSAL_REL_TYPES list.
    Add _DENSE_CAPPED entry: DIFFERENTIALLY_EXPRESSED — cap to top-k by abs(log2fc).
    Add conductance case:
      if rel_type == "DIFFERENTIALLY_EXPRESSED":
          lfc = rel_props.get("log2fc")
          return min(1.0, abs(float(lfc)) / 4.0) if lfc is not None else 0.25

- backend/api/routes/genes.py
    Add endpoint:
      GET /api/gene/{hgnc_symbol}/cancer
      Returns: list of {tumor_type, efo_id, disease_name, up_count, down_count,
                        top_up_genes (top 5 by log2fc), top_down_genes (top 5)}
      Useful for: "what cancers is TP53 associated with differentially?"

After Phase 4 verify:
  /api/gene/TP53 returns cancer_gene: true (after Phase 2 COSMIC run).
  /api/gene/TP53/cancer returns at least one tumor type entry.
  Signal-decay traversal from TP53 reaches Disease nodes via DIFFERENTIALLY_EXPRESSED.

---

PHASE 5 — ADR: Metabolomics as Layer 4

Files to create:
- docs/adr/0009-metabolomics-layer-4.md
    Title: Metabolomics as Layer 4 — Metabolite nodes between proteomics and phenotype
    Status: Accepted
    Context: Phase 3 adds metabolite nodes. Two choices:
      A. Add metabolites to the proteomics layer (same plane as proteins).
      B. Add metabolomics as a new Layer 4, shifting Disease to Layer 5.
    Decision: B — new layer. Biological rationale: the central dogma extended is
      gene → RNA → protein → metabolite → phenotype. Metabolites are downstream
      of proteins but upstream of observable phenotype. Separating the layers
      preserves traversal directionality and visual clarity. Metabolites in the
      proteomics plane would create a visual mess of INTERACTS_WITH + CATALYSES
      edges on the same plane.
    Consequences:
      Disease layer_z shifts from 900 → 1200 in backend models.py.
      Frontend phenotype Y shifts from 600 → 900.
      New frontend LayerKey 'metabolomics' at Y=600.
      METABOLITE_LAYER_Z = 900 in backend (between proteomics=600 and disease=1200).
      Existing Disease nodes in Neo4j do NOT need their layer_z property updated —
      layer_z is metadata, not stored on the graph node.
    Machine ID for Metabolite: HMDB ID (primary, e.g. "HMDB0000122" for glucose).
      Fallback: ChEBI ID (e.g. "CHEBI:4167"). Same primary+fallback pattern as
      protein (UniProt primary) and variant (rsid primary).
    Color: orange (#fb923c) — distinct from all existing node types.

After Phase 5: no code yet. ADR is the deliverable.

---

PHASE 6 — Metabolomics ETL

Files to create:
- etl/14_metabolomics.py
    Purpose: parse Recon3D human metabolic reconstruction SBML to extract
    Metabolite nodes and CATALYSES edges (Protein → Metabolite).

    Steps:
    1. Parse data/raw/Recon3D.xml using libsbml or xml.etree.ElementTree.
       Recon3D SBML structure:
         <model> contains <listOfSpecies> (metabolites) and <listOfReactions>
         Each reaction has <listOfReactants>, <listOfProducts>, and gene associations
         via <notes> or <annotation> in MIRIAM/gene_association format.
    2. Extract metabolites: id (Recon3D internal) → HMDB ID and/or ChEBI ID
       from <annotation> MIRIAM URNs. Discard if neither HMDB nor ChEBI resolvable.
       Metabolite props: hmdb_id, chebi_id, name, formula, charge.
    3. Extract reactions: reaction_id, gene_association_string
       (e.g. "ENSG00000197142 or ENSG00000131828"), reactant metabolites, product metabolites.
       Parse gene_association into list of Ensembl gene IDs.
    4. Map Ensembl gene IDs → UniProt IDs via the existing HGNC mappings in Neo4j:
       MATCH (g:Gene {ensembl_id:$eid})-[:ENCODES|PRODUCES*..2]->(p:Protein)
       RETURN p.uniprot_id LIMIT 1
       Cache the lookup; batch 500/query.
    5. For each (uniprot_id, metabolite, role):
       role = "substrate" if metabolite is reactant, "product" if product.
       MERGE (:Metabolite {hmdb_id: $hmdb_id})
         ON CREATE SET m.name=$name, m.formula=$formula, m.chebi_id=$chebi_id,
                       m.node_type='metabolite', m.layer_z=900,
                       m.source_db='Recon3D', m.source_version='3.04'
       MERGE (p:Protein {uniprot_id: $uniprot_id})-[r:CATALYSES]->(m)
         ON CREATE SET r.role=$role, r.reaction_id=$rxn_id,
                       r.source_db='Recon3D', r.source_version='3.04'
    6. Apply METABOLOMICS_MIN_REACTIONS filter: after load, delete Metabolite nodes
       that appear in fewer than $METABOLOMICS_MIN_REACTIONS reactions (default 1 = keep all).
    7. Log: node count, edge count to DataSource node.

    Handling missing HMDB IDs: if HMDB absent but ChEBI present, use chebi_id as
    canonical key field (same fallback logic as rsid/chr:pos for variants).

    Install requirement: libsbml (add to etl/requirements.txt).

- etl/run_pipeline.py
    Add 14_metabolomics after 13_tcga.

After Phase 6 verify:
  MATCH (m:Metabolite) RETURN count(m)     → expect > 1000
  MATCH ()-[r:CATALYSES]->() RETURN count(r) → expect > 5000
  MATCH (p:Protein)-[:CATALYSES]->(m:Metabolite) WHERE p.hgnc_symbol='LDHA' RETURN m.name
  Should return lactate or pyruvate (LDHA catalyses lactate dehydrogenase reaction).

---

PHASE 7 — Backend: Metabolomics models + layer Z shift + API

Files to modify:
- backend/api/models.py
    Update layer Z constants — shift Disease up, add Metabolomics:
      METABOLITE_LAYER_Z = 900    # new Layer 4
      DISEASE_LAYER_Z = 1200      # shifted from 900 (was Layer 4, now Layer 5)
    Add MetaboliteNode:
      class MetaboliteNode(BaseModel):
          id: str              # hmdb_id (primary) or chebi_id (fallback)
          hmdb_id: Optional[str] = None
          chebi_id: Optional[str] = None
          name: Optional[str] = None
          formula: Optional[str] = None
          charge: Optional[int] = None
          node_type: Literal["metabolite"] = "metabolite"
          layer_z: int = METABOLITE_LAYER_Z
    Update GraphNode Union to include MetaboliteNode.
    Update _NODE_BUILDERS to handle "metabolite" kind.
    Add metabolite_node_from_props() builder.
    Update GraphEdge comment to include CATALYSES and DIFFERENTIALLY_EXPRESSED.
    Add CATALYSES edge fields:
      role: Optional[str] = None           # "substrate" | "product"
      reaction_id: Optional[str] = None    # Recon3D reaction ID

- backend/db/queries/traversal.py
    Add "CATALYSES" to _TRAVERSAL_REL_TYPES.
    Add CATALYSES conductance case: return 0.7
    Note: CATALYSES is NOT dense-capped (most proteins catalyse 1-5 reactions).

- backend/db/neo4j_client.py
    Add to INDEX_STATEMENTS:
      CREATE INDEX metabolite_hmdb_idx IF NOT EXISTS FOR (n:Metabolite) ON (n.hmdb_id)
      CREATE INDEX metabolite_chebi_idx IF NOT EXISTS FOR (n:Metabolite) ON (n.chebi_id)
      Update node_search fulltext index to include Metabolite:
        DROP INDEX node_search IF EXISTS
        CREATE FULLTEXT INDEX node_search IF NOT EXISTS
        FOR (n:Gene|Transcript|Protein|Disease|Metabolite)
        ON EACH [n.hgnc_symbol, n.description, n.summary_text, n.name, n.formula]

- backend/api/routes/search.py
    Update fulltext_types set to include 'metabolite'.
    Add 'metabolite' to TABS in EntityBrowser (frontend Phase 8 will pick this up).

- backend/api/routes/genes.py (or new metabolomics.py)
    Add endpoint:
      GET /api/metabolite/{hmdb_id}/graph → GraphResponse
      Signal-decay traversal from a Metabolite node as seed.
      Supported because Metabolite nodes are first-class (ADR-0009).

After Phase 7 verify:
  /api/metabolite/{hmdb_id}/graph returns a subgraph with Protein + Metabolite nodes.
  GraphNode discriminator resolves MetaboliteNode correctly (Pydantic union test).
  MATCH (m:Metabolite) RETURN m.layer_z LIMIT 1 → should be 900.

---

PHASE 8 — Frontend: metabolomics layer + Z shift + UI polish

This is the largest frontend phase. Implement in this order:
  8a — Layer system update (required before any new node renders)
  8b — New node rendering (metabolites)
  8c — UI polish

### 8a — Layer system

Files to modify:
- frontend/src/styles/layers.ts
    Add 'metabolomics' LayerKey.
    Shift phenotype Y from 600 to 900. Add metabolomics at Y=600.
    Updated LAYERS:
      genomics:       { y: -300, color: '#6b7280', accent: '#4ade80',  label: 'Genomics' }
      transcriptomics:{ y: 0,    color: '#6b7280', accent: '#60a5fa',  label: 'Transcriptomics' }
      proteomics:     { y: 300,  color: '#6b7280', accent: '#c084fc',  label: 'Proteomics' }
      metabolomics:   { y: 600,  color: '#fb923c', accent: '#fb923c',  label: 'Metabolomics' }  ← NEW
      phenotype:      { y: 900,  color: '#f472b6', accent: '#f472b6',  label: 'Phenotype' }     ← shifted

    Add NODE_COLORS.metabolite = '#fb923c' (orange)
    Add NODE_SIZES.metabolite = 7
    Add EDGE_COLORS.catalyses = '#fb923c'
    Add EDGE_COLORS.differentially_expressed = '#f59e0b' (amber — cancer context)
    Update nodeLayer() to return 'metabolomics' for node_type === 'metabolite'.
    Update nodeColor() for metabolite.
    Update nodeSize() for metabolite.
    Update edgeColor() for CATALYSES and DIFFERENTIALLY_EXPRESSED.

- frontend/src/components/GraphViewer3D.tsx
    Add 5th semi-transparent layer plane (PlaneGeometry at Y=600, orange tint, 0.08 opacity).
    Shift phenotype plane from Y=600 to Y=900.
    Update node renderer to handle 'metabolite' node_type: orange spheres, size 7.
    CATALYSES edges render at linkWidth*0.7 (same weight tier as INTERACTS_WITH).
    DIFFERENTIALLY_EXPRESSED edges: amber (#f59e0b), linkWidth*0.5, dashed appearance
    (use linkDash if react-force-graph-3d supports it, else just color+width).

- frontend/src/components/LayerToggle.tsx
    Add 5th checkbox: Metabolomics (between Proteomics and Phenotype).

### 8b — New node panels and entity browser

- frontend/src/components/NodeDetailPanel.tsx
    Add MetabolitePanel:
      Show hmdb_id, chebi_id, name, formula, charge.
      Show linked proteins (first 5 CATALYSES edges) as chips.
      Show "Reactions: N" count.
    Update SearchResult type to include 'metabolite' node_type.

- frontend/src/components/EntityBrowser.tsx
    Add 'Metabolite' tab (after Variant, before Disease).
    Metabolite search uses same fulltext index (name, formula) via /api/entities.

### 8c — UI polish (professional, modern, functional)

Apply across all existing components. Goal: the app should look like a polished
research tool, not a prototype.

- frontend/src/App.tsx + App.css
    Typography:
      Use Inter (import from Google Fonts) for UI chrome.
      Use 'JetBrains Mono' or 'Fira Code' for IDs, Cypher output, metrics.
      Increase base font weight from 400→450 for better legibility on dark background.
    Spacing:
      Audit all panels — enforce 16px padding, 8px gaps between elements.
      Remove tight packing in NodeDetailPanel (add breathing room between sections).
    Panels — glass morphism:
      Upgrade panel backgrounds from flat #0f0f12 to frosted glass:
        background: rgba(15, 15, 18, 0.82)
        backdrop-filter: blur(12px)
        border: 1px solid rgba(255,255,255,0.06)
      Apply to: NodeDetailPanel, EntityBrowser, QueryPanel, EdgeDetailPanel.
    Status bar:
      Add a thin (28px) bottom status bar showing:
        graph metrics (N nodes · M edges), active seed names, current camera mode.
    Hover tooltips on graph nodes:
      When hovering a node in the 3D viewer, show a floating tooltip (positioned
      in 3D screen space via react-force-graph-3d's onNodeHover + overlayCanvas)
      containing: display name, node_type chip, layer chip, key metric
      (e.g. pli_score for genes, combined_score for interactions).
    Graph legend:
      Collapsible legend bottom-right: color swatches for all active node types
      and edge types visible in the current graph. Auto-updates as graph changes.
    Keyboard shortcuts:
      Add a help overlay (? key) listing all keyboard shortcuts:
        C = toggle camera mode   F = fly mode
        / = focus search         Esc = close panel
        ← → = prev/next node in detail panel history
      Show shortcuts as pill badges on the relevant UI elements on first visit
      (localStorage 'shortcuts_shown' gate — show once, dismiss forever).
    Loading states:
      Replace all spinners with skeleton loaders (animated gradient shimmer)
      matching the shape of the content being loaded.
    Error states:
      Unify error display: red banner at top of the affected panel, icon + message.
      Never crash the whole graph on a failed panel API call.
    Entity browser refinements:
      Pin selected items to the top of the list (not just tracked in Map).
      Show a "selected" badge count on the panel handle when collapsed.
      "Load selected (N)" button pulses when N > 0 to draw attention.
    SearchBar refinements:
      Show node_type icon/chip in autocomplete results.
      Keyboard arrow navigation in results dropdown.
      Clear button (×) on the search input.

After Phase 8 verify:
  1. 5 layer planes visible in 3D viewer (genomics, transcriptomics, proteomics,
     metabolomics, phenotype) with correct Y positions and colors.
  2. Metabolite nodes render orange in the metabolomics plane.
  3. CATALYSES edges render orange; DIFFERENTIALLY_EXPRESSED edges render amber.
  4. Disease nodes appear in the phenotype plane (Y=900), above metabolomics (Y=600).
  5. Phenotype layer toggle hides disease nodes correctly.
  6. Metabolomics layer toggle hides metabolite nodes correctly.
  7. Glass-morphism panels visible in all 4 panel types.
  8. Bottom status bar shows node/edge count.
  9. Graph legend renders correct swatches.
  10. ? key opens keyboard shortcut overlay.
  11. Hover tooltip appears on node hover with correct data.

---

PHASE 9 — ENCODE cCREs (GATED — only after AuraDB migration)

⚠ STOP before this phase. Read the migration gate:
  MATCH (n) RETURN count(n) AS total_nodes
  If total_nodes > 500000 OR pagecache hits/misses ratio (from `CALL dbms.queryJmx()`)
  shows >30% misses on current hardware: proceed to AuraDB migration.
  Otherwise: Neo4j Community on current machine still has headroom. Do not migrate
  until the gate is triggered.

### AuraDB migration (when triggered)

1. Dump current graph:
   neo4j-admin database dump --database=neo4j --to-path=data/aura_dump/
2. Create AuraDB Professional instance on https://console.neo4j.io
   (select region closest to HPC / lab location).
3. Import dump:
   neo4j-admin database upload --database=neo4j --from-path=data/aura_dump/ \
     --to <aura-connection-string>
4. Update .env: NEO4J_URI=neo4j+s://<aura-id>.databases.neo4j.io
   NEO4J_USER=neo4j  NEO4J_PASSWORD=<aura-password>
5. Run create_indexes() (backend startup) to recreate indexes on Aura instance.
6. Smoke-test: all existing /api/ routes return correct data.

### ENCODE ETL (after Aura confirmed working)

Files to modify/create:
- etl/00_download.sh
    Add:
    # ENCODE cCRE annotation (GRCh38, all cCRE types, ~30MB BED+metadata)
    curl -C - -o data/raw/encode_ccre.bed.gz \
      "https://downloads.wenglab.org/Registry-V4/GRCh38-cCREs.bed.gz"
    curl -C - -o data/raw/encode_ccre_chip.tsv.gz \
      "https://api.encodeproject.org/metadata/?type=Experiment&assay_term_name=ChIP-seq..."
    # Full ENCODE ChIP-seq TF binding data is large — limit to TF proteins already
    # in graph to avoid loading irrelevant experiments. See etl/15_encode.py step 1.

- etl/15_encode.py
    Purpose: load cCRE nodes and BINDS edges (TF Protein → cCRE).
    Steps:
    1. Read graph TF proteins:
       MATCH (p:Protein {subtype:'transcription_factor'}) RETURN p.hgnc_symbol, p.uniprot_id
       These are the only TFs for which we load ChIP-seq data — prevents loading
       experiments for non-TF proteins that happen to have ChIP data.
    2. Parse data/raw/encode_ccre.bed.gz (BED format: chr, start, end, ccre_id, ccre_type).
       ccre_type values: "PLS" (promoter-like), "pELS" (proximal enhancer), "dELS" (distal enhancer),
       "CTCF-only", "DNase-H3K4me3".
       Create cCRE nodes:
         (:cCRE {
           encode_id: string,       canonical key (e.g. "EH38E1234567")
           chromosome: string,
           start_grch38: int,
           end_grch38: int,
           ccre_type: string,       "PLS" | "pELS" | "dELS" | "CTCF-only" | "DNase-H3K4me3"
           node_type: "ccre",
           layer_z: 0               genomics layer (DNA-level element)
         })
       Load in batches of ENCODE_BATCH_SIZE (default 5000) via UNWIND to avoid
       large single transactions. This is critical — 1.7M nodes in one transaction
       will OOM.
    3. For BINDS edges: use ENCODE ChIP-seq signal data.
       MATCH known TF proteins to ENCODE experiments by gene symbol.
       For each TF × cCRE intersection (from ENCODE peak calls):
         MERGE (p:Protein {hgnc_symbol: $symbol})-[r:BINDS]->(c:cCRE {encode_id: $ccre_id})
         SET r.chip_score = $signal_score,  # ENCODE signal p-value normalised 0-1
             r.experiment_accession = $accession,
             r.source_db = "ENCODE", r.source_version = "V4"
    4. For REGULATES_VIA (cCRE → Gene) — structural genomic link:
       Assign each cCRE to its nearest gene(s) within 500kb using BED coordinate
       lookup against Gene chromosome/start data already in Neo4j.
       MERGE (c:cCRE)-[:REGULATES_VIA {distance_bp: $dist}]->(g:Gene)
       Cap: max 3 nearest genes per cCRE (avoids hub genes dominating).
    5. Log: cCRE count, BINDS count, REGULATES_VIA count to DataSource.

- backend/api/models.py
    Add cCRENode:
      class cCRENode(BaseModel):
          id: str                    # encode_id
          encode_id: str
          chromosome: Optional[str] = None
          start_grch38: Optional[int] = None
          end_grch38: Optional[int] = None
          ccre_type: Optional[str] = None
          node_type: Literal["ccre"] = "ccre"
          layer_z: int = 0           # genomics layer
    Add BINDS + REGULATES_VIA to traversal (conductance = chip_score for BINDS, ~1.0 for REGULATES_VIA).
    Add cCRE to node_search fulltext index.

- frontend/src/styles/layers.ts + GraphViewer3D.tsx
    cCRE nodes: charcoal (#475569) — neutral, DNA-level annotation.
    cCRE nodes: small (size 4), rendered as flat diamond/square.
    BINDS edges: slate (#64748b), very thin (linkWidth*0.3).
    REGULATES_VIA edges: indigo (#6366f1), thin (linkWidth*0.4).
    cCRE nodes sit in the genomics plane (same Y=-300 as Gene/Variant).
    Add 'cCRE' type to EntityBrowser tabs and to LayerToggle genomics sub-filter.

After Phase 9 verify:
  1. AuraDB smoke test: all routes from Phase 1–8 return correct data.
  2. MATCH (c:cCRE) RETURN count(c) → expect ~1.7M
  3. MATCH (:Protein)-[:BINDS]->(:cCRE) RETURN count(*) → expect > 100k
  4. TP53 protein has BINDS edges to cCREs.
  5. cCRE nodes render in genomics plane, small charcoal diamonds.
  6. REGULATES_VIA edges visible between cCRE and Gene nodes.

---

PHASE 10 — Tests

Files to modify/create:
- backend/tests/test_queries.py
    Add:
      test_cancer_gene_flag: MATCH (g:Gene {cancer_gene:true}) RETURN count(g) > 0
      test_differentially_expressed_edges:
        MATCH (:Gene)-[r:DIFFERENTIALLY_EXPRESSED]->(:Disease) RETURN count(r) > 0
      test_metabolite_nodes: MATCH (m:Metabolite) RETURN count(m) > 0
      test_catalyses_edges: MATCH ()-[r:CATALYSES]->() RETURN count(r) > 0
      test_metabolite_traversal:
        /api/metabolite/{any_hmdb_id}/graph returns non-empty nodes + edges.
      test_tcga_traversal:
        /api/gene/TP53/cancer returns at least one tumor type entry.
      test_five_layer_z:
        GENE_LAYER_Z=0, TRANSCRIPT_LAYER_Z=300, PROTEIN_LAYER_Z=600,
        METABOLITE_LAYER_Z=900, DISEASE_LAYER_Z=1200 — assert all correct.
      test_layer_z_no_overlap:
        Assert METABOLITE_LAYER_Z != DISEASE_LAYER_Z (layer shift regression).

- backend/tests/test_text2cypher.py
    Add benchmark questions:
      "Which enzymes catalyse reactions involving glucose?"
      "What genes are differentially expressed in lung adenocarcinoma?"
      "Find metabolites produced by TP53-regulated proteins."
      "What cCREs are bound by TP53?" (Phase 9 only — skip if cCRE index absent)
    Each: assert cypher non-empty, assert no write keywords, assert answer non-empty.

Run pytest backend/tests/ — all tests must pass.

---

KNOWN RISKS:

- TCGA FPKM normalization: UCSC Xena PANCAN data uses FPKM which is sample-level
  normalized. Direct tumor vs GTEx comparison using tw_whole_blood as proxy normal
  is a simplification. For publication-grade analysis, use DESeq2/edgeR with count
  data. For the graph, the proxy is sufficient for directional signal.

- Recon3D gene associations: some reactions have complex Boolean gene associations
  ("ENSG1 and ENSG2 or ENSG3"). Parse conservatively: split on OR, take first valid
  Ensembl ID per OR-group. Log count of reactions with unparsed associations.

- HMDB zip size: hmdb_metabolites.zip is ~1.5GB uncompressed. Use streaming XML
  parse (xml.etree.ElementTree iterparse) to extract just hmdb_id + name + chebi_id
  without loading the full file into RAM. Write a minimal lookup TSV to data/processed/
  then delete the unzipped XML.

- ENCODE Phase 9 memory: 1.7M cCRE nodes × ENCODE_BATCH_SIZE=5000 = 340 Cypher
  UNWIND batches. Each batch must be its own transaction. Neo4j AuraDB has
  per-transaction size limits — keep batches ≤ 5000 nodes.

- Layer Z shift (metabolomics): DISEASE_LAYER_Z changes from 900 → 1200.
  Any hardcoded 900 in frontend or backend not routed through the constant will
  break silently. Audit with: grep -rn "= 900" frontend/src/ backend/
  Fix any hardcoded occurrences before proceeding.

---

RULES (non-negotiable — same as Phases 1 and 2):
- No placeholder code or TODOs — every file complete and functional.
- All ETL uses MERGE (idempotent), never CREATE alone.
- Topology (new nodes/edges) from bulk downloaded files only. API calls for enrichment only.
- All agent writes carry: source_agent, agent_version, run_timestamp.
- validate_cypher() blocks MERGE/CREATE/DELETE/SET — enforced before every LLM execution.
- No new graph topology from LLM — embeddings and PMIDs are agent-written, never LLM-hallucinated.
- After each phase: /code-review high, fix all findings before next phase.
- After Phase 8: /verify all 11 smoke-test checks. All must pass before Phase 9.
- After Phase 9: /verify ENCODE smoke tests (6 checks) only after AuraDB migration confirmed.
- If any verify check fails: /diagnose before trying random fixes.
- ENCODE Phase 9 is hard-gated: DO NOT start unless node count > 500k or pagecache miss
  rate > 30%. Attempting it on Neo4j Community will OOM.
- DISEASE_LAYER_Z = 1200 (not 900 — that was Phase 2). METABOLITE_LAYER_Z = 900.
  The layer Z shift is a regression vector — test_layer_z_no_overlap catches it.
- STRING_MIN_CONFIDENCE, GWAS_MIN_SIGNIFICANCE, TCGA_MIN_LOG2FC are env vars — never hardcode.
- CONTEXT.md and 06_data_vision.md are the domain authority — if code conflicts, fix the code.
```
