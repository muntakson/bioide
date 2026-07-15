#!/usr/bin/env bash
set -euo pipefail

# 00_setup_env.sh
# 단계 [env]: aarch64 Python/GPU 환경 구성
# - ~/ghbio-venv 가상환경 생성
# - Scanpy·AnnData·scVI·rapids-singlecell·inferCNVpy·cNMF·pysradb 설치
# - STAR aarch64 소스 컴파일 준비
# 재실행 안전(idempotent). 모든 로그/산출물은 $GHBIO_RESULTS 아래에 기록.

# ---------------------------------------------------------------------------
# 경로 설정
# ---------------------------------------------------------------------------
GHBIO_RESULTS="${GHBIO_RESULTS:-${HOME}/ghbio-tutorial/results}"
GHBIO_HOME="${HOME}/ghbio-tutorial"
VENV_DIR="${HOME}/ghbio-venv"
PYBIN="${VENV_DIR}/bin/python"

# 공용 입력(FASTQ, index, STAR 소스)은 ~/ghbio-tutorial 아래에서 재사용
SHARED_DIR="${GHBIO_HOME}"
STAR_SRC_DIR="${SHARED_DIR}/tools/STAR-src"
STAR_BIN_DIR="${HOME}/bin"
STAR_BIN="${STAR_BIN_DIR}/STAR"

LOG_DIR="${GHBIO_RESULTS}/logs"
LOCK_DIR="${GHBIO_RESULTS}/.locks"

mkdir -p "${GHBIO_RESULTS}" "${LOG_DIR}" "${LOCK_DIR}" \
         "${SHARED_DIR}/tools" "${STAR_BIN_DIR}"

SETUP_LOG="${LOG_DIR}/00_setup_env.log"
STAMP_DIR="${GHBIO_RESULTS}/.stamps"
mkdir -p "${STAMP_DIR}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "${SETUP_LOG}"; }

log "=== 00_setup_env.sh 시작 ==="
log "GHBIO_RESULTS=${GHBIO_RESULTS}"
log "VENV_DIR=${VENV_DIR}"

# ---------------------------------------------------------------------------
# 아키텍처 확인 (aarch64 기대)
# ---------------------------------------------------------------------------
ARCH="$(uname -m)"
log "감지된 아키텍처: ${ARCH}"
if [[ "${ARCH}" != "aarch64" && "${ARCH}" != "arm64" ]]; then
  log "경고: aarch64가 아닙니다(${ARCH}). 계속 진행하지만 GPU/컴파일 옵션을 확인하세요."
fi

# ---------------------------------------------------------------------------
# 1) Python 가상환경 생성 (idempotent)
# ---------------------------------------------------------------------------
if [[ -x "${PYBIN}" ]]; then
  log "가상환경이 이미 존재합니다: ${VENV_DIR} (재생성 건너뜀)"
else
  log "가상환경 생성 중: ${VENV_DIR}"
  # 시스템 python3 사용
  PY_SYS="$(command -v python3.11 || command -v python3)"
  log "사용 시스템 파이썬: ${PY_SYS}"
  "${PY_SYS}" -m venv "${VENV_DIR}"
fi

log "pip/setuptools/wheel 업그레이드"
"${PYBIN}" -m pip install --upgrade pip setuptools wheel >>"${SETUP_LOG}" 2>&1

# ---------------------------------------------------------------------------
# 2) 핵심 파이썬 패키지 설치 (idempotent: 이미 설치되면 pip가 스킵)
# ---------------------------------------------------------------------------
PKG_STAMP="${STAMP_DIR}/pip_core.done"
if [[ -f "${PKG_STAMP}" ]]; then
  log "핵심 파이썬 패키지 설치 완료 스탬프 존재 — 건너뜀 (${PKG_STAMP})"
else
  log "핵심 CPU 패키지 설치 중 (scanpy/anndata/pysradb/infercnvpy/cnmf ...)"
  # 버전 핀은 재현성을 위해 상한을 완만히 지정. 필요시 조정.
  "${PYBIN}" -m pip install \
    "numpy<2.0" \
    "scipy" \
    "pandas" \
    "scikit-learn" \
    "matplotlib" \
    "h5py" \
    "anndata>=0.10" \
    "scanpy>=1.10" \
    "leidenalg" \
    "igraph" \
    "pysam" \
    "pysradb>=2.0" \
    "infercnvpy>=0.4" \
    "cnmf>=1.5" \
    "pyyaml" \
    "jinja2" \
    >>"${SETUP_LOG}" 2>&1

  # scVI (scvi-tools): PyTorch 의존. aarch64에서는 기본 인덱스의 CPU/ARM 휠 사용.
  log "PyTorch + scvi-tools 설치 중 (aarch64 기본 휠)"
  # TODO: 확인 필요 — aarch64 GPU(CUDA arm64/Jetson) 환경이면 아래 index-url을 조정
  "${PYBIN}" -m pip install "torch" >>"${SETUP_LOG}" 2>&1
  "${PYBIN}" -m pip install "scvi-tools>=1.1" >>"${SETUP_LOG}" 2>&1

  touch "${PKG_STAMP}"
  log "핵심 파이썬 패키지 설치 완료"
fi

# ---------------------------------------------------------------------------
# 3) rapids-singlecell (GPU) — 조건부 설치
#    RAPIDS는 aarch64 GPU(CUDA)에서만 의미. GPU 미탐지 시 스킵하고 CPU 폴백 안내.
# ---------------------------------------------------------------------------
RAPIDS_STAMP="${STAMP_DIR}/pip_rapids.done"
HAS_GPU="no"
if command -v nvidia-smi >/dev/null 2>&1; then
  if nvidia-smi >/dev/null 2>&1; then
    HAS_GPU="yes"
  fi
fi
log "GPU 감지 결과: ${HAS_GPU}"

if [[ -f "${RAPIDS_STAMP}" ]]; then
  log "rapids-singlecell 설치 스탬프 존재 — 건너뜀"
elif [[ "${HAS_GPU}" == "yes" ]]; then
  log "GPU 감지됨 — rapids-singlecell 설치 시도"
  # TODO: 확인 필요 — CUDA 버전에 맞는 cuda-version extra / RAPIDS 채널
  if "${PYBIN}" -m pip install "rapids-singlecell" >>"${SETUP_LOG}" 2>&1; then
    touch "${RAPIDS_STAMP}"
    log "rapids-singlecell 설치 완료"
  else
    log "경고: rapids-singlecell 설치 실패 — GPU 가속 없이 Scanpy CPU 경로로 폴백합니다."
  fi
else
  log "GPU 미탐지 — rapids-singlecell 설치 생략 (하류 단계는 Scanpy CPU 폴백)"
fi

# ---------------------------------------------------------------------------
# 4) STAR aarch64 소스 컴파일 준비
#    Cell Ranger 미지원 환경. STARsolo 조건부 경로(03_star_optional.sh)용.
#    이미 ~/bin/STAR 가 있으면 컴파일 스킵.
# ---------------------------------------------------------------------------
STAR_VERSION="2.7.11b"  # TODO: 확인 필요 — 최신 안정 릴리스 태그
STAR_TARBALL_URL="https://github.com/alexdobin/STAR/archive/refs/tags/${STAR_VERSION}.tar.gz"

if [[ -x "${STAR_BIN}" ]]; then
  log "STAR 실행파일이 이미 존재합니다: ${STAR_BIN} (컴파일 건너뜀)"
  "${STAR_BIN}" --version 2>>"${SETUP_LOG}" | tee -a "${SETUP_LOG}" || true
else
  log "STAR aarch64 소스 준비/컴파일 시작 (v${STAR_VERSION})"

  # 빌드 도구 확인 (설치는 권한 문제로 시도만, 실패 시 안내)
  for tool in make g++ gcc; do
    if ! command -v "${tool}" >/dev/null 2>&1; then
      log "경고: 빌드 도구 '${tool}' 미탐지 — STAR 컴파일이 실패할 수 있습니다 (build-essential 필요)."
    fi
  done

  STAR_TARBALL="${SHARED_DIR}/tools/STAR-${STAR_VERSION}.tar.gz"
  LOCK_FILE="${LOCK_DIR}/star_download.lock"

  # flock으로 중복 다운로드 방지 + curl 재개/타임아웃 옵션
  (
    flock -x 9
    if [[ -f "${STAR_TARBALL}" ]]; then
      log "STAR 소스 tarball 이미 존재 — 다운로드 건너뜀 (${STAR_TARBALL})"
    else
      log "STAR 소스 tarball 다운로드: ${STAR_TARBALL_URL}"
      curl -L -C - --retry 5 --speed-limit 1024 --speed-time 60 \
        -o "${STAR_TARBALL}.part" "${STAR_TARBALL_URL}"
      mv "${STAR_TARBALL}.part" "${STAR_TARBALL}"
    fi
  ) 9>"${LOCK_FILE}"

  # 소스 전개 (idempotent)
  if [[ ! -d "${STAR_SRC_DIR}" ]]; then
    log "STAR 소스 전개 중"
    mkdir -p "${STAR_SRC_DIR}"
    tar -xzf "${STAR_TARBALL}" -C "${STAR_SRC_DIR}" --strip-components=1
  else
    log "STAR 소스 디렉터리 이미 존재 — 전개 건너뜀 (${STAR_SRC_DIR})"
  fi

  # aarch64 컴파일: SIMDe 경유로 x86 SSE 인트린식을 ARM으로 변환
  log "STAR 컴파일 시작 (aarch64, SIMDe 경유)"
  (
    cd "${STAR_SRC_DIR}/source"
    # STARforLinux 대신 aarch64는 명시적으로 make STAR 사용.
    # SIMDe 헤더로 SSE 인트린식 폴백. STAR Makefile은 CXXFLAGS_SIMD를 지원.
    # TODO: 확인 필요 — STAR 버전에 따라 CXXFLAGS_SIMD 변수명/값이 다를 수 있음
    make clean >>"${SETUP_LOG}" 2>&1 || true
    if make STAR \
         CXX=g++ \
         "CXXFLAGS_SIMD=-std=c++11 -DSIMDE_ENABLE_NATIVE_ALIASES" \
         >>"${SETUP_LOG}" 2>&1; then
      log "STAR 컴파일 성공"
    else
      log "1차 컴파일 실패 — SIMD 무효화 폴백으로 재시도"
      make clean >>"${SETUP_LOG}" 2>&1 || true
      make STAR CXX=g++ >>"${SETUP_LOG}" 2>&1
    fi
  )

  # 실행파일 설치
  if [[ -x "${STAR_SRC_DIR}/source/STAR" ]]; then
    cp "${STAR_SRC_DIR}/source/STAR" "${STAR_BIN}"
    chmod +x "${STAR_BIN}"
    log "STAR 설치 완료: ${STAR_BIN}"
    "${STAR_BIN}" --version 2>>"${SETUP_LOG}" | tee -a "${SETUP_LOG}" || true
  else
    log "경고: STAR 컴파일 산출물을 찾지 못했습니다. 원시 FASTQ 부재 시 STARsolo 경로는 비활성이므로 하류 진행 가능."
  fi
fi

# ---------------------------------------------------------------------------
# 5) 환경 요약 기록
# ---------------------------------------------------------------------------
SUMMARY="${GHBIO_RESULTS}/env_summary.txt"
{
  echo "# BioIDE 환경 요약 — $(date '+%Y-%m-%d %H:%M:%S')"
  echo "arch: ${ARCH}"
  echo "venv: ${VENV_DIR}"
  echo "python: $(${PYBIN} --version 2>&1)"
  echo "gpu_detected: ${HAS_GPU}"
  echo "star_bin: ${STAR_BIN}"
  if [[ -x "${STAR_BIN}" ]]; then
    echo "star_version: $(${STAR_BIN} --version 2>/dev/null || echo unknown)"
  else
    echo "star_version: NOT_BUILT"
  fi
  echo "--- pip freeze ---"
  "${PYBIN}" -m pip freeze 2>/dev/null || true
} > "${SUMMARY}"

log "환경 요약 기록: ${SUMMARY}"
log "다음 단계: source ${VENV_DIR}/bin/activate 후 01_check_availability.sh 실행"
log "=== 00_setup_env.sh 완료 ==="
