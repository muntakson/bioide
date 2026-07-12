# Reproducing Salcher *et al.* (2022) — LuCA

This directory pins and launches the authors' workflow for **"High-resolution single-cell atlas reveals diversity and plasticity of tissue-resident neutrophils in non-small cell lung cancer"** (Cancer Cell 40, 1503–1520, doi:10.1016/j.ccell.2022.10.008).

It intentionally does not use the repository's `scrna-seq-nsclc` tutorial: that tutorial analyses a different, single 10x NSCLC sample (GSE117570), whereas the paper's LuCA atlas combines 29 datasets, 1,283,972 cells, and 318 patients.

## Public reproduction routes

| Goal | Command | Required public archives | Notes |
|---|---|---|---|
| Rebuild the core/extended atlas | `bash fetch_luca.sh full` then `bash run_luca.sh build` | containers + input data | Very expensive; uses scVI/scANVI and needs an x86_64 NVIDIA GPU/HPC for a faithful run. |
| Regenerate public downstream analyses | `bash fetch_luca.sh downstream` then `bash run_luca.sh downstream` | containers + input data + published build results | Preferred route for reproducing public figures without rebuilding the atlas. |
| Inspect publication outputs | `bash fetch_luca.sh published-results` | downstream results | Does not execute the workflow. |
| Project a new dataset into the core atlas | `bash fetch_luca.sh model` | core-atlas scANVI model | Requires a compatible x86_64 container runtime/environment. |

The `downstream` route is the closest practical reproduction: it starts from the authors' published `build_atlas` outputs and reruns their downstream Nextflow modules.

## Requirements

* x86_64 Linux; the supplied Singularity images were published for the authors' HPC environment.
* Nextflow **22.04.5** (the authors pin this version).
* Apptainer/Singularity >= 3.7 and a Java version compatible with Nextflow.
* For `build`: an NVIDIA GPU, substantial RAM, and HPC-scale CPU allocation.

The supplied host is `aarch64` and lacks Nextflow and Apptainer/Singularity, so it can prepare and checksum-verify the materials but cannot execute the authors' containerized workflow.

## Data provenance and limitation

Archives are retrieved from the authors' immutable Zenodo record 7227571 (paper data record: doi:10.5281/zenodo.6411867). `fetch_luca.sh` verifies the published MD5 checksum before extraction.

The `--with_genentech` branch is deliberately disabled. It produces the checkpoint-inhibitor response analysis (including the paper's anti–PD-L1 association) but requires controlled-access Genentech/EGA cohort EGAS00001005013. Obtain authorization and place the required files under the authors' expected `data/14_ici_treatment/` locations before enabling it.

Exact numeric/label equality is not guaranteed even on compatible hardware: the authors note that scVI, scANVI, and UMAP are stochastic and hardware/core-count dependent. Preserve the workflow revision recorded in `MANIFEST.tsv`.

## First run

```bash
cd reproduction/luca
bash fetch_luca.sh downstream
bash run_luca.sh downstream
```

Set `LUCA_DIR` to use a clone elsewhere. By default the scripts use `../../third_party/luca`, the author repository checked out alongside this guide. Results are written to `third_party/luca/data/30_downstream_analyses`.

To execute on an HPC, copy/clone the author repository and this directory, download the archives on shared storage, configure an appropriate Nextflow profile, and set `LUCA_PROFILE` when launching:

```bash
LUCA_PROFILE=your_hpc_profile bash run_luca.sh downstream
```
