# Pan-Cancer Atlas (Use 1 TME + Use 2 malignant meta-programs)

Builds one cross-cancer atlas from BioIDE's **11 validated reproduction pipelines**
(≈795,700 cells · 9 cancer types). Two compartments, two methods:

- **Use 1 — non-malignant TME**: integrate immune/stroma across studies (scVI, or
  Harmony fallback) → cell-state annotation → *cell-state × cancer occurrence*
  (pan-cancer hallmark vs tissue-specific states).
- **Use 2 — malignant**: **not integrated** (malignant cells cluster by patient via
  private CNV). Per-sample NMF → cluster programs by gene overlap → **recurrent
  meta-programs** (Gavish/Tirosh 2023 style).
- **Use 3 (bonus)** — cross-cancer dedifferentiation along normal→tumour→metastasis.

Per the BioIDE constitution, author labels are **not re-consumed** — each source
pipeline already re-derived them; here they are only a harmonisation key.

## Data-driven config
`inputs.json` declares the 11 source h5ads, their obs columns (cell-type / malignant /
sample / progression), the canonical **lineage map**, and the TME lineage set. Change
this file, not the code, when a source pipeline moves or a new label appears.

## Stages
| # | script | output |
|---|---|---|
| 0 | `00_setup_env.sh` | venv + scvi-tools + cnmf |
| 1 | `run_harmonize.sh` → `00_harmonize.py` | `harmonized/*.{tme,malignant}.h5ad`, manifest, `common_genes.txt` |
| 2 | `run_tme_integrate.sh` → `01_tme_integrate.py` | `tme_atlas.h5ad`, UMAPs |
| 3 | `02_tme_annotate.py` | `tme_cellstate_occurrence.csv/png` |
| 4 | `03_malignant_nmf.py` | `malignant_programs.{csv,json}` |
| 5 | `04_meta_programs.py` | `meta_programs.json`, `mp_occurrence.csv/png` |
| 6 | `05_progression.py` | `progression_dedifferentiation.png` |
| 7 | `06_validate.py` | `atlas_validation_verdict.txt` |
| 9 | `07_make_report.py` | `GHBIO_pan_cancer_atlas_report.pdf` |

All stages honour `GHBIO_RESULTS` and are re-runnable. Stage 1 is CPU/IO; stages 2–6
prefer GPU but fall back to CPU.

## Known TODO before a full production run
1. **Raw-counts recovery** — 9 of 11 source h5ads lack `layers['counts']` (only puram
   and Maynard have them). Stage 0 detects and reports this; scVI needs counts, so
   until recovered, Stage 2 uses the **Harmony fallback**. To enable scVI, re-run those
   source pipelines saving `layers['counts']`, or add a counts-recovery step.
2. **Maynard** has no `cell_type` column in its current h5ad → contributes only to
   Use 2 / progression, not the TME lineage annotation, until a lineage column is added.
3. **Balance** — big-4 studies (lung/thyroid/gastric/hcc) dominate; use
   `run_tme_integrate.sh --max-per-sample N`.

## Smoke test (done)
Stage 0 + 3 + 5 verified on melanoma + GBM: 8,094 malignant cells → 198 per-sample
programs → 23 meta-programs; **MP1 = cell-cycle** (UBE2C/TYMS/CDK1/TOP2A) recurs across
both — the expected pan-cancer program. Full run: `bash 00_setup_env.sh` then run
stages 1→9 from the Dashboard (or `run_harmonize.sh` with no `--only`).
