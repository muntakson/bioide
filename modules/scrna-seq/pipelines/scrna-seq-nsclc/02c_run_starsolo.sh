#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 02c_run_starsolo.sh
# Run STARsolo on the downloaded 10x FASTQs -> gene-barcode count matrix.
# 다운로드한 10x FASTQ에 STARsolo를 실행해 유전자 x 세포 카운트 행렬을 만듭니다.
#
# Handles 10x chemistry correctly:
#   * v3: CB length 16, UMI length 12, whitelist 3M-february-2018.txt
#   * v2: CB length 16, UMI length 10, whitelist 737K-august-2016.txt
# CHEMISTRY="auto" 는 재구성한 R1 길이에서 자동 판별합니다 (R1 = 16bp CB + UMI).
# =============================================================================

# ---- Configuration ----------------------------------------------------------
CHEMISTRY="auto"                                  # "auto" | "v3" | "v2"

TUT="${HOME}/ghbio-tutorial"
STAR_BIN="${HOME}/bin/STAR"
INDEX_DIR="${TUT}/ref/star_index"
# FASTQ reconstructed from the 10x BAM by 01_download_nsclc.sh.
FASTQ_DIR="${TUT}/data/fastq/nsclc_p1_tumor"
WL_DIR="${TUT}/ref/whitelist"
# Results are first-class project files. GHBIO_RESULTS is injected by the extension and
# points at the project (~/ghbio-workspace/projects/<tutorial>/results). Falls back to the
# legacy path (a symlink to the project) for manual runs.
RESULTS="${GHBIO_RESULTS:-${TUT}/results}"
OUT_DIR="${RESULTS}/starsolo"

mkdir -p "${WL_DIR}" "${OUT_DIR}"

echo "==> [02c] Running STARsolo"

# --- 0z. Guard: refuse to run while step 1 (download/BAM→FASTQ) is still going ---
# The conversion holds this lock for its whole run; if we can't grab it, the FASTQs are still being
# written (truncated) — fail fast with a clear message instead of crashing STARsolo mid-map.
LOCK_FILE="${HOME}/ghbio-tutorial/data/fastq/.nsclc_download.lock"
if [[ -e "${LOCK_FILE}" ]] && ! flock -n "${LOCK_FILE}" true 2>/dev/null; then
  echo "ERROR: 1단계(다운로드/FASTQ 변환)가 아직 진행 중입니다. 끝난 뒤 다시 실행하세요." >&2
  echo "       Step 1 (download / BAM→FASTQ conversion) is still running; wait for it to finish, then re-run 2c." >&2
  exit 1
fi

# --- 0a. Auto-detect chemistry from the reconstructed R1 length ---------------
# R1 = 16 bp cell barcode + UMI. UMI 12 → v3, UMI 10 → v2.
if [[ "${CHEMISTRY}" == "auto" ]]; then
  R1F="$(ls "${FASTQ_DIR}"/*_R1_*.fastq.gz 2>/dev/null | head -1)"
  [[ -n "${R1F}" ]] || { echo "ERROR: no R1 FASTQ in ${FASTQ_DIR} (run step 1 first)." >&2; exit 1; }
  # Read ONLY the first read's sequence (awk exits at line 2). The `|| true` swallows zcat's SIGPIPE
  # so `set -o pipefail` doesn't abort, and we never decompress the whole (multi-GB) file.
  R1LEN="$( { zcat "${R1F}" 2>/dev/null || true; } | awk 'NR==2{print length($0); exit}')"
  [[ -n "${R1LEN}" && "${R1LEN}" -ge 24 ]] || { echo "ERROR: could not read R1 length (FASTQ incomplete? re-run step 1)." >&2; exit 1; }
  if [[ "${R1LEN}" -ge 28 ]]; then CHEMISTRY="v3"; else CHEMISTRY="v2"; fi
  echo "==> Auto-detected chemistry: ${CHEMISTRY}  (R1 ${R1LEN} bp = CB 16 + UMI $((R1LEN-16)))"
fi

# --- 0. Preconditions ---------------------------------------------------------
if [[ ! -x "${STAR_BIN}" ]]; then
  echo "ERROR: STAR not found at ${STAR_BIN}. Run 02a first." >&2; exit 1
fi
if [[ ! -f "${INDEX_DIR}/SAindex" ]]; then
  echo "ERROR: STAR index not found in ${INDEX_DIR}. Run 02b first." >&2; exit 1
fi

# --- 0b. Idempotency: skip if the count matrix already exists -----------------
# 이미 count matrix가 있으면 재정렬(10~30분)을 건너뜁니다. 다시 하려면 FORCE=1.
FILTERED_MTX="${OUT_DIR}/Solo.out/Gene/filtered/matrix.mtx"
if [[ -f "${FILTERED_MTX}" && "${FORCE:-0}" != "1" ]]; then
  echo "==> Count matrix already exists — skipping STARsolo (no re-alignment)."
  echo "    ${FILTERED_MTX}"
  echo "    Re-run from scratch with:  FORCE=1 bash 02c_run_starsolo.sh"
  echo "==> [02c] Done (reused)."
  exit 0
fi

# --- 1. Chemistry-specific parameters + whitelist ----------------------------
# chemistry에 따라 CB/UMI 길이와 whitelist 파일을 선택합니다.
if [[ "${CHEMISTRY}" == "v3" ]]; then
  CB_LEN=16
  UMI_LEN=12
  WL_FILE="${WL_DIR}/3M-february-2018.txt"
  # Primary: Teichlab scg_lib_structs (stable, well-known single-cell library
  # structure reference). Mirror: 10x cellranger repo (path changes over time).
  WL_PRIMARY="https://teichlab.github.io/scg_lib_structs/data/10X-Genomics/3M-february-2018.txt.gz"
  WL_MIRROR="https://github.com/10XGenomics/cellranger/raw/master/lib/python/cellranger/barcodes/3M-february-2018.txt.gz"
  WL_IS_GZ=1
elif [[ "${CHEMISTRY}" == "v2" ]]; then
  CB_LEN=16
  UMI_LEN=10
  WL_FILE="${WL_DIR}/737K-august-2016.txt"
  # Teichlab scg_lib_structs hosts the gzipped whitelist; the old 10x cellranger repo path 404s now.
  WL_PRIMARY="https://teichlab.github.io/scg_lib_structs/data/10X-Genomics/737K-august-2016.txt.gz"
  WL_MIRROR=""
  WL_IS_GZ=1
else
  echo "ERROR: unknown CHEMISTRY='${CHEMISTRY}' (use 'v3' or 'v2')." >&2; exit 1
fi

# --- 2. Download the barcode whitelist (idempotent, with fallback) -----------
# 바코드 whitelist 다운로드 (이미 있으면 건너뜀, 미러 fallback 포함).
if [[ ! -f "${WL_FILE}" ]]; then
  echo "==> Downloading ${CHEMISTRY} barcode whitelist..."
  TMP="${WL_FILE}.download"
  if [[ "${WL_IS_GZ}" -eq 1 ]]; then
    TMP="${TMP}.gz"
    if ! curl -L -C - -f -o "${TMP}" "${WL_PRIMARY}"; then
      echo "==> Primary source failed, trying mirror..."
      curl -L -C - -f -o "${TMP}" "${WL_MIRROR}"
    fi
    echo "==> Decompressing whitelist..."
    gunzip -c "${TMP}" > "${WL_FILE}"
    rm -f "${TMP}"
  else
    curl -L -C - -f -o "${WL_FILE}" "${WL_PRIMARY}"
  fi
else
  echo "==> Whitelist already present: ${WL_FILE}"
fi
echo "==> Whitelist barcode count: $(wc -l < "${WL_FILE}")"

# --- 3. Assemble comma-separated R1 and R2 file lists ------------------------
# STARsolo expects: --readFilesIn <cDNA=R2 list> <barcode=R1 list>
# (즉 R2가 먼저, R1이 나중입니다. lane별 파일을 콤마로 연결합니다.)
R1_LIST="$(ls "${FASTQ_DIR}"/*_R1_*.fastq.gz | sort | paste -sd, -)"
R2_LIST="$(ls "${FASTQ_DIR}"/*_R2_*.fastq.gz | sort | paste -sd, -)"

if [[ -z "${R1_LIST}" || -z "${R2_LIST}" ]]; then
  echo "ERROR: Could not find R1/R2 FASTQ files in ${FASTQ_DIR}." >&2; exit 1
fi
echo "==> R1 (barcode+UMI): ${R1_LIST}"
echo "==> R2 (cDNA):        ${R2_LIST}"

THREADS="$(nproc)"

# --- 4. Run STARsolo ----------------------------------------------------------
# Key options / 주요 옵션:
#   --soloType CB_UMI_Simple : standard 10x droplet layout (one CB + one UMI in R1)
#   --soloCBwhitelist        : the barcode whitelist we just downloaded
#   --soloCBstart/CBlen/UMIstart/UMIlen : 10x layout (CB then UMI in R1)
#   --soloFeatures Gene      : produce a gene x cell matrix
#   --soloCellFilter EmptyDrops_CR : Cell Ranger-like cell calling (filtered matrix)
#   --readFilesCommand zcat  : inputs are gzipped
#   STARsolo writes BOTH a 'raw' (all barcodes) and 'filtered' (real cells) matrix.
echo ""
echo "==> Launching STARsolo with ${THREADS} threads..."
cd "${OUT_DIR}"

# STAR refuses to start if a leftover temp dir from an interrupted run exists.
# 중단된 이전 실행이 남긴 임시 디렉터리를 제거합니다(있으면 STAR가 실패함).
rm -rf "${OUT_DIR}/_STARtmp"

# STARsolo is SILENT during the mapping phase — it can map for many minutes printing
# nothing after "started mapping", which looks like a hang. Run it in the background and
# print a heartbeat so the terminal always shows it is alive.
# STARsolo는 매핑 중에는 화면 출력이 거의 없습니다(정상). 아래 ⏳ 표시로 살아있음을 알립니다.
echo "==> 참고: STAR는 매핑 중에는 메시지를 거의 출력하지 않습니다. 아래 ⏳ 표시가 보이면 정상 작동 중이며 멈춘 것이 아닙니다. (대용량은 수십 분 걸릴 수 있어요.)"
"${STAR_BIN}" \
  --runMode alignReads \
  --runThreadN "${THREADS}" \
  --genomeDir "${INDEX_DIR}" \
  --readFilesIn "${R2_LIST}" "${R1_LIST}" \
  --readFilesCommand zcat \
  --soloType CB_UMI_Simple \
  --soloCBwhitelist "${WL_FILE}" \
  --soloCBstart 1 --soloCBlen "${CB_LEN}" \
  --soloUMIstart $((CB_LEN + 1)) --soloUMIlen "${UMI_LEN}" \
  --soloFeatures Gene \
  --soloCellFilter EmptyDrops_CR \
  --outSAMtype BAM Unsorted \
  --outFileNamePrefix "${OUT_DIR}/" &
STAR_PID=$!

# Heartbeat: while STAR runs, print an elapsed-time line every 20s, plus STAR's own
# latest progress row from Log.progress.out once it starts writing it.
SECS=0
while kill -0 "${STAR_PID}" 2>/dev/null; do
  sleep 20
  SECS=$((SECS + 20))
  PROG=""
  if [[ -f "${OUT_DIR}/Log.progress.out" ]]; then
    PROG="| STAR: $(tail -n 1 "${OUT_DIR}/Log.progress.out" 2>/dev/null | tr -s ' \t' ' ')"
  fi
  printf "\033[1;33m  ⏳ 매핑 진행 중… 경과 %dm%02ds — 정상입니다, 기다려 주세요.\033[0m %s\n" \
    $((SECS / 60)) $((SECS % 60)) "${PROG}"
done

# set -e cannot observe a backgrounded process, so surface STAR's real exit code here.
if wait "${STAR_PID}"; then
  echo "==> STAR 매핑 완료."
else
  STAR_RC=$?
  echo "ERROR: STAR가 종료 코드 ${STAR_RC}로 멈췄습니다. 위 로그를 확인하세요." >&2
  exit "${STAR_RC}"
fi

# --- 5. Explain the output ----------------------------------------------------
cat <<EOF

------------------------------------------------------------------------------
STARsolo output  /  STARsolo 출력물
------------------------------------------------------------------------------
Main result directory:
    ${OUT_DIR}/Solo.out/Gene/

  Solo.out/Gene/Summary.csv     : mapping + cell-calling summary stats
  Solo.out/Gene/raw/            : ALL barcodes (mostly empty droplets)
  Solo.out/Gene/filtered/       : only barcodes called as real cells  <-- use this

The 'filtered/' matrix is what Scanpy loads. It contains 3 files (10x MEX format):
  matrix.mtx      : sparse gene x cell count matrix (MatrixMarket format)
                    -> 값 = 각 세포에서 각 유전자의 UMI 카운트
  barcodes.tsv    : one cell barcode per column of the matrix (세포 = 열)
  features.tsv    : one gene per row (gene_id, gene_name, "Gene Expression") (유전자 = 행)

Step 3 (03_scanpy_qc.py) reads:
    ${OUT_DIR}/Solo.out/Gene/filtered/
via scanpy.read_10x_mtx().
------------------------------------------------------------------------------
EOF

echo "==> [02c] Done. Filtered matrix: ${OUT_DIR}/Solo.out/Gene/filtered/"
