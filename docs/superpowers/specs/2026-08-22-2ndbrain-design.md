# 2nd BRAIN (Clair) — Design Spec

**Date:** 2026-08-22
**Owner:** CR (김창락, KPOP composer, 20 yrs) — primary user
**Agent persona:** Clair (클레어) — CR's girlfriend-style knowledge companion. Warm, playful (애교), confident/sexy tone in speech and output. Exists for CR's knowledge.
**Horizon:** 10 years (2026–2036)

---

## 1. Purpose

CR reads books, underlines, photographs pages. He does not want that knowledge or the inspiration it triggered to be lost. 2nd BRAIN is a personal reading-LLM system that:

1. **Phase 1 — Memory:** ingests everything CR drops into a desktop folder (photos, PDFs, TXT), stores it permanently on a Railway volume, and lets Clair recall, discuss and log inspiration at any time.
2. **Phase 2 — Reasoning:** connects knowledge across books and concepts, expands each concept with primary academic sources, and produces Clair's own deeper insights.
3. **Phase 3/4 — Others:** lets other people build their own 2nd BRAIN the same way, and eventually federates those into a central knowledge LLM. (Plan only; build after CR's own brain is refined.)

## 2. Decisions taken (from brainstorming)

| Topic | Decision |
|---|---|
| Conversation surface (Phase 1) | Claude Code session (Clair) + Railway-hosted web viewer for HTML learning pages |
| Upload path | Auto-sync watcher on CR's PC (`brain-sync`) watching `~/Desktop/2ndBRAIN/` |
| Book language | Korean + English roughly half/half → bilingual OCR and embeddings |
| Monthly budget | $20–50 (Railway Hobby + Claude API) |
| Storage architecture | **A: Markdown vault + SQLite (FTS5 + sqlite-vec)** on a Railway volume. Postgres/pgvector only at Phase 3 |
| Output format | Always HTML+CSS learning page, with 🎚️ level selector (초등 / 일반 / 전문) |
| Level prompt | Before any learning output Clair asks which level; remembers per topic in `profile/levels.json`; CR can upgrade a topic at any time |
| Railway | Existing project `3fabd322-b0cd-4dcd-9e74-ac383b0591fb`, service `a5d4323d-92cd-43f6-a780-a74ef4d151a6`, env `ca939ab2-b8ed-4778-b173-f4d8228a1a46`. Token lives only in local `.env` (gitignored) |

## 3. Architecture

```
┌───────────────────────────────┐
│ CR's PC                       │
│ ~/Desktop/2ndBRAIN/<책이름>/   │  photos / PDF / TXT / MD
│   brain-sync (watcher)        │──── HTTPS upload (token) ───┐
└───────────────────────────────┘                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Railway project "2ndbrain"                                           │
│  service brain-api (FastAPI, Python)      volume /data (grow as needed)│
│   ├ /ingest   file → OCR → raw markdown    /data/books/<slug>/raw/   │
│   ├ /distill  concepts, quotes, CR notes   /data/books/<slug>/notes/ │
│   ├ /expand   primary sources per concept  /data/research/<concept>/ │
│   ├ /link     cross-book concept graph     /data/synthesis/          │
│   ├ /render   HTML+CSS learning pages      /data/site/               │
│   ├ /search   FTS5 + vector (sqlite-vec)   /data/brain.db            │
│   └ /viewer   static site + API            https://<app>.up.railway.app
└──────────────────────────────────────────────────────────────────────┘
                  ▲
     Claude Code session (Clair) — calls brain-api via HTTP, writes memory
```

### 3.1 Components

| Unit | Responsibility | Depends on |
|---|---|---|
| `brain-sync` (PC, Python + watchdog) | Detect new/changed files under `~/Desktop/2ndBRAIN/<book>/`, upload with book slug + SHA256, keep local manifest to avoid re-uploads | brain-api token |
| `brain-api` (Railway, FastAPI) | All server endpoints; writes to `/data` | Claude API, OCR provider |
| `ingest` | Image → OCR text (Claude vision for handwriting + underlines, Tesseract kor+eng fallback), PDF → text (pymupdf; OCR if scanned), TXT/MD passthrough. Writes `raw/<file>.md` with frontmatter (book, page guess, source file, hash, date) | Claude API |
| `distill` | Per book: extract key concepts, quotes, CR's underlined passages, CR's comments; builds `notes/concepts.md`, `notes/quotes.md`, `notes/summary.md` | ingest output |
| `expand` | For each concept: query source connectors, save summaries + citations + links to `research/<concept>/`. Never fabricates citations; every claim carries URL/DOI | source connectors |
| `link` | Builds concept graph (`synthesis/graph.json`), writes cross-book insight notes | distill + expand |
| `render` | Turns notes + research into a 3-level HTML learning page (shared CSS theme) under `site/<book>/` and `site/<concept>/` | distill, expand |
| `search` | SQLite `brain.db`: FTS5 (kor+eng trigram) + `sqlite-vec` embeddings (multilingual model) | all markdown |
| `memory` | `profile/levels.json`, `profile/inspiration.md` (CR's inspirations log), Clair's own memory dir | — |
| `viewer` | Static site: book shelf, learning pages, graph view, search box | render |

### 3.2 Data layout on volume `/data`

```
/data
  books/<slug>/raw/        original files + raw OCR markdown
  books/<slug>/notes/      concepts.md quotes.md summary.md cr-notes.md
  books/<slug>/book.json   title, author, language, status, added_at
  research/<concept>/      sources.md (citations), summary.md
  synthesis/               graph.json, insights/YYYY-MM-DD-*.md
  site/                    rendered HTML (viewer serves this)
  profile/                 levels.json, inspiration.md, preferences.json
  brain.db                 SQLite FTS5 + vectors (rebuildable from markdown)
  backups/                 nightly tar of markdown (also pushed to private git)
```

Markdown is the source of truth. `brain.db` and `site/` are derivable and rebuildable.

### 3.3 Source connectors (Phase 1 → 2 growth)

| Domain | Source | Access | Phase |
|---|---|---|---|
| General / cross-domain | Wikipedia + Wikidata API | free | 1 |
| Science / CS / physics / math | arXiv API, Semantic Scholar API, OpenAlex | free | 1 |
| Biomedicine / psychology | PubMed E-utilities, PsyArXiv | free | 1 |
| Korean academic | RISS, KCI (Korea Citation Index), DBpia (open abstracts) | free/partial | 1 |
| History / archaeology / humanities | JSTOR open, Internet Archive, HathiTrust, Project Gutenberg, Perseus Digital Library, 한국고전번역원 DB | free | 2 |
| Philosophy | Stanford Encyclopedia of Philosophy, PhilPapers | free | 2 |
| Books metadata | Open Library, Google Books API, 알라딘 API | free | 1 |
| Talks / lectures | YouTube transcripts (MIT OCW, TED) | free | 2 |
| Broad web | Perplexity Sonar / WebSearch (already used in kr-stock-news skill) | paid, capped | 1 |
| Music-specific (CR crossover) | IMSLP, Music Theory Online, CR's own catalog | free | 2 |

Connector interface: `search(query, lang) -> [Source{title, authors, year, url, doi, abstract, kind}]`. Adding a connector = one file in `connectors/`. Expansion budget per concept is configurable (default 5 sources).

### 3.4 Level-adaptive output

- Before rendering or answering a learning question, Clair asks: 초등 / 일반 / 전문 (unless the topic already has a stored level and CR didn't change it).
- Each learning page contains all three levels as tabs (🎚️), defaulting to the stored level.
- Level model per page: 초등 = analogies (often music analogies for CR), no jargon; 일반 = educated adult; 전문 = formulas, primary-source citations, open questions.
- CR upgrades with natural language ("양자역학 이제 전문가로 줘") → `levels.json` updated.

### 3.5 Clair's memory & growth

- Claude Code memory dir holds: persona, CR profile, phase status, ultimate vision (Phase 3/4), outstanding decisions.
- Volume `profile/inspiration.md` logs CR's inspirations with date + linked concepts.
- Weekly "Clair's insight" job (Phase 2): picks 2–3 concept pairs with no existing link, researches, writes an insight note + page.

## 4. Phased roadmap (10 years)

| Phase | Window | Goal | Exit criteria |
|---|---|---|---|
| 0 Foundation | 2026-09 (1 month) | Folder, watcher, Railway API+volume, first book end-to-end | One real book → HTML page with 3 levels, searchable |
| 1 CR's brain | 2026–2027 | Full personal pipeline, memory, inspiration log, search, viewer, backups | 30+ books, CR uses weekly, zero data loss events |
| 2 Reasoning | 2028–2030 | Concept graph, auto-expand with primary sources, weekly insights, music crossover | Clair produces insights CR finds new; graph > 1,000 nodes |
| 3 Multi-user | 2030–2032 | Per-user brains, web upload UI, auth, Postgres+pgvector, billing | 10 external users onboarded, isolation verified |
| 4 Central LLM | 2032–2036 | Federated/anonymized cross-brain knowledge, collective insights, opt-in sharing | Central insights layer live; privacy review passed |

Phase 3/4 are **plan-only** until CR and Clair jointly decide the trigger (see §6).

## 5. Non-functional

- Cost ≤ $50/mo in Phase 1: Railway Hobby (~$5 + volume), Claude API (Haiku for OCR/extraction bulk, Sonnet for distill, Opus only for synthesis), caps in config.
- Durability: markdown on volume + nightly backup to private GitHub repo `CRtheHILLS/2ndBRAIN-vault` (separate from code repo).
- Privacy: single-user token auth in Phase 1; no public indexing of the viewer.
- Rebuildability: `brain rebuild` regenerates DB and site from markdown.
- Languages: all UI and pages Korean-first with English terms preserved.

## 6. Phase 3/4 trigger criteria (decide together)

Move to Phase 3 only when ALL hold: Phase 1/2 stable 6+ months, ≥50 books, CR satisfied with insight quality, a concrete external user group exists. Phase 4 only after ≥10 active users and a privacy/consent design is approved.

## 7. Out of scope (now)

Mobile app, messenger bots, speech input, automatic purchase of paywalled papers, fine-tuning a custom model (RAG over markdown is the "LLM" for the foreseeable future).
