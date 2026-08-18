#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 00_setup_env.sh  (H1299-P3 PD-1 내성 폐암 독립재현)
# Reuse the shared virtual environment (~/ghbio-venv) used by the other BioIDE
# pipelines. This bulk RNA-seq reproduction starts from an already-labeled count
# matrix (Excel), so it needs only a core stats/plotting stack — no aligner, no
# scanpy. Everything runs on CPU; no internet is required after setup.
# 이 예제는 이미 라벨된 count matrix(xlsx)에서 시작하므로 통계·시각화 스택만 있으면 됩니다.
#
# Idempotent: if the stack already imports, we skip pip entirely. FORCE=1 reinstalls.
# =============================================================================

VENV="${HOME}/ghbio-venv"
echo "==> [00] Python stats stack for the H1299-P3 (PD-1 내성) reproduction: ${VENV}"

if [[ ! -d "${VENV}" ]]; then
  echo "==> Creating virtualenv..."
  python3 -m venv "${VENV}"
else
  echo "==> Virtualenv already exists, reusing it."
fi

# shellcheck disable=SC1091
source "${VENV}/bin/activate"

# openpyxl is required to read the vendor's .xlsx isoform report; the rest are the
# usual numeric/plotting stack shared with the scRNA-seq pipelines.
if python -c "import pandas, numpy, scipy, statsmodels, matplotlib, openpyxl" 2>/dev/null \
   && [[ "${FORCE:-0}" != "1" ]]; then
  echo "==> Core analysis stack already installed — skipping pip install."
  echo "    (Reinstall with:  FORCE=1 bash 00_setup_env.sh)"
else
  echo "==> Upgrading pip / setuptools / wheel..."
  python -m pip install --upgrade pip setuptools wheel
  echo "==> Installing core dependencies..."
  python -m pip install \
    pandas numpy scipy statsmodels matplotlib openpyxl
fi

echo ""
echo "==> Installed versions:"
python - <<'PY'
import importlib.metadata as md, sys
print(f"  python   {sys.version.split()[0]}")
for p in ["pandas", "numpy", "scipy", "statsmodels", "matplotlib", "openpyxl"]:
    try:
        print(f"  {p:<12} {md.version(p)}")
    except md.PackageNotFoundError:
        pass
PY

echo ""
echo "==> [00] Done. Next: 1. Count matrix 준비 (isoform→gene)."
