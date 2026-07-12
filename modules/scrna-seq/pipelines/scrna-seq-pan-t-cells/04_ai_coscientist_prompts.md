# Step 4 — Feeding results into the GHBIO AI Co-Scientist

결과를 GHBIO AI Co-Scientist에 입력해 가설을 생성하는 방법입니다. (교모세포종 샘플)

After `03_scanpy_qc.py` you have:

- `~/ghbio-tutorial/results/markers_by_cluster.csv` — top 25 marker genes per cluster
- `~/ghbio-tutorial/results/celltype_draft.csv` — cluster → draft brain-tumor cell type
- `~/ghbio-tutorial/results/umap_clusters.png` — the UMAP
- the printed summary table

This page shows **(a)** a paste-in template and **(b)** ~10 strong prompts to ask the AI.

> Glioblastoma tissue is very different from blood: expect **malignant glioma cells** mixed
> with the **tumor microenvironment (TME)** — astrocytes, oligodendrocytes/OPCs, neurons,
> microglia and tumor-associated macrophages (TAMs), T cells, endothelium and pericytes.

---

## (a) Context template — paste this into the Co-Scientist first

Fill in the `<...>` fields from your CSV outputs, then send it as your first message.
아래 템플릿의 `<...>` 부분을 CSV 결과로 채워 첫 메시지로 보내세요.

```
[EXPERIMENT / 실험 개요]
- Sample: 10x Genomics scRNA-seq, human glioblastoma (dissociated tumor, 3' v3 chemistry)
- Reference: GRCh38 (GENCODE), aligned/counted with STARsolo
- Analysis: Scanpy — QC, normalize_total+log1p, HVG, PCA, Leiden clustering, Wilcoxon markers
- Cells after QC: <N_CELLS>   Clusters: <N_CLUSTERS>

[PER-CLUSTER MARKERS + DRAFT ANNOTATION / 클러스터별 마커 및 초안 주석]
| cluster | n_cells | draft_celltype | matched_markers | top marker genes (by Wilcoxon) |
|---------|---------|----------------|-----------------|--------------------------------|
| 0       | <...>   | <...>          | <...>           | <gene1, gene2, gene3, ...>     |
| 1       | <...>   | <...>          | <...>           | <...>                          |
| ...     |         |                |                 |                                |

[KEY PATHWAYS / GENE SETS OF INTEREST (optional) / 관심 경로·유전자셋]
- <e.g. hypoxia: VEGFA, HIF1A, CA9 up in cluster 3>
- <e.g. proliferation: MKI67, TOP2A in cluster 5>

[QUESTION / 질문]
<one of the prompts below>
```

> Tip: paste the raw `markers_by_cluster.csv` and `celltype_draft.csv` contents directly —
> the Co-Scientist can read tabular text. Attach `umap_clusters.png` if the UI allows images.

---

## (b) Strong analysis / hypothesis-generation prompts

Ask these one at a time. Each is bilingual (Korean / English).
아래 프롬프트를 하나씩 물어보세요.

1. **Malignant vs. normal / 종양세포 vs 정상세포 구분**
   > 어떤 cluster가 악성 종양세포(glioma)이고 어떤 것이 정상 미세환경(TME) 세포인지
   > 마커 근거와 함께 판단해줘. (EGFR/SOX2/PTPRZ1 등 악성 신호 vs 정상 계통)
   > Which clusters are malignant glioma cells vs. normal TME cells? Use marker evidence
   > (malignant programs like EGFR/SOX2/PTPRZ1 vs. normal lineage markers).

2. **Confirm or challenge the draft annotation / 초안 주석 검증**
   > celltype_draft.csv의 자동 주석이 각 클러스터에서 타당한지 마커 근거와 함께 평가하고,
   > 재검토가 필요한 클러스터를 지적해줘.
   > Assess whether each draft cell-type label is well supported by its markers. Flag any
   > cluster whose annotation is ambiguous, mixed, or likely wrong, and say why.

3. **Glioma cellular states / 교모세포종 세포 상태**
   > 악성 cluster들을 Neftel et al.의 상태(NPC-like, OPC-like, AC-like, MES-like)로
   > 분류할 수 있는지, 어떤 마커가 근거가 되는지 설명해줘.
   > Can the malignant clusters be mapped onto the Neftel glioblastoma states
   > (NPC-like, OPC-like, AC-like, MES-like)? Give the marker evidence for each.

4. **Tumor-associated immune infiltrate / 종양 관련 면역 침윤**
   > 미세아교세포(microglia)와 골수 유래 대식세포(TAM), T 세포를 구분하고 각 집단의 활성화
   > 상태(예: 염증성/면역억제성)에 대한 가설을 세워줘.
   > Distinguish resident microglia from monocyte-derived TAMs and T cells, and hypothesize
   > each population's activation state (inflammatory vs. immunosuppressive/M2-like).

5. **Pathway / enrichment interpretation / 경로 및 농축 해석**
   > cluster N의 상위 마커로 GO/KEGG/Reactome 농축 분석을 한다면 어떤 경로가 두드러질지 예측하고,
   > 그 생물학적 의미를 설명해줘 (예: 저산소증, 혈관신생, EMT-유사, 증식).
   > Predict which GO/KEGG/Reactome pathways would be enriched among cluster N's top markers,
   > and interpret the biology (hypoxia, angiogenesis, EMT-like, proliferation).

6. **Cross-cluster differential biology / 클러스터 간 차별 생물학**
   > 같은 계통으로 보이는 cluster A와 cluster B를 구분하는 핵심 유전자와 그것이 시사하는
   > 기능적 차이(예: 증식성 vs 침습성)에 대한 가설을 세워줘.
   > Clusters A and B look like the same lineage — what key genes separate them, and what
   > functional difference (e.g. proliferative vs. invasive) does that imply?

7. **Composition & tumor architecture / 세포 구성과 종양 구조**
   > 이 샘플의 종양세포 대 미세환경 세포 비율과 면역 침윤 정도를 평가하고, 예후·치료 반응과
   > 관련될 수 있는 특징이 있으면 알려줘.
   > Assess the malignant-to-TME ratio and the degree of immune infiltration in this sample,
   > and flag any features that might relate to prognosis or therapy response.

8. **Rare / novel population detection / 희귀·신규 집단**
   > 세포 수가 적은 클러스터 중에서 희귀하지만 의미 있는 집단(예: 종양 줄기세포-유사,
   > 증식성 전구세포, 혈관주위세포)을 근거 마커와 함께 제시해줘.
   > Among the small clusters, identify any rare but meaningful population (glioma stem-like,
   > cycling progenitor, perivascular niche) and give the marker evidence.

9. **Suggested follow-up experiments / 후속 실험 제안**
   > 위 가설들을 검증하기 위한 후속 실험(예: 면역조직화학, spatial transcriptomics, CNV 추론,
   > 특정 유전자 넉다운, 약물 반응 assay)을 우선순위와 함께 제안해줘.
   > Propose follow-up experiments to validate the top hypotheses (IHC, spatial transcriptomics,
   > CNV inference, gene knockdown, drug-response assays), ranked by expected information gain.

10. **Prioritized list of further analyses / 추가 분석 우선순위**
    > 이 데이터로 다음에 수행할 계산 분석(예: inferCNV로 악성세포 확인, 세포주기 회귀,
    > trajectory/pseudotime, cell-cell communication, TME 통합)을 우선순위와 이유와 함께 목록으로 만들어줘.
    > Give a prioritized list of next computational analyses (inferCNV to confirm malignancy,
    > cell-cycle regression, trajectory/pseudotime, cell-cell communication, TME integration),
    > each with a one-line rationale.

---

## Suggested workflow with the Co-Scientist / 권장 사용 흐름

1. Send the **context template (a)** filled with your real numbers.
2. Ask prompt **#1** to separate malignant tumor cells from the microenvironment.
3. Ask prompt **#2** to sanity-check the automatic annotation.
4. Use **#3–#7** to characterize glioma states and the immune TME.
5. Close with **#9** and **#10** to plan validation and next analyses.

> 결과를 붙여넣은 뒤, #1로 종양/정상세포를 나누고 → #2로 주석을 점검하고 →
> #3~#7로 교모세포종 상태와 면역 미세환경을 분석하고 → #9, #10으로 검증·후속 분석 계획을
> 세우는 순서를 권장합니다.
