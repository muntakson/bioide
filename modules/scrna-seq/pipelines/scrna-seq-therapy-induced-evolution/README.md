# Therapy-Induced Evolution of Human Lung Cancer

BioIDE tutorial for reproducing Maynard *et al.*, *Cell* 182 (2020), 1232–1251, doi:10.1016/j.cell.2020.07.017.

It deliberately executes the authors' public R Markdown notebooks, rather than reimplementing the analysis. The tutorial pins `czbiohub/scell_lung_adenocarcinoma` at `de138c79bcfc2fa3a28c8a039a28ab560da78099` and obtains its processed `Data_input` directory from the Google Drive link in the authors' README. The raw read archive is NCBI BioProject [PRJNA591860](https://www.ncbi.nlm.nih.gov/bioproject/PRJNA591860).

Run the steps in order. The tutorial uses an isolated user R library at `~/ghbio-venv-r/maynard-2020` and works in `~/ghbio-tutorial/maynard-2020`; it never overwrites a system R library. The public repository does not include the `NI03.1_Running_inferCNV_R3_4_4.Rmd` notebook that the authors cite for the actual legacy-R inferCNV run. BioIDE therefore reproduces the published code through the epithelial/CNV preparation and writes an explicit hand-off file instead of silently substituting a different CNV analysis or claiming downstream cancer results were reproduced.

The outputs remain beside the authors' code (`Data_input`, `data_out`, and `plot_out`) and BioIDE records a completion/provenance file in the tutorial project results directory.
