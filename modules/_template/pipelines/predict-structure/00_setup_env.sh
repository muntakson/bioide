#!/usr/bin/env bash
set -euo pipefail
# Example stage script. Write outputs into "$GHBIO_RESULTS" (injected by the app;
# falls back to the project results dir). That keeps results as first-class project files.
RESULTS="${GHBIO_RESULTS:-$HOME/ghbio-workspace/projects/predict-structure/results}"
mkdir -p "$RESULTS"
echo "==> [00] (example) install your domain's tools here."
echo "    Results dir: $RESULTS"
