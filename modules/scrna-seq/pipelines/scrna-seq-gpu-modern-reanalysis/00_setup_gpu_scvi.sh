#!/usr/bin/env bash
set -euo pipefail

ENV_ROOT="${GHBIO_MAYNARD_GPU_ENV:-$HOME/ghbio-venv-gpu/maynard-modern}"
mkdir -p "$(dirname "$ENV_ROOT")"
if [[ ! -x "$ENV_ROOT/bin/python" ]]; then python3 -m venv "$ENV_ROOT"; fi
"$ENV_ROOT/bin/python" -m pip install --upgrade pip
# scvi-tools documents this CUDA extra for Linux/NVIDIA systems. Keeping it in a
# tutorial-local venv avoids changing the system Python or the legacy R workflow.
"$ENV_ROOT/bin/python" -m pip install --upgrade "scvi-tools[cuda]" scanpy pandas matplotlib igraph leidenalg
"$ENV_ROOT/bin/python" - <<'PY'
import torch
if not torch.cuda.is_available():
    raise SystemExit("CUDA is not available to PyTorch. Check the NVIDIA driver/PyTorch wheel before continuing.")
print("GPU ready:", torch.cuda.get_device_name(0), "| CUDA:", torch.version.cuda)
PY
touch "$ENV_ROOT/.ready"
