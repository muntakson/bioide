# 간암 독립 재현 (Ma 2019, liver cancer · GPU)

**원 논문:** Ma et al., *Cancer Cell* 2019 — *Tumor Cell Biodiversity Drives
Microenvironmental Reprogramming in Liver Cancer*
([GSE125449](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE125449),
~9,900 cells · 19 patients · HCC + iCCA · 10x Genomics Set1/Set2).

이 파이프라인은 **BioIDE 헌장**에 따라 저자 결과를 소비하지 않고, 새로 짠 GPU·Python
코드로 세포유형과 악성 종양세포를 **처음부터 다시 도출**한 뒤 원 논문의 주장을 정량
검증합니다.

## 라벨을 어떻게 다루나
GSE125449의 GEO 공개물은 **10x 원시 UMI 카운트 행렬(Set1+Set2)**과 세포별 주석
파일(`samples.txt`: Sample · Cell Barcode · **Type**)을 함께 배포합니다. 헌장 제1조에 따라
저자 `Type` 라벨(Malignant cell · HPC-like · T cell · TAM · CAF · TEC · B cell)은 분석
입력으로 쓰지 않고 `author_labels.csv`로 **보관만** 했다가, 3단계 독립 검증에서만
정답 대조용으로 사용합니다(제2조).

## 파이프라인 단계
| # | 스크립트 | 내용 |
|---|---|---|
| 0 | `00_setup_env.sh` | 공유 GPU venv(Scanpy·PyTorch·Harmony·scikit-learn) |
| 1 | `01_download_liver.sh` | Set1+Set2 10x 삼중 파일 + samples.txt(~46 MB) 다운로드 (flock·curl stall-timeout) |
| 2 | `run_gpu_reanalysis.sh` → `02_gpu_reanalysis.py` | 두 배치 병합(공통 유전자)→QC→정규화→HVG→GPU 스케일·PCA→Harmony→Leiden→UMAP→marker 주석→비지도 GMM 악성/HPC-like 상피세포 분리 |
| 3 | `03_validate_vs_authors.py` | 저자 라벨과 대조 (ARI/NMI·세포유형 혼동행렬·악성 상피세포 정확도/F1) |
| 4 | (AI 패널) | 결과 해석·가설, 🎓 고등학생 리포트 |
| 5 | `05_make_report.sh` / `05_make_easy_report.sh` | PDF 리포트 |

## 검증 지표 (저자 라벨 대비)
저자 라벨이 함께 배포되므로 3단계는 **정답 대조** 방식으로 재현성을 정량화합니다:
- **ARI / NMI** — 우리 Leiden 클러스터·세포유형이 저자 `Type`과 얼마나 같은 방식으로 세포를 나눴는가
- **세포유형 혼동행렬 · 라벨 일치 정확도** — 저자 라벨이 우리 어느 세포유형으로 갔는지 (저자의 Malignant cell + HPC-like 는 우리 상피 계통에 대응)
- **악성 상피세포 정확도/F1/ARI** — 우리 비지도 악성/HPC-like 판정 vs 저자 Malignant cell / HPC-like

저자와는 **다른 비지도 GMM**으로 악성세포를 가르므로, 일치는 두 독립 경로의
수렴을 뜻합니다(제6조). 특히 **악성세포 vs HPC-like 경계는 두 집단 모두 상피성**이라
본질적으로 애매하며, 리포트/AI 해석에서 이 점을 명시합니다.

## 데이터 형식 주의
GSE125449는 배치별 **10x MatrixMarket 삼중 파일**(matrix.mtx / genes.tsv / barcodes.tsv)로
배포됩니다. `genes.tsv`는 `ENSEMBL_id<tab>symbol` 2열이며 로더는 symbol 열을 유전자명으로
씁니다. `samples.txt`의 `Cell Barcode` 순서는 `barcodes.tsv`와 일치하므로 배치별로
바코드로 join해 Sample·Type을 붙입니다.

## 실행 요건
- CUDA GPU 필수(제4조: CPU 대체 실행 차단). aarch64 박스에서 Cell Ranger 없이 돌도록
  **정렬이 아닌 행렬 기반**으로 설계했습니다(공개 데이터가 이미 UMI 카운트 행렬).
- 모든 산출물은 `$GHBIO_RESULTS`(파이프라인 자체 프로젝트 결과 폴더)에 씁니다.
