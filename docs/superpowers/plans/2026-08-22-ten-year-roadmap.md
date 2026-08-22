# 2nd BRAIN — 10-Year Roadmap (2026–2036)

**Spec:** `docs/superpowers/specs/2026-08-22-2ndbrain-design.md`
**Detailed plan for the first month:** `2026-08-22-phase0-foundation.md`
Each later phase gets its own spec → plan cycle when it starts. This document fixes the direction, the growth strategy for sources/reasoning, and the trigger points.

---

## Phase 0 · Foundation — 2026-09 (1 month)
See detailed plan. Exit: one real book → 3-level HTML page, searchable, on Railway volume.

## Phase 1 · CR's 2nd Brain — 2026-10 → 2027-12

**Goal:** Clair is CR's reliable external memory. Nothing read is lost; inspirations are logged; any topic can be re-learned at any level.

| # | Deliverable | Notes |
|---|---|---|
| 1.1 | Embeddings + hybrid search | `sqlite-vec` filled with a multilingual model (`bge-m3` via API or local ONNX); hybrid BM25+vector ranking |
| 1.2 | `expand` v1 — 5 free connectors | Wikipedia/Wikidata, arXiv, Semantic Scholar, OpenAlex, PubMed. Interface `search(query, lang) -> [Source]`; results to `research/<concept>/sources.md` with DOI/URL (no citation without a link) |
| 1.3 | Korean academic connectors | RISS, KCI open APIs; DBpia abstracts; 알라딘 book metadata |
| 1.4 | Inspiration log | Clair command "영감 기록": appends to `profile/inspiration.md` with date, book, concept links; rendered as timeline page |
| 1.5 | Concept pages | `site/concepts/<concept>/` — 3-level page per concept, merged across books |
| 1.6 | Level memory UX | Clair asks level before every output; `levels.json`; "이제 전문가로" upgrades |
| 1.7 | Backups | Nightly tar of markdown → private repo `CRtheHILLS/2ndBRAIN-vault`; monthly restore drill |
| 1.8 | brain-sync as Windows service | Auto-start on login (Task Scheduler), tray notification on upload |
| 1.9 | Cost guard | Per-day token caps, monthly report page |
| 1.10 | Claude Code MCP tool | `brain` MCP server so Clair calls search/ingest/render natively in-session |

Exit: ≥30 books, CR uses weekly, zero data-loss events, restore drill passed.

## Phase 2 · Reasoning & Connection — 2028 → 2030

**Goal:** Clair produces insights CR didn't ask for but finds valuable.

| # | Deliverable |
|---|---|
| 2.1 | Concept graph (`synthesis/graph.json`, D3 view in viewer): nodes = concepts/books/people/eras; edges typed (supports, contradicts, generalizes, example-of) |
| 2.2 | Weekly "클레어의 통찰" job: pick 2–3 unlinked concept pairs, run expand, write insight note + page, notify CR |
| 2.3 | Contradiction finder: where two books disagree, build a side-by-side page with primary sources |
| 2.4 | Humanities connectors: JSTOR open, Internet Archive, HathiTrust, Gutenberg, Perseus, SEP, PhilPapers, 한국고전번역원 |
| 2.5 | Lecture connectors: YouTube transcripts (MIT OCW, TED), podcasts via Whisper |
| 2.6 | Music crossover: IMSLP, music-theory sources; "이 개념을 곡으로 표현하면?" page type linking CR's catalog |
| 2.7 | Question-driven research: CR asks anything → Clair plans a research tree, runs connectors, writes a report page with level tabs |
| 2.8 | Reader-model: Clair tracks which concepts CR has mastered (levels + quiz pages) and suggests next reads |
| 2.9 | Model upgrades: swap to newest Claude models; evaluation set of 50 CR-rated answers to prevent regressions |

Exit: graph > 1,000 nodes; CR rates ≥70% of weekly insights useful for 3 consecutive months.

## Phase 3 · Multi-user 2nd Brains — 2030 → 2032 (PLAN ONLY until triggered)

**Trigger (all):** Phase 1/2 stable ≥6 months · ≥50 books · CR satisfied with insight quality · a concrete first user group (e.g., 5–10 musicians/friends).

| # | Deliverable |
|---|---|
| 3.1 | Data model promotion: Markdown stays per-user source of truth (`/data/users/<uid>/...`); index moves to Postgres + pgvector; Railway multi-service (api, worker, db) |
| 3.2 | Auth (email magic link / Google), per-user token, strict isolation tests |
| 3.3 | Web upload UI (drag & drop, phone camera), mobile-friendly viewer |
| 3.4 | Per-user Clair persona settings (name, tone) — CR's Clair stays CR's |
| 3.5 | Billing (Stripe) or invite-only; cost caps per user |
| 3.6 | Privacy: encryption at rest for raw files, export/delete-my-data, consent records |
| 3.7 | Offline path: email-in or folder-sync client for others |

Exit: 10 external users onboarded, isolation & restore verified, support load manageable.

## Phase 4 · Central Knowledge LLM — 2032 → 2036 (PLAN ONLY)

**Trigger:** ≥10 active users · approved privacy/consent design · CR decides.

| # | Deliverable |
|---|---|
| 4.1 | Opt-in sharing tiers: private / anonymized concepts only / full notes |
| 4.2 | Federated concept graph: merge anonymized concept nodes across brains; popularity & disagreement signals |
| 4.3 | Collective insights: "사람들이 이 개념을 어떻게 다르게 읽었나" pages |
| 4.4 | Central model strategy: RAG over federated vault first; consider fine-tuning only if measured gain; evaluation harness from 2.9 |
| 4.5 | Governance: data retention, right to be forgotten across federation, audit logs |
| 4.6 | Scale: object storage (S3-compatible) for raw files, Railway volumes for hot data, CDN for pages |

## Growth strategy — how Clair gets smarter every year

**Source expansion is a living strategy (CR directive, 2026-08-22).** The connector table above is only the seed. (a) CR and Clair review source strategy together continuously — what new domains appeared, what worked, what to add. (b) Clair takes initiative: whenever a new topic appears in a book or question, she judges on her own which new sources fit (academic DBs, archives, primary texts, lectures, any language) and **frequently tries them** without being asked, logging each attempt and its usefulness in `research/<concept>/sources.md`, and reporting "이번에 새로 시도한 소스" in the weekly insight. Phase 1 `expand` therefore includes a *source-discovery* step (propose 2–3 candidates beyond the connector list → try → record), under cost caps.


1. **Sources grow by connector files.** One file per source; budget per concept grows with CR's budget. Priority order: free academic APIs → Korean academic → humanities archives → lectures → paid (Perplexity) as capped booster.
2. **Depth grows by research trees.** Concept → sub-questions → sources → synthesis; depth limit raised as cost falls.
3. **Reasoning grows by graph density.** More typed edges → better multi-hop answers; weekly insight job is the engine.
4. **Quality grows by CR's ratings.** Every page has 👍/👎 + comment → evaluation set → model/prompt upgrades must not regress.
5. **Durability by plain Markdown + Git.** Any tool can be replaced; data never is.

## Yearly checkpoints (CR + Clair together)

Every January: review phase exit criteria, budget, model landscape, CR's goals; update this file and memory; decide whether a phase trigger has fired.
