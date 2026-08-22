# NEXT.md — 2nd BRAIN (Clair)

Phase: **0 complete → Phase 1 starting**. Live: https://2ndbrain-production-4ab7.up.railway.app (volume /data 5GB). Branch main @ bc9c12e.
- Spec: docs/superpowers/specs/2026-08-22-2ndbrain-design.md
- Phase 0 plan (done): docs/superpowers/plans/2026-08-22-phase0-foundation.md
- 10-year roadmap: docs/superpowers/plans/2026-08-22-ten-year-roadmap.md
- NotebookLM import guide: docs/guides/notebooklm-import.md

## 내일(2026-08-23) 제일 먼저 — CR이 2026-08-22 저녁 미룸
- [ ] ANTHROPIC_API_KEY: CR이 채팅에 올린 키 → 로컬 .env에 넣고 Railway 변수로 설정 (키는 재발급 권장)
- [ ] 눈높이 규칙 변경 반영: 3단 탭 말고 **선택한 한 레벨만** 출력, 작성 전에 **항상** 질문 → brain/render.py + 양자역학 페이지 v2
- [ ] NotebookLM: 깃헙의 NotebookLM 스킬/MCP 재조사("notebooklm mcp", "notebooklm skill", notebooklm-py) → 양자역학 노트북 소스 가져오기 구현

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
