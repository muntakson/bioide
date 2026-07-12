# scRNA-seq — Metastatic melanoma (Tirosh et al., Science 2016)

Reproduces the key figures of **Tirosh et al., "Dissecting the multicellular
ecosystem of metastatic melanoma by single-cell RNA-seq," Science 352:189 (2016)**
starting from the authors' published expression matrix.

## Data & source
- **Matrix:** NCBI GEO **GSE72056** — `GSE72056_melanoma_single_cell_revised_v2.txt.gz`
  (log2(TPM/10+1), ~23k genes × 4,645 cells, 19 patients). Its header rows carry the
  authors' own **malignant / non-malignant** and **cell-type** (T/B/Macro/Endo/CAF/NK)
  labels — this is what lets the figures be reproduced without raw FASTQ.
- **Interactive portal:** Broad Institute Single Cell Portal **SCP11**.
- **inferCNV** (the method that originated in this paper):
  https://github.com/broadinstitute/inferCNV. Here it is re-implemented directly
  (order genes by chromosomal position from the installed GRCh38 GTF, moving average
  over 100-gene windows, relative to reference normal cells).

## Steps
| # | Script | Output |
|---|--------|--------|
| 0 | `00_setup_env.sh` | shared `~/ghbio-venv` Scanpy stack |
| 1 | `01_download_melanoma.sh` | GSE72056 matrix under `~/ghbio-tutorial/data/melanoma-gse72056/` |
| 2 | `02_figure1_infercnv.py` | **Fig 1B/C/D**, `melanoma_processed.h5ad`, `markers_by_cluster.csv`, `celltype_draft.csv` |
| 3 | `03_figures2_3_malignant_states.py` | **Fig 2** (cell cycle), **Fig 3** (MITF/AXL) |
| 4 | `04_figures4_5_microenvironment.py` | **Fig 4** (CAF complement), **Fig 5** (T-cell exhaustion) |
| 5 | AI panel | interpretation + hypotheses (cached to the report) |
| 6 | `05_make_report.sh` | `GHBIO_melanoma_tirosh_report.pdf` |

## Scope note
Figure 4A/C bulk-TCGA deconvolution needs external TCGA SKCM data and is out of
scope; the single-cell portion (cell-type signatures + CAF-preferential complement
genes) is reproduced. Everything else derives from the single published matrix.
