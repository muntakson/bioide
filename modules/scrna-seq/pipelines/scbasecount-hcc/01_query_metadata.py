#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
01_query_metadata.py  (scBaseCount / Arc Virtual Cell Atlas — HCC sample selector)

scBaseCount ships one uniformly-reprocessed h5ad PER SAMPLE (SRX accession), plus a
sample-level metadata table with SRAgent-inferred fields including
`disease_ontology_term_id`, `single_disease_confidence`, `organism` and `tissue`.
This script downloads that metadata table from the Requester-Pays Virtual Cell Atlas
bucket, filters it down to HUMAN HEPATOCELLULAR CARCINOMA samples, and writes the
selected samples' gs:// h5ad paths to `hcc_samples.csv` for the download step to pull.

Nothing here reads per-cell labels — this is dataset *selection*, upstream of any
analysis. The authors'/SRAgent's per-cell `cell_type` is only touched by the
validation step (03), never as an analysis input (BioIDE 헌장 제1·2조).

⚠ DRAFT — the exact metadata filename, its column names and the per-sample h5ad path
layout inside the bucket must be confirmed on the FIRST live run (this box has no
bucket access at authoring time). The script is written defensively: it discovers the
metadata object with `gsutil ls`, accepts several plausible column spellings, and, if
it can't find what it expects, prints the bucket listing so you can point it at the
right paths with --metadata-object / --h5ad-prefix. See README.md.

Requester Pays: every gsutil call is billed to your GCP project (2 TB/month free).
Resolve the project from $GHBIO_GCP_PROJECT, ~/.config/ghbio/gcp.json, or gcloud.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile

import pandas as pd

# New Google Cloud Marketplace bucket (the old gs://arc-scbasecount is retired 2026-03-31).
DEFAULT_BUCKET = "gs://arc-institute-virtual-cell-atlas"
DEFAULT_PREFIX = "scBaseCount"          # top-level dir inside the bucket
# HCC = hepatocellular carcinoma. CELLxGENE/CZI disease ontology uses MONDO terms;
# hepatocellular carcinoma is MONDO:0007256. We also match on free-text as a fallback
# because SRAgent's confidence/label spelling varies across releases.
HCC_ONTOLOGY = {"MONDO:0007256"}
HCC_TEXT = ("hepatocellular carcinoma", "hepatocellular", "hcc")
HUMAN = ("homo sapiens", "human", "9606", "ncbitaxon:9606")


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
        sys.exit("ERROR: no GCP billing project. Set GHBIO_GCP_PROJECT or write "
                 "~/.config/ghbio/gcp.json {\"project\": \"...\"} (see 00_setup_env.sh).")
    return p


def gsutil(project: str, *args: str, capture: bool = False) -> str:
    """Run gsutil with Requester-Pays billing (-u PROJECT) on the top-level command."""
    cmd = ["gsutil", "-u", project, *args]
    print("    $", " ".join(cmd), flush=True)
    if capture:
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stderr, file=sys.stderr)
        return r.stdout
    subprocess.run(cmd, check=True)
    return ""


def find_metadata_object(project: str, bucket: str, prefix: str, override: str) -> str:
    if override:
        return override if override.startswith("gs://") else f"{bucket}/{override}"
    # Look for a metadata table (parquet/csv/tsv) under the scBaseCount prefix.
    listing = gsutil(project, "ls", "-r", f"{bucket}/{prefix}/**", capture=True)
    cands = [ln.strip() for ln in listing.splitlines()
             if ln.strip().lower().endswith((".parquet", ".csv", ".csv.gz", ".tsv", ".tsv.gz"))
             and "metadata" in ln.lower() or "obs" in ln.lower()]
    # Prefer sample/observation-level metadata; parquet first.
    cands.sort(key=lambda s: (0 if s.endswith(".parquet") else 1, len(s)))
    if not cands:
        print("\n---- bucket listing (no obvious metadata table found) ----", file=sys.stderr)
        print(listing[:8000], file=sys.stderr)
        sys.exit("ERROR: could not auto-locate the scBaseCount metadata table. Re-run with "
                 "--metadata-object gs://.../<the_metadata_file> (see listing above).")
    print(f"==> metadata table: {cands[0]}")
    return cands[0]


def load_table(local: str) -> pd.DataFrame:
    low = local.lower()
    if low.endswith(".parquet"):
        return pd.read_parquet(local)
    sep = "\t" if (".tsv" in low) else ","
    return pd.read_csv(local, sep=sep)


def col(df: pd.DataFrame, *names: str) -> str | None:
    lut = {c.lower(): c for c in df.columns}
    for n in names:
        if n.lower() in lut:
            return lut[n.lower()]
    # loose contains-match fallback
    for n in names:
        for c in df.columns:
            if n.lower() in c.lower():
                return c
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Select human HCC samples from scBaseCount.")
    ap.add_argument("--data-dir", default=os.path.expanduser("~/ghbio-tutorial/data/scbasecount-hcc"))
    ap.add_argument("--bucket", default=DEFAULT_BUCKET)
    ap.add_argument("--prefix", default=DEFAULT_PREFIX)
    ap.add_argument("--metadata-object", default="", help="explicit gs:// path to the metadata table")
    ap.add_argument("--h5ad-prefix", default="", help="explicit gs:// prefix that holds per-sample h5ads")
    ap.add_argument("--min-confidence", default="medium", choices=["low", "medium", "high"],
                    help="minimum single_disease_confidence to keep (default medium)")
    ap.add_argument("--max-samples", type=int, default=40,
                    help="cap sample count for a manageable draft run (0 = no cap)")
    args = ap.parse_args()

    os.makedirs(args.data_dir, exist_ok=True)
    project = resolve_project()
    print(f"==> [01] scBaseCount HCC selector — billing project: {project}")

    meta_obj = find_metadata_object(project, args.bucket, args.prefix, args.metadata_object)
    local_meta = os.path.join(args.data_dir, os.path.basename(meta_obj))
    if not os.path.exists(local_meta):
        gsutil(project, "cp", meta_obj, local_meta)
    df = load_table(local_meta)
    print(f"==> metadata rows: {len(df):,}  cols: {list(df.columns)[:12]}{'…' if len(df.columns)>12 else ''}")

    c_org = col(df, "organism", "organism_ontology_term_id", "species")
    c_dis = col(df, "disease_ontology_term_id", "disease", "disease_label")
    c_conf = col(df, "single_disease_confidence", "disease_confidence", "confidence")
    c_srx = col(df, "srx_accession", "srx", "sample", "sample_accession", "experiment_accession")
    c_tis = col(df, "tissue", "tissue_ontology_term_id")
    c_h5 = col(df, "h5ad_path", "h5ad", "file_path", "path", "gcs_path", "uri")
    if not (c_dis and c_srx):
        sys.exit(f"ERROR: metadata missing disease/SRX columns. Found: {list(df.columns)}. "
                 "Point the column detection at the right names or pre-filter manually.")

    def norm(s):  # lower, str
        return df[s].astype(str).str.lower()

    keep = pd.Series(True, index=df.index)
    if c_org:
        keep &= norm(c_org).apply(lambda v: any(h in v for h in HUMAN))
    dis = norm(c_dis)
    keep &= (df[c_dis].astype(str).isin(HCC_ONTOLOGY) | dis.apply(lambda v: any(t in v for t in HCC_TEXT)))
    if c_conf:
        rank = {"low": 0, "medium": 1, "high": 2}
        thr = rank[args.min_confidence]
        keep &= norm(c_conf).map(lambda v: rank.get(v, 0)).ge(thr)

    sel = df[keep].copy()
    # De-duplicate to one row per sample (SRX).
    sel = sel.drop_duplicates(subset=[c_srx])
    print(f"==> human HCC samples matched (conf ≥ {args.min_confidence}): {len(sel):,}")
    if sel.empty:
        sys.exit("ERROR: no HCC samples matched. Inspect the metadata table columns/values and "
                 "adjust HCC_ONTOLOGY/HCC_TEXT or --min-confidence.")

    # Resolve each sample's gs:// h5ad path.
    def h5ad_uri(row) -> str:
        if c_h5 and isinstance(row[c_h5], str) and row[c_h5].startswith("gs://"):
            return row[c_h5]
        srx = str(row[c_srx])
        base = args.h5ad_prefix or f"{args.bucket}/{args.prefix}"
        # scBaseCount is organised by organism; common layout is <prefix>/<Organism>/<SRX>.h5ad.
        return f"{base.rstrip('/')}/Homo_sapiens/{srx}.h5ad"

    out = pd.DataFrame({
        "srx": sel[c_srx].astype(str).values,
        "gs_path": [h5ad_uri(r) for _, r in sel.iterrows()],
        "organism": sel[c_org].astype(str).values if c_org else "Homo sapiens",
        "tissue": sel[c_tis].astype(str).values if c_tis else "",
        "disease": sel[c_dis].astype(str).values,
        "confidence": sel[c_conf].astype(str).values if c_conf else "",
    })
    if args.max_samples and len(out) > args.max_samples:
        print(f"==> capping to --max-samples {args.max_samples} (draft subsample). "
              f"Set --max-samples 0 to pull all {len(out)}.")
        out = out.head(args.max_samples)

    out_csv = os.path.join(args.data_dir, "hcc_samples.csv")
    out.to_csv(out_csv, index=False)
    print(f"==> wrote {len(out)} sample rows → {out_csv}")
    print(out.head(10).to_string(index=False))
    print("==> [01] Next: 01_download_scbasecount_hcc.sh pulls these h5ads.")


if __name__ == "__main__":
    main()
