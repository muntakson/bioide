# Puram 2017 두경부암(HNSCC) p-EMT 프로그램 독립 재현 — 스캐폴드 초안 (검토용)

이 폴더는 **"파이프라인 만들기"** 카드가 초안 계획서(.md)로부터 AI로 자동 생성한 **검토용 스캐폴드**입니다. 아직 실제 튜토리얼이 아니며, 검토·수정 후 `modules/`로 **승격(promote)** 해야 합니다.

- 스테이징 위치: `pipeline-drafts/puram-2017-hnscc-pemt-reproduction/`
- 생성 파일: `pipeline.json`, `00_setup_env.sh`, `01_check_availability.sh`, `02_download_matrix.sh`, `03_star_optional.sh`, `04_build_adata.py`, `05_qc.py`, `06_normalize_hvg.py`, `07_scvi_latent.py`, `08_cluster_umap.py`, `09_malignant_cnv.py`, `… (+4개 스크립트 생략됨)`

## ⚠ 반드시 검토하세요
AI가 생성한 스크립트에는 **추측한 URL·accession·파라미터**가 들어 있을 수 있습니다. 각 파일에서 `# TODO: 확인 필요` 주석을 찾아 데이터 접근번호와 명령을 검증하세요. 스크립트는 `$GHBIO_RESULTS`에 결과를 씁니다.

## 실제 튜토리얼로 승격(promote)
```bash
cp -r ~/ghbio-workspace/pipeline-drafts/puram-2017-hnscc-pemt-reproduction ~/ghbio-coscientist/modules/scrna-seq/pipelines/puram-2017-hnscc-pemt-reproduction
# package.json 의 version 을 올린 뒤
cd ~/ghbio-coscientist && bash build.sh
```

그런 다음 브라우저 탭을 **Ctrl+Shift+R** 로 새로고침하면 새 튜토리얼 카드가 GHBIO Home 에 나타납니다.
