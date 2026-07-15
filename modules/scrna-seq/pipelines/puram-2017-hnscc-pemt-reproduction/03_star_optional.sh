#!/usr/bin/env bash
set -euo pipefail

# 03_star_optional.sh
# 단계 [star_optional]: Optional STARsolo alignment (conditional)
# SRA/GEO에 raw(FASTQ 또는 BAM)가 존재하면 aarch64 소스 컴파일 STAR로 정렬·정량.
# raw가 없으면(GSE103322는 처리 행렬만 공개) 자동 스킵하되,
# 하류 단계 계약(matrix/matrix.mtx)을 만족하도록 skip 마커 mtx를 남긴다.

RESULTS="${GHBIO_RESULTS:-${HOME}/ghbio-tutorial/results}"
SHARED="${HOME}/ghbio-tutorial"
STAR_BIN="${HOME}/bin/STAR"
PYTHON="${HOME}/ghbio-venv/bin/python"

MATRIX_DIR="${RESULTS}/matrix"
FASTQ_DIR="${SHARED}/fastq"
INDEX_DIR="${SHARED}/refs/GRCh38_star_index"   # TODO: 확인 필요 (공유 GRCh38 STAR 인덱스 경로)
AVAIL_JSON="${RESULTS}/data_availability.json"
LOCK_DIR="${RESULTS}/.locks"

mkdir -p "${MATRIX_DIR}" "${FASTQ_DIR}" "${LOCK_DIR}"

MTX_OUT="${MATRIX_DIR}/matrix.mtx"

# ---------------------------------------------------------------------------
# 0) 이미 완료된 경우 스킵 (idempotent)
# ---------------------------------------------------------------------------
if [[ -s "${MTX_OUT}" ]]; then
  echo "[star_optional] matrix.mtx 이미 존재 -> 스킵: ${MTX_OUT}"
  exit 0
fi

# ---------------------------------------------------------------------------
# 스킵 마커 mtx 생성 헬퍼 (raw 부재 시 하류 계약 충족용 빈 placeholder)
# ---------------------------------------------------------------------------
write_skip_matrix() {
  local reason="$1"
  echo "[star_optional] STARsolo 경로 비활성: ${reason}"
  echo "[star_optional] 하류 단계 계약을 위해 placeholder matrix.mtx 작성 (SKIPPED 마커)"
  cat > "${MTX_OUT}" <<'EOF'
%%MatrixMarket matrix coordinate integer general
%%STAR_OPTIONAL_SKIPPED: no raw FASTQ/BAM available; processed matrix path is authoritative.
0 0 0
EOF
  # barcodes/features placeholder도 남겨 read_mtx 계열 도구 호환성 확보
  : > "${MATRIX_DIR}/barcodes.tsv"
  : > "${MATRIX_DIR}/features.tsv"
  echo "SKIPPED: ${reason}" > "${MATRIX_DIR}/STAR_STATUS.txt"
  echo "[star_optional] 완료(스킵): ${MTX_OUT}"
}

# ---------------------------------------------------------------------------
# 1) 데이터 가용성 확인 (01_check_availability.sh 산출물 우선 참조)
# ---------------------------------------------------------------------------
RAW_AVAILABLE="no"
RAW_KIND="none"   # fastq | bam | none

if [[ -f "${AVAIL_JSON}" ]] && command -v "${PYTHON}" >/dev/null 2>&1; then
  echo "[star_optional] ${AVAIL_JSON} 파싱하여 raw 유무 확인"
  set +e
  READ=$("${PYTHON}" - "${AVAIL_JSON}" <<'PYEOF'
import json, sys
try:
    with open(sys.argv[1]) as f:
        d = json.load(f)
except Exception:
    print("no none")
    sys.exit(0)

def truthy(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("yes", "true", "1", "available", "present")
    if isinstance(v, (int, float)):
        return v > 0
    return False

# 여러 가능한 키를 관용적으로 조회
raw_avail = False
for k in ("raw_available", "sra_raw", "has_raw", "raw_present"):
    if k in d and truthy(d[k]):
        raw_avail = True
        break

kind = "none"
for k in ("raw_kind", "raw_type", "start_path"):
    if k in d and isinstance(d[k], str):
        v = d[k].strip().lower()
        if "fastq" in v:
            kind = "fastq"; raw_avail = True
        elif "bam" in v:
            kind = "bam"; raw_avail = True

if raw_avail and kind == "none":
    kind = "fastq"  # raw 있다고만 표기된 경우 기본 fastq 가정

print(("yes" if raw_avail else "no"), kind)
PYEOF
)
  set -e
  RAW_AVAILABLE="$(echo "${READ}" | awk '{print $1}')"
  RAW_KIND="$(echo "${READ}" | awk '{print $2}')"
else
  echo "[star_optional] ${AVAIL_JSON} 없음 -> raw 부재로 간주"
fi

echo "[star_optional] raw_available=${RAW_AVAILABLE}, raw_kind=${RAW_KIND}"

if [[ "${RAW_AVAILABLE}" != "yes" ]]; then
  write_skip_matrix "SRA/GEO에 raw run 없음 (GSE103322는 처리 TPM 행렬만 공개)"
  exit 0
fi

# ---------------------------------------------------------------------------
# 2) STAR 바이너리 확인 (aarch64 소스 컴파일)
# ---------------------------------------------------------------------------
if [[ ! -x "${STAR_BIN}" ]]; then
  write_skip_matrix "STAR 바이너리 부재(${STAR_BIN}) - 00_setup_env.sh에서 컴파일 필요"
  exit 0
fi
if [[ ! -d "${INDEX_DIR}" ]]; then
  write_skip_matrix "GRCh38 STAR 인덱스 부재(${INDEX_DIR})"
  exit 0
fi

# ---------------------------------------------------------------------------
# 3) BAM만 있으면 pysam/samtools로 FASTQ 복원 (조건부)
# ---------------------------------------------------------------------------
if [[ "${RAW_KIND}" == "bam" ]]; then
  BAM_DIR="${SHARED}/bam"
  echo "[star_optional] BAM->FASTQ 복원 경로 (raw_kind=bam)"
  if ! ls "${BAM_DIR}"/*.bam >/dev/null 2>&1; then
    write_skip_matrix "raw_kind=bam이지만 ${BAM_DIR}/*.bam 없음"
    exit 0
  fi
  (
    flock -n 9 || { echo "[star_optional] BAM 변환 lock 획득 실패 - 다른 실행 진행 중"; exit 0; }
    for bam in "${BAM_DIR}"/*.bam; do
      base="$(basename "${bam}" .bam)"
      r1="${FASTQ_DIR}/${base}_R1.fastq.gz"
      r2="${FASTQ_DIR}/${base}_R2.fastq.gz"
      if [[ -s "${r1}" && -s "${r2}" ]]; then
        echo "[star_optional] ${base} FASTQ 이미 복원됨 -> 스킵"
        continue
      fi
      echo "[star_optional] samtools collate + fastq: ${base}"
      # TODO: 확인 필요 (paired-end 가정; single-end이면 -1만 사용)
      samtools collate -@ 4 -u -O "${bam}" \
        | samtools fastq -@ 4 -1 "${r1}" -2 "${r2}" -0 /dev/null -s /dev/null -n
    done
  ) 9>"${LOCK_DIR}/bam2fastq.lock"
fi

# ---------------------------------------------------------------------------
# 4) FASTQ 수집
# ---------------------------------------------------------------------------
shopt -s nullglob
R1_FILES=( "${FASTQ_DIR}"/*_R1*.fastq.gz "${FASTQ_DIR}"/*_1.fastq.gz )
R2_FILES=( "${FASTQ_DIR}"/*_R2*.fastq.gz "${FASTQ_DIR}"/*_2.fastq.gz )
shopt -u nullglob

if [[ ${#R1_FILES[@]} -eq 0 ]]; then
  write_skip_matrix "정렬할 FASTQ 파일을 ${FASTQ_DIR}에서 찾지 못함"
  exit 0
fi

R1_CSV="$(IFS=,; echo "${R1_FILES[*]}")"
R2_CSV="$(IFS=,; echo "${R2_FILES[*]}")"

# ---------------------------------------------------------------------------
# 5) STARsolo 정렬·정량 실행 (lock으로 중복 방지)
# ---------------------------------------------------------------------------
STAR_OUT="${RESULTS}/star_out"
mkdir -p "${STAR_OUT}"

(
  flock -n 9 || { echo "[star_optional] STAR lock 획득 실패 - 다른 실행 진행 중"; exit 0; }

  echo "[star_optional] STARsolo 실행 시작"
  # GSE103322는 Smart-seq2(full-length, UMI 없음)이므로 SmartSeq 모드 사용.
  # TODO: 확인 필요 (스레드 수, --soloUMIdedup, readFilesManifest 사용 여부 등 데이터에 맞춰 조정)
  "${STAR_BIN}" \
    --runMode alignReads \
    --runThreadN 8 \
    --genomeDir "${INDEX_DIR}" \
    --readFilesIn "${R1_CSV}" "${R2_CSV}" \
    --readFilesCommand zcat \
    --soloType SmartSeq \
    --soloUMIdedup Exact \
    --soloStrand Unstranded \
    --outSAMtype BAM Unsorted \
    --outFileNamePrefix "${STAR_OUT}/" \
    --outTmpDir "${STAR_OUT}/_tmp"

  echo "[star_optional] STARsolo 완료 - 출력 정리"
) 9>"${LOCK_DIR}/star_align.lock"

# ---------------------------------------------------------------------------
# 6) STARsolo 출력 mtx를 계약 경로로 배치
# ---------------------------------------------------------------------------
# STARsolo Solo.out 기본 위치 (Gene/filtered 우선, 없으면 raw)
SOLO_MTX=""
for cand in \
  "${STAR_OUT}/Solo.out/Gene/filtered/matrix.mtx" \
  "${STAR_OUT}/Solo.out/Gene/raw/matrix.mtx" \
  "${STAR_OUT}/Solo.out/Gene/filtered/matrix.mtx.gz" \
  "${STAR_OUT}/Solo.out/Gene/raw/matrix.mtx.gz"; do
  if [[ -s "${cand}" ]]; then
    SOLO_MTX="${cand}"
    break
  fi
done

if [[ -z "${SOLO_MTX}" ]]; then
  write_skip_matrix "STARsolo 실행 후 Solo.out matrix.mtx를 찾지 못함"
  exit 0
fi

SOLO_DIR="$(dirname "${SOLO_MTX}")"
echo "[star_optional] Solo 출력 발견: ${SOLO_DIR}"
for f in matrix.mtx barcodes.tsv features.tsv; do
  src="${SOLO_DIR}/${f}"
  if [[ -s "${src}.gz" && ! -s "${src}" ]]; then
    gunzip -c "${src}.gz" > "${MATRIX_DIR}/${f}"
  elif [[ -s "${src}" ]]; then
    cp -f "${src}" "${MATRIX_DIR}/${f}"
  fi
done

echo "DONE: STARsolo aligned via ${STAR_BIN}" > "${MATRIX_DIR}/STAR_STATUS.txt"

if [[ ! -s "${MTX_OUT}" ]]; then
  write_skip_matrix "Solo mtx 복사 실패"
  exit 0
fi

echo "[star_optional] 완료: ${MTX_OUT}"
