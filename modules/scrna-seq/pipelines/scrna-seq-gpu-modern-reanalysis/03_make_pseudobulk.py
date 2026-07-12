#!/usr/bin/env python3
"""Export sample-level count sums for statistically valid treatment comparisons."""
from __future__ import annotations

import argparse
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
from scipy import sparse


def choose_column(obs: pd.DataFrame, candidates: list[str]) -> str | None:
    lookup = {str(c).lower(): str(c) for c in obs.columns}
    return next((lookup[c.lower()] for c in candidates if c.lower() in lookup), None)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    args = parser.parse_args()
    adata = ad.read_h5ad(args.input)
    sample_key = choose_column(adata.obs, ["sample_name", "sample", "sample_id"])
    if sample_key is None:
        raise ValueError("No sample identifier exists in author metadata; cannot build pseudobulk.")
    treatment_key = choose_column(adata.obs, ["best_response_status", "response_status", "treatment_status", "timepoint"])
    groups = adata.obs[sample_key].astype(str)
    counts = adata.layers.get("counts", adata.X)
    rows, metadata = [], []
    for sample in sorted(groups.unique()):
        mask = np.asarray(groups == sample)
        summed = counts[mask].sum(axis=0)
        rows.append(np.asarray(summed).ravel())
        row = {"sample": sample, "n_cells": int(mask.sum())}
        if treatment_key:
            values = adata.obs.loc[mask, treatment_key].dropna().astype(str)
            row["treatment_stage"] = values.mode().iat[0] if not values.empty else "Unknown"
        metadata.append(row)
    table = pd.DataFrame(np.vstack(rows), index=[m["sample"] for m in metadata], columns=adata.var_names)
    table.index.name = "sample"
    table.to_csv(args.results / "pseudobulk_by_sample.csv")
    pd.DataFrame(metadata).to_csv(args.results / "pseudobulk_metadata.csv", index=False)
    print(f"Wrote pseudobulk counts for {len(metadata)} samples; use these, not individual cells, for TN/RD/PD inference.")


if __name__ == "__main__":
    main()
