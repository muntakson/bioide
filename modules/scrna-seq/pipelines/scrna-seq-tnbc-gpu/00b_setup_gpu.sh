#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 00b_setup_gpu.sh
# Create a dedicated GPU Python environment for the modern reprocessing step:
# scvi-tools (CUDA/PyTorch) + scanpy. Used by 03_gpu_tumor_cnv.py, which learns
# a GPU scVI latent space and then infers copy-number to separate tumor cells.
# GPU 전용 파이썬 환경(scvi-tools + scanpy)을 만들고 실제 GPU가 보이는지 검사합니다.
#
# Kept in a tutorial-local venv so it never touches ~/ghbio-venv (the CPU Scanpy
# stack) or the system Python. Idempotent: re-running only installs what's missing.
# =============================================================================

ENV_ROOT="${GHBIO_TNBC_GPU_ENV:-$HOME/ghbio-venv-gpu/tnbc-copykat}"
mkdir -p "$(dirname "$ENV_ROOT")"

echo "==> [00b] Setting up GPU environment at: ${ENV_ROOT}"

if [[ ! -x "$ENV_ROOT/bin/python" ]]; then
  echo "==> Creating GPU virtualenv..."
  python3 -m venv "$ENV_ROOT"
else
  echo "==> GPU virtualenv already exists, reusing it."
fi

PY="$ENV_ROOT/bin/python"

# Skip the (slow) pip step entirely if everything already imports. FORCE=1 reinstalls.
if "$PY" -c "import scvi, scanpy, torch, leidenalg, igraph" 2>/dev/null \
   && [[ "${FORCE:-0}" != "1" ]]; then
  echo "==> GPU stack already installed — skipping pip install."
else
  "$PY" -m pip install --upgrade pip
  # scvi-tools documents the [cuda] extra for Linux/NVIDIA. scanpy/igraph/leidenalg
  # give us neighbors/UMAP/Leiden/markers on the scVI latent space.
  echo "==> Installing scvi-tools[cuda] + scanpy (this can take several minutes)..."
  "$PY" -m pip install --upgrade "scvi-tools[cuda]" scanpy pandas matplotlib igraph leidenalg
fi

# --- Verify a real CUDA GPU is visible to PyTorch ----------------------------
"$PY" - <<'PYEOF'
import torch
if not torch.cuda.is_available():
    raise SystemExit(
        "CUDA is not available to PyTorch. This tutorial's step 3 runs GPU scVI and "
        "refuses a silent CPU fallback. Check the NVIDIA driver / PyTorch wheel first."
    )
print("GPU ready:", torch.cuda.get_device_name(0), "| CUDA:", torch.version.cuda)
PYEOF

touch "$ENV_ROOT/.ready"
echo "==> [00b] Done. GPU env ready: ${ENV_ROOT}"
