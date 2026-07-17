#!/usr/bin/env bash
set -euo pipefail
# =============================================================================
# 00_setup_env.sh  (Pan-cancer atlas — Use 1 TME integration + Use 2 malignant NMF)
# Reuses the shared venv (~/ghbio-venv) and adds the two extra libs this pipeline
# needs on top of the standard GPU stack: scvi-tools (TME integration) and cNMF
# (per-sample malignant meta-programs). Idempotent; FORCE=1 reinstalls.
# =============================================================================
VENV="${HOME}/ghbio-venv"
echo "==> [00] Pan-cancer atlas environment: ${VENV}"
[[ -d "${VENV}" ]] || python3 -m venv "${VENV}"
# shellcheck disable=SC1091
source "${VENV}/bin/activate"

if python -c "import scanpy, anndata, torch, scvi, cnmf, harmonypy, sklearn" 2>/dev/null \
   && [[ "${FORCE:-0}" != "1" ]]; then
  echo "==> Atlas stack (scanpy+torch+scvi-tools+cnmf+harmonypy) already present — skipping pip."
else
  python -m pip install --upgrade pip setuptools wheel
  python -m pip install scanpy anndata h5py leidenalg python-igraph umap-learn \
    matplotlib pandas numpy scipy scikit-learn harmonypy scvi-tools cnmf
fi

python - <<'PY'
import importlib.metadata as md
for p in ["scanpy","anndata","torch","scvi-tools","cnmf","harmonypy"]:
    try: print(f"  {p:<12} {md.version(p)}")
    except md.PackageNotFoundError: print(f"  {p:<12} MISSING")
import torch
print("  CUDA:", torch.cuda.is_available(),
      "-", (torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU only"))
PY
echo "==> [00] Done. Next: 1. Harmonise the 11 source h5ads (run_harmonize.sh)."
