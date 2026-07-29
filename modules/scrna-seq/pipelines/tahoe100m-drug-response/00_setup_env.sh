#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 00_setup_env.sh  (Tahoe-100M drug-response — INDEPENDENT GPU reanalysis)
#
# Tahoe-100M (Vevo Therapeutics × Arc Institute) is a >95M-cell single-cell DRUG
# PERTURBATION atlas: 50 cancer cell lines × ~1,100 small molecules, generated on
# Vevo's MOSAIC platform. It ships as ~14 per-plate h5ads (~1.69 TB total) in the
# Requester-Pays Virtual Cell Atlas bucket — far too big to download whole. So this
# pipeline SELECTS one drug (+ its DMSO vehicle controls) across a few cell lines and
# STREAM-SUBSETS just those cells, then re-derives the drug response with our own GPU
# code (헌장 제1·4조: we don't consume any provided 'response' label).
#
# Needs:
#   - analysis stack: Scanpy + PyTorch(GPU) + Harmony + scikit-learn (shared venv)
#   - pyarrow: read the metadata parquet tables
#   - gcsfs: stream-subset cells out of the huge per-plate h5ads WITHOUT downloading them
#   - gsutil (Google Cloud SDK) + a GCP billing project (Requester Pays)
#
# Idempotent: skips pip if already importable. FORCE=1 reinstalls.
# =============================================================================

VENV="${HOME}/ghbio-venv"
echo "==> [00] Tahoe-100M drug-response environment: ${VENV}"

if [[ ! -d "${VENV}" ]]; then
  python3 -m venv "${VENV}"
else
  echo "==> Virtualenv already exists, reusing it."
fi
# shellcheck disable=SC1091
source "${VENV}/bin/activate"

if python -c "import scanpy, anndata, h5py, torch, harmonypy, sklearn, leidenalg, umap, matplotlib, pyarrow, gcsfs" 2>/dev/null \
   && [[ "${FORCE:-0}" != "1" ]]; then
  echo "==> Core stack (+pyarrow +gcsfs) already installed — skipping pip install."
  echo "    (Reinstall with:  FORCE=1 bash 00_setup_env.sh)"
else
  echo "==> Upgrading pip / setuptools / wheel..."
  python -m pip install --upgrade pip setuptools wheel
  echo "==> Installing scanpy + PyTorch + harmonypy + scikit-learn + pyarrow + gcsfs..."
  python -m pip install \
    scanpy anndata h5py leidenalg python-igraph umap-learn \
    matplotlib pandas numpy scipy scikit-learn harmonypy pyarrow gcsfs
  if command -v nvidia-smi >/dev/null 2>&1 && ! python -c "import torch" 2>/dev/null; then
    echo "==> GPU detected — installing PyTorch..."
    python -m pip install torch || echo "==> torch install failed; GPU step will refuse to run."
  fi
fi

# --- gsutil + GCP billing project (Requester Pays) -----------------------------
echo ""
if command -v gsutil >/dev/null 2>&1; then
  echo "==> gsutil found: $(command -v gsutil)"
else
  echo "==> gsutil (Google Cloud SDK) NOT found — needed to browse the atlas bucket."
  echo "    Install:  curl -sSL https://sdk.cloud.google.com | bash && exec -l \"\$SHELL\""
fi

CFG="${HOME}/.config/ghbio/gcp.json"
HELPER="$(cd "$(dirname "$0")/../_shared" 2>/dev/null && pwd)/setup_gcp.sh"
PROJECT="${GHBIO_GCP_PROJECT:-}"
if [[ -z "${PROJECT}" && -f "${CFG}" ]]; then
  PROJECT="$(python -c "import json;print(json.load(open('${CFG}')).get('project',''))" 2>/dev/null || true)"
fi
if [[ -z "${PROJECT}" ]] && command -v gcloud >/dev/null 2>&1; then
  PROJECT="$(gcloud config get-value project 2>/dev/null || true)"
fi
if [[ -n "${PROJECT}" && "${PROJECT}" != "(unset)" ]]; then
  echo "==> GCP billing project for Requester-Pays access: ${PROJECT}"
else
  cat <<MSG
==> No GCP billing project configured yet. Run the shared helper (writes ${CFG},
    checks auth, live bucket test):
      bash "${HELPER}" <your-project-id>
    (Requester-Pays: billed to this project; 2 TB/month free. This pipeline downloads
     only a small SUBSET, so a single drug run stays well within the free tier.)
MSG
fi

echo ""
echo "==> Installed versions + GPU status:"
python - <<'PY'
import importlib.metadata as md, sys
print(f"  python   {sys.version.split()[0]}")
for p in ["scanpy", "anndata", "torch", "harmonypy", "scikit-learn", "pyarrow", "gcsfs"]:
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
echo "==> [00] Done. Next: 1. Select a drug + controls and stream-subset the cells."
