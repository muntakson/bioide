# 췌장암 독립 재현 (Peng 2019, PDAC · GPU)

**BioIDE 헌장**에 따라 **Peng et al., Cell Research 2019**(췌장암 PDAC)을 **독립 재현**하는
파이프라인입니다. 핵심 원칙(**제1조 · Reproduce, don't consume**): 저자가 붙인 세포유형
라벨(`Cell_type`: 도관 type1/2 등)을 **분석 입력으로 소비하지 않습니다**. 저자가 공개한
log-정규화 발현행렬만 받아, **우리가 새로 짠 GPU·Python 코드**로 세포유형과 악성 도관세포를
처음부터 다시 도출한 뒤, **독립 검증(제2조)**에서 저자 결론과 정량 대조합니다.

- 논문: https://www.nature.com/articles/s41422-019-0195-y
- 데이터: Zenodo `3969339` (`StdWf1_PRJCA001063_CRC_besca2.annotated.h5ad`, ~1.7 GB) — 우리는
  이 안의 `adata.raw`(17,004 유전자, log-정규화)만 입력으로 사용.

## 스텝 구성 (GPU 독립 재현)
| # | 파일 | 하는 일 |
|---|------|---------|
| 0 | `00_setup_env.sh` | 공유 venv에 Scanpy·**PyTorch(GPU)**·Harmony·scikit-learn 설치 |
| 1 | `01_download_peng_pdac.sh` | Zenodo에서 발현행렬(.h5ad) 내려받기 (flock·stall 타임아웃·무결성 검사) |
| 2 | `run_gpu_reanalysis.sh` → `02_gpu_reanalysis.py` | **저자 라벨 미사용.** HVG → GPU(PyTorch) 스케일·PCA(SVD) → Harmony(환자) → Leiden → UMAP → marker 기반 세포유형 주석 → **비지도 GMM** 악성/정상 도관 분리. 저자 `Cell_type`은 `author_labels.csv`로 보관만. |
| 3 | `03_validate_vs_authors.py` | **독립 검증(제2조).** 우리 결과 vs 저자 라벨 — ARI/NMI·혼동행렬·악성 정확도/F1 → `validation_summary.csv`·`validation_verdict.txt` |
| 4 | (AI 단계) | 재현 성공 여부 판정·해석 (kind `ai`) |
| 5 | `05_make_report.sh` / `05_make_easy_report.sh` | 독립 그림 + 검증 결과 PDF / 🎓 고등학생 PDF |

모든 스크립트는 결과를 **`$GHBIO_RESULTS`** 아래에 씁니다. GPU 단계는 CUDA가 없으면 **실행을
거부**합니다(제4조 — CPU 대체 없음).

## 왜 scVI가 아니라 PyTorch+Harmony인가 (제6조 · 정직)
scVI는 **정수 카운트**가 필요한데, 이 공개 객체는 스케일링/log-정규화 값만 담고 카운트가
없습니다. 그래서 무거운 밀집 연산(스케일·PCA SVD)을 **PyTorch로 GPU 가속**하고, 환자 배치는
**Harmony**로 통합하는 경로를 택했습니다(therapy-induced-evolution 참조 파이프라인과 동일 방식).

## 재현의 층위 (제6조)
이것은 **저자의 처리 데이터로부터의 계산 재현**입니다 — 원시 리드(FASTQ)부터의 독립 복제도,
저자 코드로의 정밀 재현도 아닙니다. 저자의 log-정규화 값을 물려받되, **세포유형 주석과 악성
판정은 저자 라벨 없이 우리 코드로 독립 도출**하고, 그 결론이 저자와 수렴하는지 검증합니다.
