#!/usr/bin/env bash
set -euo pipefail

# 01_check_availability.sh
# Step [availability]: Verify data availability for GSE103322
# - curl로 GEO GSE103322 supplementary 파일 목록 확인
# - pysradb로 SRA raw run 유무 조회
# - 시작 경로(처리행렬 vs STARsolo) 결정 -> data_availability.json

GHBIO_RESULTS="${GHBIO_RESULTS:-${HOME}/ghbio-tutorial/results}"
mkdir -p "$GHBIO_RESULTS"

PY="${HOME}/ghbio-venv/bin/python"
OUT="${GHBIO_RESULTS}/data_availability.json"
WORK="${GHBIO_RESULTS}/_availability_tmp"
mkdir -p "$WORK"

GSE="GSE103322"
GSE_PREFIX="GSE103nnn"  # GEO FTP는 accession의 마지막 3자리를 nnn으로 치환한 하위 디렉토리 사용
SRP="SRP116721"          # TODO: 확인 필요 (GSE103322에 연결된 SRA study accession)

# 이미 산출물이 있으면 스킵 (idempotent)
if [[ -s "$OUT" ]]; then
    echo "[availability] $OUT already exists — skipping."
    exit 0
fi

LOCK="${WORK}/availability.lock"

run_checks() {
    # ---- 1. GEO supplementary 목록 확인 (curl) ----
    local supp_url="https://ftp.ncbi.nlm.nih.gov/geo/series/${GSE_PREFIX}/${GSE}/suppl/"
    local supp_listing="${WORK}/geo_suppl_listing.html"
    local supp_ok="false"

    echo "[availability] Fetching GEO supplementary listing: $supp_url"
    if curl -fsSL -C - --retry 5 --speed-limit 1024 --speed-time 60 \
            "$supp_url" -o "$supp_listing"; then
        supp_ok="true"
    else
        echo "[availability] WARN: GEO supplementary listing fetch failed."
    fi

    # 처리 완료 TPM 행렬 파일 존재 여부
    local matrix_file="${GSE}_HNSCC_all_data.txt.gz"
    local matrix_present="false"
    if [[ "$supp_ok" == "true" ]] && grep -qi "HNSCC_all_data" "$supp_listing"; then
        matrix_present="true"
    fi

    # supplementary 파일명 목록 추출 (best-effort)
    local supp_files_json="[]"
    if [[ "$supp_ok" == "true" ]]; then
        supp_files_json=$(grep -oiE 'href="[^"]+"' "$supp_listing" 2>/dev/null \
            | sed -E 's/href="([^"]+)"/\1/i' \
            | grep -viE '^\?|/$|Parent Directory' \
            | "$PY" -c 'import sys,json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))' \
            2>/dev/null || echo "[]")
        [[ -z "$supp_files_json" ]] && supp_files_json="[]"
    fi

    # ---- 2. pysradb로 SRA raw run 조회 ----
    local sra_json="${WORK}/sra_metadata.json"
    local raw_available="false"
    local raw_kind="none"
    local n_runs=0

    echo "[availability] Querying SRA via pysradb for study ${SRP} / ${GSE}"
    if "${HOME}/ghbio-venv/bin/pysradb" srp-to-srr "$SRP" >"${WORK}/pysradb_srr.tsv" 2>"${WORK}/pysradb_srr.err"; then
        # 헤더 제외 run 수 계산
        n_runs=$(awk 'NR>1' "${WORK}/pysradb_srr.tsv" | grep -cE 'SRR|ERR|DRR' || true)
    else
        echo "[availability] WARN: pysradb srp-to-srr failed (SRP may be absent)."
        n_runs=0
    fi

    # gse-to-srp로도 교차확인 (SRP 하드코딩이 틀릴 수 있음)
    local resolved_srp=""
    if "${HOME}/ghbio-venv/bin/pysradb" gse-to-srp "$GSE" >"${WORK}/pysradb_gse2srp.tsv" 2>/dev/null; then
        resolved_srp=$(awk 'NR>1{print $2}' "${WORK}/pysradb_gse2srp.tsv" | head -n1 || true)
    fi

    if [[ "$n_runs" -gt 0 ]]; then
        raw_available="true"
        raw_kind="fastq_or_bam"  # TODO: 확인 필요 (실제 파일 형식 FASTQ vs BAM 구분)
    fi

    # ---- 3. 시작 경로 결정 ----
    local start_path="processed_matrix"
    local star_optional="skip"
    if [[ "$raw_available" == "true" ]]; then
        # raw가 존재해도 GSE103322는 처리행렬이 기본; STARsolo는 선택 경로 활성화
        star_optional="enabled"
    fi
    if [[ "$matrix_present" != "true" ]] && [[ "$raw_available" == "true" ]]; then
        # 처리행렬이 없고 raw만 있으면 STARsolo 경로로 시작
        start_path="starsolo"
        star_optional="enabled"
    fi

    # ---- 4. JSON 산출 ----
    SUPP_FILES_JSON="$supp_files_json" \
    GEO_ACC="$GSE" \
    SUPP_URL="$supp_url" \
    SUPP_OK="$supp_ok" \
    MATRIX_PRESENT="$matrix_present" \
    MATRIX_FILE="$matrix_file" \
    SRP_HARDCODED="$SRP" \
    SRP_RESOLVED="$resolved_srp" \
    N_RUNS="$n_runs" \
    RAW_AVAILABLE="$raw_available" \
    RAW_KIND="$raw_kind" \
    START_PATH="$start_path" \
    STAR_OPTIONAL="$star_optional" \
    "$PY" - "$OUT" <<'PYEOF'
import os, sys, json, datetime

out = sys.argv[1]

try:
    supp_files = json.loads(os.environ.get("SUPP_FILES_JSON", "[]"))
except Exception:
    supp_files = []

data = {
    "step": "availability",
    "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
    "geo_accession": os.environ.get("GEO_ACC", ""),
    "geo_supplementary": {
        "url": os.environ.get("SUPP_URL", ""),
        "listing_ok": os.environ.get("SUPP_OK", "false") == "true",
        "files": supp_files,
        "processed_matrix_file": os.environ.get("MATRIX_FILE", ""),
        "processed_matrix_present": os.environ.get("MATRIX_PRESENT", "false") == "true",
    },
    "sra": {
        "srp_hardcoded": os.environ.get("SRP_HARDCODED", ""),
        "srp_resolved": os.environ.get("SRP_RESOLVED", ""),
        "n_runs": int(os.environ.get("N_RUNS", "0")),
        "raw_available": os.environ.get("RAW_AVAILABLE", "false") == "true",
        "raw_kind": os.environ.get("RAW_KIND", "none"),
    },
    "decision": {
        "start_path": os.environ.get("START_PATH", "processed_matrix"),
        "star_optional": os.environ.get("STAR_OPTIONAL", "skip"),
        "note": "GSE103322는 처리 완료 TPM 행렬(log2(TPM/10+1))만 공개돼 있어 기본 경로는 processed_matrix. SRA raw가 존재하면 star_optional=enabled로 STARsolo 선택 경로 활성화.",
    },
}

tmp = out + ".tmp"
with open(tmp, "w") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
os.replace(tmp, out)
print(f"[availability] wrote {out}")
print(json.dumps(data["decision"], indent=2, ensure_ascii=False))
PYEOF
}

# flock으로 중복 실행 방지
exec 9>"$LOCK"
if flock -n 9; then
    run_checks
else
    echo "[availability] Another instance is running (lock held) — waiting..."
    flock 9
    if [[ -s "$OUT" ]]; then
        echo "[availability] Completed by another instance — skipping."
    else
        run_checks
    fi
fi

echo "[availability] Done."
