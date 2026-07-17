#!/usr/bin/env python
"""
07_make_report.py  —  assemble atlas figures + summaries into one PDF.
Dependency-free (matplotlib PdfPages). Missing pieces are skipped gracefully.
Emits: GHBIO_pan_cancer_atlas_report.pdf
"""
from __future__ import annotations
import argparse, os
from pathlib import Path
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.image as mpimg

FIGS = [
    ("umap_tme_lineage.png", "Use 1 · TME atlas — lineage"),
    ("umap_tme_cancer.png", "Use 1 · TME atlas — cancer of origin"),
    ("umap_tme_leiden.png", "Use 1 · TME atlas — Leiden clusters"),
    ("tme_cellstate_occurrence.png", "Use 1 · cell state × cancer occurrence"),
    ("mp_occurrence.png", "Use 2 · malignant meta-programs × study"),
    ("progression_dedifferentiation.png", "Use 3 · cross-cancer dedifferentiation"),
]
TEXTS = ["harmonize_manifest.csv", "tme_integration_summary.txt",
         "meta_programs_summary.txt", "atlas_validation_verdict.txt"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=os.environ.get("GHBIO_RESULTS",
                    os.path.expanduser("~/ghbio-tutorial/results")))
    args = ap.parse_args()
    R = Path(args.results)
    out = R / "GHBIO_pan_cancer_atlas_report.pdf"
    with PdfPages(out) as pdf:
        fig = plt.figure(figsize=(8.3, 11.7)); fig.text(0.5, 0.7,
            "BioIDE Pan-Cancer Atlas", ha="center", size=22, weight="bold")
        fig.text(0.5, 0.63, "Use 1 — TME integration · Use 2 — malignant meta-programs",
                 ha="center", size=12); plt.axis("off"); pdf.savefig(fig); plt.close()
        for fn, title in FIGS:
            p = R / fn
            if not p.exists():
                continue
            fig = plt.figure(figsize=(8.3, 11.7))
            plt.imshow(mpimg.imread(p)); plt.axis("off"); plt.title(title, size=13)
            pdf.savefig(fig); plt.close()
        for t in TEXTS:
            p = R / t
            if not p.exists():
                continue
            fig = plt.figure(figsize=(8.3, 11.7)); plt.axis("off")
            plt.title(t, size=12, loc="left")
            plt.text(0.02, 0.96, p.read_text()[:4000], va="top", family="monospace", size=7)
            pdf.savefig(fig); plt.close()
    print(f"==> [07] Report: {out}")


if __name__ == "__main__":
    main()
