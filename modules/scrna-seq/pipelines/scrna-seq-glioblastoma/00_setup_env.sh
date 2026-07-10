#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 00_setup_env.sh
# Create a Python virtual environment and install the Scanpy analysis stack.
# Scanpy 분석에 필요한 파이썬 가상환경을 만들고 라이브러리를 설치합니다.
#
# Idempotent: re-running only upgrades/installs what is missing.
# 멱등성: 다시 실행해도 안전합니다 (누락된 것만 설치).
# =============================================================================

VENV="${HOME}/ghbio-venv"

echo "==> [00] Setting up Python virtual environment at: ${VENV}"

# --- 1. Create the venv if it does not already exist -------------------------
# 가상환경이 없으면 생성합니다.
if [[ ! -d "${VENV}" ]]; then
  echo "==> Creating virtualenv..."
  python3 -m venv "${VENV}"
else
  echo "==> Virtualenv already exists, reusing it."
fi

# shellcheck disable=SC1091
source "${VENV}/bin/activate"

# --- 2 & 3. Install the analysis stack (idempotent) --------------------------
# scanpy/anndata/leidenalg/igraph/umap-learn/matplotlib/pandas/numpy/scipy/harmonypy.
# If everything already imports, we SKIP the install entirely so re-clicking the
# tutorial button is instant and never re-downloads/rebuilds packages. FORCE=1 reinstalls.
# 모든 패키지가 import 되면 설치를 건너뜁니다(재실행 시 즉시 완료). 재설치는 FORCE=1.
if python -c "import scanpy, anndata, leidenalg, igraph, umap, matplotlib, pandas, numpy, scipy, harmonypy" 2>/dev/null \
   && [[ "${FORCE:-0}" != "1" ]]; then
  echo "==> Core analysis stack already installed — skipping pip install."
  echo "    (Reinstall with:  FORCE=1 bash 00_setup_env.sh)"
else
  echo "==> Upgrading pip / setuptools / wheel..."
  python -m pip install --upgrade pip setuptools wheel
  echo "==> Installing scanpy and core dependencies (this can take a few minutes)..."
  python -m pip install \
    scanpy \
    anndata \
    leidenalg \
    python-igraph \
    umap-learn \
    matplotlib \
    pandas \
    numpy \
    scipy \
    harmonypy
fi

# scikit-misc is OPTIONAL (only for highly_variable_genes(flavor="seurat_v3")). It has
# no aarch64 wheel, so pip builds from source, which needs python3-dev (apt/sudo). We try
# it ONCE and record the outcome in a sentinel, so a known-failing build is never retried
# on subsequent runs. The QC script uses flavor="seurat", which does NOT need it.
# scikit-misc는 선택 사항입니다. 소스 빌드에 python3-dev가 필요해, 한 번 시도 후 실패하면
# sentinel 파일에 기록하여 다음 실행부터는 재시도하지 않습니다.
SKM_SENTINEL="${VENV}/.scikit_misc_skipped"
if python -c "import skmisc" 2>/dev/null; then
  echo "==> scikit-misc already installed."
elif [[ -f "${SKM_SENTINEL}" ]]; then
  echo "==> scikit-misc previously unavailable (optional) — not retrying. (rm ${SKM_SENTINEL} to retry)"
else
  echo "==> (optional) Trying scikit-misc — best-effort, safe to skip..."
  if python -m pip install scikit-misc; then
    echo "==> scikit-misc installed."
  else
    touch "${SKM_SENTINEL}"
    echo "==> NOTE: scikit-misc could not be built (needs python3-dev). Skipping — this is fine."
    echo "    The tutorial uses highly_variable_genes(flavor='seurat'), which does not need it."
  fi
fi

# --- 4. Print versions for reproducibility -----------------------------------
# 설치된 버전 출력 (재현성 확인용).
echo ""
echo "==> Installed package versions:"
python - <<'PY'
import importlib.metadata as md

# igraph is imported as "igraph" but distributed as "python-igraph".
packages = [
    "scanpy", "anndata", "leidenalg", "igraph", "python-igraph",
    "umap-learn", "scikit-misc", "matplotlib", "pandas", "numpy",
    "scipy", "harmonypy",
]
import sys
print(f"  python           {sys.version.split()[0]}")
for p in packages:
    try:
        print(f"  {p:<16} {md.version(p)}")
    except md.PackageNotFoundError:
        pass  # e.g. 'igraph' vs 'python-igraph' — only one will resolve
PY

echo ""
echo "==> [00] Done. Activate the environment with:"
echo "        source ${VENV}/bin/activate"
