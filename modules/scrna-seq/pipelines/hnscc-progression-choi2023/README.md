# 두경부암 진행 단계 독립 재현 (Choi 2023, head & neck · GPU)

**원 논문:** Choi et al., *Nature Communications* 2023 — *Single-cell transcriptome
profiling of the stepwise progression of head and neck cancer*
([GSE181919](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE181919),
[s41467-023-36691-x](https://www.nature.com/articles/s41467-023-36691-x),
54,239 cells · 23 patients · 37 samples).

이 파이프라인은 **BioIDE 헌장**에 따라 저자 세포유형 라벨을 분석 입력으로 소비하지
않고, 새로 짠 GPU·Python 코드로 세포유형과 악성 상피세포를 **처음부터 다시 도출**한 뒤
저자 라벨과 논문의 진행 단계 주장을 정량 검증합니다.

## 진행 단계 (이 데이터셋의 핵심)
정상 점막(**NL**) → 백반증/전암(**LP**) → 암(**CA**) → 림프절 전이(**LN**)의 4단계
시료를 모았습니다. 논문의 핵심 주장은 **병리적으로 아직 정상처럼 보이는 백반증(LP)
단계에 이미 상피내암 유사 악성세포가 존재**하고, 악성세포 비율이 NL→LP→CA→LN로
증가한다는 것입니다.

## 라벨은 어떻게 다루나 (제1·2조)
GSE181919 메타데이터에는 저자 `cell.type` 라벨이 들어 있지만, 이는 **3단계(독립 검증)
에서만** 사용합니다(제2조). 2단계 재분석은 저자 라벨을 전혀 보지 않습니다(제1조).
반면 **진행 단계(tissue.type = NL/LP/CA/LN)**는 '어느 시료에서 온 세포인가'라는
**실험 설계 정보**(세포 라벨이 아님)라 공변량으로 유지해 진행 주장을 검증합니다.

## 파이프라인 단계
| # | 스크립트 | 내용 |
|---|---|---|
| 0 | `00_setup_env.sh` | 공유 GPU venv(Scanpy·PyTorch·Harmony·scikit-learn) |
| 1 | `01_download_hnscc.sh` | `GSE181919_UMI_counts.txt.gz`(~122 MB) + `_Barcode_metadata.txt.gz` 다운로드 (flock·curl stall-timeout·gzip 무결성) |
| 2 | `run_gpu_reanalysis.sh` → `02_gpu_reanalysis.py` | dense 행렬 로드→QC→정규화→HVG→GPU 스케일·PCA→Harmony→Leiden→UMAP→marker 주석→비지도 GMM 악성 분리→진행 단계별 조성 |
| 3 | `03_validate_vs_authors.py` | 저자 라벨 대조(ARI/NMI·혼동행렬·정확도·악성 F1) + 진행 단계별 악성세포 출현 주장 검증 |
| 4 | (AI 패널) | 결과 해석·가설, 🎓 고등학생 리포트 |
| 5 | `05_make_report.sh` / `05_make_easy_report.sh` | PDF 리포트 |

## 검증 대상
- **세포유형 재현** — 저자 `cell.type`(T·B/plasma·대식세포·수지상·비만·내피·섬유아세포·
  근세포·정상 상피·악성) 대비 우리 독립 세포유형: ARI/NMI·혼동행렬·라벨 일치 정확도
- **악성세포 판정** — 우리 비지도 GMM 악성/정상 상피세포 vs 저자 Malignant/Epithelial:
  precision/recall/F1/accuracy
- **진행 주장** — 악성 상피세포 비율이 **LP(백반증)부터 존재**하고 NL→LP→CA로 증가하는지

저자와는 **다른 비지도 GMM**으로 악성 상피세포를 가르므로, 일치는 두 독립 경로의
수렴을 뜻합니다(제6조).

## 데이터 형식 주의
GSE181919는 10x MTX가 아니라 **dense TSV UMI 행렬**(genes × cells)로 배포됩니다. 로더는
행렬을 유전자 청크 단위로 읽어 sparse cells×genes 로 변환하고(메모리 절약), 카운트 헤더의
바코드(`AAAC….1`, 점)와 메타데이터 바코드(`AAAC…-1`, 대시)를 **정규화**해 1:1로 조인합니다.

## 실행 요건
- CUDA GPU 필수(제4조: CPU 대체 실행 차단). aarch64 박스에서 Cell Ranger 없이 돌도록
  **정렬이 아닌 행렬 기반**으로 설계했습니다.
- 모든 산출물은 `$GHBIO_RESULTS`(파이프라인 자체 프로젝트 결과 폴더)에 씁니다.
