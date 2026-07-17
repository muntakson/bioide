#!/usr/bin/env bash
set -euo pipefail
# run_tme_integrate.sh — Stage 1 wrapper. Prefers scVI on GPU; falls back to
# Harmony (CPU) automatically inside the script if counts are missing or no GPU.
# Pass through args, e.g. balance big studies:  bash run_tme_integrate.sh --max-per-sample 2000
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${HOME}/ghbio-venv/bin/python"
RESULTS="${GHBIO_RESULTS:-${HOME}/ghbio-tutorial/results}"
export GHBIO_RESULTS="${RESULTS}"
[[ -x "$PY" ]] || { echo "ERROR: venv python missing at $PY (run 00_setup_env.sh)." >&2; exit 1; }
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=name,memory.total --format=csv,noheader | sed 's/^/    GPU: /'
else
  echo "    (no GPU — will use Harmony CPU fallback)"
fi
exec "$PY" "${HERE}/01_tme_integrate.py" --results "${RESULTS}" "$@"
