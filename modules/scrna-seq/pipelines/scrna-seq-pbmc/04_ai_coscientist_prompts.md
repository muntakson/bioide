# Step 4 — Feeding results into the GHBIO AI Co-Scientist

결과를 GHBIO AI Co-Scientist에 입력해 가설을 생성하는 방법입니다.

After `03_scanpy_qc.py` you have:

- `~/ghbio-tutorial/results/markers_by_cluster.csv` — top 25 marker genes per cluster
- `~/ghbio-tutorial/results/celltype_draft.csv` — cluster → draft PBMC cell type
- `~/ghbio-tutorial/results/umap_clusters.png` — the UMAP
- the printed summary table

This page shows **(a)** a paste-in template and **(b)** ~10 strong prompts to ask the AI.

---

## (a) Context template — paste this into the Co-Scientist first

Fill in the `<...>` fields from your CSV outputs, then send it as your first message.
아래 템플릿의 `<...>` 부분을 CSV 결과로 채워 첫 메시지로 보내세요.

```
[EXPERIMENT / 실험 개요]
- Sample: 10x Genomics scRNA-seq, human PBMC (1k cells, 3' v3 chemistry)
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
- <e.g. interferon response: ISG15, IFI6, MX1 up in cluster 3>
- <e.g. cytotoxicity: GZMB, PRF1, GNLY in cluster 5>

[QUESTION / 질문]
<one of the prompts below>
```

> Tip: paste the raw `markers_by_cluster.csv` and `celltype_draft.csv` contents directly —
> the Co-Scientist can read tabular text. Attach `umap_clusters.png` if the UI allows images.

---

## (b) Strong analysis / hypothesis-generation prompts

Ask these one at a time. Each is bilingual (Korean / English).
아래 프롬프트를 하나씩 물어보세요.

1. **Cluster identity & activation state / 세포 정체성과 활성화 상태**
   > 이 마커 조합으로 볼 때 cluster N의 세포 정체성과 활성화 상태에 대한 가설을 세워줘.
   > Given these marker genes, propose a hypothesis for the identity **and activation/differentiation
   > state** of cluster N. Distinguish resting vs. activated/effector where possible.

2. **Confirm or challenge the draft annotation / 초안 주석 검증**
   > celltype_draft.csv의 자동 주석이 각 클러스터에서 타당한지 마커 근거와 함께 평가하고,
   > 재검토가 필요한 클러스터를 지적해줘.
   > Assess whether each draft cell-type label is well supported by its markers. Flag any
   > cluster whose annotation is ambiguous, mixed, or likely wrong, and say why.

3. **Resolve ambiguous / mixed clusters / 모호하거나 혼합된 클러스터 해석**
   > 여러 세포 유형 마커가 섞여 나오는 cluster N은 doublet인지, 전이 상태인지,
   > 아니면 하위 클러스터로 더 나눠야 하는지 판단해줘.
   > For cluster N with mixed lineage markers, is this a doublet artifact, a transitional state,
   > or an under-clustered population that should be subclustered? Recommend a next step.

4. **Sub-lineage resolution (T/NK, monocyte subsets) / 세부 계통 구분**
   > T 세포 클러스터들을 CD4 naive / CD4 memory / CD8 effector / Treg 등으로 더 세분화하려면
   > 어떤 추가 마커와 분석을 봐야 할지 제안해줘.
   > Suggest additional marker genes and analyses to resolve T-cell subsets (CD4 naive/memory,
   > CD8 effector, Treg) and monocyte subsets (classical vs. non-classical).

5. **Pathway / enrichment interpretation / 경로 및 농축 해석**
   > cluster N의 상위 마커로 GO/KEGG/Reactome 농축 분석을 한다면 어떤 경로가 두드러질지 예측하고,
   > 그 생물학적 의미를 설명해줘.
   > Predict which GO/KEGG/Reactome pathways would be enriched among cluster N's top markers,
   > and interpret the biology (e.g. interferon response, oxidative phosphorylation, cytotoxicity).

6. **Cross-cluster differential biology / 클러스터 간 차별 생물학**
   > cluster A와 cluster B는 같은 계통으로 보이는데, 두 클러스터를 구분하는 핵심 유전자와
   > 그것이 시사하는 기능적 차이에 대한 가설을 세워줘.
   > Clusters A and B look like the same lineage — what key genes separate them, and what
   > functional difference (e.g. activation, exhaustion, cytokine polarization) does that imply?

7. **Composition & abundance questions / 세포 구성·비율 질문**
   > 이 PBMC 샘플의 세포 유형 구성 비율이 건강한 공여자의 전형적 분포와 얼마나 일치하는지 평가하고,
   > 이상적으로 보이는 집단이 있으면 알려줘.
   > Do the cell-type proportions match a typical healthy-donor PBMC profile? Flag any population
   > that is unexpectedly over- or under-represented and hypothesize why.

8. **Rare / novel population detection / 희귀·신규 집단**
   > 세포 수가 적은 클러스터 중에서 희귀하지만 생물학적으로 의미 있는 집단(예: pDC, Treg, MAIT,
   > progenitor)일 가능성이 있는 것을 찾아 근거 마커와 함께 제시해줘.
   > Among the small clusters, identify any that could be a rare but meaningful population
   > (pDC, Treg, MAIT, ILC, progenitor) and give the marker evidence.

9. **Suggested follow-up experiments / 후속 실험 제안**
   > 위 가설들을 검증하기 위한 후속 실험(예: flow cytometry 패널, CITE-seq 항체, 특정 유전자
   > 넉다운, 기능 assay)을 우선순위와 함께 제안해줘.
   > Propose follow-up wet-lab experiments to validate the top hypotheses (flow cytometry panels,
   > CITE-seq antibody choices, functional assays), ranked by expected information gain.

10. **Prioritized list of further analyses / 추가 분석 우선순위**
    > 이 데이터로 다음에 수행할 계산 분석(예: doublet 제거, 세포주기 회귀, trajectory/pseudotime,
    > cell-cell communication, batch integration)을 우선순위와 이유와 함께 목록으로 만들어줘.
    > Give a prioritized list of the next computational analyses to run on this dataset
    > (doublet removal, cell-cycle regression, trajectory/pseudotime, cell-cell communication,
    > batch integration), each with a one-line rationale.

---

## Suggested workflow with the Co-Scientist / 권장 사용 흐름

1. Send the **context template (a)** filled with your real numbers.
2. Ask prompt **#2** to sanity-check the automatic annotation.
3. Go cluster-by-cluster with prompt **#1** for the interesting clusters.
4. Use **#5–#8** to build biological hypotheses.
5. Close with **#9** and **#10** to plan validation and next analyses.

> 결과를 붙여넣은 뒤, #2로 주석을 점검하고 → #1로 클러스터별 정체성을 파악하고 →
> #5~#8로 생물학적 가설을 세우고 → #9, #10으로 검증·후속 분석 계획을 세우는 순서를 권장합니다.
