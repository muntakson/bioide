# scbasecount-hcc — scBaseCount 간암(HCC) 다연구 통합 재분석 (DRAFT)

Independent, cross-study GPU reproduction of human **hepatocellular carcinoma (HCC)**
built from **Arc Institute's scBaseCount** (the Virtual Cell Atlas): a >500M-cell
scRNA-seq atlas that the **SRAgent** LLM agent mined from SRA/GEO and that
**scRecounter (STARsolo)** re-quantified *uniformly*. Because every sample went
through the same pipeline, many independent HCC studies can be pooled without
pipeline-driven batch effects.

**Why this pipeline is different from every other one in the repo:** there is **no
FASTQ→counts alignment step.** scBaseCount already ships uniformly-processed count
`h5ad`s, so we download the human-HCC samples and go straight into the GPU
reanalysis — skipping the heaviest, slowest, most fragile stage (the aarch64
STARsolo build / 40 GB indices) entirely.

Per the **BioIDE constitution** we do **not** consume scBaseCount's per-cell
`cell_type` (itself SRAgent-inferred); we re-derive cell types, the malignant
hepatocyte population and the TLS module from the raw counts, and use the labels
**only** for validation.

## Steps
| # | script | what |
|---|--------|------|
| 0 | `00_setup_env.sh` | shared GPU venv + `pyarrow`; checks for **gsutil** + a **GCP billing project** |
| 1 | `01_download_scbasecount_hcc.sh` → `01_query_metadata.py` | select human HCC samples from the atlas metadata, `gsutil cp` their h5ads |
| 2 | `run_gpu_reanalysis.sh` → `02_gpu_reanalysis.py` | concat → QC → norm → HVG → GPU PCA → Harmony(batch=SRX) → Leiden → UMAP → markers → GMM malignant → TLS module |
| 3 | `03_validate.py` | ARI/NMI/confusion vs scBaseCount labels + cross-study dispersion + tumour-vs-normal TLS |
| 4 | AI panel | interpretation & hypotheses |
| 5 | `05_make_report.sh` | PdfPages report → `GHBIO_scbasecount_hcc_report.pdf` |

## ⚠ First-run checklist (this is a DRAFT — staged, not yet deployed/run)
Authored without live bucket access, so confirm these against the real bucket on the
first run:

1. **GCP billing project** (Requester Pays — downloads billed to you, 2 TB/mo free).
   Use the shared helper (`../_shared/setup_gcp.sh`, reused by all Atlas pipelines) —
   it writes `~/.config/ghbio/gcp.json` (chmod 600), checks gsutil + auth, and does a
   live bucket-access test:
   ```bash
   bash ../_shared/setup_gcp.sh <your-project-id>
   ```
2. **gsutil auth** (the helper prompts if missing): `gcloud auth login && gcloud auth application-default login`.
3. **Metadata table path + column names.** `01_query_metadata.py` auto-discovers the
   metadata object under `gs://arc-institute-virtual-cell-atlas/scBaseCount` and
   accepts several column spellings (`disease_ontology_term_id`,
   `single_disease_confidence`, `srx_accession`, …). If discovery fails it prints the
   bucket listing — then pass `--metadata-object gs://…` and, if needed,
   `--h5ad-prefix gs://…` (per-sample h5ad layout is assumed `…/Homo_sapiens/<SRX>.h5ad`).
4. **HCC filter.** Defaults to MONDO:0007256 / free-text "hepatocellular"; widen in
   `HCC_ONTOLOGY`/`HCC_TEXT` if the atlas spells it differently.
5. Draft caps: `MAX_SAMPLES=40`, `MIN_CONF=medium`. Raise (`MAX_SAMPLES=0` = all) once
   paths are confirmed. Verify end-to-end on a subsample (`run_gpu_reanalysis.sh
   --max-cells 60000`) before promoting to the landing roster.

## To promote (per CLAUDE.md)
Bump `package.json` version, `bash build.sh`, hard-refresh. If it reaches an on-disk
`AGREE` verdict in `validation_summary.csv`, it can join the landing
"Verified Reproductions" roster. Consider swapping the light PdfPages report for the
pandoc/wkhtmltopdf figure-rich report used by `hcc-tls-lu2022`.
