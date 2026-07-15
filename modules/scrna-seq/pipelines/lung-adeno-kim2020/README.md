# 폐선암 전이 진행 독립 재현 (Kim 2020, lung adeno · GPU)

**원 논문:** Kim et al., *Nature Communications* 2020 — *Single-cell RNA sequencing
demonstrates the molecular and cellular reprogramming of metastatic lung
adenocarcinoma* ([GSE131907](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE131907),
[s41467-020-16164-1](https://www.nature.com/articles/s41467-020-16164-1),
208,506 cells · 44 patients · 58 samples). 한국(삼성유전체연구소·성균관의대) 연구진.

이 파이프라인은 **BioIDE 헌장**에 따라 저자 세포유형 라벨을 분석 입력으로 소비하지
않고, 새로 짠 GPU·Python 코드로 세포유형과 악성 상피세포를 **처음부터 다시 도출**한 뒤
저자 라벨과 논문의 전이 축 주장을 정량 검증합니다.

## 전이 축 (이 데이터셋의 핵심)
정상 폐(**nLung**) → 원발 종양(**tLung**, 진행 **tL/B**) → 정상/전이 림프절(**nLN**/**mLN**)
→ 뇌 전이(**mBrain**) → 흉수(**PE**)의 조직 시료를 모았습니다. 논문의 핵심 주장은
**종양·전이 조직일수록 악성 상피세포가 편중**되고, **전이 림프절(mLN)에는 골수성 세포가
침윤**하며(정상 림프절 nLN엔 적음), 악성세포가 정상 폐포(AT2) 분화를 잃고 종양 상태
(tS1·tS2·tS3, 특히 tS2는 예후 불량)로 바뀐다는 것입니다.

## 라벨은 어떻게 다루나 (제1·2조)
GSE131907 세포 주석에는 저자 `Cell_type`/`Cell_subtype` 라벨이 들어 있지만, 이는 **3단계
(독립 검증)에서만** 사용합니다(제2조). 2단계 재분석은 저자 라벨을 전혀 보지 않습니다(제1조).
반면 **조직 기원(Sample_Origin)**은 '어느 시료에서 온 세포인가'라는 **실험 설계 정보**
(세포 라벨이 아님)라 공변량으로 유지해 전이 축 주장을 검증합니다.

## 파이프라인 단계
| # | 스크립트 | 내용 |
|---|---|---|
| 0 | `00_setup_env.sh` | 공유 GPU venv(Scanpy·PyTorch·Harmony·scikit-learn) |
| 1 | `01_download_lung.sh` | `GSE131907_Lung_Cancer_raw_UMI_matrix.txt.gz`(~390 MB) + `_cell_annotation.txt.gz` 다운로드 (flock·curl stall-timeout·gzip 무결성) |
| 2 | `run_gpu_reanalysis.sh` → `02_gpu_reanalysis.py` | dense 행렬(208k) 청크 로드→QC→정규화→HVG→GPU 스케일·PCA→Harmony→Leiden→UMAP→marker 주석→비지도 GMM 악성 분리→조직 기원별 조성 |
| 3 | `03_validate_vs_authors.py` | 저자 라벨 대조(ARI/NMI·혼동행렬·정확도·악성 F1) + 전이 축(악성 편중·mLN 골수성 침윤) 주장 검증 |
| 4 | (AI 패널) | 결과 해석·가설, 🎓 고등학생 리포트 |
| 5 | `05_make_report.sh` / `05_make_easy_report.sh` | PDF 리포트 |

## 검증 대상
- **세포유형 재현** — 저자 `Cell_type`(T·NK·B·골수성·상피·섬유아세포·비만·내피·희소돌기아교·미결정)
  대비 우리 독립 세포유형: ARI/NMI·혼동행렬·라벨 일치 정확도
- **악성세포 판정** — 우리 비지도 GMM 악성/정상 상피세포 vs 저자 `Cell_subtype == "Malignant cells"`:
  precision/recall/F1/accuracy
- **전이 축 주장** — 악성 상피세포가 정상(nLung/nLN) 대비 종양·전이(tLung/mLN/mBrain) 조직에
  편중되는지, 전이 림프절(mLN)에 골수성 세포가 정상 림프절(nLN)보다 많은지

저자와는 **다른 비지도 GMM**으로 악성 상피세포를 가르므로, 일치는 두 독립 경로의
수렴을 뜻합니다(제6조).

## 데이터 형식 주의
GSE131907은 10x MTX가 아니라 **dense TSV UMI 행렬**(genes × cells)로 배포됩니다. 208k 세포라
전체를 통째로 읽으면 메모리가 폭발하므로, 로더는 행렬을 **유전자 청크 단위**로 읽어 sparse
cells×genes 로 변환합니다. 행렬 열 헤더(cell id `AAACCTGAGAAACCGC_LN_05`)와 주석 `Index`가
같은 `<barcode>_<Sample>` 형식이라 1:1로 조인됩니다. (2.9 GB 정규화 log2TPM 행렬은 쓰지 않고
원시 카운트를 직접 정규화합니다.)

## 실행 요건
- CUDA GPU 필수(제4조: CPU 대체 실행 차단). aarch64 박스에서 Cell Ranger 없이 돌도록
  **정렬이 아닌 행렬 기반**으로 설계했습니다.
- 208k 세포는 큰 편입니다. 빠른 시연은 `bash run_gpu_reanalysis.sh --max-cells 60000`.
- 모든 산출물은 `$GHBIO_RESULTS`(파이프라인 자체 프로젝트 결과 폴더)에 씁니다.
