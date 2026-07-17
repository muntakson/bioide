# BioIDE — Raw Dataset Inventory

_Survey of all scRNA-seq pipelines and the datasets downloaded on disk, toward a cross-cancer gene atlas._

Generated: 2026-07-17

## 1. Disk footprint

| Location | Size | Contents |
|---|---:|---|
| `~/ghbio-tutorial/` | **191 GB** | shared heavy-input store |
| ├─ `data/fastq/` | 135 GB | raw 10x FASTQ / BAM (from-scratch alignment demos) |
| ├─ `data/<cancer>/` | ~7.6 GB | processed count matrices (atlas-relevant) |
| ├─ `ref/` | ~30 GB | GRCh38 STAR index + Cell Ranger ref + GTF |
| ├─ `maynard-2020/` | 7.8 GB | Maynard 2020 lung therapy dataset |
| `~/ghbio-workspace/projects/` | ~72 GB | per-pipeline results (h5ad, figures, CSVs) |

## 2. Cell counts (from processed `.h5ad`)

### Cancer atlas-ready cells (validated reproductions)

| Pipeline | Cancer | Paper | Accession | Cells |
|---|---|---|---|---:|
| lung-adeno-kim2020 | Lung adeno | Kim 2020 Nat Commun | GSE131907 | **207,900** |
| thyroid-cancer-ptc-pu2021 | Thyroid PTC | Pu 2021 Nat Commun | GSE184362 | **195,928** |
| gastric-cancer-kumar2022 | Gastric | Kumar 2022 Cancer Discov | GSE183904 | **158,641** |
| hcc-tls-lu2022 | Liver HCC (+TLS) | Lu 2022 Nat Commun | GSE149614 | **71,915** |
| pancreatic-cancer-sc-rna-seq | PDAC | Peng 2019 Cell Res | PRJCA001063 | **57,423** |
| hnscc-progression-choi2023 | Head & neck | Choi 2023 Nat Commun | GSE181919 | **54,224** |
| therapy-induced-evolution (Maynard) | Lung (therapy) | Maynard 2020 Nat Genet | — | **21,620** |
| liver-cancer-ma2019 | Liver HCC/iCCA | Ma 2019 Cancer Cell | GSE125449 | **9,549** |
| glioblastoma-neftel-2019 | GBM | Neftel 2019 Cell | GSM3828672 | **7,930** |
| puram-2017-hnscc-pemt | HNSCC p-EMT | Puram 2017 Cell | GSE103322 | **5,902** |
| scrna-seq-melanoma-tirosh | Melanoma | Tirosh 2016 Science | GSE72056 | **4,645** |
| **Total** | **9 tumor types** | | | **≈795,700** |

**≈795k cells across ~9 distinct cancer types**, each with independently-derived cell-type + malignant-cell labels (author labels NOT consumed — re-derived by fresh GPU-Python code per the BioIDE constitution).

**De-duplication notes**
- **Maynard 2020 appears twice** — `scrna-seq-gpu-modern-reanalysis` (21,620) and `scrna-seq-therapy-induced-evolution` (21,444) are the *same* dataset processed two ways. Counted once (21,620) above.
- **puram** has 6 h5ad files but they are pipeline stages of the *same* 5,902 cells (raw → qc → norm → clustered → latent → annotated). Counted once.

## 3. Two classes of dataset

### A. Cancer reproduction pipelines — matrix-based, GPU-Python, author-label-independent, VALIDATED

These are the atlas building blocks: each ships a processed `.h5ad` with a fresh cell-type + malignant-cell annotation already computed and a validation verdict on disk.

| Pipeline | Data on disk | Size | Verdict |
|---|---|---:|---|
| scrna-seq-melanoma-tirosh | GSE72056 matrix | 72 MB | ✅ AGREE |
| pancreatic-cancer-sc-rna-seq | Peng h5ad (besca) | 1.6 GB | ✅ |
| thyroid-cancer-ptc-pu2021 | GSE184362_RAW.tar | 1.9 GB | ✅ AGREE |
| lung-adeno-kim2020 | GSE131907 UMI matrix | 1.9 GB | ✅ AGREE |
| gastric-cancer-kumar2022 | GSE183904_RAW.tar | 659 MB | ✅ |
| liver-cancer-ma2019 | GSE125449 (Set1/Set2 MTX) | 45 MB | ✅ PARTIAL |
| hcc-tls-lu2022 | GSE149614 count + metadata | 862 MB | ✅ AGREE |
| hnscc-progression-choi2023 | GSE181919 UMI counts | 123 MB | ✅ |
| glioblastoma-neftel-2019 | GSM3828672 Smartseq2 TPM | 298 MB | ✅ |
| puram-2017-hnscc-pemt | GSE103322 HNSCC all data | 90 MB | ✅ (PARTIAL) |
| gpu-modern / therapy-evolution | Maynard 2020 Data_input | 7.8 GB | ✅ |

### B. 10x raw-FASTQ tutorial pipelines — teach alignment from scratch (STARsolo)

Heavy, mostly non-malignant reference tissue. Less useful for a *cancer-gene* atlas except NSCLC / GBM / TNBC. No processed h5ad unless noted.

| Pipeline | Data | Size | Status |
|---|---|---:|---|
| scrna-seq-pan-t-cells | t_4k FASTQ tar | 33 GB | raw only, not processed |
| scrna-seq-glioblastoma | 10x GBM FASTQ tar | 18 GB | raw only |
| scrna-seq-nsclc | P1 tumor BAM → FASTQ | 8.6 GB | ✅ processed (STARsolo) |
| scrna-seq-tnbc-gpu | tnbc1 BAM | 7.9 GB | ⚠️ downloaded, **no results yet** |
| scrna-seq-pbmc | pbmc_1k_v3 FASTQ tar | 5.2 GB | reference/demo |

### C. Legacy / utility

- `scanpy-byo-matrix` — bring-your-own matrix
- `_template` — pipeline scaffold (ignored by loader)

## 4. Toward the cross-cancer gene atlas

The **11 class-A pipelines** are the natural substrate: ~795k cells, 9 tumor types, malignant-vs-normal split and per-cell-type markers already computed. An atlas can harmonize genes across these h5ads **without re-running alignment**.

Dominated by four large studies (lung, thyroid, gastric, liver) accounting for ~635k of the ~795k cells.

**Gaps to address before building:**
- `scrna-seq-tnbc-gpu` — 7.9 GB BAM downloaded but produced **zero results** (not yet run).
- Raw-FASTQ pipelines (pan-t, glioblastoma-10x) are unprocessed — skip for the atlas or process first.
- Two Maynard entries and six puram stage-files must be de-duplicated when merging.
