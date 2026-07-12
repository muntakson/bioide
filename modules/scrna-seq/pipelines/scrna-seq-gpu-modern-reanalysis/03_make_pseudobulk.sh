#!/usr/bin/env bash
set -euo pipefail

ENV_ROOT="${GHBIO_MAYNARD_GPU_ENV:-$HOME/ghbio-venv-gpu/maynard-modern}"
RESULTS="${GHBIO_RESULTS:?BioIDE must provide GHBIO_RESULTS}"
[[ -f "$RESULTS/modern_reanalysis.h5ad" ]] || { echo "Run Step 2 first." >&2; exit 1; }
"$ENV_ROOT/bin/python" 03_make_pseudobulk.py --input "$RESULTS/modern_reanalysis.h5ad" --results "$RESULTS"
"$ENV_ROOT/bin/python" 04_evidence_summary.py --input "$RESULTS/modern_reanalysis.h5ad" --results "$RESULTS"
