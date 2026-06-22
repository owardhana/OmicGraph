#!/usr/bin/env bash
#
# Download all raw source files for the OmniGraph ETL pipeline into data/raw/.
# Idempotent: files already present (non-empty) are skipped. Re-run safely.
#
# Sources:
#   HGNC          gene symbols + Ensembl ID mapping (+ uniprot_ids)
#   GENCODE v46   gene + transcript structure (GTF)
#   GENCODE v46   SwissProt metadata: transcript (ENST) -> UniProt (ADR-0004)
#   GTEx v10      tissue median TPM (GCT)
#   DoRothEA      TF -> target regulons with confidence tiers
#   --- Phase 2 (06_data_vision.md) ---
#   STRING v12    protein-protein interactions (INTERACTS_WITH edges)
#   GWAS Catalog  variant-trait associations (Variant + Disease nodes)
#   ClinVar       variant clinical significance enrichment
#   gnomAD v4     gene loss-of-function constraint (pLI)
#   EFO           disease/phenotype ontology
#   --- Phase 3 (08_phase3_build_prompt.md / 09_data_catalog.md) ---
#   TCGA Xena     pan-cancer FPKM expression + phenotype (DIFFERENTIALLY_EXPRESSED)
#   COSMIC CGC    Cancer Gene Census v99 (cancer_gene / cosmic_tier flags)
#   cttv mappings TCGA cancer code -> EFO ontology id
#   Recon3D       human metabolic reconstruction SBML (Metabolite + CATALYSES)
#   HMDB          metabolite identifiers (hmdb_id / chebi_id / name lookup)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RAW_DIR="${SCRIPT_DIR}/../data/raw"
mkdir -p "${RAW_DIR}"

# name|url
#
# NOTE on URLs (verified 2026-06-15, see docs/adr/0003-data-source-urls.md):
#   - HGNC moved off the EBI FTP path to Google Cloud Storage.
#   - DoRothEA no longer ships a CSV; only an .rda (R data) is published. We
#     download the .rda and read it in Python via pyreadr in 04_dorothea.py.
SOURCES=(
  "hgnc_complete_set.txt|https://storage.googleapis.com/public-download-files/hgnc/tsv/tsv/hgnc_complete_set.txt"
  "gencode.v46.annotation.gtf.gz|https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_human/release_46/gencode.v46.annotation.gtf.gz"
  "gencode.v46.metadata.SwissProt.gz|https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_human/release_46/gencode.v46.metadata.SwissProt.gz"
  "GTEx_Analysis_v10_RNASeQCv2.4.2_gene_median_tpm.gct.gz|https://storage.googleapis.com/adult-gtex/bulk-gex/v10/rna-seq/GTEx_Analysis_v10_RNASeQCv2.4.2_gene_median_tpm.gct.gz"
  "dorothea_hs.rda|https://raw.githubusercontent.com/saezlab/dorothea/master/data/dorothea_hs.rda"
  # --- Phase 2 sources (06_data_vision.md). Same curl + skip-if-present pattern. ---
  "9606.protein.links.detailed.v12.0.txt.gz|https://stringdb-downloads.org/download/protein.links.detailed.v12.0/9606.protein.links.detailed.v12.0.txt.gz"
  "gwas-catalog-associations_ontology-annotated-full.zip|https://ftp.ebi.ac.uk/pub/databases/gwas/releases/latest/gwas-catalog-associations_ontology-annotated-full.zip"
  "ClinVarVariantSummary.txt.gz|https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/variant_summary.txt.gz"
  "gnomad_v4_constraint.tsv|https://storage.googleapis.com/gcp-public-data--gnomad/release/4.1/constraint/gnomad.v4.1.constraint_metrics.tsv"
  "efo.json|https://github.com/EBISPOT/efo/releases/latest/download/efo.json"
  # --- Phase 3 sources (08_phase3_build_prompt.md). Same curl + skip-if-present pattern. ---
  # TCGA Pan-Cancer gene expression + phenotype (UCSC Xena public hub, no auth).
  "tcga_pancan_expression.tsv.gz|https://tcga-xena-hub.s3.us-east-1.amazonaws.com/download/TCGA-PANCAN.htseq_fpkm.tsv.gz"
  "tcga_pancan_phenotype.tsv.gz|https://tcga-xena-hub.s3.us-east-1.amazonaws.com/download/TCGA-PANCAN.GDC_phenotype.tsv.gz"
  # COSMIC Cancer Gene Census (v99, public tier). NOTE: Sanger gates this behind a
  # login in practice; if the download 403s, fetch the CSV manually into data/raw/.
  "cosmic_cancer_gene_census.csv|https://cancer.sanger.ac.uk/cosmic/file_download/GRCh38/cosmic/v99/cancer_gene_census.csv"
  # TCGA cancer type -> EFO mapping (Open Targets / cttv_mappings).
  "tcga_efo_mapping.tsv|https://raw.githubusercontent.com/opentargets/cttv_mappings/master/tcga_efo_mapping.tsv"
  # Recon3D SBML (human metabolic reconstruction, ~60MB).
  "Recon3D.xml|https://www.vmh.life/files/reconstructions/Recon/3D.04/Recon3D_301.xml"
  # HMDB metabolite identifiers (zip; ~1.5GB unzipped, streamed in 14_metabolomics.py).
  "hmdb_metabolites.zip|https://hmdb.ca/system/downloads/current/hmdb_metabolites.zip"
)

download_one() {
  local name="$1" url="$2" dest="${RAW_DIR}/$1"
  if [[ -s "${dest}" ]]; then
    echo "[skip] ${name} already present ($(du -h "${dest}" | cut -f1))"
    return 0
  fi
  echo "[download] ${name}"
  echo "           <- ${url}"
  # Download to a temp file, then atomically move on success so an interrupted
  # download never leaves a partial file that the skip-check would accept.
  local tmp="${dest}.part"
  if curl -fL --retry 3 --retry-delay 5 --progress-bar -o "${tmp}" "${url}"; then
    mv "${tmp}" "${dest}"
    echo "[done] ${name} ($(du -h "${dest}" | cut -f1))"
  else
    rm -f "${tmp}"
    echo "[ERROR] failed to download ${name} from ${url}" >&2
    return 1
  fi
}

echo "Downloading raw sources to ${RAW_DIR}"
failures=0
for entry in "${SOURCES[@]}"; do
  name="${entry%%|*}"
  url="${entry#*|}"
  # Attempt every source even if one fails, then report at the end.
  download_one "${name}" "${url}" || failures=$((failures + 1))
done

if [[ "${failures}" -gt 0 ]]; then
  echo "${failures} download(s) failed — see errors above." >&2
  exit 1
fi
echo "All downloads complete."
