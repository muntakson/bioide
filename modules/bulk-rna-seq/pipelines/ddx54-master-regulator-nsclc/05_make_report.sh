#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 05_make_report.sh  (DDX54 면역회피 마스터조절자 — LLC1 Ddx54-KD 독립재현)
# Assemble the DE / GSEA / independent-reproduction verdict + figures (+ any saved
# AI drafts) into ONE branded GHBIO PDF via wkhtmltopdf.
#   • Always builds the main report:  <results>/GHBIO_ddx54_report.pdf
#   • If the high-school AI draft (step4_ai_report_easy.md) exists, ALSO builds
#     <results>/GHBIO_고등학생_리포트.pdf  (the ai.easyReport filename contract).
# Builds from figures alone; AI sections fold in only when present.
# Requires: wkhtmltopdf, venv python (~/ghbio-venv).
# =============================================================================

RESULTS="${GHBIO_RESULTS:-${HOME}/ghbio-tutorial/results}"
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${HOME}/ghbio-venv/bin/python"

echo "==> [05] Building DDX54-KD reproduction report PDF  (results: $RESULTS)"
command -v wkhtmltopdf >/dev/null 2>&1 || { echo "ERROR: 'wkhtmltopdf' not found." >&2; exit 1; }
[[ -x "$PY" ]] || { echo "ERROR: venv python not found at $PY (run 00_setup_env.sh)." >&2; exit 1; }
for f in validation_verdict.txt validation_bars.png; do
  [[ -f "${RESULTS}/${f}" ]] || { echo "ERROR: missing ${RESULTS}/${f} (run step 4 first)." >&2; exit 1; }
done

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
WK_OPTS=(--enable-local-file-access --quiet --encoding utf-8 \
         --margin-top 14 --margin-bottom 14 --margin-left 12 --margin-right 12)

# --- main report ---
MAIN="${RESULTS}/GHBIO_ddx54_report.pdf"
"$PY" "$HERE/_build_report.py" "$RESULTS" "$TMP/report.html"
wkhtmltopdf "${WK_OPTS[@]}" "$TMP/report.html" "$MAIN"
echo "==> wrote $MAIN"

# --- easy (high-school) report — only when the AI draft exists ---
if [[ -f "${RESULTS}/step4_ai_report_easy.md" ]]; then
  EASY="${RESULTS}/GHBIO_고등학생_리포트.pdf"
  "$PY" "$HERE/_build_report.py" "$RESULTS" "$TMP/easy.html" --easy
  wkhtmltopdf "${WK_OPTS[@]}" "$TMP/easy.html" "$EASY"
  echo "==> wrote $EASY"
fi

echo "==> [05] Done."
