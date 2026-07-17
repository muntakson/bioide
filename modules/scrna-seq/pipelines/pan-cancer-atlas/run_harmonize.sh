#!/usr/bin/env bash
set -euo pipefail
# run_harmonize.sh — Stage 0 wrapper. Standardises the 11 source h5ads into
# $GHBIO_RESULTS/harmonized/. CPU-only step (I/O bound); no GPU required.
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${HOME}/ghbio-venv/bin/python"
RESULTS="${GHBIO_RESULTS:-${HOME}/ghbio-tutorial/results}"
export GHBIO_RESULTS="${RESULTS}"
echo "==> [00·harmonize] -> ${RESULTS}"
[[ -x "$PY" ]] || { echo "ERROR: venv python missing at $PY (run 00_setup_env.sh)." >&2; exit 1; }
exec "$PY" "${HERE}/00_harmonize.py" --results "${RESULTS}" "$@"
