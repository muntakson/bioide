#!/usr/bin/env python3
"""
03_gsea_hallmark.py — preranked GSEA (Subramanian weighted-KS enrichment score
with gene-label permutation for NES/p) over OUR KD-vs-WT moderated-t ranking,
against a self-contained set of MSigDB Hallmark gene sets (no internet). Tests
the paper's Fig-6 program-level claims — all expected DOWN in the Ddx54-KNOCKDOWN:
  EMT (Fig 6B), Myc targets (Fig 6B), IL6-Jak-Stat3 (Fig 6D), TNFA via NF-κB
  (Fig 6F). Context sets (Wnt/β-catenin, Interferon-γ, E2F, Inflammatory) round
  out the picture.

Mouse gene symbols are UPPER-CASED to match the human Hallmark sets (ortholog-
level enrichment) — the direction is the reproduction target. Reads GHBIO_RESULTS.

Outputs: gsea_hallmark.csv, gsea_hallmark.png.
"""
import os, sys
import numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C

RESULTS = C.RESULTS
print(f"==> [03] results dir: {RESULTS}")

# --- Embedded Hallmark gene sets (curated cores from MSigDB h.all). Enough
#     membership for a stable rank-based enrichment; direction is the target. ---
HALLMARK = {
"HALLMARK_EPITHELIAL_MESENCHYMAL_TRANSITION": """FN1 VIM ZEB1 ZEB2 SNAI2 TWIST1 CDH2 COL1A1 COL1A2
COL3A1 COL4A1 COL5A1 COL5A2 COL6A1 COL6A2 COL6A3 COL11A1 FBN1 FBN2 SPARC SPP1 THBS1 THBS2 TIMP1
TIMP3 TAGLN ACTA2 POSTN LOX LOXL1 LOXL2 MMP2 MMP3 MMP14 TGFBI TGFB1 TGFBR3 SERPINE1 SERPINE2 PDGFRB
FBLN1 FBLN2 FBLN5 DCN LUM BGN VCAN ELN CTGF CYR61 IGFBP3 IGFBP4 INHBA WNT5A GREM1 FGF2 PMP22 CDH11
ITGA5 ITGAV ITGB1 ITGB3 NNMT FSTL1 SFRP1 SFRP4 COMP EMP3 GLIPR1 GEM CAP2 CALD1 TPM1 TPM2 MYL9
COL8A1 COL8A2 COL12A1 COL16A1 CAPG QSOX1 PCOLCE FUCA1 GAS1 P4HA2 PLOD1 PLOD2 PLOD3 PRRX1""",
"HALLMARK_MYC_TARGETS_V1": """MYC MAX NPM1 NCL NOLC1 FBL GNL3 NOP56 NOP16 PA2G4 HSPD1 HSPE1 EIF4E
EIF4G2 EIF3B EIF3D EIF3J EIF2S1 EIF2S2 EIF1AX RPL3 RPL6 RPL14 RPL22 RPL34 RPS2 RPS3 RPS5 RPS6 RPSA
PABPC1 SRM ODC1 CAD PPAT TYMS DHFR IMPDH2 PRPS2 CCT2 CCT3 CCT4 CCT5 CCT7 TCP1 SNRPA1 SNRPB2 SNRPD1
SNRPD2 SNRPG HNRNPA1 HNRNPA2B1 HNRNPC HNRNPD HNRNPR PTGES3 RUVBL2 CBX3 CDK4 SET SSB TFDP1 NDUFAB1
PHB PHB2 RAN RANBP1 XPO1 KPNA2 KPNB1 SERBP1 SLC25A3 VDAC1 VDAC3 GLO1 LDHA APEX1 C1QBP MCM5 ORC2
POLD2 PRDX3 PSMA1 PSMA4 PSMA6 PSMB2 PSMC4 PSMD1 PSMD3 EPRS FARSA""",
"HALLMARK_IL6_JAK_STAT3_SIGNALING": """IL6 IL6R IL6ST JAK1 JAK2 JAK3 STAT1 STAT2 STAT3 SOCS1 SOCS3
IL4R IL2RG IL2RA IL9R IL10RB IL13RA1 IL15RA IL17RA IL18R1 CSF2RA CSF2RB CSF1 CSF2 CSF3R TNF TNFRSF1A
TNFRSF1B TNFRSF12A TNFRSF21 TGFB1 CXCL1 CXCL3 CXCL9 CXCL10 CXCL11 CXCL13 CCL7 CCR1 A2M PIM1 MYD88
IRF1 IRF9 TLR2 CD14 CD36 CD38 CD44 CD9 EBI3 GRB2 HAX1 HMOX1 INHBE ITGA4 ITGB3 LTB LTBR MAP3K8
OSMR PF4 PLA2G2A PTPN1 PTPN2 PTPN11 REG1A STAM2 TYK2""",
"HALLMARK_TNFA_SIGNALING_VIA_NFKB": """TNF NFKB1 NFKB2 NFKBIA NFKBIE RELB REL RELA CXCL1 CXCL2 CXCL3
CXCL10 CXCL11 CCL2 CCL4 CCL5 CCL20 IL1A IL1B IL6 IL18 CXCL8 PTGS2 PTX3 TNFAIP2 TNFAIP3 TNFAIP6
TNFAIP8 BIRC2 BIRC3 TRAF1 ICAM1 VCAM1 SELE CD83 CD69 CD80 JUN JUNB FOS FOSB FOSL1 FOSL2 EGR1 EGR2
EGR3 IER2 IER3 IER5 ATF3 DUSP1 DUSP2 DUSP4 DUSP5 SOD2 PLAU PLAUR NR4A1 NR4A2 NR4A3 GADD45A GADD45B
BCL3 BCL2A1 SGK1 ZFP36 PDE4B PLK2 KLF6 KLF10 MAP3K8 SLC2A6 SPHK1 PIM1 CEBPB CEBPD RIPK2 TRIB1 IL7R""",
"HALLMARK_WNT_BETA_CATENIN_SIGNALING": """CTNNB1 MYC CCND1 JAG1 JAG2 NOTCH1 NOTCH4 DLL1 DKK1 DKK4
HEY1 HEY2 AXIN1 AXIN2 FZD1 FZD8 LEF1 TCF7 WNT1 WNT5B WNT6 GNAI1 NKD1 PPARD PSEN2 NUMB HDAC2 HDAC5
HDAC11 KAT2A CUL1 SKP2 FRAT1 RBPJ ADAM17 MAML1 SLC9A3R1 TP53""",
"HALLMARK_INTERFERON_GAMMA_RESPONSE": """STAT1 IRF1 GBP2 GBP4 CXCL9 CXCL10 CXCL11 PSMB8 PSMB9
PSMB10 TAP1 TAP2 B2M OAS2 OAS3 MX1 MX2 IRF7 IRF8 IRF9 ISG15 IFIT1 IFIT2 IFIT3 IFI35 IFIH1 SOCS1
STAT2 NLRC5 CIITA VCAM1 ICAM1 CASP1 CASP4 XAF1 RSAD2 BST2 NMI PARP14 SP100 USP18 IL15RA HERC6 ISG20
IDO1 CD40 CD69 CD86 FGL2 UBE2L6""",
"HALLMARK_E2F_TARGETS": """MKI67 PCNA MCM2 MCM3 MCM4 MCM5 MCM6 MCM7 CDK1 CDC6 CDC20 CDC25A CCNE1
CCNB2 E2F1 E2F8 TK1 RRM2 RRM1 TYMS DHFR ORC6 POLE POLA1 POLD1 POLD3 GINS1 CDKN2C CDKN3 BUB1B PLK1
PLK4 AURKA AURKB TOP2A EXO1 RFC2 RFC3 CHEK1 BRCA1 BRCA2 RAD51 RAD51AP1 UNG DUT SLBP HMGB2 HELLS
DNMT1 SMC1A SMC3 SMC4 NASP MYBL2 KIF22 CDC45 WDR76 LMNB1 CBX5 NUSAP1 TRIP13 ASF1B CENPE CENPM""",
"HALLMARK_INFLAMMATORY_RESPONSE": """IL1A IL1B IL6 IL18 TNF CCL2 CCL5 CCL7 CCL20 CXCL8 CXCL9
CXCL10 CXCL11 CCR7 PTGS2 PTGER4 NLRP3 TLR1 TLR2 TLR3 NOD2 IRF1 IRF7 NFKB1 RELA ICAM1 SELE SELL
CD14 CD40 CD48 CD69 CD70 CSF1 CSF3 IFNGR2 IL10 IL15 IL4R IL7R OSM AHR ADM BST2 SLC7A2 SPHK1
MSR1 MMP14 PLAUR SERPINE1 F3 HBEGF EREG TIMP1 GPR183 P2RX7 LAMP3 RGS1""",
}


def parse(s):
    return [g.strip() for g in s.split() if g.strip()]


HALLMARK = {k: parse(v) for k, v in HALLMARK.items()}


def preranked_gsea(rank, gene_order, gs, n_perm=1000, seed=0):
    """Weighted-KS enrichment score + gene-permutation NES/p. rank aligned to gene_order."""
    N = len(gene_order)
    idx = {g: i for i, g in enumerate(gene_order)}
    hits = np.array([idx[g] for g in gs if g in idx])
    if len(hits) < 5:
        return None
    r = np.abs(rank)

    def es_for(hit_idx):
        tag = np.zeros(N)
        tag[hit_idx] = r[hit_idx]
        Nh = tag.sum()
        if Nh == 0:
            return 0.0
        Phit = np.cumsum(tag) / Nh
        miss = np.ones(N); miss[hit_idx] = 0
        Pmiss = np.cumsum(miss) / (N - len(hit_idx))
        d = Phit - Pmiss
        return d[np.argmax(np.abs(d))]

    es = es_for(hits)
    rng = np.random.default_rng(seed)
    null = np.empty(n_perm)
    for i in range(n_perm):
        null[i] = es_for(rng.choice(N, size=len(hits), replace=False))
    same = null[(null >= 0)] if es >= 0 else null[(null < 0)]
    mu = np.abs(same).mean() if len(same) else (np.abs(null).mean() + 1e-9)
    nes = es / (mu + 1e-9)
    if es >= 0:
        p = (np.sum(null >= es) + 1) / (n_perm + 1)
    else:
        p = (np.sum(null <= es) + 1) / (n_perm + 1)
    return {"ES": es, "NES": nes, "p": p, "size": len(hits)}


def main():
    de = pd.read_csv(os.path.join(RESULTS, "de_kd_vs_wt.csv"), index_col=0)
    de = de.sort_values("t", ascending=False)
    # mouse symbol -> UPPER to match human Hallmark sets (ortholog-level)
    gene_order = np.array([str(g).upper() for g in de.index])
    rank = de["t"].to_numpy()

    rows = []
    for name, gs in HALLMARK.items():
        res = preranked_gsea(rank, gene_order, gs)
        if res is None:
            continue
        exp = C.PAPER_GSEA_DIR.get(name)  # expected KD direction (paper), or None
        rows.append({
            "hallmark": name.replace("HALLMARK_", ""),
            "NES": round(res["NES"], 3), "p": round(res["p"], 4), "size": res["size"],
            "our_dir": "UP" if res["NES"] > 0 else "DOWN",
            "paper_dir": exp or "",
            "dir_match": (None if exp is None else
                          (("DOWN" if res["NES"] < 0 else "UP") == exp)),
        })
    g = pd.DataFrame(rows).sort_values("NES", ascending=False)
    g.to_csv(os.path.join(RESULTS, "gsea_hallmark.csv"), index=False)
    scored = g.dropna(subset=["dir_match"])
    match = (scored["dir_match"].astype(bool).sum() / len(scored) * 100) if len(scored) else float("nan")
    print(f"==> GSEA: {len(g)} sets; paper-comparable {len(scored)}; direction match {match:.0f}%")
    print(g[["hallmark", "NES", "p", "our_dir", "paper_dir", "dir_match"]].to_string(index=False))

    # figure: NES bar, colored by direction, paper-set annotated (KD arm)
    fig, ax = plt.subplots(figsize=(9.5, max(4.5, 0.5 * len(g))))
    colors = ["#d64545" if v > 0 else "#3b6fd6" for v in g["NES"]]
    y = np.arange(len(g))
    ax.barh(y, g["NES"], color=colors, edgecolor="k", lw=.4)
    for i, (_, row) in enumerate(g.iterrows()):
        if pd.notna(row["dir_match"]):
            mark = "일치" if row["dir_match"] else "불일치"
            ax.text(row["NES"] + (0.06 if row["NES"] > 0 else -0.06), i,
                    f"{mark} (paper {row['paper_dir']})",
                    va="center", ha="left" if row["NES"] > 0 else "right", fontsize=8,
                    color="#2c8a4a" if row["dir_match"] else "#c00")
    ax.set_yticks(y); ax.set_yticklabels(g["hallmark"], fontsize=9)
    ax.axvline(0, color="k", lw=.7)
    ax.set_xlabel("NES  (양수 = Ddx54-KD에서 상향 / 음수 = KD에서 하향)")
    ttl = "Hallmark GSEA — Ddx54 녹다운 (독립재현)"
    if len(scored):
        ttl += f"  ·  Fig 6 방향 일치 {match:.0f}%"
    ax.set_title(ttl)
    mx = max(abs(g["NES"].min()), abs(g["NES"].max())) + 1.4
    ax.set_xlim(-mx, mx)
    fig.tight_layout()
    fig.savefig(os.path.join(RESULTS, "gsea_hallmark.png.tmp"), dpi=135, format="png")
    os.replace(os.path.join(RESULTS, "gsea_hallmark.png.tmp"),
               os.path.join(RESULTS, "gsea_hallmark.png"))
    plt.close(fig)
    print("==> [03] done: gsea_hallmark.csv, gsea_hallmark.png")


if __name__ == "__main__":
    main()
