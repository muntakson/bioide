# BioIDE 범암종(Pan-Cancer) 아틀라스 상세 계획

**Use 1 — 범암종 TME 통합 아틀라스 (비악성 세포)**
**Use 2 — 악성세포 재발성 메타프로그램(recurrent meta-programs)**

작성일: 2026-07-17 · 대상 기질(substrate): 검증 완료 11개 파이프라인, **≈795,700 세포 · 9개 암종**

---

## 0. 목표 한 줄 요약

이미 각 파이프라인이 **저자 라벨 없이 GPU-Python으로 독립 재현**해 놓은 11개 h5ad를 하나로 모아,

- **Use 1**: 여러 암종에 걸쳐 **면역·기질(TME) 세포 상태**가 공유되는지 / 조직특이적인지를 보이는 **통합 참조 아틀라스**
- **Use 2**: **악성세포**의 전사 프로그램 중 모든 암에서 **반복 출현하는 메타프로그램**(세포주기·저산소·EMT·스트레스·인터페론·탈분화 등) 지도

를 만든다. 두 구획을 **다른 방법**으로 다루는 것이 이 계획의 핵심이다.

---

## 1. 입력 데이터 실측 스키마 (디스크에서 직접 확인)

| 파이프라인 | 암종 | 세포수 | 유전자 | 플랫폼 | 계통 라벨 컬럼 | 악성 라벨 컬럼 | 배치 키 | 진행 축 |
|---|---|---:|---:|---|---|---|---|---|
| lung-adeno-kim2020 | 폐선암 | 207,900 | ~20k | 10x/UMI | `cell_type` (9) | `malignant_call` | `sample` | `origin_label` (nLung→tLung→mLN→mBrain) |
| thyroid-cancer-ptc-pu2021 | 갑상선유두암 | 195,928 | 24,358 | 10x/UMI | `cell_type` (9) | `malignant_call` | `sample`/`patient` | `site` (Primary→LN→Distant) |
| gastric-cancer-kumar2022 | 위암 | 158,641 | 23,968 | 10x/UMI | `cell_type` (9) | `malignant_call` | `sample`(24+) | `site`(Tumor) |
| hcc-tls-lu2022 | 간암(HCC)+TLS | 71,915 | 23,628 | 10x/UMI | `cell_type` (6) | `malignant_call` | `sample`/`patient` | `site`(Normal→Tumor→PVTT→Lymph) |
| pancreatic-cancer-sc-rna-seq | 췌장암(PDAC) | 57,423 | 17,004 | 10x/UMI | `cell_type` (9)* | `malignant_call` | `Patient`/`Type` | `Type`(N/T) |
| hnscc-progression-choi2023 | 두경부암 | 54,224 | 20,000 | 10x/UMI | `cell_type` (9) | `malignant_call` | `sample` | `stage`(NL→LP→CA→LN) |
| therapy-evolution (Maynard) | 폐암(치료) | 21,620 | 26,577 | Smart-seq2 | (별도) | (치료상태) | `sample_name`/`patient_id` | `treatment_type`, `biopsy_site` |
| liver-cancer-ma2019 | 간암(HCC/iCCA) | 9,549 | 18,372 | 10x/UMI | `cell_type` (6: B/CAF/Epi/T/TAM/TEC) | `malignant_call`(+HPC-like) | `sample` | `set` |
| glioblastoma-neftel-2019 | 교모세포종 | 7,930 | 21,723 | Smart-seq2 | `cell_type` (4) | `cell_type=Malignant` | `tumor` | — (4상태 축) |
| puram-2017-hnscc-pemt | 두경부암 p-EMT | 5,902 | 21,485 | Smart-seq2 | `noncancer_celltype` | `cnv_malignant_pred` | `_batch` | `lymph_node` |
| scrna-seq-melanoma-tirosh | 흑색종 | 4,645 | 23,686 | Smart-seq2 | `celltype` | `malignant` | `tumor` | — |

\* PDAC는 `cell_type`, `Cell_type`, `celltype0~3`, `dblabel` 등 다중 계통 컬럼을 가짐 → 하모나이제이션 필요.

**즉시 드러나는 사실**
- **7개(gastric/hcc/hnscc/liver/lung/pancreatic/thyroid)는 스키마가 사실상 동일**: `cell_type` + `malignant_call{악성/정상/n/a}` + `sample`/`patient` + 진행축 + `X_pca_harmony`(연구 내부 배치보정 완료).
- **3개(GBM/melanoma/puram)는 Smart-seq2**(full-length, UMI 없음) → depth·유전자 커버리지가 다름 → **배치 공변량에 platform 반드시 포함**.
- **유전자 심볼 공간이 17,004~26,577로 제각각** → 심볼 하모나이제이션 후 **교집합(≈13~15k) 또는 scVI용 공통 HVG**로 통일.
- 계통 어휘가 연구마다 다름(`T-NK cell` vs `T cell`+`NK`, `Macrophage-Myeloid` vs `Myeloid`, `B-Plasma` vs `B`+`Plasma`) → **통제 어휘(controlled vocabulary) 매핑 필수**.

---

## 2. 핵심 설계 원칙 — 왜 두 구획을 나누는가

> **악성세포는 세포상태가 아니라 "환자"로 뭉친다.** 각 종양의 사적(private) CNV/복제수 프로파일이 전사체를 지배하기 때문. 반대로 **비악성 T/골수성/섬유아/내피세포는 계통 정체성으로 뭉쳐 암종을 넘어 잘 통합된다.**

따라서:

| 구획 | 방법 | 이유 |
|---|---|---|
| **비악성 (Use 1)** | scVI/Harmony **통합** → 공통 UMAP/클러스터 | 계통이 보존돼 통합이 성립 → "여러 암 공통 TME 참조" |
| **악성 (Use 2)** | **통합하지 않음.** 표본별 cNMF → 프로그램 → 교차표본 클러스터링 | 통합하면 환자별 덩어리(과소보정) 또는 생물학 소거(과대보정). 재발성 프로그램은 통합 없이 발견해야 함 (Gavish/Tirosh 2023 *Nature* 방식) |

이 원칙 하나가 아래 모든 단계를 결정한다.

---

## 3. 공통 전처리 / 스키마 하모나이제이션 (Stage 0)

산출: `~/ghbio-workspace/projects/pan-cancer-atlas/` (신규 프로젝트, `GHBIO_RESULTS` 규약 준수)

### 3-1. 통제 어휘(controlled vocabulary) 매핑
각 연구의 `cell_type` → **공통 계통 레이블 15종**으로 사전 매핑 (JSON 테이블로 관리):

```
CD4 T · CD8 T · NK · T/NK(미분리) · B · Plasma · Myeloid/Macrophage ·
Dendritic · Mast · Neutrophil · Endothelial · Fibroblast/CAF ·
Pericyte/Stellate · (정상 상피: 조직특이) · Malignant(→Use 2로 분리)
```
- 예: `T-NK cell`→`T/NK`, `Macrophage-Myeloid`→`Myeloid`, `B-Plasma cell`→`B`+`Plasma`(재클러스터로 분리), `CAF`/`TAM`/`TEC`(liver)→`Fibroblast/CAF`/`Myeloid`/`Endothelial`.
- 조직특이 정상 상피(Hepatocyte/Thyrocyte/Ductal/Acinar/Oligodendrocyte)는 **TME 아틀라스에서 제외**하되 별도 태그 보존.

### 3-2. 유전자 심볼 하모나이제이션
- 모든 var를 HGNC 최신 심볼로 통일(별칭·구심볼 매핑), 중복 심볼 합산.
- **공통 유전자 교집합** 계산(예상 ≈13~15k) → scVI 입력. cNMF는 표본별이라 각자 유전자 사용 가능.

### 3-3. 배치 키 정의
- `study_id`(11), `sample`(연구내 표본), `platform`{10x, smartseq2} 를 obs에 표준화.
- scVI 배치 공변량: **`sample` + `platform`**(연구는 sample에 종속되므로 자동 포함), 연속 공변량: `pct_counts_mito`, `total_counts`(log).

### 3-4. 원시 카운트 확보
- scVI/cNMF는 **원시 카운트**가 필요. `layers['counts']`가 있는 것(puram, Maynard)은 그대로, 없는 7개는 각 파이프라인의 `01~03` 단계 재실행 또는 저장된 정규화 전 행렬에서 복원. (없으면 해당 파이프라인 raw h5ad 재생성 스텝 추가.)

---

## 4. Use 1 — 범암종 TME 통합 아틀라스 (비악성)

### 스테이지
1. **추출**: 11개 h5ad에서 `malignant_call ∈ {정상, n/a}` **AND** 계통이 면역·기질인 세포만 추출 (악성·정상상피 제외). 예상 규모: 전체의 60~70% ≈ **45만~55만 세포**.
2. **병합**: 공통 유전자 교집합으로 concat, obs에 `study_id/cancer/platform/sample` 부여.
3. **HVG**: `seurat_v3`, batch-aware, 2,000~3,000개.
4. **통합**: **scVI**(GPU) — `batch_key=sample`, `categorical_covariate=[platform]`, `continuous_covariate=[pct_mito, log_counts]`, latent 30차원. (대안: `X_pca_harmony`가 이미 있는 7개는 참고용, 신규 통합은 scVI로 일원화.)
5. **클러스터링**: latent → neighbors → Leiden(GPU/rapids) → 계통·세포상태 주석.
6. **세포상태 주석**: 표준 마커 스코어로 하위상태 라벨 —
   - CD8: cytotoxic / exhausted(진행표지) / memory
   - 골수성: SPP1⁺ TAM / C1Q⁺ / 단핵구유래 / cDC / pDC
   - 섬유아: myCAF / iCAF / apCAF
   - 내피: tip / venous / lymphatic
7. **공유 vs 조직특이 분석**:
   - 각 세포상태가 **몇 개 암종에서 나타나는지**(occurrence) 집계 → "범암 공통 hallmark 상태" vs "특정 암 전용".
   - 세포상태 조성을 진행축(정상→종양→전이)에 따라 비교.

### 산출물
- `tme_atlas.h5ad` (통합 latent + 공통 UMAP + 세포상태 라벨)
- `tme_cellstate_occurrence.csv` (상태 × 암종 출현 매트릭스)
- 그림: 통합 UMAP(암종/계통/상태), 상태별 암종 출현 히트맵, 진행축별 조성 막대
- 대화형: 세포상태 하나를 골라 **여러 암에서** feature/dot plot (아틀라스 explorer 확장)

---

## 5. Use 2 — 악성세포 재발성 메타프로그램

> **통합하지 않는다.** Gavish/Tirosh 2023 *Nature* "hallmarks of transcriptional intratumor heterogeneity" 방식.

### 스테이지
1. **악성세포 추출**: `malignant_call = 악성*` / GBM `cell_type=Malignant` / melanoma `malignant`=malignant / puram `cnv_malignant_pred=malignant`. 예상 **20만~25만 세포**.
2. **표본별 분해**: **각 표본(sample) 안에서** cNMF(consensus NMF) 실행, K=예: 5~10개 프로그램/표본. (표본별이므로 배치효과 없음.)
   - 표본당 최소 세포수(예 ≥50 악성세포) 필터 → 적격 표본만.
3. **프로그램 수집**: 모든 표본의 모든 프로그램(각 = 상위 유전자 랭킹 벡터)을 모음(수백~수천 개).
4. **교차표본 클러스터링**: 프로그램 간 유전자중복(Jaccard/코사인)으로 클러스터링 → **재발성 메타프로그램(MP)** 도출.
5. **주석**: 각 MP를 상위 유전자·GO/hallmark로 명명 —
   - 예상 공통 MP: Cell cycle, Hypoxia, EMT/pEMT, Stress, Interferon/IFN, Respiration/Metabolism, Astrocyte/AC-like 등 조직특이.
6. **암종 교차 매핑**: MP × 암종 출현표 → 어떤 프로그램이 **모든 암에 공통**이고 어떤 것이 계통특이인지. 각 파이프라인의 기존 결론(흑색종 MITF↔AXL, 폐 tS1/2/3, GBM 4상태, HNSCC p-EMT)을 **하나의 MP 프레임으로 통일**.

### 산출물
- `malignant_programs_per_sample.csv` (표본 × 프로그램 × 유전자)
- `meta_programs.json` (MP 정의 + 유전자 서명 + 출현 암종)
- `mp_occurrence_heatmap.png` (MP × 암종)
- 각 세포에 MP 스코어 부여한 `malignant_scored.h5ad`

---

## 6. Use 3 (보너스) — 탈분화 / 진행 축

4개 데이터셋(lung Kim `origin_label`, HCC Lu `site`, HNSCC Choi `stage`, thyroid Pu `site`)이 **정상→종양→전이 단계 라벨**을 가짐.
- 악성세포의 "정상조직 정체성 상실 점수"(각 파이프라인의 gds/hds/normalduct/thyrocyte score 재활용)를 진행단계에 따라 정렬 → **암종을 가로지르는 공통 탈분화 궤적** 히어로 그림 1장.

---

## 7. 검증 (BioIDE 헌법 준수: 저자 라벨 비소비, 정량 검증)

- **Use 1**: 통합 후에도 계통 마커가 정상 발현(무결성), 배치 대비 생물변수 분리(iLISI/kBET), 각 연구 원 세포수 대비 회수율.
- **Use 2**: MP가 개별 파이프라인의 기존 결론을 재현하는지(예: 흑색종 표본에서 MITF/AXL MP가, GBM에서 AC/MES/NPC/OPC MP가 재검출) → **AGREE/PARTIAL 판정** 파일 생성.
- 각 산출에 `06_validate` 스텝으로 verdict CSV → 랜딩 "Verified Reproductions" 로스터 편입 후보.

---

## 8. BioIDE 통합 방식

- **신규 파이프라인**: `modules/scrna-seq/pipelines/pan-cancer-atlas/pipeline.json`
  - 스테이지: `00_harmonize` → `01_tme_integrate`(scVI) → `02_tme_annotate` → `03_malignant_nmf` → `04_meta_programs` → `05_progression` → `06_validate` → `07_report`(easyReport + paper.ts).
  - `dataSource` 없음(입력이 기존 프로젝트 산출물) → 대신 11개 h5ad 경로를 `00_harmonize`가 읽음. **모든 스크립트 `GHBIO_RESULTS` 준수.**
- **Atlas explorer 확장**(`src/atlas.ts`, `webview-src/atlas/`): 기존 NSCLC explorer를 재사용해 **범암 TME 아틀라스**를 로드(현 데이터 변환 스크립트 `convert_h5ad.py`로 `meta.json`/`expr.bin` 재생성). "세포상태 × 암종" 교차 탐색 탭 추가.
- **easyReport / paper.ts**: `paperClaim`을 "여러 암을 관통하는 공통 TME·악성 프로그램" 서사로 작성(고등학생 버전 + research 버전).

---

## 9. 단계별 실행 계획 & 예상 규모

| 단계 | 작업 | 도구 | 예상 산출 |
|---|---|---|---|
| S0 | 스키마·유전자·라벨 하모나이제이션 | scanpy/anndata | `harmonized/*.h5ad` (11개) |
| S1 | 비악성 추출·병합 | scanpy | `tme_raw.h5ad` (~50만 세포) |
| S2 | scVI 통합 + Leiden | scvi-tools(GPU), rapids | `tme_atlas.h5ad` |
| S3 | 세포상태 주석·출현분석 | scanpy | occurrence CSV + 그림 |
| S4 | 악성 추출·표본별 cNMF | cNMF | per-sample programs |
| S5 | 메타프로그램 클러스터링·주석 | scipy/scanpy | `meta_programs.json` + 히트맵 |
| S6 | 진행축 탈분화 궤적 | scanpy | 히어로 그림 |
| S7 | 검증 verdict + 리포트 | pandas + paper.ts | verdict CSV, PDF |

**계산 규모**: scVI 50만 세포 GPU 학습 수십 분~1~2시간, cNMF는 표본별 병렬(수백 표본, 각 수 분). 신규 디스크 ~수 GB(원시 카운트 복원 시 +).

---

## 10. 리스크 & 한계 (착수 전 명시)

1. **플랫폼 혼재** — Smart-seq2 3종 vs 10x 8종. depth/커버리지 상이 → 배치 공변량에 platform 필수, 필요시 Smart-seq2는 별도 검증.
2. **공통 정상 기준 없음** — "정상"은 각 연구 인접조직. 절대 비교 아님.
3. **대형 4연구가 지배**(lung/thyroid/gastric/hcc ≈ 63.5만) → GBM·흑색종이 묻힘. **표본당 상한 서브샘플링**으로 균형.
4. **원시 카운트 복원 필요**(layers['counts'] 없는 7개) → S0에 복원 스텝, 안 되면 해당 파이프라인 raw 재생성.
5. **Maynard·PDAC 다중 라벨 컬럼** → 매핑 시 어떤 컬럼을 정본으로 쓸지 명시(권장: 각 파이프라인이 최종 사용한 `cell_type`).
6. **중복 제거** — Maynard 2회(gpu-modern=therapy-evolution) 1회만, puram 6 stage-file 중 `adata_annotated.h5ad`만 사용.

---

### 부록 A. 세포 집계 재확인 (중복 제거 후)
lung 207,900 · thyroid 195,928 · gastric 158,641 · hcc 71,915 · pdac 57,423 · hnscc 54,224 · Maynard 21,620 · liver 9,549 · gbm 7,930 · puram 5,902 · melanoma 4,645 = **≈795,700 세포 · 9 암종**. 비악성 ~50만(Use 1), 악성 ~20~25만(Use 2).
