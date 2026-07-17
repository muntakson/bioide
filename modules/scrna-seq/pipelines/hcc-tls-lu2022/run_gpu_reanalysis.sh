#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# run_gpu_reanalysis.sh  (Lu 2022 HCC / TLS — independent GPU reanalysis wrapper)
# Runs 02_gpu_reanalysis.py on the GPU. Per BioIDE 헌장 제4조 this is a GPU-first
# workflow; it refuses to run without CUDA (no silent CPU fallback that would
# quietly take hours). Writes all outputs into $GHBIO_RESULTS.
#
# 72k cells is a moderate run; pass extra args through, e.g. a faster subsampled
# run:  bash run_gpu_reanalysis.sh --max-cells 40000
# =============================================================================

HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${HOME}/ghbio-venv/bin/python"
RESULTS="${GHBIO_RESULTS:-${HOME}/ghbio-tutorial/results}"
export GHBIO_RESULTS="${RESULTS}"

echo "==> [02] Independent GPU reanalysis (Lu 2022 HCC / TLS) → ${RESULTS}"
[[ -x "$PY" ]] || { echo "ERROR: venv python missing at $PY (run 00_setup_env.sh)." >&2; exit 1; }

if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "ERROR: no nvidia-smi — this GPU-first reanalysis needs a CUDA GPU." >&2
  echo "       (헌장 제4조: 현대 GPU 스택. CPU 대체 실행을 막습니다.)" >&2
  exit 3
fi
if ! "$PY" -c "import torch,sys; sys.exit(0 if torch.cuda.is_available() else 1)"; then
  echo "ERROR: torch.cuda.is_available() is False — check the CUDA/PyTorch install." >&2
  exit 3
fi
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader | sed 's/^/    GPU: /'

exec "$PY" "${HERE}/02_gpu_reanalysis.py" --results "${RESULTS}" "$@"
