import * as vscode from "vscode"

// A reference webview: the catalog of public 10x Genomics human Single Cell 3' Gene Expression
// FASTQ datasets (verified live on the 10x CDN with their tar sizes). Opened from a card on GHBIO
// Home. Datasets marked `inApp` already ship as a pipeline in this workbench.

const CDN = "https://cf.10xgenomics.com/samples/"

interface Dataset {
  name: string
  chem: string // 10x 3' chemistry
  size: string
  path: string // relative to CDN
  inApp?: string // pipeline id if already available as a tutorial
}

// Ordered smallest → largest (smaller = friendlier for a first run).
const DATASETS: Dataset[] = [
  { name: "PBMC 1k", chem: "3′ v3", size: "5.2 GB", path: "cell-exp/3.0.0/pbmc_1k_v3/pbmc_1k_v3_fastqs.tar", inApp: "scrna-seq-pbmc" },
  { name: "PBMC 1k", chem: "3′ v2", size: "5.9 GB", path: "cell-exp/3.0.0/pbmc_1k_v2/pbmc_1k_v2_fastqs.tar" },
  { name: "PBMC 500 (Low-Throughput)", chem: "3′ v3.1", size: "6.0 GB", path: "cell-exp/6.1.0/500_PBMC_3p_LT_Chromium_Controller/500_PBMC_3p_LT_Chromium_Controller_fastqs.tar" },
  { name: "PBMC 3k", chem: "3′ v1", size: "17.4 GB", path: "cell-exp/1.1.0/pbmc3k/pbmc3k_fastqs.tar" },
  { name: "Glioblastoma tumor", chem: "3′ v3", size: "17.9 GB", path: "cell-exp/4.0.0/Parent_SC3v3_Human_Glioblastoma/Parent_SC3v3_Human_Glioblastoma_fastqs.tar", inApp: "scrna-seq-glioblastoma" },
  { name: "PBMC 5k", chem: "3′ v3", size: "27.2 GB", path: "cell-exp/3.0.2/5k_pbmc_v3/5k_pbmc_v3_fastqs.tar" },
  { name: "Pan T cells 4k", chem: "3′ v2", size: "32.7 GB", path: "cell-exp/2.1.0/t_4k/t_4k_fastqs.tar", inApp: "scrna-seq-pan-t-cells" },
  { name: "Pan T cells 3k", chem: "3′ v2", size: "35.4 GB", path: "cell-exp/2.1.0/t_3k/t_3k_fastqs.tar" },
  { name: "PBMC 4k", chem: "3′ v2", size: "36.4 GB", path: "cell-exp/2.1.0/pbmc4k/pbmc4k_fastqs.tar" },
  { name: "PBMC 10k (Chromium X)", chem: "3′ v3.1", size: "41.0 GB", path: "cell-exp/6.1.0/10k_PBMC_3p_nextgem_Chromium_X/10k_PBMC_3p_nextgem_Chromium_X_fastqs.tar" },
  { name: "PBMC 10k", chem: "3′ v3", size: "48.1 GB", path: "cell-exp/3.0.0/pbmc_10k_v3/pbmc_10k_v3_fastqs.tar" },
]

let panel: vscode.WebviewPanel | undefined

export function openDatasetCatalog() {
  if (!panel) {
    panel = vscode.window.createWebviewPanel("ghbioCatalog", "10x 데이터셋 카탈로그", vscode.ViewColumn.One, {
      enableScripts: true,
      retainContextWhenHidden: true,
    })
    panel.onDidDispose(() => (panel = undefined))
  }
  panel.webview.html = html()
  panel.reveal()
}

const esc = (s: unknown) =>
  String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!)

function html(): string {
  const rows = DATASETS.map((d) => {
    const url = CDN + d.path
    const badge = d.inApp
      ? `<span class="badge in">이 앱에 있음 ✓</span>`
      : ""
    return `<tr>
      <td class="nm">${esc(d.name)} ${badge}</td>
      <td class="chem">${esc(d.chem)}</td>
      <td class="sz">${esc(d.size)}</td>
      <td class="url"><a href="${esc(url)}" title="브라우저에서 열림">${esc(d.path)}</a></td>
    </tr>`
  }).join("\n")

  return /* html */ `<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root{color-scheme:dark}
  *{box-sizing:border-box}
  body{font-family:-apple-system,"Segoe UI","Malgun Gothic",system-ui,sans-serif;color:#e6edf3;background:#0d1117;
    margin:0;padding:26px 30px 60px;line-height:1.55}
  h1{font-size:22px;margin:0 0 4px}
  h1 .a{color:#2dd4bf}
  .sub{color:#8b98a5;font-size:13px;margin-bottom:18px;max-width:70ch}
  table{border-collapse:collapse;width:100%;font-size:13px}
  th,td{text-align:left;padding:8px 12px;border-bottom:1px solid #21262d;vertical-align:top}
  th{color:#7ee7d6;font-size:12px;text-transform:uppercase;letter-spacing:.03em;position:sticky;top:0;background:#0d1117}
  tr:hover td{background:#12181f}
  td.nm{font-weight:600;white-space:nowrap}
  td.chem,td.sz{white-space:nowrap;color:#b6c2cf}
  td.url a{color:#2dd4bf;word-break:break-all}
  .badge{font-size:10.5px;font-weight:700;border-radius:10px;padding:1px 7px;margin-left:6px}
  .badge.in{background:#12312b;color:#7ee7d6;border:1px solid #1f5a4f}
  .note{margin-top:16px;color:#8b98a5;font-size:12.5px;max-width:80ch}
  code{background:#161b22;padding:1px 5px;border-radius:4px}
</style></head><body>
  <h1>Human Single Cell <span class="a">3′ Gene Expression</span> FASTQ datasets</h1>
  <div class="sub">공개 10x Genomics 사람 단일세포 3′ 유전자 발현 FASTQ 데이터셋 목록입니다. 모든 링크는 10x 공식 CDN(<code>cf.10xgenomics.com</code>)에서 실제로 확인된 <code>_fastqs.tar</code> 주소이며, 크기 순으로 정렬했습니다. 링크를 누르면 브라우저에서 열립니다.</div>
  <table>
    <thead><tr><th>Dataset (조직/샘플)</th><th>Chemistry</th><th>Size</th><th>FASTQ 다운로드 (10x CDN)</th></tr></thead>
    <tbody>
      ${rows}
    </tbody>
  </table>
  <div class="note">
    · <b>Chemistry</b> 는 바코드 화학 버전입니다. <b>v2</b> 는 UMI 10 bp + 737K 바코드 목록, <b>v3/v3.1</b> 은 UMI 12 bp + 3M 목록을 씁니다 — STARsolo 단계가 자동으로 맞춥니다.<br>
    · 모두 사람(GRCh38) 데이터라 이미 만든 STAR 색인을 <b>재사용</b>합니다.<br>
    · <span class="badge in">이 앱에 있음 ✓</span> 표시된 데이터셋은 튜토리얼 파이프라인으로 이미 등록되어 있습니다.
  </div>
</body></html>`
}
