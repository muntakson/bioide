#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
01_query_metadata.py  (Tahoe-100M — drug + control cell selector)

Tahoe-100M is sharded into ~14 per-plate h5ads (~1.69 TB) — you never download it
whole. Instead we read the SMALL metadata parquet tables, pick a target DRUG and its
matched DMSO vehicle controls across a few cancer cell lines, and write the exact list
of cells (BARCODE_SUB_LIB_ID) + which plate h5ad holds each. Step 1b then stream-subsets
only those cells out of the plate h5ads (via gcsfs, no full download).

Nothing here reads expression — this is dataset SELECTION. Per the BioIDE constitution
we later re-derive the drug response with our own DE code; no provided 'response' label
is consumed.

Metadata tables (under <bucket>/tahoe100M/<date>/metadata/):
  obs_metadata.parquet     per-cell: BARCODE_SUB_LIB_ID, drug, sample, plate, cell_line_id
  sample_metadata.parquet  per-sample: sample, plate, drug, drugname_drugconc, QC means
  drug_metadata.parquet    per-drug: drug, targets, moa-broad, moa-fine, canonical_smiles
  cell_line_metadata.parquet  Cell_ID_Cellosaur, cell_name, Organ, Driver_Gene_Symbol

⚠ DRAFT — the date prefix (default 2025-02-25), exact column spellings and the per-plate
h5ad path layout must be confirmed on the FIRST live run. The script auto-discovers the
date dir + h5ad objects with `gsutil ls` and accepts several column spellings; if it
can't find them it prints the listing so you can pass --date / --h5ad-prefix. See README.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

import pandas as pd

DEFAULT_BUCKET = "gs://arc-institute-virtual-cell-atlas"
DEFAULT_ROOT = "tahoe100M"
DEFAULT_DATE = "2025-02-25"
# Tahoe's vehicle control is DMSO (labelled DMSO_TF in the drug column).
CONTROL_PATTERNS = ("dmso",)
META_FILES = ["obs_metadata.parquet", "sample_metadata.parquet",
              "drug_metadata.parquet", "cell_line_metadata.parquet"]


def resolve_project() -> str:
    p = os.environ.get("GHBIO_GCP_PROJECT", "").strip()
    cfg = os.path.expanduser("~/.config/ghbio/gcp.json")
    if not p and os.path.exists(cfg):
        try:
            p = str(json.load(open(cfg)).get("project", "")).strip()
        except Exception:
            pass
    if not p:
        try:
            p = subprocess.run(["gcloud", "config", "get-value", "project"],
                               capture_output=True, text=True).stdout.strip()
        except Exception:
            p = ""
    if not p or p == "(unset)":
        sys.exit("ERROR: no GCP billing project. Run ../_shared/setup_gcp.sh <project-id>.")
    return p


def gsutil(project, *args, capture=False):
    cmd = ["gsutil", "-u", project, *args]
    print("    $", " ".join(cmd), flush=True)
    if capture:
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stderr, file=sys.stderr)
        return r.stdout
    subprocess.run(cmd, check=True)
    return ""


def discover_date(project, bucket, root, date) -> str:
    listing = gsutil(project, "ls", f"{bucket}/{root}/", capture=True)
    dates = sorted({ln.rstrip("/").split("/")[-1] for ln in listing.splitlines()
                    if ln.strip().rstrip("/").split("/")[-1][:2].isdigit()})
    if date in dates or not dates:
        return date
    print(f"==> date {date} not found; using latest available: {dates[-1]} (of {dates})")
    return dates[-1]


def col(df, *names):
    lut = {c.lower(): c for c in df.columns}
    for n in names:
        if n.lower() in lut:
            return lut[n.lower()]
    for n in names:
        for c in df.columns:
            if n.lower() in c.lower():
                return c
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Select a drug + DMSO controls from Tahoe-100M.")
    ap.add_argument("--data-dir", default=os.path.expanduser("~/ghbio-tutorial/data/tahoe100m"))
    ap.add_argument("--bucket", default=DEFAULT_BUCKET)
    ap.add_argument("--root", default=DEFAULT_ROOT)
    ap.add_argument("--date", default=os.environ.get("TAHOE_DATE", DEFAULT_DATE))
    ap.add_argument("--drug", default=os.environ.get("TAHOE_DRUG", "Vorinostat"),
                    help="target drug name (must match drug_metadata; default Vorinostat, a "
                         "pan-HDAC inhibitor with a strong reproducible signature)")
    ap.add_argument("--max-cell-lines", type=int, default=6)
    ap.add_argument("--max-cells-per-group", type=int, default=1500,
                    help="cap cells per (cell_line, drug|control) group for a tractable subset")
    ap.add_argument("--h5ad-prefix", default="", help="explicit gs:// prefix holding per-plate h5ads")
    args = ap.parse_args()

    os.makedirs(args.data_dir, exist_ok=True)
    project = resolve_project()
    date = discover_date(project, args.bucket, args.root, args.date)
    meta_base = f"{args.bucket}/{args.root}/{date}/metadata"
    print(f"==> [01] Tahoe-100M selector — project {project}, date {date}, drug '{args.drug}'")

    # 1) download the (small) metadata tables --------------------------------------
    local = {}
    for f in META_FILES:
        dst = os.path.join(args.data_dir, f)
        if not os.path.exists(dst):
            gsutil(project, "cp", f"{meta_base}/{f}", dst)
        local[f] = dst
    obs = pd.read_parquet(local["obs_metadata.parquet"])
    drugm = pd.read_parquet(local["drug_metadata.parquet"])
    cellm = pd.read_parquet(local["cell_line_metadata.parquet"])
    print(f"==> obs rows: {len(obs):,}  cols: {list(obs.columns)}")

    c_bc = col(obs, "BARCODE_SUB_LIB_ID", "barcode", "cell_id") or obs.index.name
    c_drug = col(obs, "drug")
    c_plate = col(obs, "plate")
    c_sample = col(obs, "sample")
    c_cl = col(obs, "cell_line_id", "cell_line", "Cell_ID_Cellosaur", "cell_name")
    if not (c_drug and c_plate and c_cl):
        sys.exit(f"ERROR: obs_metadata missing drug/plate/cell_line columns. Found {list(obs.columns)}.")
    if c_bc not in obs.columns:
        obs = obs.reset_index().rename(columns={obs.index.name or "index": "BARCODE_SUB_LIB_ID"})
        c_bc = "BARCODE_SUB_LIB_ID"

    dl = obs[c_drug].astype(str)
    is_ctrl = dl.str.lower().str.contains("|".join(CONTROL_PATTERNS))
    is_drug = dl.str.lower().str.fullmatch(args.drug.lower()) | dl.str.lower().str.contains(args.drug.lower())
    if not is_drug.any():
        opts = sorted(dl.unique())[:40]
        sys.exit(f"ERROR: drug '{args.drug}' not found in obs. Examples: {opts}. "
                 "Set --drug / $TAHOE_DRUG to an exact drug_metadata name.")

    # cell lines that have BOTH the drug and a DMSO control (so DE has a baseline)
    cls_drug = set(obs.loc[is_drug, c_cl].astype(str))
    cls_ctrl = set(obs.loc[is_ctrl, c_cl].astype(str))
    usable = sorted(cls_drug & cls_ctrl)
    if not usable:
        sys.exit(f"ERROR: no cell line has both '{args.drug}' and a DMSO control.")
    usable = usable[:args.max_cell_lines]
    print(f"==> cell lines with drug+control (capped {args.max_cell_lines}): {usable}")

    # 2) gather the exact cells (drug + control) per cell line, capped -------------
    rows = []
    for cl in usable:
        for cond, mask in (("drug", is_drug), ("control", is_ctrl)):
            sub = obs[mask & (obs[c_cl].astype(str) == cl)]
            if len(sub) > args.max_cells_per_group:
                sub = sub.sample(n=args.max_cells_per_group, random_state=0)
            for _, r in sub.iterrows():
                rows.append({"barcode": str(r[c_bc]), "plate": str(r[c_plate]),
                             "sample": str(r[c_sample]) if c_sample else "",
                             "cell_line": cl, "drug": str(r[c_drug]), "condition": cond})
    sel = pd.DataFrame(rows)
    sel.to_csv(os.path.join(args.data_dir, "selected_cells.csv"), index=False)
    print(f"==> selected {len(sel):,} cells across {sel['cell_line'].nunique()} cell lines "
          f"({(sel.condition=='drug').sum()} drug / {(sel.condition=='control').sum()} control)")

    # 3) which plate h5ads hold them → discover their gs:// paths ------------------
    plates = sorted(sel["plate"].unique())
    h5base = args.h5ad_prefix or f"{args.bucket}/{args.root}/{date}/h5ad"
    listing = gsutil(project, "ls", f"{h5base}/", capture=True)
    h5objs = [ln.strip() for ln in listing.splitlines() if ln.strip().lower().endswith(".h5ad")]
    plate_map = []
    for p in plates:
        hits = [o for o in h5objs if p.lower() in o.lower() or f"plate{p}".lower() in o.lower()]
        plate_map.append({"plate": p, "h5ad": hits[0] if hits else ""})
        if not hits:
            print(f"    WARNING: no h5ad object matched plate '{p}'. Objects: {h5objs[:5]}…", file=sys.stderr)
    pd.DataFrame(plate_map).to_csv(os.path.join(args.data_dir, "plate_h5ads.csv"), index=False)

    # 4) stash the drug's known targets / MOA for the validation step -------------
    d_drug = col(drugm, "drug")
    dm = drugm[drugm[d_drug].astype(str).str.lower().str.contains(args.drug.lower())] if d_drug else drugm.iloc[0:0]
    dm.to_csv(os.path.join(args.data_dir, "drug_targets.csv"), index=False)
    cellm.to_csv(os.path.join(args.data_dir, "cell_line_metadata.csv"), index=False)

    print("==> wrote selected_cells.csv, plate_h5ads.csv, drug_targets.csv")
    print("==> [01] Next: 01_subset_download.py streams these cells from the plate h5ads.")


if __name__ == "__main__":
    main()
