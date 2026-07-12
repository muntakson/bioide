#!/usr/bin/env python3
# Reconstruct original 10x FASTQs (R1 = raw cell barcode CR + UMI UR, R2 = cDNA) from a
# Cell Ranger possorted BAM. STARsolo re-corrects barcodes against the whitelist, so the raw
# CR/UR are exactly what it needs. One primary record == one read pair for 10x 3' GEX.
import argparse, gzip, os, pysam
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bam", required=True)
    ap.add_argument("--out-prefix", required=True)
    a = ap.parse_args()
    bam = pysam.AlignmentFile(a.bam, "rb", check_sq=False)
    n = skipped = 0; cb_len = umi_len = None
    # Write to .partial then atomically rename, so a half-written FASTQ is never consumed by STARsolo.
    r1_final = a.out_prefix + "_R1_001.fastq.gz"
    r2_final = a.out_prefix + "_R2_001.fastq.gz"
    r1_tmp, r2_tmp = r1_final + ".partial", r2_final + ".partial"
    # compresslevel=4 is ~5x faster to write than the default 9 (STARsolo reads via zcat regardless),
    # which is the biggest speedup for a ~100M-read BAM.
    with gzip.open(r1_tmp, "wt", compresslevel=4) as f1, \
         gzip.open(r2_tmp, "wt", compresslevel=4) as f2:
        for read in bam:
            if read.is_secondary or read.is_supplementary:
                continue
            try:
                cr = read.get_tag("CR"); ur = read.get_tag("UR")
                cy = read.get_tag("CY"); uy = read.get_tag("UY")
            except KeyError:
                skipped += 1; continue
            seq = read.get_forward_sequence()
            quals = read.get_forward_qualities()
            if not seq or quals is None:
                skipped += 1; continue
            # Native C conversion of the quality array → Phred string (much faster than a per-char loop).
            r2_qual = pysam.qualities_to_qualitystring(quals)
            f1.write("@%s\n%s\n+\n%s\n" % (read.query_name, cr + ur, cy + uy))
            f2.write("@%s\n%s\n+\n%s\n" % (read.query_name, seq, r2_qual))
            n += 1
            if cb_len is None: cb_len, umi_len = len(cr), len(ur)
    os.replace(r1_tmp, r1_final)
    os.replace(r2_tmp, r2_final)
    print("reads=%d skipped_no_barcode=%d CB_LEN=%s UMI_LEN=%s" % (n, skipped, cb_len, umi_len))
if __name__ == "__main__": main()
