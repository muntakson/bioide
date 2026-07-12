#!/usr/bin/env bash
set -euo pipefail

ENV_ROOT="${GHBIO_MAYNARD_GPU_ENV:-$HOME/ghbio-venv-gpu/maynard-modern}"
SOURCE="${GHBIO_MAYNARD_DIR:-$HOME/ghbio-tutorial/maynard-2020}/scell_lung_adenocarcinoma"
RESULTS="${GHBIO_RESULTS:?BioIDE must provide GHBIO_RESULTS}"
[[ -x "$ENV_ROOT/bin/python" && -f "$ENV_ROOT/.ready" ]] || { echo "Run Step 0 first." >&2; exit 1; }
mkdir -p "$RESULTS"
# -u keeps stage messages visible in VS Code's task terminal immediately rather than
# buffering them until the long CSV read or GPU training has finished.
"$ENV_ROOT/bin/python" -u 02_gpu_scvi_reanalysis.py --source "$SOURCE" --results "$RESULTS"
