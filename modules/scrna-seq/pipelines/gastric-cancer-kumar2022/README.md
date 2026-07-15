# 위암 독립 재현 (Kumar 2022, gastric cancer · GPU)

**원 논문:** Kumar et al., *Cancer Discovery* 2022 — *Single-Cell Atlas of Lineage
States, Tumor Microenvironment, and Subtype-Specific Expression Programs in Gastric
Cancer* ([GSE183904](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE183904),
>200,000 cells · 31 patients · 48 samples).

이 파이프라인은 **BioIDE 헌장**에 따라 저자 결과를 소비하지 않고, 새로 짠 GPU·Python
코드로 세포유형과 악성 상피세포를 **처음부터 다시 도출**한 뒤 원 논문의 주장을 정량
검증합니다.

## 왜 라벨을 안 쓰나 (쓸 수가 없다)
GSE183904의 GEO 공개물은 **시료별 원시 카운트 CSV 행렬(genes × cells)뿐**이며,
세포유형/클러스터 라벨이나 처리된 객체는 **배포되지 않습니다**(원시 시퀀싱 자료는
환자 프라이버시를 이유로 비공개). 따라서 헌장 제1조(라벨 미소비)가 이 데이터에서는
**필수**입니다.

## 파이프라인 단계
| # | 스크립트 | 내용 |
|---|---|---|
| 0 | `00_setup_env.sh` | 공유 GPU venv(Scanpy·PyTorch·Harmony·scikit-learn) |
| 1 | `01_download_gastric.sh` | `GSE183904_RAW.tar`(~329 MB) 다운로드 + 시료별 CSV 추출 (flock·curl stall-timeout) |
| 2 | `run_gpu_reanalysis.sh` → `02_gpu_reanalysis.py` | 시료 병합(공통 유전자)→QC→정규화→HVG→GPU 스케일·PCA→Harmony→Leiden→UMAP→marker 주석→비지도 GMM 악성 상피세포 분리 |
| 3 | `03_validate_vs_authors.py` | 논문 주장과 대조 (세포계통·marker 재현·악성 분화점수 하락·악성 증식 상승·조직별 편중) |
| 4 | (AI 패널) | 결과 해석·가설, 🎓 고등학생 리포트 |
| 5 | `05_make_report.sh` / `05_make_easy_report.sh` | PDF 리포트 |

## 검증 대상 (논문 주장)
저자 라벨이 없으므로 3단계는 **정답 대조가 아니라** 논문이 보고한 주장을 우리 독립
결과가 재현하는지 봅니다:
- **C1** 주요 세포계통(상피·T/NK·B·형질·골수성·내피·섬유아세포)과 canonical marker 재현
- **C2** 악성 상피세포의 위 분화점수(GDS: TFF1/MUC5AC/GKN1/LIPF/PGC 등) 하락
- **C3** 악성 상피세포의 증식 프로그램(MKI67/TOP2A 등) 상승
- **C4** 종양 조직에서 악성 상피세포 편중 (정상 대비 — 조직 라벨을 파일명에서 도출할 수 있을 때만)

저자와는 **다른 비지도 GMM**으로 악성 상피세포를 가르므로, 일치는 두 독립 경로의
수렴을 뜻합니다(제6조).

## 데이터 형식 주의
GSE183904는 10x MTX가 아니라 **시료별 CSV**(genes × cells)로 배포됩니다. 로더는 각 CSV의
행/열 중 알려진 유전자 심볼과 더 많이 겹치는 축을 유전자 축으로 판단해, 전치된 파일도
올바르게 cells×genes 로 읽습니다.

## 실행 요건
- CUDA GPU 필수(제4조: CPU 대체 실행 차단). aarch64 박스에서 Cell Ranger 없이 돌도록
  **정렬이 아닌 행렬 기반**으로 설계했습니다.
- 모든 산출물은 `$GHBIO_RESULTS`(파이프라인 자체 프로젝트 결과 폴더)에 씁니다.
