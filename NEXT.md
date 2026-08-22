# NEXT.md — 2nd BRAIN (Clair)

Phase: **0 complete → Phase 1 starting**. Live: https://2ndbrain-production-4ab7.up.railway.app (volume /data 5GB). Branch main @ bc9c12e.
- Spec: docs/superpowers/specs/2026-08-22-2ndbrain-design.md
- Phase 0 plan (done): docs/superpowers/plans/2026-08-22-phase0-foundation.md
- 10-year roadmap: docs/superpowers/plans/2026-08-22-ten-year-roadmap.md
- NotebookLM import guide: docs/guides/notebooklm-import.md

## Pending (needs CR)
- [ ] ANTHROPIC_API_KEY → put in local `.env`; Clair sets it on Railway (`railway variable set`). Until then /process (OCR·distill·render) cannot run live.
- [ ] 양자역학 sources: export NotebookLM notes to Google Docs → download .md/.txt → ~/Desktop/2ndBRAIN/양자역학/ ; copy original PDFs there too.
- [ ] Run brain-sync once, then POST /books/양자역학/process?level=<초등|일반|전문>, open /site/양자역학/.
- [ ] Delete test book "클레어-연결테스트" from the volume (needs a delete endpoint — Phase 1 item).

## Phase 1 backlog (from final review)
- run OCR in threadpool; watcher timeout 900s + incremental manifest; PDF page cap
- nightly backup to private repo (before CR deletes local files!)
- /upload refreshes shelf + index; `brain rebuild` command; DELETE /books/{slug}
- embeddings (sqlite-vec), connectors v1 (Wikipedia/arXiv/Semantic Scholar/OpenAlex/PubMed + RISS/KCI), inspiration log, concept pages, Clair MCP tool

## Rules each session
- Ask level (초등/일반/전문) before any learning output; output is always an HTML page.
- Local desktop files are transient; the volume is the permanent store.
- Phase 3/4 are plan-only until CR + Clair decide together.
