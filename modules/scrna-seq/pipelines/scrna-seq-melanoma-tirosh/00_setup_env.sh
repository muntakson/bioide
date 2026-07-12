#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 00_setup_env.sh  (Tirosh 2016 melanoma reproduction)
# Reuse the shared Scanpy virtual environment (~/ghbio-venv) used by the other
# scRNA-seq tutorials. This example starts from a published expression matrix,
# so it needs only the core Scanpy stack — no STAR / pysam / GPU packages.
# 이 예제는 공개 발현 행렬에서 시작하므로 다른 예제와 같은 Scanpy 환경만 있으면 됩니다.
#
# Idempotent: if the stack already imports, we skip pip entirely. FORCE=1 reinstalls.
# =============================================================================

VENV="${HOME}/ghbio-venv"
echo "==> [00] Scanpy environment for the melanoma (GSE72056) reproduction: ${VENV}"

if [[ ! -d "${VENV}" ]]; then
  echo "==> Creating virtualenv..."
  python3 -m venv "${VENV}"
else
  echo "==> Virtualenv already exists, reusing it."
fi

# shellcheck disable=SC1091
source "${VENV}/bin/activate"

# scanpy pulls in anndata/leidenalg/igraph/umap/matplotlib/pandas/numpy/scipy.
# This tutorial additionally uses scipy.stats (bundled) for the tSNE / correlations.
if python -c "import scanpy, anndata, leidenalg, igraph, umap, matplotlib, pandas, numpy, scipy" 2>/dev/null \
   && [[ "${FORCE:-0}" != "1" ]]; then
  echo "==> Core analysis stack already installed — skipping pip install."
  echo "    (Reinstall with:  FORCE=1 bash 00_setup_env.sh)"
else
  echo "==> Upgrading pip / setuptools / wheel..."
  python -m pip install --upgrade pip setuptools wheel
  echo "==> Installing scanpy and core dependencies (this can take a few minutes)..."
  python -m pip install \
    scanpy anndata leidenalg python-igraph umap-learn \
    matplotlib pandas numpy scipy
fi

echo ""
echo "==> Installed versions:"
python - <<'PY'
import importlib.metadata as md, sys
print(f"  python   {sys.version.split()[0]}")
for p in ["scanpy", "anndata", "leidenalg", "umap-learn", "matplotlib", "pandas", "numpy", "scipy"]:
    try:
        print(f"  {p:<12} {md.version(p)}")
    except md.PackageNotFoundError:
        pass
PY

echo ""
echo "==> [00] Done. Next: 1. Download melanoma matrix (GSE72056)."
