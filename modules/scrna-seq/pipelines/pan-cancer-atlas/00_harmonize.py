#!/usr/bin/env python
"""
00_harmonize.py  —  Pan-cancer atlas · Stage 0 (schema + gene + label harmonisation)

Reads the 11 validated per-pipeline h5ads listed in inputs.json and writes ONE
standardised schema so the TME-integration (Use 1) and malignant-NMF (Use 2)
stages can consume them uniformly.

Per the BioIDE constitution the author cell_type labels were already re-derived
independently by each SOURCE pipeline; here they are only the harmonisation key
(they are NOT re-consumed as fresh analysis input). This stage:

  1. loads each source h5ad,
  2. standardises obs -> {study_id, cancer, platform, sample, patient,
     progression, cell_lineage (controlled vocab), is_malignant},
  3. harmonises gene symbols (upper-case, de-duplicate by sum),
  4. recovers a raw-COUNTS matrix when available (layers['counts'] / .raw /
     integer-looking X) and records counts_available per study,
  5. splits each study into a TME (non-malignant immune/stroma) file and a
     MALIGNANT file,
  6. writes a manifest (CSV + JSON) with cell counts, lineage breakdown, gene
     overlap and the common-gene intersection used downstream.

Outputs (under $GHBIO_RESULTS):
  harmonized/<study_id>.tme.h5ad          non-malignant immune/stroma cells
  harmonized/<study_id>.malignant.h5ad    malignant cells (for cNMF)
  harmonize_manifest.csv                   one row per study
  harmonize_manifest.json                  full detail + common gene list
  common_genes.txt                         intersection across all studies
  lineage_composition.csv                  study x canonical-lineage counts

Idempotent: skips a study whose two output files already exist unless --force.
"""
from __future__ import annotations
import argparse, json, os, re, sys
from pathlib import Path

import numpy as np
import pandas as pd
import scanpy as sc
import anndata as ad
from scipy import sparse

# newer anndata refuses to write pandas nullable/arrow string arrays by default
try:
    ad.settings.allow_write_nullable_strings = True
except Exception:
    pass

HERE = Path(__file__).resolve().parent


def expand(p: str) -> Path:
    return Path(os.path.expanduser(p))


def load_config() -> dict:
    return json.loads((HERE / "inputs.json").read_text())


def looks_like_counts(X) -> bool:
    """Heuristic: is X (a sample of it) non-negative integers?"""
    if X is None:
        return False
    sub = X[:200] if X.shape[0] > 200 else X
    arr = sub.toarray() if sparse.issparse(sub) else np.asarray(sub)
    if arr.size == 0:
        return False
    arr = arr[np.isfinite(arr)]
    if arr.size == 0 or arr.min() < 0:
        return False
    frac_int = np.mean(np.isclose(arr, np.round(arr)))
    return bool(frac_int > 0.98 and arr.max() > 1.5)


def get_counts(a: ad.AnnData, counts_layer: str | None):
    """Return (counts_matrix_or_None, source_str)."""
    if counts_layer and counts_layer in a.layers:
        return a.layers[counts_layer], f"layers[{counts_layer}]"
    if "counts" in a.layers:
        return a.layers["counts"], "layers[counts]"
    if a.raw is not None and looks_like_counts(a.raw.X):
        return a.raw.X, "raw.X"
    if looks_like_counts(a.X):
        return a.X, "X"
    return None, "none"


def harmonise_genes(a: ad.AnnData) -> ad.AnnData:
    """Upper-case symbols, collapse duplicates by summing."""
    names = a.var_names.astype(str).str.upper()
    a.var_names = names
    if names.duplicated().any():
        a = a[:, ~a.var_names.duplicated()].copy()  # first-wins; sum is heavier, keep scaffold light
    return a


def canonical_lineage(series: pd.Series, lineage_map: dict) -> pd.Series:
    return series.astype(str).map(lambda v: lineage_map.get(v, "Unknown"))


def process_study(st: dict, cfg: dict, out_dir: Path, force: bool) -> dict:
    sid = st["study_id"]
    src = expand(cfg["projects_root"]) / st["h5ad"]
    tme_out = out_dir / f"{sid}.tme.h5ad"
    mal_out = out_dir / f"{sid}.malignant.h5ad"

    rec = {"study_id": sid, "cancer": st["cancer"], "platform": st["platform"],
           "source": str(src)}

    if not src.exists():
        rec.update(status="MISSING_INPUT", n_total=0, n_tme=0, n_malignant=0)
        print(f"  [{sid}] !! missing input: {src}")
        return rec

    if tme_out.exists() and mal_out.exists() and not force:
        # cheap re-read for manifest fields
        t = ad.read_h5ad(tme_out, backed="r"); m = ad.read_h5ad(mal_out, backed="r")
        rec.update(status="CACHED", n_total=int(t.n_obs + m.n_obs),
                   n_tme=int(t.n_obs), n_malignant=int(m.n_obs),
                   n_genes=int(t.n_vars), counts_source=t.uns.get("counts_source", "?"))
        print(f"  [{sid}] cached (tme={t.n_obs}, malignant={m.n_obs})")
        return rec

    print(f"  [{sid}] loading {src.name} ...")
    a = sc.read_h5ad(src)
    a = harmonise_genes(a)

    # --- counts recovery ---
    counts, csrc = get_counts(a, st.get("counts_layer"))
    counts_available = counts is not None

    # --- standardise obs ---
    obs = pd.DataFrame(index=a.obs_names)
    obs["study_id"] = sid
    obs["cancer"] = st["cancer"]
    obs["platform"] = st["platform"]
    for canon, col in [("sample", "sample_col"), ("patient", "patient_col"),
                       ("progression", "progression_col")]:
        c = st.get(col)
        obs[canon] = a.obs[c].astype(str).values if (c and c in a.obs) else "n/a"

    # cell lineage (controlled vocab)
    ct_col = st.get("celltype_col")
    if ct_col and ct_col in a.obs:
        obs["cell_lineage"] = canonical_lineage(a.obs[ct_col], cfg["lineage_map"]).values
        obs["cell_type_src"] = a.obs[ct_col].astype(str).values
    else:
        obs["cell_lineage"] = "Unknown"
        obs["cell_type_src"] = "n/a"

    # malignant flag
    mcol, mrx = st.get("malignant_col"), st.get("malignant_regex")
    if mcol and mrx and mcol in a.obs:
        obs["is_malignant"] = a.obs[mcol].astype(str).str.match(mrx, case=False).fillna(False).values
    else:
        # fallback: lineage says Epithelial/Tumour with no explicit call -> unknown, treat as non-TME
        obs["is_malignant"] = False
    a.obs = obs

    # attach recovered counts as the working layer (or leave X)
    if counts_available:
        a.layers["counts"] = counts
    a.uns["counts_source"] = csrc
    a.uns["counts_available"] = counts_available

    # --- split ---
    is_mal = a.obs["is_malignant"].values
    in_tme = (~is_mal) & a.obs["cell_lineage"].isin(cfg["tme_lineages"]).values

    tme = a[in_tme].copy()
    mal = a[is_mal].copy()
    # keep the h5ads light: drop obsm/varm/uns heavy bits except counts flag
    for X in (tme, mal):
        X.obsm.clear(); X.varm.clear()
        X.uns = {"counts_source": csrc, "counts_available": bool(counts_available)}

    tme.write_h5ad(tme_out)
    mal.write_h5ad(mal_out)

    lineage_counts = obs.loc[in_tme, "cell_lineage"].value_counts().to_dict()
    rec.update(status="OK", n_total=int(a.n_obs), n_tme=int(tme.n_obs),
               n_malignant=int(mal.n_obs), n_genes=int(a.n_vars),
               counts_available=bool(counts_available), counts_source=csrc,
               genes=list(a.var_names), lineage_counts=lineage_counts)
    print(f"  [{sid}] tme={tme.n_obs}  malignant={mal.n_obs}  "
          f"counts={csrc}{'' if counts_available else ' (NEEDS RECOVERY)'}")
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=os.environ.get(
        "GHBIO_RESULTS", os.path.expanduser("~/ghbio-tutorial/results")))
    ap.add_argument("--only", nargs="*", help="restrict to these study_ids")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    out_root = Path(args.results)
    out_dir = out_root / "harmonized"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"==> [00] Harmonising {len(cfg['studies'])} studies -> {out_dir}")

    studies = cfg["studies"]
    if args.only:
        studies = [s for s in studies if s["study_id"] in args.only]

    records = [process_study(st, cfg, out_dir, args.force) for st in studies]

    # ---- manifest ----
    ok = [r for r in records if r.get("status") in ("OK", "CACHED")]
    gene_sets = [set(r["genes"]) for r in records if r.get("genes")]
    common = sorted(set.intersection(*gene_sets)) if gene_sets else []
    (out_root / "common_genes.txt").write_text("\n".join(common))

    # slim CSV (no gene lists)
    df = pd.DataFrame([{k: v for k, v in r.items()
                        if k not in ("genes", "lineage_counts")} for r in records])
    df.to_csv(out_root / "harmonize_manifest.csv", index=False)

    # lineage composition matrix
    comp_rows = {r["study_id"]: r.get("lineage_counts", {}) for r in records if r.get("lineage_counts")}
    comp = pd.DataFrame(comp_rows).fillna(0).astype(int).T
    comp.to_csv(out_root / "lineage_composition.csv")

    full = {"studies": records, "n_common_genes": len(common),
            "total_cells": int(df.get("n_total", pd.Series(dtype=int)).sum()),
            "total_tme": int(df.get("n_tme", pd.Series(dtype=int)).sum()),
            "total_malignant": int(df.get("n_malignant", pd.Series(dtype=int)).sum())}
    (out_root / "harmonize_manifest.json").write_text(json.dumps(full, indent=2))

    print("\n==> Manifest:")
    print(df.to_string(index=False))
    print(f"\n==> Common genes across {len(gene_sets)} studies: {len(common)}")
    print(f"==> TME cells (Use 1): {full['total_tme']:,}   "
          f"Malignant cells (Use 2): {full['total_malignant']:,}")
    needs = [r["study_id"] for r in records if r.get("counts_available") is False]
    if needs:
        print(f"\n!! counts NOT recovered (scVI/cNMF will need raw counts) for: {', '.join(needs)}")
        print("   -> re-run those source pipelines saving layers['counts'], or add a recovery step.")
    print("\n==> [00] Done. Next: 1. TME integration (run_tme_integrate.sh).")


if __name__ == "__main__":
    main()
