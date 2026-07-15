#!/usr/bin/env bash
set -euo pipefail

# GPU (PyTorch) port of the authors' Seurat workflow. Uses BioIDE's main Python
# venv, which already carries torch+CUDA (GB10) and scanpy/leidenalg/umap — no
# separate environment is needed. Override GHBIO_PY to point elsewhere.
PY="${GHBIO_PY:-$HOME/ghbio-venv/bin/python}"
SOURCE="${GHBIO_MAYNARD_DIR:-$HOME/ghbio-tutorial/maynard-2020}/scell_lung_adenocarcinoma"
RESULTS="${GHBIO_RESULTS:?BioIDE must provide GHBIO_RESULTS}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

[[ -x "$PY" ]] || { echo "Python venv not found at $PY. Run the BioIDE scRNA-seq setup first." >&2; exit 1; }
required=(
  "$SOURCE/Data_input/csv_files/S01_datafinal.csv"
  "$SOURCE/Data_input/csv_files/S01_metacells.csv"
)
for file in "${required[@]}"; do
  [[ -s "$file" ]] || { echo "Missing author data: $file — run the Maynard tutorial's data step first." >&2; exit 1; }
done
mkdir -p "$RESULTS"

# -u keeps the per-stage messages visible immediately rather than buffering them
# until the long CSV read or the GPU SVD has finished.
"$PY" -u "$HERE/gpu_seurat_workflow.py" --source "$SOURCE" --results "$RESULTS" "$@"
