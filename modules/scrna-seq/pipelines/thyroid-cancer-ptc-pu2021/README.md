# 갑상선유두암 독립 재현 (Pu 2021, PTC · GPU)

**원 논문:** Pu et al., *Nature Communications* 2021 — *Single-cell transcriptomic
analysis of the tumor ecosystems underlying initiation and progression of papillary
thyroid carcinoma* ([GSE184362](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE184362),
158,577 cells · 11 patients · 23 samples).

이 파이프라인은 **BioIDE 헌장**에 따라 저자 결과를 소비하지 않고, 새로 짠 GPU·Python
코드로 세포유형과 악성 갑상선세포를 **처음부터 다시 도출**한 뒤 원 논문의 주장을 정량
검증합니다.

## 왜 라벨을 안 쓰나 (쓸 수가 없다)
GSE184362의 GEO 공개물은 **원시 카운트 행렬(23개 시료의 barcodes/features/matrix)뿐**이며,
세포유형/클러스터 라벨이나 처리된 객체는 **배포되지 않습니다**. 저자 코드 저장소
([puweilin/scRNAseq_PTC](https://github.com/puweilin/scRNAseq_PTC))에도 분석 스크립트만
있고 라벨은 없습니다. 따라서 헌장 제1조(라벨 미소비)가 이 데이터에서는 **필수**입니다.

## 파이프라인 단계
| # | 스크립트 | 내용 |
|---|---|---|
| 0 | `00_setup_env.sh` | 공유 GPU venv(Scanpy·PyTorch·Harmony·scikit-learn) |
| 1 | `01_download_thyroid.sh` | `GSE184362_RAW.tar`(~926 MB) 다운로드 + 시료별 추출 (flock·curl stall-timeout) |
| 2 | `run_gpu_reanalysis.sh` → `02_gpu_reanalysis.py` | 시료 병합(공통 유전자)→QC→정규화→HVG→GPU 스케일·PCA→Harmony→Leiden→UMAP→marker 주석→비지도 GMM 악성 분리 |
| 3 | `03_validate_vs_authors.py` | 논문 주장과 대조 (세포계통·marker 재현·악성 TDS 하락·TMSB4X 진행 구배·조직별 악성 편중) |
| 4 | (AI 패널) | 결과 해석·가설, 🎓 고등학생 리포트 |
| 5 | `05_make_report.sh` / `05_make_easy_report.sh` | PDF 리포트 |

## 검증 대상 (논문 주장)
저자 라벨이 없으므로 3단계는 **정답 대조가 아니라** 논문이 보고한 주장을 우리 독립
결과가 재현하는지 봅니다:
- **C1** 주요 세포계통(갑상선세포·T/NK·B·형질·골수성·내피·섬유아세포)과 canonical marker 재현
- **C2** 악성 갑상선세포의 갑상선 분화점수(TDS: TG/TPO/IYD/TFF3/DIO2) 하락
- **C3** 원발→림프절→원격 전이 진행축을 따라 TMSB4X 상승
- **C4** 종양/전이 조직에서 악성 갑상선세포 편중 (정상곁 대비)

저자는 TCGA 학습 KNN 분류기로 악성세포를 판정했고, 우리는 의도적으로 **다른 비지도 GMM**을
씁니다 — 일치는 두 독립 경로의 수렴을 뜻합니다(제6조).

## 실행 요건
- CUDA GPU 필수(제4조: CPU 대체 실행 차단). aarch64 박스에서 Cell Ranger 없이 돌도록
  **정렬이 아닌 행렬 기반**으로 설계했습니다.
- 모든 산출물은 `$GHBIO_RESULTS`(파이프라인 자체 프로젝트 결과 폴더)에 씁니다.
