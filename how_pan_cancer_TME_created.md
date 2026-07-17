# 범암종 아틀라스(Pan-Cancer TME + 악성 메타프로그램)를 만든 전 과정

_BioIDE의 검증 완료 11개 재현 파이프라인에서 하나의 범암종 아틀라스를 만들기까지의 실제 작업 기록._

작성일: 2026-07-17 · 파이프라인 id: `pan-cancer-atlas` · 배포 버전: v0.9.31

---

## 0. 목표

BioIDE가 이미 **저자 라벨 없이 GPU-Python으로 독립 재현**해 둔 11개 암 파이프라인(≈795,700 세포·9개 암종)의 결과 h5ad를 하나로 모아,

- **Use 1 — 범암종 TME 아틀라스**: 비악성 면역·기질세포를 통합해 여러 암에 공유되는 세포상태 vs 조직특이 세포상태를 밝힌다.
- **Use 2 — 악성 메타프로그램**: 악성세포는 통합하지 않고 표본별 NMF로 분해해 모든 암에서 반복 출현하는 프로그램을 도출한다.

---

## 1. 1단계 — 데이터 실측 조사 (무엇이 디스크에 있나)

먼저 파이프라인 매니페스트와 실제 디스크를 대조했다.

- 18개 파이프라인 중 **11개가 검증 완료(AGREE/PARTIAL)된 matrix 기반 암 재현**이고, 각각 처리된 `.h5ad`(세포유형 + 악성 라벨)를 가지고 있음을 확인.
- `~/ghbio-tutorial/`(191 GB) 중 135 GB는 raw FASTQ(정렬 데모용), 아틀라스에 필요한 것은 각 프로젝트 `results/`의 처리된 h5ad(≈7.6 GB).
- 각 h5ad의 `n_obs`를 직접 세어 **총 ≈795,700 세포·9 암종** 확인. (요약: `raw_dataset_BioIDE.md`)

각 h5ad를 introspect해 **obs 컬럼 스키마**를 실측했고, 중요한 사실을 발견:
- 7개(gastric/hcc/hnscc/liver/lung/pancreatic/thyroid)는 스키마가 사실상 동일 — `cell_type` + `malignant_call{악성/정상/n/a}` + `sample`/`patient` + 진행축.
- 3개(GBM/melanoma/puram)는 Smart-seq2 → depth·유전자 커버리지 상이.
- 유전자 심볼 공간이 17,004~26,577로 제각각 → 하모나이제이션 필요.

---

## 2. 2단계 — 핵심 설계 원칙 결정

> **악성세포는 세포상태가 아니라 "환자"로 뭉친다** (사적 CNV가 전사체 지배). 반면 **비악성 면역·기질세포는 계통 정체성으로 뭉쳐 암종을 넘어 통합된다.**

이 한 문장이 전체 설계를 결정:

| 구획 | 방법 | 이유 |
|---|---|---|
| 비악성 (Use 1) | scVI/Harmony **통합** | 계통 보존 → 공유 TME 참조 성립 |
| 악성 (Use 2) | **통합 안 함.** 표본별 cNMF → 교차표본 메타프로그램 | 통합하면 환자별 덩어리(과소보정) 또는 생물학 소거(과대보정). Gavish/Tirosh 2023 방식 |

상세 설계는 `BioIDE_TME_ATLAS.md`에 정리.

---

## 3. 3단계 — 파이프라인 스캐폴드

`modules/scrna-seq/pipelines/pan-cancer-atlas/`에 **데이터 주도(data-driven)** 파이프라인 생성. BioIDE 모듈 레지스트리가 런타임에 읽으므로 TypeScript 변경 없이 드롭인.

생성한 파일:
- **`inputs.json`** — 11개 소스 h5ad 경로 + obs 컬럼 매핑 + **계통 통제 어휘(lineage_map)** + TME 계통 집합. *코드가 아닌 이 JSON만 고치면 스터디 추가/이동 가능.*
- **`pipeline.json`** — 10단계 매니페스트(한국어 UI, `produces`, AI 시스템 프롬프트 + 프리셋 5개, help/glossary).
- **`00_setup_env.sh`** — 공유 venv에 `scvi-tools` + `cnmf` 추가.
- **`00_harmonize.py`** — 스키마·유전자·라벨 표준화, TME/악성 분리, 원시 카운트 가용성 감지.
- **`01_tme_integrate.py`** — Use 1: scVI(카운트 있을 때) 또는 Harmony 폴백 → Leiden → UMAP.
- **`02_tme_annotate.py`** — 15개 TME 세포상태 서명 채점 → 세포상태×암종 출현 매트릭스.
- **`03_malignant_nmf.py`** — Use 2: 표본별 NMF.
- **`04_meta_programs.py`** — 프로그램을 Jaccard로 클러스터링 → 재발성 메타프로그램.
- **`05_progression.py`** — Use 3: 범암종 탈분화 궤적.
- **`06_validate.py`** — 자기일관성 검증 → AGREE/PARTIAL/DISAGREE.
- **`07_make_report.py`** — 모든 그림·요약을 PDF로.
- **`run_harmonize.sh` / `run_tme_integrate.sh`** — 래퍼(GHBIO_RESULTS 준수).
- **`README.md`** — 사용법·TODO.

스캐폴드 직후 **소규모 스모크 테스트**(melanoma+GBM 2개)로 `00→03→04`가 동작함을 확인:
8,094 악성세포 → 198 프로그램 → 23 메타프로그램, **MP1 = 세포주기**(UBE2C/TYMS/CDK1/TOP2A) 도출 — 기대한 생물학 확인.

---

## 4. 4단계 — 전체 11개 스터디 하모나이제이션 실행

```
python 00_harmonize.py --results <RESULTS> --force
```

결과(핵심 수치):
- **공통 유전자: 13,845개** (11개 스터디 교집합 → scVI/아틀라스 유전자 공간)
- **Use 1 (TME, 비악성): 588,587 세포**
- **Use 2 (악성): 117,036 세포**

TME 계통 조성(588k):
| 계통 | 세포수 |
|---|---:|
| T/NK | 265,866 |
| Myeloid | 104,203 |
| Fibroblast/CAF | 53,457 |
| B | 38,189 |
| Endothelial | 34,642 |
| B/Plasma | 34,335 |
| Plasma | 23,980 |
| NK | 15,642 |
| Mast | 7,933 |
| Pericyte/Stellate | 5,682 |
| Dendritic | 4,658 |

**실행 중 드러난 한계**:
- **Maynard(scrna-seq-gpu-modern-reanalysis)는 tme=0, malignant=0** — `cell_type`·악성 컬럼이 없어 전 세포가 Unknown → 제외. 따라서 **유효 아틀라스는 10개 암종**.
- 원시 카운트는 **puram·Maynard만** 보유, 나머지 9개는 `NEEDS RECOVERY` → Stage 2는 scVI 대신 **Harmony 폴백** 사용.

---

## 5. 5단계 — 각 스테이지 실행

### Use 2 (악성) — NMF → 메타프로그램
```
python 03_malignant_nmf.py --k 8 --min-cells 50
python 04_meta_programs.py
```
결과: **177 표본 × 10 암종 → 1,416 프로그램 → 124 메타프로그램**, 그중 **13개가 재발성(≥3 암종)**.

명명한 재발성 메타프로그램(교과서적 범암 프로그램):

| MP | 암종수 | 프로그램 | 대표 유전자 |
|---|---:|---|---|
| **MP1** | **9/10** | **세포주기(G2/M)** | UBE2C, BIRC5, CCNB1/2, TOP2A, CDC20, TPX2 |
| **MP122** | 7 | **스트레스/AP-1 즉시초기반응** | JUN, FOS, FOSB, JUNB, EGR1, ATF3 |
| MP12 | 6 | *면역 오염(QC)* | CD3D, CD3E, CCL5, PTPRC |
| MP113 | 6 | *미토콘드리아/저품질(QC)* | MT-CO1/2/3, MT-ND1-5 |
| **MP19** | 5 | **저산소(Hypoxia)** | NDRG1, SLC2A1, HILPDA, VEGFA, DDIT4 |
| **MP59** | 4 | **인터페론/ISG** | ISG15, IFIT3, MX1, OAS1, IFI6 |
| MP82 | 4 | 상피 분비(GI 특이) | TFF1/2/3, SPINK1, AGR2 |
| **MP2** | 3 | **세포주기(S기)** | PCNA, TYMS, GMNN, MCM3 |
| MP11 | 3 | **MHC-II 항원제시** | CD74, HLA-DRA/DP/DQ |
| MP58 | 3 | 염증/IFN-γ | SOD2, CXCL10, TAP1 |

각 소스 논문의 사적 발견(흑색종 MITF↔AXL, GBM 4상태, 폐 tS1/2/3, 두경부 p-EMT)이 이 공통 프레임의 한 단면으로 통합됨. (MP12·MP113은 QC 아티팩트 — 출판 전 제거 권장.)

### Use 3 (진행) — 탈분화 궤적
```
python 05_progression.py
```
5개 암종 중:
- **갑상선(Thyroid PTC): 깨끗한 단조 탈분화** — Paratumor 0.39 → Primary 0.32 → LN met 0.19 → **Distant met −0.08** (TG/TPO/PAX8 상실). Pu 2021 주장 재현.
- 두경부·폐: 부분 재현(전이 조직이 가장 탈분화).
- 간(Ma): noisy(악성 간세포가 계통상 ALB/CYP 유지).

### Use 1 (TME) — 통합 → 주석
```
python 01_tme_integrate.py --max-per-sample 1000   # 균형 + 속도
python 02_tme_annotate.py
```
Harmony로 **200,841 세포**(1000/표본 상한) 통합 → **24 Leiden 클러스터** → 15개 세포상태 채점 → 세포상태×암종 출현 매트릭스.

세포상태×암종 출현(공유 vs 조직특이):
- **보편(10/10)**: CD8 세포독성 T, C1Q⁺ TAM, naive/memory T
- **준보편(8~9)**: B, Treg, tip 내피, monocyte, NK, cDC, myCAF, plasma
- **맥락특이(5)**: **CD8 소진(exhausted)** — HNSCC·두경부·간·흑색종 등 면역원성 종양에만 (면역치료 관련 신호)
- **부재(0)**: iCAF — 마커가 클러스터를 지배 못 함(해상도/마커 튜닝 필요)

### 검증 + 리포트
```
python 06_validate.py
python 07_make_report.py
```

---

## 6. 6단계 — 실행 중 만난 버그와 수정 (정직한 기록)

스캐폴드가 첫 실행에 완벽하진 않았다. 다음을 실제로 만나 고쳤다:

1. **anndata nullable 문자열 쓰기 거부** — 최신 anndata가 `pd.arrays.StringArray` 쓰기를 기본 거부. → `ad.settings.allow_write_nullable_strings=True` opt-in (00/01/02).
2. **03이 빈 Maynard 파일에서 크래시** — Maynard 악성 h5ad가 0 세포인데 정규화 시도 → `ValueError: 0 sample(s)`. 03은 루프 끝에만 결과를 쓰므로 9개 스터디 작업이 통째로 소실. → 로드 직후 `if a.n_obs < min_cells: continue` 가드 추가.
3. **Harmony(scanpy 래퍼) 형태 오류** — `sc.external.pp.harmony_integrate`의 obsm write-back이 버전 간 취약(shape mismatch). → `harmonypy`를 **직접 호출**로 전환.
4. **harmonypy 2.0 API 변경** — 직접 호출도 실패. 경험적 디버깅으로 확인: harmonypy 2.0.0의 `ho.Z_corr`는 **이미 (cells, PCs)** 형태(구버전은 (PCs, cells)). 내 `.T`가 형태를 뒤집고 있었음. → 전치 제거 + 양쪽 API 대응 가드(`if Z.shape[0] != n_obs: Z = Z.T`). **이것이 마지막 실질 버그** — 이전 두 번의 "성공(exit 0)"은 사실 Harmony가 조용히 uncorrected PCA로 폴백한 것이었다.
5. **Leiden 속도** — leidenalg가 334k 세포에서 18분+ (실행 중 확인: `State R`, 58 threads, 12 GB). → **igraph 백엔드**(`flavor="igraph"`)로 전환 + 상한을 1000/표본으로 낮춰 재실행 → 수 분으로 단축, Harmony가 실제 적용됨(클러스터 45→24로 정돈, 통합 성공 신호).

각 수정 후 재실행은 백그라운드 + 파일-대기 체이닝으로 자동 캐스케이드(통합→주석→검증→리포트)했다.

---

## 7. 최종 결과

### ✅ 판정: **AGREE (3/3)**
| 검증 | 결과 |
|---|---|
| U1 공유 TME 상태 | ✅ **12개 상태**가 ≥3 암종에 출현 |
| U2b 재발성 메타프로그램 | ✅ **13개 MP**가 ≥3 암종에 걸침 |
| U3 탈분화 축 | ✅ **5개 암종**에 진행단계 악성세포 |

### 산출물 (`~/ghbio-workspace/projects/pan-cancer-atlas/results/`)
- `harmonized/*.{tme,malignant}.h5ad` (22개), `harmonize_manifest.{csv,json}`, `common_genes.txt`, `lineage_composition.csv`
- `tme_atlas.h5ad`, `umap_tme_{lineage,cancer,leiden}.png`, `tme_cellstate_occurrence.{csv,png}`
- `malignant_programs.{csv,json}`, `meta_programs.json`, `mp_occurrence.{csv,png}`
- `progression_scores.csv`, `progression_dedifferentiation.png`
- `atlas_validation_{summary.csv,verdict.txt}`
- **`GHBIO_pan_cancer_atlas_report.pdf`** (≈660 KB)

---

## 8. 7단계 — 배포

```
# package.json version 0.9.30 → 0.9.31
bash build.sh                                   # esbuild → vsix(zip) → code-server 설치 → 서비스 재시작
rm -rf ~/.local/share/code-server/extensions/ghbio.ghbio-coscientist-0.9.30   # stale 제거
systemctl --user restart ghbio-code
```
- 배포 전 `npx tsc --noEmit` 통과, pipeline.json 파싱 확인.
- `build.sh`가 `modules/`를 vsix에 포함 → 파이프라인 전체(9개 스크립트+매니페스트)가 설치본에 존재함을 확인.
- 서비스 `active`, 설치본 버전 `0.9.31`.

### 사용자가 아틀라스를 보는 곳
- **워크벤치(rna.bioide.org) → GHBIO Home** — 홈이 레지스트리의 모든 파이프라인을 자동 나열하므로 **"범암종 아틀라스" 카드가 자동 노출**. 클릭 → Dashboard(9단계·결과·AI 패널·PDF).
- ⚠️ 새 번들 반영을 위해 브라우저 **Ctrl+Shift+R**.
- (참고) 공개 랜딩 `www.bioide.org`(정적 `~/ghbio-landing/index.html`)와 in-IDE "Verified Reproductions" 표에는 아직 미노출 — 아틀라스는 11개 논문 메타분석이라 '1논문=1행' 모델에 맞지 않아 별도 showcase 카드가 적합.

---

## 9. 한계 (출판/확장 전 처리 권장)

1. **Harmony 사용(scVI 아님)** — 9/11 스터디에 원시 카운트가 없어서. 카운트 복원 시 scVI로 업그레이드.
2. **Maynard 제외** — 세포유형/악성 라벨 부재 → 유효 10개 암종.
3. **1000 세포/표본 상한** — 속도용. 588k 중 ~201k만 사용. 최종본은 상한 상향.
4. **QC 메타프로그램 2개**(MP12 면역·MP113 미토) 필터 후 게시.
5. **iCAF 부재·CD8 소진 거칠음** — 마커 서명/해상도 튜닝 필요.

---

## 10. 재현 방법 (처음부터)

```
cd modules/scrna-seq/pipelines/pan-cancer-atlas
export GHBIO_RESULTS=~/ghbio-workspace/projects/pan-cancer-atlas/results
bash 00_setup_env.sh
bash run_harmonize.sh                                  # 11개 → TME/악성 분리
bash run_tme_integrate.sh --max-per-sample 1000        # Use 1
~/ghbio-venv/bin/python 02_tme_annotate.py             # Use 1 주석
~/ghbio-venv/bin/python 03_malignant_nmf.py --k 8      # Use 2
~/ghbio-venv/bin/python 04_meta_programs.py            # Use 2
~/ghbio-venv/bin/python 05_progression.py              # Use 3
~/ghbio-venv/bin/python 06_validate.py                 # 판정
~/ghbio-venv/bin/python 07_make_report.py              # PDF
```
전 단계 `GHBIO_RESULTS` 준수, 재실행 가능(idempotent), Stage 2~6은 GPU 우선·CPU 폴백.

---

### 관련 문서
- `raw_dataset_BioIDE.md` — 원본 데이터셋 인벤토리(세포수·암종·검증상태)
- `BioIDE_TME_ATLAS.md` — 상세 설계 계획(Use 1+2 방법론)
- `modules/scrna-seq/pipelines/pan-cancer-atlas/README.md` — 파이프라인 사용법
