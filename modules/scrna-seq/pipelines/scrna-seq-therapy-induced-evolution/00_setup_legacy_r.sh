#!/usr/bin/env bash
set -euo pipefail

# Keep the paper-specific Seurat v4 stack separate from the user's system R
# library and from BioIDE's Scanpy environment.
LIB_ROOT="${GHBIO_MAYNARD_R_LIB:-$HOME/ghbio-venv-r/maynard-2020}"
mkdir -p "$LIB_ROOT"
export R_LIBS_USER="$LIB_ROOT"
LOG_FILE="$LIB_ROOT/setup.log"
# The dashboard reads the final three lines of this persistent log while setup is
# running, so users can see activity and avoid clicking this one-time step twice.
exec > >(tee -a "$LOG_FILE") 2>&1
rm -f "$LIB_ROOT/.ready" # recreated only after the package load verification below

command -v Rscript >/dev/null || {
  echo "Rscript is required. Install a system R distribution, then run this step again." >&2
  exit 1
}

Rscript --vanilla - <<'RSCRIPT'
lib <- Sys.getenv("R_LIBS_USER")
dir.create(lib, recursive = TRUE, showWarnings = FALSE)
.libPaths(c(lib, .libPaths()))

install_if_missing <- function(pkg, repo = "https://cloud.r-project.org") {
  if (!requireNamespace(pkg, quietly = TRUE))
    install.packages(pkg, repos = repo, lib = lib)
}

install_if_missing("remotes")
# ggplot2 4.0 (S7 rewrite) breaks Seurat v4's VlnPlot/SingleExIPlot, which still adds geoms via
# do.call("+", ...) against what is now an S7 `+` method (deparse(substitute()) fails, halting the
# render). Pin BELOW v4 to the last 3.5 line before anything else can pull 4.x as a dependency.
gg_ok <- requireNamespace("ggplot2", quietly = TRUE) &&
  packageVersion("ggplot2") >= "3.4.0" && packageVersion("ggplot2") < "4.0.0"
if (!gg_ok)
  remotes::install_version("ggplot2", version = "3.5.2", lib = lib, upgrade = "never", repos = "https://cloud.r-project.org")

for (pkg in c("remotes", "devtools", "useful", "dplyr", "tidyverse", "gridExtra", "ggridges", "ggExtra", "clustree", "rmarkdown")) install_if_missing(pkg)
install_if_missing("BiocManager")
if (!requireNamespace("multtest", quietly = TRUE))
  BiocManager::install("multtest", lib = lib, ask = FALSE, update = FALSE)
if (!requireNamespace("SDMTools", quietly = TRUE))
  remotes::install_url("https://cran.r-project.org/src/contrib/Archive/SDMTools/SDMTools_1.1-221.2.tar.gz", lib = lib, upgrade = "never")
# The authors' notebooks (czbiohub/scell_lung_adenocarcinoma @ de138c7) are written
# for the Seurat v3+ object API: CreateSeuratObject(counts=), obj@assays$RNA@counts,
# nCount_RNA/nFeature_RNA, FindVariableFeatures, etc. On R 4.3 the matching install
# is the Seurat v4 line. Do NOT install v2 (its CreateSeuratObject wants raw.data=,
# which fails these notebooks) and pin BELOW v5 (v5 replaces the Assay @counts/@data
# slots with layers, which also breaks obj@assays$RNA@counts). Pin SeuratObject to the
# v4 line first so the Seurat install does not pull SeuratObject 5.x as a dependency.
seurat_obj_ok <- requireNamespace("SeuratObject", quietly = TRUE) &&
  packageVersion("SeuratObject") >= "4.0.0" && packageVersion("SeuratObject") < "5.0.0"
if (!seurat_obj_ok)
  remotes::install_version("SeuratObject", version = "4.1.4", lib = lib, upgrade = "never", repos = "https://cloud.r-project.org")
seurat_ok <- requireNamespace("Seurat", quietly = TRUE) &&
  packageVersion("Seurat") >= "4.0.0" && packageVersion("Seurat") < "5.0.0"
if (!seurat_ok)
  remotes::install_version("Seurat", version = "4.4.0", lib = lib, upgrade = "never", repos = "https://cloud.r-project.org")
if (!requireNamespace("DoubletFinder", quietly = TRUE))
  remotes::install_github("chris-mcginnis-ucsf/DoubletFinder@5dfd96b06365d7843adf3a72ffb6a30f42c74a01", lib = lib, upgrade = "never")

missing <- c("Seurat", "DoubletFinder")[!vapply(c("Seurat", "DoubletFinder"), requireNamespace, logical(1), quietly = TRUE)]
if (length(missing)) stop("Setup incomplete: required package(s) could not load: ", paste(missing, collapse = ", "))
RSCRIPT

touch "$LIB_ROOT/.ready"
echo "Ready: legacy Seurat environment at $LIB_ROOT"
