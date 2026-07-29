# tahoe100m-drug-response — Tahoe-100M 항암제 반응 재현 (DRAFT)

Independent GPU reproduction of a **single drug's transcriptional response** across
cancer cell lines, built from **Tahoe-100M** (Vevo Therapeutics × Arc Institute): a
95.6M-cell single-cell **drug-perturbation** atlas — 50 cancer cell lines × ~1,100 small
molecules, ~14 per-plate h5ads, **~1.69 TB**.

**Why this pipeline is unusual:** Tahoe-100M is far too big to download whole and is
sharded by *plate*, not by drug. So the pipeline reads the small metadata parquet tables,
picks one drug (+ DMSO controls) across a few cell lines, and **streams only those cells**
out of the plate h5ads via `gcsfs` backed reads — a few thousand cells, not terabytes.
Then, per the **BioIDE constitution**, it re-derives the drug's signature from raw counts
(no provided response label) and asks: is the signature **reproducible across cell lines**,
and does it **hit the drug's known target/mechanism**?

## Steps
| # | script | what |
|---|--------|------|
| 0 | `00_setup_env.sh` | shared GPU venv + `pyarrow` + **`gcsfs`**; checks gsutil + GCP billing |
| 1 | `01_download_tahoe.sh` → `01_query_metadata.py`, `01_subset_download.py` | select drug + DMSO controls, stream-subset the cells → `tahoe_subset.h5ad` |
| 2 | `run_gpu_reanalysis.sh` → `02_gpu_reanalysis.py` | QC → GPU PCA → Harmony(batch=cell_line) → UMAP → per-cell-line DE (drug vs DMSO) → cross-line reproducibility → target recovery |
| 3 | `03_validate.py` | verdict from logFC correlation + consensus DE count + target-recovery fraction |
| 4 | AI panel | interpretation & hypotheses |
| 5 | `05_make_report.sh` | PdfPages report → `GHBIO_tahoe100m_drug_report.pdf` |

## Choosing the drug
Default is **Vorinostat** (pan-HDAC inhibitor — a strong, reproducible signature, good for
a demo/positive control). Change it:
```bash
TAHOE_DRUG="Dabrafenib" MAX_CELL_LINES=6 bash 01_download_tahoe.sh
```
The name must match `drug_metadata`; if it doesn't, `01_query_metadata.py` prints example
drug names from the atlas.

## ⚠ First-run checklist (DRAFT — staged, not yet deployed/run)
Authored without live bucket access; confirm against the real bucket on first run:

1. **GCP billing** (Requester Pays; a single-drug subset stays within the 2 TB/mo free tier).
   Use the shared helper:
   ```bash
   bash ../_shared/setup_gcp.sh <your-project-id>
   ```
2. **gsutil + gcsfs auth**: `gcloud auth login && gcloud auth application-default login`
   (gcsfs uses application-default credentials).
3. **Date prefix / paths.** Default `2025-02-25`; `01_query_metadata.py` auto-discovers the
   date dir and the per-plate h5ad objects via `gsutil ls`. Override with `--date` /
   `--h5ad-prefix` if the layout differs.
4. **Column names / barcode format.** The metadata column detection accepts several
   spellings (`BARCODE_SUB_LIB_ID`, `drug`, `plate`, `cell_line_id`, …). The stream-subset
   matches `selected_cells.csv` barcodes against each plate h5ad's `obs_names` — if 0 match,
   the barcode format differs (e.g. plate suffix); adjust the join in `01_subset_download.py`.
5. **gcsfs backed streaming** of scattered rows over a Requester-Pays bucket is the main
   perf/robustness risk. Caps: `--max-cell-lines 6`, `--max-cells-per-group 1500`. Verify
   end-to-end on Vorinostat before widening or promoting.

## Shared infra
Reuses `../_shared/setup_gcp.sh` (the same GCP config helper as `scbasecount-hcc` and any
future Requester-Pays Atlas pipeline). To promote: bump `package.json`, `bash build.sh`,
hard-refresh; if a real run reaches `AGREE`, it can join the landing roster.
