# 간암 속 3차 림프 구조(TLS) 독립 재현 (Lu 2022, HCC · GPU)

**원 논문:** Lu et al., *Nature Communications* 2022 — *A single-cell atlas of the
multicellular ecosystem of primary and metastatic hepatocellular carcinoma*
([GSE149614](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE149614),
[s41467-022-32283-3](https://www.nature.com/articles/s41467-022-32283-3),
71,915 cells · 10 patients · 21 samples).

이 파이프라인은 **BioIDE 헌장**에 따라 저자 세포유형 라벨을 분석 입력으로 소비하지
않고, 새로 짠 GPU·Python 코드로 세포유형·악성 간세포·**3차 림프 구조(TLS)** 세포를
**처음부터 다시 도출**한 뒤, 저자 라벨과 논문의 진행 축·종양 내 TLS 주장을 정량 검증합니다.

## 이 튜토리얼의 주제 — 3차 림프 구조(TLS)
**TLS(tertiary lymphoid structure)**는 종양 조직 안에 생기는 **작은 림프절 같은 면역
집결지**입니다. B세포·항체를 만드는 형질세포, **CXCL13⁺ 여포도움 T세포(Tfh)**, 여포수지상
세포가 조직적으로 모이며, 케모카인 **CXCL13**(CXCR5⁺ B/Tfh 유인)과 **CCL19/CCL21**(CCR7⁺
나이브/중심기억 T 유인)이 이들을 불러모읍니다. 프랑스 면역학자 **Fridman(Wolf H. Fridman)
교수팀** 등 글로벌 면역학계는 종양 안에 TLS가 있으면 **환자 생존율과 면역치료 반응이 좋아
지며**, **CCL21·CXCL13** 같은 케모카인을 주입해 TLS를 인위적으로 만들 수 있음을 규명했습니다.
이 데이터셋으로 우리는 **종양 조직 안에 TLS가 형성되는지**(B세포·CXCL13⁺ Tfh·CXCL13의
종양 편중)를 단일세포에서 독립적으로 재도출·검증합니다.

## 전이 축 (이 데이터셋의 또 다른 축)
정상 간(**Normal**) → 원발 종양(**Tumor**) → 문맥 종양전(**PVTT**, 간 문맥 혈관 속 종양
덩어리) → 전이 림프절(**Lymph**)의 조직 시료를 모았습니다. 논문의 주장은 **종양·전이
조직일수록 악성 간세포가 편중**되고, 악성세포가 정상 간세포의 대사 기능(ALB·CYP 효소)을
잃고 HCC 종양 유전자(AFP·GPC3 등)를 켠다는 것입니다.

## 라벨은 어떻게 다루나 (제1·2조)
GSE149614 세포 주석에는 저자 `celltype` 라벨(Hepatocyte/T·NK/B/Myeloid/Endothelial/
Fibroblast)이 들어 있지만, 이는 **3단계(독립 검증)에서만** 사용합니다(제2조). 2단계 재분석은
저자 라벨을 전혀 보지 않습니다(제1조). 반면 **조직 부위(site)**는 '어느 시료에서 온 세포인가'
라는 **실험 설계 정보**(세포 라벨이 아님)라 공변량으로 유지해 진행 축·TLS 주장을 검증합니다.

## 데이터 형식 (주의)
`GSE149614_HCC.scRNAseq.S71915.count.txt.gz`는 **dense TSV**(genes × cells)이며, **헤더 행이
세포 바코드**입니다(선행 라벨 토큰 없음). 로더는 첫 데이터 행의 열 수로 헤더 배치를 자동 감지해
`<sample>_<barcode>` 형식의 세포 id로 메타데이터와 1:1 조인합니다. 저자 메타데이터에는
**악성/정상 간세포 구분 라벨이 없어**, 악성 판정은 저자 F1이 아니라 '종양 부위 편중'의
자기일관성으로 검증합니다.

## 파이프라인 단계
| # | 스크립트 | 내용 |
|---|---|---|
| 0 | `00_setup_env.sh` | 공유 GPU venv(Scanpy·PyTorch·Harmony·scikit-learn) |
| 1 | `01_download_hcc.sh` | `GSE149614_HCC.scRNAseq.S71915.count.txt.gz`(~158 MB) + `_metadata.updated.txt.gz` 다운로드 (flock·curl stall-timeout·gzip 무결성) |
| 2 | `run_gpu_reanalysis.sh` → `02_gpu_reanalysis.py` | dense 행렬(72k) 병렬 로드→QC→정규화→HVG→GPU 스케일·PCA→Harmony→Leiden→UMAP→marker 주석→비지도 GMM 악성 간세포 분리→TLS 모듈 점수화→조직 부위별 조성 |
| 3 | `03_validate_vs_authors.py` | 저자 라벨 대조(ARI/NMI·혼동행렬·정확도) + 진행 축(악성 편중)·종양 내 TLS(B·CXCL13⁺ Tfh·CXCL13) 주장 검증 |
| 4 | (AI 패널) | 결과 해석·가설, 🎓 고등학생 리포트 |
| 5 | `05_make_report.sh` / `05_make_easy_report.sh` | PDF 리포트 |

## 검증 대상
- **세포유형 재현** — 저자 `celltype`(Hepatocyte·T/NK·B·Myeloid·Endothelial·Fibroblast)
  대비 우리 독립 세포유형: ARI/NMI·혼동행렬·라벨 일치 정확도
- **진행 축** — 정상 간(Normal) 대비 종양/전이(Tumor/PVTT/Lymph)에서 악성 간세포 편중
  (저자 악성 라벨 부재 → 부위 편중 자기일관성)
- **종양 내 TLS** — B세포·CXCL13⁺ Tfh·평균 CXCL13이 정상 간보다 종양 조직에서 높은지
  (3/3 신호 상승 → AGREE)

## 실행
BioIDE Dashboard에서 0→5 순서로 실행하거나, "전체 분석 실행"으로 0–3단계를 한 번에 돌립니다
(AI 단계에서 멈춤). 72k 세포는 전체 실행이 감당할 만하지만, 빠른 시험 실행은
`bash run_gpu_reanalysis.sh --max-cells 40000` 로 축소할 수 있습니다.

> ⚠️ 교육용 재현입니다. '재현/부분재현'은 서로 다른 두 독립 분석이 수렴한다는 뜻이지,
> 어느 쪽이 절대적 정답이라는 뜻이 아닙니다(제6조). scRNA 단일세포의 'TLS 점수'는 조직 수준
> 구조를 세포 조성으로 근사한 것으로, 공간전사체(spatial)로 확증하는 것이 이상적입니다.
