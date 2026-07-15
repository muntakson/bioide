#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 00_setup_env.sh  (Kumar 2022 gastric cancer — INDEPENDENT GPU reanalysis)
# BioIDE 헌장 제4조: 현대 GPU·Python 스택으로 재분석합니다. 이 파이프라인은
# 저자 라벨을 소비하지 않고(제1조) 새로 짠 코드로 세포유형·악성 상피세포를
# 다시 도출하므로, Scanpy + PyTorch(GPU) + Harmony + scikit-learn 이 필요합니다.
# 다른 예제와 같은 공유 venv(~/ghbio-venv)를 재사용합니다.
#
# Idempotent: if the stack already imports, we skip pip. FORCE=1 reinstalls.
# =============================================================================

VENV="${HOME}/ghbio-venv"
echo "==> [00] GPU reanalysis environment for Kumar 2022 gastric cancer: ${VENV}"

if [[ ! -d "${VENV}" ]]; then
  python3 -m venv "${VENV}"
else
  echo "==> Virtualenv already exists, reusing it."
fi
# shellcheck disable=SC1091
source "${VENV}/bin/activate"

if python -c "import scanpy, anndata, h5py, torch, harmonypy, sklearn, leidenalg, umap, matplotlib" 2>/dev/null \
   && [[ "${FORCE:-0}" != "1" ]]; then
  echo "==> Core GPU analysis stack already installed — skipping pip install."
  echo "    (Reinstall with:  FORCE=1 bash 00_setup_env.sh)"
else
  echo "==> Upgrading pip / setuptools / wheel..."
  python -m pip install --upgrade pip setuptools wheel
  echo "==> Installing scanpy + PyTorch + harmonypy + scikit-learn (few minutes)..."
  python -m pip install \
    scanpy anndata h5py leidenalg python-igraph umap-learn \
    matplotlib pandas numpy scipy scikit-learn harmonypy
  # PyTorch drives the GPU scaling + PCA(SVD). Install only if a GPU is present.
  if command -v nvidia-smi >/dev/null 2>&1 && ! python -c "import torch" 2>/dev/null; then
    echo "==> GPU detected — installing PyTorch..."
    python -m pip install torch || echo "==> torch install failed; GPU step will refuse to run."
  fi
fi

echo ""
echo "==> Installed versions + GPU status:"
python - <<'PY'
import importlib.metadata as md, sys
print(f"  python   {sys.version.split()[0]}")
for p in ["scanpy", "anndata", "torch", "harmonypy", "scikit-learn", "umap-learn", "leidenalg"]:
    try: print(f"  {p:<13} {md.version(p)}")
    except md.PackageNotFoundError: pass
try:
    import torch
    print(f"  CUDA available: {torch.cuda.is_available()}"
          + (f" — {torch.cuda.get_device_name(0)}" if torch.cuda.is_available() else " (CPU only — GPU step will refuse)"))
except Exception as e:
    print("  torch check failed:", e)
PY

echo ""
echo "==> [00] Done. Next: 1. Download the Kumar 2022 gastric matrices (GEO GSE183904_RAW.tar)."
