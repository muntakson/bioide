#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
01_subset_download.py  (Tahoe-100M — stream-subset the selected cells)

Given selected_cells.csv + plate_h5ads.csv from 01_query_metadata.py, open each huge
per-plate h5ad in BACKED mode over gcsfs (Requester-Pays) and pull ONLY the selected
cells' rows — never downloading the ~120 GB plate file. Concatenate into one small local
`tahoe_subset.h5ad` (drug + DMSO controls, a handful of cell lines) that the GPU step
reanalyses.

This is the crux of making a 1.69 TB atlas usable on a workstation: we stream a few
thousand rows, not terabytes. gcsfs handles Requester-Pays via requester_pays=True.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import anndata as ad
import numpy as np
import pandas as pd


def resolve_project() -> str:
    p = os.environ.get("GHBIO_GCP_PROJECT", "").strip()
    cfg = os.path.expanduser("~/.config/ghbio/gcp.json")
    if not p and os.path.exists(cfg):
        try:
            p = str(json.load(open(cfg)).get("project", "")).strip()
        except Exception:
            pass
    if not p:
        sys.exit("ERROR: no GCP billing project. Run ../_shared/setup_gcp.sh <project-id>.")
    return p


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=os.path.expanduser("~/ghbio-tutorial/data/tahoe100m"))
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    out = args.out or os.path.join(args.data_dir, "tahoe_subset.h5ad")
    if os.path.exists(out):
        print(f"==> {out} already exists — skipping (delete to rebuild).")
        return

    sel = pd.read_csv(os.path.join(args.data_dir, "selected_cells.csv"), dtype=str)
    plates = pd.read_csv(os.path.join(args.data_dir, "plate_h5ads.csv"), dtype=str)
    plate2h5 = dict(zip(plates["plate"], plates["h5ad"]))
    project = resolve_project()

    import gcsfs
    fs = gcsfs.GCSFileSystem(project=project, requester_pays=True)

    parts = []
    for plate, grp in sel.groupby("plate"):
        uri = plate2h5.get(plate, "")
        if not uri:
            print(f"    WARNING: no h5ad path for plate {plate}; skipping {len(grp)} cells.", file=sys.stderr)
            continue
        want = set(grp["barcode"])
        print(f"==> plate {plate}: streaming {len(want):,} cells from {uri}")
        try:
            with fs.open(uri, "rb") as fh:
                adata = ad.read_h5ad(fh, backed="r")
                names = adata.obs_names.astype(str)
                mask = names.isin(want)
                n = int(mask.sum())
                if n == 0:
                    print(f"    WARNING: 0 of {len(want)} barcodes matched obs_names on plate {plate} "
                          f"(barcode format mismatch?). Example obs_name: {names[0]}", file=sys.stderr)
                    continue
                sub = adata[mask].to_memory()
        except Exception as e:
            print(f"    ERROR streaming plate {plate}: {e}", file=sys.stderr)
            continue
        # attach our selection covariates (drug / control / cell_line / sample)
        meta = grp.set_index("barcode")
        keep = [b for b in sub.obs_names.astype(str) if b in meta.index]
        sub = sub[keep].copy()
        for c in ("condition", "cell_line", "drug", "sample"):
            sub.obs[c] = meta.loc[sub.obs_names.astype(str), c].values
        sub.obs["plate"] = plate
        parts.append(sub)

    if not parts:
        sys.exit("ERROR: no cells streamed. Check auth, barcode format, and plate h5ad paths.")
    merged = ad.concat(parts, join="outer", index_unique=None, fill_value=0)
    merged.obs_names_make_unique()
    merged.write(out)
    print(f"==> wrote {out}: {merged.n_obs:,} cells × {merged.n_vars:,} genes")
    print(merged.obs.groupby(["cell_line", "condition"]).size().to_string())


if __name__ == "__main__":
    main()
