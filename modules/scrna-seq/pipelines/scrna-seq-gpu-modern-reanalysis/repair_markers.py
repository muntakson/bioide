#!/usr/bin/env python3
"""Migrate an early GPU-tutorial marker CSV to BioIDE's ranked-marker schema."""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    args = parser.parse_args()
    path = args.results / "markers_by_cluster.csv"
    markers = pd.read_csv(path)
    if {"cluster", "rank", "gene"}.issubset(markers.columns):
        print("Marker CSV already uses the BioIDE ranked-marker schema.")
        return
    required = {"group", "names", "scores", "logfoldchanges", "pvals", "pvals_adj"}
    if not required.issubset(markers.columns):
        raise ValueError(f"Unrecognized marker columns: {list(markers.columns)}")
    markers = markers.rename(columns={"group": "cluster", "names": "gene", "scores": "score", "logfoldchanges": "logfoldchange"})
    markers["rank"] = markers.groupby("cluster", observed=True).cumcount() + 1
    markers[["cluster", "rank", "gene", "score", "logfoldchange", "pvals", "pvals_adj"]].to_csv(path, index=False)
    print(f"Rewrote {path} with cluster/rank/gene columns for BioIDE AI.")


if __name__ == "__main__":
    main()
