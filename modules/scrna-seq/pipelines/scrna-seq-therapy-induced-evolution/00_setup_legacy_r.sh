#!/usr/bin/env bash
set -euo pipefail

# Keep the paper-specific, older Seurat stack separate from the user's system R
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

for (pkg in c("remotes", "devtools", "useful", "dplyr", "tidyverse", "gridExtra", "ggridges", "ggExtra", "clustree", "rmarkdown")) install_if_missing(pkg)
install_if_missing("BiocManager")
if (!requireNamespace("multtest", quietly = TRUE))
  BiocManager::install("multtest", lib = lib, ask = FALSE, update = FALSE)
if (!requireNamespace("SDMTools", quietly = TRUE))
  remotes::install_url("https://cran.r-project.org/src/contrib/Archive/SDMTools/SDMTools_1.1-221.2.tar.gz", lib = lib, upgrade = "never")
if (!requireNamespace("Seurat", quietly = TRUE) || packageVersion("Seurat") >= "3.0.0")
  remotes::install_url("https://cran.r-project.org/src/contrib/Archive/Seurat/Seurat_2.3.4.tar.gz", lib = lib, upgrade = "never")
if (!requireNamespace("DoubletFinder", quietly = TRUE))
  remotes::install_github("chris-mcginnis-ucsf/DoubletFinder@5dfd96b06365d7843adf3a72ffb6a30f42c74a01", lib = lib, upgrade = "never")

missing <- c("Seurat", "DoubletFinder")[!vapply(c("Seurat", "DoubletFinder"), requireNamespace, logical(1), quietly = TRUE)]
if (length(missing)) stop("Setup incomplete: required package(s) could not load: ", paste(missing, collapse = ", "))
RSCRIPT

touch "$LIB_ROOT/.ready"
echo "Ready: legacy Seurat environment at $LIB_ROOT"
