#!/usr/bin/env python
"""
04_meta_programs.py  —  Use 2 · cluster per-sample programs into recurrent meta-programs.

Reads malignant_programs.json (per-sample NMF programs) and clusters them by
gene-set overlap (Jaccard) into recurrent META-PROGRAMS (MPs). Each MP is
annotated by its consensus top genes and by the set of cancers it recurs in —
the pan-cancer malignant-program map (Gavish/Tirosh 2023 style).

Outputs ($GHBIO_RESULTS):
  meta_programs.json           MP id -> {consensus_genes, member_programs, cancers}
  mp_occurrence.csv            MP x cancer recurrence
  mp_occurrence.png            heatmap
  meta_programs_summary.txt
"""
from __future__ import annotations
import argparse, os, json
from pathlib import Path
from collections import Counter, defaultdict
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from scipy.cluster.hierarchy import linkage, fcluster
from scipy.spatial.distance import squareform


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if (a or b) else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=os.environ.get("GHBIO_RESULTS",
                    os.path.expanduser("~/ghbio-tutorial/results")))
    ap.add_argument("--top", type=int, default=30, help="top genes per program for Jaccard")
    ap.add_argument("--dist", type=float, default=0.9, help="1-Jaccard cut height")
    ap.add_argument("--min-members", type=int, default=3, help="min programs to call an MP")
    args = ap.parse_args()
    R = Path(args.results)

    progs = json.loads((R / "malignant_programs.json").read_text())
    if not progs:
        raise SystemExit("malignant_programs.json empty — run Stage 3 first.")
    gsets = [set(p["genes"][:args.top]) for p in progs]
    n = len(gsets)

    D = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            D[i, j] = D[j, i] = 1 - jaccard(gsets[i], gsets[j])
    Z = linkage(squareform(D, checks=False), method="average")
    labels = fcluster(Z, t=args.dist, criterion="distance")

    mps, cancers_of = {}, {p["study"]: p.get("cancer", p["study"]) for p in progs}
    for lab in sorted(set(labels)):
        members = [i for i in range(n) if labels[i] == lab]
        if len(members) < args.min_members:
            continue
        gene_counts = Counter(g for i in members for g in gsets[i])
        consensus = [g for g, _ in gene_counts.most_common(args.top)]
        studies = sorted({progs[i]["study"] for i in members})
        mps[f"MP{len(mps)+1}"] = {
            "consensus_genes": consensus,
            "n_member_programs": len(members),
            "studies": studies,
            "n_studies": len(studies),
        }

    (R / "meta_programs.json").write_text(json.dumps(mps, indent=2))

    # MP x study occurrence
    all_studies = sorted({p["study"] for p in progs})
    occ = pd.DataFrame(0, index=list(mps), columns=all_studies)
    for mp, d in mps.items():
        for s in d["studies"]:
            occ.loc[mp, s] = 1
    occ["n_studies"] = occ.sum(axis=1)
    occ.sort_values("n_studies", ascending=False).to_csv(R / "mp_occurrence.csv")

    if len(mps):
        m = occ.drop(columns="n_studies")
        plt.figure(figsize=(1 + 0.5 * m.shape[1], 0.4 * m.shape[0] + 1))
        plt.imshow(m.values, aspect="auto", cmap="Greys")
        plt.xticks(range(m.shape[1]), m.columns, rotation=90, fontsize=7)
        plt.yticks(range(m.shape[0]), m.index, fontsize=7)
        plt.title("Meta-program x study recurrence")
        plt.savefig(R / "mp_occurrence.png", dpi=130, bbox_inches="tight"); plt.close()

    (R / "meta_programs_summary.txt").write_text(
        f"input_programs={n}\nmeta_programs={len(mps)}\n"
        f"recurrent_MPs(>=3 studies)={sum(1 for d in mps.values() if d['n_studies']>=3)}\n")
    print(f"==> [04] Done. {n} programs -> {len(mps)} meta-programs. Next: 5. progression.")


if __name__ == "__main__":
    main()
