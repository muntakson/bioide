#!/usr/bin/env python3
"""Create descriptive, sample-aware RD/PD evidence outputs for the GPU reanalysis."""
from __future__ import annotations

import argparse
from pathlib import Path

import anndata as ad
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def column(obs: pd.DataFrame, names: list[str]) -> str | None:
    lookup = {str(c).lower(): str(c) for c in obs.columns}
    return next((lookup[n.lower()] for n in names if n.lower() in lookup), None)


def mean_score(adata: ad.AnnData, genes: list[str]) -> np.ndarray:
    present = [g for g in genes if g in adata.var_names]
    if not present:
        return np.full(adata.n_obs, np.nan)
    values = adata[:, present].X
    return np.asarray(values.mean(axis=1)).ravel()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    args = parser.parse_args()
    args.results.mkdir(parents=True, exist_ok=True)
    adata = ad.read_h5ad(args.input)
    sample_key = column(adata.obs, ["sample_name", "sample", "sample_id"])
    analysis_key = column(adata.obs, ["analysis"])
    if sample_key is None or analysis_key is None:
        raise ValueError("Author sample_name/analysis metadata is required for treatment-stage evidence outputs.")

    stage_map = {"naive": "TN", "grouped_pr": "RD", "grouped_pd": "PD"}
    obs = adata.obs.copy()
    obs["treatment_stage"] = obs[analysis_key].astype(str).map(stage_map)
    obs["cluster"] = obs["leiden_scvi"].astype(str)
    obs = obs[obs["treatment_stage"].isin(["TN", "RD", "PD"])].copy()
    order = ["TN", "RD", "PD"]

    # Composition is descriptive; report fractions within each stage, not p-values over cells.
    comp = obs.groupby(["treatment_stage", "cluster"], observed=True).size().rename("n_cells").reset_index()
    comp["fraction_within_stage"] = comp["n_cells"] / comp.groupby("treatment_stage", observed=True)["n_cells"].transform("sum")
    comp.to_csv(args.results / "treatment_stage_cluster_composition.csv", index=False)
    pivot = comp.pivot(index="treatment_stage", columns="cluster", values="fraction_within_stage").fillna(0).reindex(order, fill_value=0)
    ax = pivot.plot(kind="bar", stacked=True, figsize=(9, 5), colormap="tab20", width=0.75)
    ax.set_ylabel("Fraction of cells within treatment stage")
    ax.set_xlabel("Treatment stage (author metadata mapping)")
    ax.set_title("scVI/Leiden cluster composition by treatment stage\nDescriptive supportive reanalysis — not clinical proof")
    ax.legend(title="Cluster", bbox_to_anchor=(1.02, 1), loc="upper left", fontsize=8)
    plt.tight_layout()
    plt.savefig(args.results / "treatment_stage_cluster_composition.png", dpi=180)
    plt.close()

    # These published-paper-inspired programs are summarized per sample, avoiding cell-level
    # pseudoreplication. They are not a cancer-cell-only analysis: CNV/driver filtering is needed.
    alveolar = ["AQP4", "SFTPB", "SFTPC", "SFTPD", "CLDN18", "FOXA2", "NKX2-1", "PGC", "SUSD2", "CAV1"]
    pd_program = ["IDO1", "PLAU", "PLAUR", "SERPINE1", "GJA1"]
    obs["alveolar_injury_repair_score"] = mean_score(adata, alveolar)[obs.index.map(adata.obs_names.get_loc)]
    obs["pd_resistance_program_score"] = mean_score(adata, pd_program)[obs.index.map(adata.obs_names.get_loc)]
    sample_scores = (
        obs.groupby([sample_key, "treatment_stage"], observed=True)
        .agg(n_cells=("cluster", "size"), alveolar_injury_repair_score=("alveolar_injury_repair_score", "mean"), pd_resistance_program_score=("pd_resistance_program_score", "mean"))
        .reset_index()
        .rename(columns={sample_key: "sample"})
    )
    sample_scores.to_csv(args.results / "rd_vs_pd_program_by_sample.csv", index=False)
    colors = {"TN": "#6e7b8a", "RD": "#2dd4bf", "PD": "#f0883e"}
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.5), sharex=True)
    for ax, score, title in zip(axes, ["alveolar_injury_repair_score", "pd_resistance_program_score"], ["Alveolar / injury-repair program", "PD resistance / immune-suppression program"]):
        for i, stage in enumerate(order):
            values = sample_scores.loc[sample_scores.treatment_stage == stage, score].dropna().to_numpy()
            if len(values):
                jitter = np.linspace(-0.08, 0.08, len(values)) if len(values) > 1 else np.array([0.0])
                ax.scatter(np.full(len(values), i) + jitter, values, color=colors[stage], alpha=0.85, label=stage)
                ax.plot([i - 0.18, i + 0.18], [np.median(values)] * 2, color="white", lw=2)
        ax.set_xticks(range(3), order)
        ax.set_title(title)
        ax.set_ylabel("Mean log-normalized score per sample")
    fig.suptitle("RD/PD program scores by sample\nSupportive reanalysis — descriptive; not clinical proof or cancer-cell-only inference")
    fig.tight_layout()
    fig.savefig(args.results / "rd_vs_pd_program_summary.png", dpi=180)
    plt.close(fig)

    (args.results / "evidence_focused_summary.md").write_text(
        "# Evidence-focused RD/PD reanalysis\n\n"
        "These charts are descriptive outputs from the GPU scVI reanalysis. They do **not** establish causality, clinical benefit, or a cancer-cell-specific effect. "
        "Treatment stages use the authors' metadata mapping: `naive → TN`, `grouped_pr → RD`, `grouped_pd → PD`. "
        "Program scores are summarized per sample to reduce cell-level pseudoreplication. A cancer-cell-restricted conclusion requires independent CNV/driver validation.\n",
        encoding="utf-8",
    )
    print("Wrote treatment-stage composition and RD/PD sample-level program evidence outputs.")


if __name__ == "__main__":
    main()
