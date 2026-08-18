#!/usr/bin/env python3
"""
04_gsea_hallmark.py — preranked GSEA (Subramanian weighted-KS enrichment score
with gene-label permutation for NES/p) over OUR P3C-vs-P0C moderated-t ranking,
against a self-contained set of MSigDB Hallmark gene sets (no internet). Tests
the report's program-level claims: IFN-γ/α Response UP, E2F Targets & G2M
Checkpoint UP, EMT DOWN, Notch & Hedgehog DOWN. Reads GHBIO_RESULTS.

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
print(f"==> [04] results dir: {RESULTS}")

# --- Embedded Hallmark gene sets (curated cores from MSigDB h.all). Enough
#     membership for a stable rank-based enrichment; direction is the target. ---
HALLMARK = {
"HALLMARK_INTERFERON_GAMMA_RESPONSE": """STAT1 IRF1 GBP1 GBP2 GBP4 GBP6 CXCL9 CXCL10 CXCL11
PSMB8 PSMB9 PSMB10 TAP1 TAP2 HLA-A HLA-B HLA-C HLA-DMA HLA-DRB1 B2M OAS2 OAS3 OASL MX1 MX2 IRF7 IRF8
IRF9 ISG15 IFIT1 IFIT2 IFIT3 IFI35 IFI44 IFIH1 IFITM2 IFITM3 WARS UBE2L6 SOCS1 SOCS3 STAT2 NLRC5
CD274 PDL1 GBP3 GBP5 CIITA VCAM1 ICAM1 CASP1 CASP4 CASP7 CASP8 XAF1 SAMD9L DDX58 DDX60 RSAD2 BST2
NMI PARP14 PARP9 PARP12 SP100 SP140 TNFAIP3 TRIM21 TRIM22 TRIM25 USP18 EIF2AK2 RIPK2 IL15RA VAMP5
LGALS3BP HERC6 ISG20 ZBP1 APOL6 IDO1 SERPING1 C1S CD40 CD69 CD86 FGL2 PSME1 PSME2 MT2A""",
"HALLMARK_INTERFERON_ALPHA_RESPONSE": """ISG15 MX1 MX2 OAS1 OAS2 OAS3 OASL IFIT1 IFIT2 IFIT3
IFI27 IFI35 IFI44 IFI44L IFITM1 IFITM2 IFITM3 IRF7 IRF9 RSAD2 USP18 STAT1 STAT2 BST2 PLSCR1 DDX60
SAMD9 SAMD9L LY6E CMPK2 HERC6 EIF2AK2 GBP2 GBP4 PSMB8 PSMB9 TAP1 UBE2L6 ISG20 IFIH1 CXCL10 ADAR
PARP9 PARP12 PARP14 TRIM21 TRIM22 TRIM25 SP100 NMI LGALS3BP RTP4 EPSTI1 CASP1 CASP8 IL15 IRF1 B2M
SELL WARS TENT5A CD74 PROCR SLC25A28 DHX58 GMPR""",
"HALLMARK_EPITHELIAL_MESENCHYMAL_TRANSITION": """FN1 VIM ZEB1 ZEB2 SNAI2 TWIST1 CDH2 COL1A1 COL1A2
COL3A1 COL4A1 COL5A1 COL5A2 COL6A1 COL6A2 COL6A3 COL11A1 FBN1 FBN2 SPARC SPP1 THBS1 THBS2 TIMP1
TIMP3 TAGLN ACTA2 POSTN LOX LOXL1 LOXL2 MMP2 MMP3 MMP14 TGFBI TGFB1 TGFBR3 SERPINE1 SERPINE2 PDGFRB
FBLN1 FBLN2 FBLN5 DCN LUM BGN VCAN ELN CTGF CYR61 IGFBP3 IGFBP4 INHBA WNT5A GREM1 FGF2 PMP22 CDH11
ITGA5 ITGAV ITGB1 ITGB3 NNMT FSTL1 SFRP1 SFRP4 COMP EMP3 GLIPR1 GEM CAP2 CALD1 TPM1 TPM2 MYL9
COL8A1 COL8A2 COL12A1 COL16A1 CAPG QSOX1 PCOLCE FUCA1 GAS1 P4HA2 PLOD1 PLOD2 PLOD3 PRRX1""",
"HALLMARK_NOTCH_SIGNALING": """NOTCH1 NOTCH2 NOTCH3 JAG1 JAG2 DLL1 DTX1 DTX2 DTX4 HES1 HEY1 HEYL
MAML1 MAML2 RBPJ PSEN1 PSEN2 PSENEN NCOR2 NCSTN LFNG MFNG APH1A ADAM17 ARRB1 CUL1 FBXW11 KAT2A
SAP30 SKP1 ST3GAL6 TCF7L2 PPARD WNT2 WNT5A HDAC2 CCND1""",
"HALLMARK_HEDGEHOG_SIGNALING": """GLI1 GLI2 GLI3 SMO PTCH1 PTCH2 SHH HHIP SCUBE2 GAS1 BMP2 BMP4
BMP6 WNT5A WNT5B CDK5R1 CDK6 RTN1 L1CAM NKX6-1 NRP1 NRP2 SLIT1 CNTFR PLG THY1 VLDLR ACHE ADGRG1
DPYSL2 HEY1 HEY2 CRMP1 UNC5C VEGFA CELSR1 ETS2 MYH9 OFD1 PML SCG2 TCF7L2""",
"HALLMARK_E2F_TARGETS": """MKI67 PCNA MCM2 MCM3 MCM4 MCM5 MCM6 MCM7 CDK1 CDC6 CDC20 CDC25A CCNE1
CCNB2 E2F1 E2F8 TK1 RRM2 RRM1 TYMS DHFR ORC6 ORC1 POLE POLA1 POLD1 POLD3 GINS1 GINS3 CDKN2C CDKN3
BUB1B PLK1 PLK4 AURKA AURKB TOP2A EXO1 RFC1 RFC2 RFC3 CHEK1 CHEK2 BRCA1 BRCA2 RAD51 RAD51AP1 RRM2B
UNG DUT SLBP HMGB2 H2AFZ HELLS DNMT1 SMC1A SMC3 SMC4 SMC6 NCAPD2 NASP MYBL2 KIF22 CDC45 GINS4 WDR76
LMNB1 CBX5 SPC24 SPC25 NUSAP1 TIMELESS TRIP13 ZW10 ASF1B CENPE CENPM CTCF DCK DEK LIG1 MRE11 PRIM2
PMS2 PNN POLD2 PPM1D PSMC3IP RANBP1 SHMT1 STMN1 SUV39H1 TFRC TUBB USP1 XRCC6 ANP32E ATAD2""",
"HALLMARK_G2M_CHECKPOINT": """CCNB1 CCNB2 CCNA2 CDK1 CDC20 CDC25A CDC25B CDC25C PLK1 PLK4 AURKA
AURKB BUB1 BUB1B BUB3 TOP2A KIF11 KIF23 KIF15 KIF2C KIF4A KIF20B CENPA CENPE CENPF NDC80 SPC24 SPC25
MKI67 TPX2 UBE2C CKS1B CKS2 CDCA2 CDCA3 CDCA8 NUSAP1 PRC1 ANLN ECT2 RACGAP1 SMC2 SMC4 NCAPD2 NCAPH
NCAPG CDK4 CCND1 E2F1 E2F2 MYBL2 FOXM1 HMGB2 H2AFX H2AFZ HMGB3 TROAP STMN1 TUBB4B CDKN3 KPNA2 KPNB1
MAD2L1 MELK ODF2 ORC5 PBK POLA2 PRMT5 PTTG1 RAD21 SFPQ SLC7A5 SQLE SRSF1 SRSF2 TACC3 TNPO2 TTK
INCENP EXO1 EFNA5 DR1 EGF ATRX AMD1 ARID4A BARD1 BCL3 BRCA2 CASP8AP2 CBX1 CHAF1A""",
"HALLMARK_MYC_TARGETS_V1": """MYC MAX NPM1 NCL NOLC1 FBL GNL3 NOP56 NOP16 PA2G4 HSPD1 HSPE1 EIF4E
EIF4G2 EIF3B EIF3D EIF3J EIF2S1 EIF2S2 EIF1AX RPL3 RPL6 RPL14 RPL22 RPL34 RPS2 RPS3 RPS5 RPS6 RPSA
PABPC1 SRM ODC1 CAD PPAT TYMS DHFR IMPDH2 PRPS2 CCT2 CCT3 CCT4 CCT5 CCT7 TCP1 SNRPA1 SNRPB2 SNRPD1
SNRPD2 SNRPG HNRNPA1 HNRNPA2B1 HNRNPC HNRNPD HNRNPR PTGES3 RUVBL2 CBX3 CDK4 SET SSB TFDP1 NDUFAB1
PHB PHB2 RAN RANBP1 XPO1 KPNA2 KPNB1 SERBP1 SLC25A3 VDAC1 VDAC3 GLO1 LDHA APEX1 C1QBP MCM5 ORC2
POLD2 PRDX3 PSMA1 PSMA4 PSMA6 PSMB2 PSMC4 PSMD1 PSMD3 EPRS FARSA""",
"HALLMARK_HYPOXIA": """VEGFA SLC2A1 LDHA PGK1 HK1 HK2 PFKL PFKFB3 ALDOA ALDOC ENO1 ENO2 GAPDH PKM
PDK1 BNIP3 BNIP3L DDIT4 EGLN1 EGLN3 P4HA1 P4HA2 PLOD1 PLOD2 CA9 CA12 ADM ANKRD37 NDRG1 SLC2A3 GYS1
PGM1 PGM2 GPI TPI1 ALDOB FOXO3 HIF1A EPAS1 ANGPTL4 SERPINE1 PGF LOX PLAC8 STC1 STC2 MT1X MT2A ERO1A
TGFB3 PPP1R15A ATF3 JMJD6 KDM3A CITED2 PIM1 DTNA GAA GBE1 IGFBP3 IGFBP1 ZNF292 WSB1""",
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
    de = pd.read_csv(os.path.join(RESULTS, "de_p3c_vs_p0c.csv"), index_col=0)
    de = de.sort_values("t", ascending=False)
    gene_order = de.index.to_numpy()
    rank = de["t"].to_numpy()

    rows = []
    for name, gs in HALLMARK.items():
        res = preranked_gsea(rank, gene_order, gs)
        if res is None:
            continue
        rep = C.REPORT_GSEA.get(name)
        rows.append({
            "hallmark": name.replace("HALLMARK_", ""),
            "NES": round(res["NES"], 3), "p": round(res["p"], 4), "size": res["size"],
            "our_dir": "UP" if res["NES"] > 0 else "DOWN",
            "report_NES": rep,
            "report_dir": ("UP" if rep > 0 else "DOWN") if rep is not None else "",
            "dir_match": (None if rep is None else (res["NES"] > 0) == (rep > 0)),
        })
    g = pd.DataFrame(rows).sort_values("NES", ascending=False)
    g.to_csv(os.path.join(RESULTS, "gsea_hallmark.csv"), index=False)
    scored = g.dropna(subset=["dir_match"])
    # dir_match is an object column (True / None) — coerce to bool before averaging.
    match = (scored["dir_match"].astype(bool).sum() / len(scored) * 100) if len(scored) else float("nan")
    print(f"==> GSEA: {len(g)} sets; report-comparable {len(scored)}; "
          f"direction match {match:.0f}%")
    print(g[["hallmark", "NES", "p", "our_dir", "report_dir", "dir_match"]].to_string(index=False))

    # figure: NES bar, colored by direction, report-set outlined
    fig, ax = plt.subplots(figsize=(9, max(4.5, 0.5 * len(g))))
    colors = ["#d64545" if v > 0 else "#3b6fd6" for v in g["NES"]]
    y = np.arange(len(g))
    ax.barh(y, g["NES"], color=colors, edgecolor="k", lw=.4)
    for i, (_, row) in enumerate(g.iterrows()):
        if pd.notna(row["dir_match"]):
            mark = "✓" if row["dir_match"] else "✗"
            ax.text(row["NES"] + (0.06 if row["NES"] > 0 else -0.06), i,
                    f"{mark} (report {row['report_dir']})",
                    va="center", ha="left" if row["NES"] > 0 else "right", fontsize=8,
                    color="#2c8a4a" if row["dir_match"] else "#c00")
    ax.set_yticks(y); ax.set_yticklabels(g["hallmark"], fontsize=9)
    ax.axvline(0, color="k", lw=.7)
    ax.set_xlabel("NES (P3 내성 vs P0 민감)")
    ttl = "Hallmark GSEA — 독립재현"
    if len(scored):
        ttl += f"  (보고서 방향 일치 {match:.0f}%)"
    ax.set_title(ttl)
    mx = max(abs(g["NES"].min()), abs(g["NES"].max())) + 1.2
    ax.set_xlim(-mx, mx)
    fig.tight_layout()
    fig.savefig(os.path.join(RESULTS, "gsea_hallmark.png.tmp"), dpi=135, format="png")
    os.replace(os.path.join(RESULTS, "gsea_hallmark.png.tmp"),
               os.path.join(RESULTS, "gsea_hallmark.png"))
    plt.close(fig)
    print("==> [04] done: gsea_hallmark.csv, gsea_hallmark.png")


if __name__ == "__main__":
    main()
