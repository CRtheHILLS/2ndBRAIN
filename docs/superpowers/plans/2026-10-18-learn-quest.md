# 학습 퀘스트 + 20년 지식 프레임 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** CR의 한 문장("나 헬리콥터 운전 배우고 싶어")으로 자료 수집 → 7일 초등 수업 → 영구 개념 그래프(다리 포함)까지 자동으로 끝나는 서버 파이프라인과 CLI·스킬을 만든다.

**Architecture:** 서버(FastAPI, Railway, 볼륨 `/data`)는 결정론적 두뇌: 연결기 수집, 그래프(append-only 이벤트 로그 + SQLite), 퀘스트 상태 기계. "생각"은 `brain/think.py`의 제공자 사슬(Anthropic → Gemini → xAI)로 꽂아 쓰고, 전부 실패하면 과제 파일로 남겨 Clair가 세션에서 대신 풀거나 스케줄러가 30분마다 재시도한다. 수업·그래프·검색 결과는 전부 볼륨에 영구 저장되고 정적 사이트로 보인다.

**Tech Stack:** Python 3.12+, FastAPI, pydantic v2, SQLite(FTS5 + sqlite-vec), httpx, Jinja2, trafilatura, pymupdf, ddgs, youtube-transcript-api, d3-force(cdnjs), pytest + respx.

**Spec:** `docs/superpowers/specs/2026-10-18-learn-quest-design.md` (실행자는 과제와 함께 스펙의 해당 절을 읽는다.)

## Global Constraints

- 사용자용 문자열(CLI 메시지, 페이지 문구, 프롬프트의 산출 언어, 오류 메시지)은 **한국어**. 코드·식별자·로그 키는 영어.
- 기본값: 레벨 `초등`, 일수 `7`. 되묻지 않는다. 한 레벨만 렌더한다.
- 외부 네트워크는 테스트에서 절대 호출하지 않는다(`respx` 또는 monkeypatch). 기존 테스트 전부 통과 유지.
- 모델 기본값: Anthropic smart `claude-sonnet-5-5` / fast `claude-haiku-5-5`; Gemini smart `gemini-3.5-flash` / fast `gemini-3.1-flash-lite` / embed `gemini-embedding-001`(768); xAI smart `grok-4.3` / fast `grok-4-1-fast-non-reasoning`. 제공자 순서 기본 `anthropic,gemini,xai`.
- 예산 기본값: `think_daily_cap=200`, `think_retry_minutes=30`, `think_retry_hours=48`, 퀘스트당 `max_think_calls=40`, `max_sources=45`, `max_doc_chars=60000`, `max_pdf_pages=40`, `max_minutes=30`, 점당 자료 `quota_per_dot=2`.
- 그래프 진실은 `/data/graph/events.jsonl`(append-only). DB는 재생성 가능해야 한다.
- 노드 id: `slugify(영어 라벨)` → 없으면 `slugify(한국어 라벨)`; 동명이의어는 `-<field_code 소문자>` 접미사. 분류 코드는 재사용 금지, 병합은 `deprecated_to`.
- 데이터 API(`/quests*`, `/graph*`, `/ask`, `/vault.zip`)는 `X-Brain-Token` 필수. `/site/**`는 기존대로 공개+noindex.
- 커밋 메시지는 한국어 또는 영어 conventional 형식, 끝에 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- HTTP User-Agent: `2ndBRAIN/0.1 (+https://github.com/CRtheHILLS/2ndBRAIN)`. 이메일은 넣지 않는다.

## Review Focus

1. 모델이 JSON을 ```json 펜스나 앞뒤 설명문으로 감싸 보낼 때 → `parse_json`이 바깥 중괄호를 구제해야 한다 (Task 1 테스트).
2. 같은 글이 `http://`, `https://`, `m.wikipedia`, 꼬리 `#`/`utm_` 으로 다르게 들어올 때 → 하나로 합쳐져야 한다 (Task 8 테스트).
3. 퀘스트 문장에 따옴표·이모지·200자 넘는 문장이 올 때 → 슬러그가 안전하고 같은 문장 재요청은 기존 퀘스트를 돌려줘야 한다 (Task 10 테스트).
4. 생각 결과가 스키마에 안 맞을 때(증거 등급 오타 등) → 서버가 죽지 않고 과제가 `open`으로 남으며 오류 사유가 기록돼야 한다 (Task 11 테스트).
5. 서버가 수집 도중 재시작될 때 → `resume`이 끝난 단계는 건너뛰고 원문 파일이 중복 생성되지 않아야 한다 (Task 12 테스트).

## 파일 구조

```
brain/
  config.py            (수정) 모델·키·예산 설정
  think.py             (신규) 제공자 사슬, parse_json, 사용량 기록, ThinkUnavailable
  embed.py             (신규) Gemini 임베딩 (없으면 None)
  db.py                (신규) brain.db 공용 connect() + 전체 스키마
  index.py             (수정) db.connect() 사용, excerpts 지원
  frame.py + frame/taxonomy.json (신규) 분류표
  graph.py             (신규) 노드·별칭·간선·리다이렉트·이벤트 로그·rebuild
  canon.py             (신규) 개념 정규화 → 노드 id
  models.py            (신규) pydantic 스키마(QuestPlan, DayLesson, CatalogBatch, BridgeBatch, AskAnswer …)
  prompts.py           (신규) 한국어 프롬프트 상수
  catalog.py           (수정) think 기반 묶음 분류, book 필터, 그래프 upsert, rebridge 후크
  connectors/          (신규) base, registry, wikipedia, wikidata, openalex, arxiv, pubmed, semanticscholar, ddgs_web, xai_search, webpage, youtube, vault
  collect.py           (신규) 점수·중복제거·할당량·수집·원문 저장·장부
  quest.py             (신규) 퀘스트 생성/상태 기계/과제 프로토콜/단계 함수
  scheduler.py         (신규) 재시도·자동 재개 스레드
  bridge.py            (신규) 다리 후보·확정·영향 퀘스트
  retrieve.py          (신규) 발췌(FTS) → M6에서 RRF 융합
  vec.py               (신규, M6) sqlite-vec 색인·유사 개념
  ask.py               (신규, M6) RAG 답변
  vault_export.py      (신규, M6) Obsidian zip
  render.py            (수정) 퀘스트 지도/일자/그래프 페이지, 서재 퀘스트 구역
  templates/quest_index.html.j2, quest_day.html.j2, brain_graph.html.j2 (신규), shelf.html.j2 (수정)
  static/brain.css     (수정)
api/main.py            (수정) 라우트
sync/learn_cli.py      (신규) brain-learn CLI
CLAUDE.md              (신규, 프로젝트 루트)
.claude/skills/learn/SKILL.md (신규)
tests/test_{think,frame,graph,canon,connectors,collect,quest,scheduler,bridge,retrieve,vec,ask,vault_export,learn_cli,render_quest,api_quests}.py (신규), test_catalog.py (수정)
pyproject.toml, Dockerfile (수정)
```

---

# M1 — 생각 부품과 분류 큐 전환

### Task 1: `brain/think.py` 제공자 사슬 + config 갱신

**Files:**
- Modify: `brain/config.py`
- Create: `brain/think.py`
- Test: `tests/test_think.py`
- Modify: `pyproject.toml` (dev에 `respx>=0.21` 추가)

**Interfaces:**
- Produces:
  - `config.Settings` 새 필드: `model_fast="claude-haiku-5-5"`, `model_smart="claude-sonnet-5-5"`, `gemini_api_key=""`, `gemini_model_fast="gemini-3.1-flash-lite"`, `gemini_model_smart="gemini-3.5-flash"`, `gemini_embed_model="gemini-embedding-001"`, `xai_api_key=""`, `xai_model_fast="grok-4-1-fast-non-reasoning"`, `xai_model_smart="grok-4.3"`, `think_providers="anthropic,gemini,xai"`, `think_daily_cap=200`, `think_retry_minutes=30`, `think_retry_hours=48`, `quest_max_think_calls=40`, `quest_max_sources=45`, `quest_max_doc_chars=60000`, `quest_max_pdf_pages=40`, `quest_max_minutes=30`, `quest_quota_per_dot=2`.
  - `class ThinkUnavailable(Exception)` (속성 `reasons: list[str]`).
  - `@dataclass ThinkResult(data: dict, provider: str, model: str, input_tokens: int, output_tokens: int, seconds: float)`.
  - `SMART_KINDS = {"plan", "teach", "bridge", "ask"}`.
  - `parse_json(raw: str) -> dict | None` (바깥 `{…}` 구제; ```json 펜스 제거).
  - `complete_text(system: str, user: str, smart: bool) -> tuple[str, str, str, int, int]` → `(text, provider, model, in_tok, out_tok)`; 제공자 순서대로 시도, 키 없는 제공자는 건너뜀, 예외는 모아 `ThinkUnavailable(reasons)`.
  - `think(kind: str, system: str, user: str, schema: type[BaseModel] | None = None, *, smart: bool | None = None, log_path: Path | None = None) -> ThinkResult`: `smart`가 None이면 `kind in SMART_KINDS`; JSON 파싱/스키마 실패 시 같은 제공자에 "JSON 객체만 출력" 덧붙여 1회 재시도 후 다음 제공자; 일일 상한 초과 시 즉시 `ThinkUnavailable(["daily cap"])`.
  - `daily_count() -> int` (`data_dir/think/usage-YYYY-MM-DD.jsonl` 줄 수), `record_usage(...)`, `providers_available() -> list[str]`.
  - 제공자 어댑터(내부): `_anthropic(system, user, model)`, `_gemini(system, user, model)`(REST `v1beta/models/{model}:generateContent`, httpx, `generationConfig.responseMimeType="application/json"`), `_xai(system, user, model)`(`POST https://api.x.ai/v1/chat/completions`). 각 어댑터는 `(text, in_tok, out_tok)` 반환.
- `llm.complete`는 유지하되 내부에서 `complete_text(system, user, smart)[0]`를 쓰도록 바꾼다(기존 호출자 호환).

- [ ] **Step 1: 실패하는 테스트 작성** `tests/test_think.py`
  - `test_parse_json_salvages_fenced_and_prefixed`: 입력 `'설명:\n```json\n{"a": 1}\n```'` → `{"a": 1}`; 입력 `'no json'` → `None`.
  - `test_chain_skips_providers_without_key_and_falls_through(data_dir, monkeypatch)`: `ANTHROPIC_API_KEY=""`, `GEMINI_API_KEY="g"`, `XAI_API_KEY=""`; `_gemini`를 monkeypatch로 `('{"ok": true}', 10, 5)` 반환 → `think("classify", "s", "u").provider == "gemini"`, `data == {"ok": True}`, `daily_count() == 1`.
  - `test_chain_raises_unavailable_with_all_reasons`: 세 어댑터 모두 예외 → `ThinkUnavailable` 발생, `len(e.reasons) >= 2`(키 없는 건 "no key").
  - `test_retry_once_on_bad_json_then_next_provider`: `_anthropic`가 첫 호출 `"oops"`, 둘째 `"still"`; `_gemini`가 `'{"x":1}'` → provider == "gemini", `_anthropic` 호출 횟수 2.
  - `test_schema_validation`: `schema=` pydantic 모델(필수 필드 `n: int`) 주고 모델이 `{"n": "a"}` 2회 → 다음 제공자로 넘어가 `{"n": 3}` → `data["n"] == 3`.
  - `test_daily_cap_blocks`: `THINK_DAILY_CAP=1`, usage 파일에 1줄 미리 기록 → `ThinkUnavailable`, reasons에 `"daily cap"`.
  - `test_smart_kind_picks_smart_model`: `_anthropic`를 가로채 model 인자를 기록 → `think("teach", …)`는 `claude-sonnet-5-5`, `think("classify", …)`는 `claude-haiku-5-5`.
- [ ] **Step 2: 실패 확인** `pytest tests/test_think.py -q` → ImportError.
- [ ] **Step 3: 구현** `brain/config.py` 필드 추가, `brain/think.py` 작성, `brain/llm.py.complete` → `complete_text` 위임. `pyproject.toml` dev에 `respx>=0.21`.
- [ ] **Step 4: 통과 확인** `pytest tests/test_think.py tests/test_llm.py -q`.
- [ ] **Step 5: 커밋** `feat(think): provider chain anthropic→gemini→xai with JSON schema + daily cap`

### Task 2: 분류 큐를 think 묶음으로 전환 (`catalog.py`)

**Files:**
- Modify: `brain/catalog.py`, `tests/test_catalog.py`, `api/main.py` (`/catalog/learn`에 `book: str | None = None`)
- Create: `brain/models.py` (이 과제에서는 `ConceptPair`, `CatalogCard`, `CatalogBatch`만), `brain/prompts.py` (이 과제에서는 `CATALOG_BATCH_SYSTEM`만)

**Interfaces:**
- Consumes: Task 1 `think`, `parse_json`.
- Produces:
  - `models.ConceptPair(ko: str, en: str = "")`, `models.CatalogCard(index: int, title: str, summary: str, domain: str, field_code: str = "", tags: list[str] = [], concepts: list[str] = [], concept_pairs: list[ConceptPair] = [], entities: list[str] = [])`, `models.CatalogBatch(cards: list[CatalogCard])`.
  - `prompts.CATALOG_BATCH_SYSTEM`: 기존 `CATALOG_SYSTEM` 규칙 + "입력은 `### 자료 {index}` 블록 여러 개, 출력은 `{"cards":[…]}`" + `field_code`는 Task 4의 `frame.field_prompt_list()`를 붙여 넣는 자리표시자 `{FIELDS}`(Task 4 전에는 빈 문자열로 포맷).
  - `catalog.learn_batch(entries: list[dict], complete=None) -> list[dict | None]`: `complete(system, user) -> str` (기본은 `think("classify", …)`의 텍스트 경로; 테스트는 가짜). 각 자료 본문 `BODY_LIMIT//len(entries)`로 자른다. 카드의 `index`로 매칭, 빠진 건 `None`.
  - `catalog.learn_pending(limit=10, llm_complete=None, book: str | None = None, batch_size: int = 5) -> dict` 반환 `{"learned", "failed", "remaining", "new_concepts": list[str]}` — `new_concepts`는 Task 5에서 그래프 upsert가 채움(지금은 `[]`).
  - learned entry JSON에 `field_code`, `concept_pairs` 필드 추가.
  - `catalog._parse_json`은 `think.parse_json` 별칭으로 유지.
- 후크 자리: `learn_pending` 끝에 `_after_learn(entries: list[dict]) -> list[str]` 호출(지금은 `[]` 반환; Task 5·15에서 채움).

- [ ] **Step 1: 테스트 수정·추가** `tests/test_catalog.py`
  - 기존 `_card()`/`_fake` 헬퍼를 묶음 형식으로 바꾼다: `_batch(*cards)` → `{"cards":[{"index":i, …}]}`; 기존 테스트 의도(멱등 등록, 학습 후 pending 감소, 파싱 실패 시 pending 유지, graph 공출현)는 그대로 통과해야 한다.
  - 추가 `test_learn_batch_matches_by_index_and_marks_missing`: 3건 넣고 가짜가 index 1,3만 돌려줌 → 결과 `[dict, None, dict]`, pending에 2번째만 남음.
  - 추가 `test_learn_pending_filters_by_book`: 두 책 등록 후 `learn_pending(book="cosmos")` → 다른 책은 pending 유지.
  - 추가 `test_learn_pending_uses_think_when_no_fake(monkeypatch)`: `think.complete_text`를 가짜로 → 호출됨.
- [ ] **Step 2: 실패 확인** `pytest tests/test_catalog.py -q`.
- [ ] **Step 3: 구현** `models.py`, `prompts.py`, `catalog.py` 수정, `/catalog/learn?limit=&book=`.
- [ ] **Step 4: 통과 확인** `pytest tests/test_catalog.py tests/test_api.py -q`.
- [ ] **Step 5: 커밋** `feat(catalog): batch classification via think(), book filter`

### Task 3: M1 배포 + 백로그 소진 시작 (지휘자 수동 과제)

- [ ] `railway variables --set GEMINI_API_KEY=… --set XAI_API_KEY=… --set THINK_PROVIDERS=anthropic,gemini,xai` (값은 로컬 `.env`에서), `railway up`, `/health` 확인.
- [ ] `POST /catalog/learn?limit=25` 3회 → `/catalog/stats`의 `learned` 증가 확인. 429가 섞이면 `failed`로 남고 다음 호출에서 재시도됨을 확인.
- [ ] 커밋 없음(운영 확인). 결과를 NEXT.md 진행 메모에 한 줄.

# M2 — 20년 프레임: 분류표·그래프·정규화

### Task 4: 분류표 `brain/frame.py` + `brain/frame/taxonomy.json`

**Files:**
- Create: `brain/frame/taxonomy.json`, `brain/frame.py`
- Modify: `pyproject.toml` package-data에 `"frame/*.json"`
- Test: `tests/test_frame.py`

**Interfaces:**
- Produces:
  - `taxonomy.json`: `{"version": 1, "status": "draft", "areas": [{"code": "B", "name_ko": "물리·우주", "name_en": "Physics & Space", "fields": [{"code": "B4", "name_ko": "양자", "name_en": "Quantum", "deprecated_to": null}, …]}, …]}` — 스펙 5.8의 17개 영역, 영역당 6~10개 분야(총 120~170). 영역 Z에는 `Z1 학습법`, `Z2 도구·소프트웨어`, `Z3 2nd BRAIN 자체`. 분야 이름은 Dewey/UDC·OpenAlex 상위 개념을 참고해 빌더가 정한다.
  - `frame.load() -> dict`(lru_cache), `frame.fields() -> dict[str, dict]` (code → field dict에 `area` 코드 포함), `frame.is_valid_code(code) -> bool`, `frame.resolve_code(code) -> str`(deprecated_to 체인 따름, 순환 시 원래 코드), `frame.area_of(code) -> str`, `frame.domain_to_area(domain: str) -> str` (`과학→B`, `역사→J`, `종교→K`, `철학→K`, `심리→H`, `경제→I`, `기술→F`, `예술→M`, `동물→O`, `건강→N`, `기타→Z`), `frame.validate() -> list[str]`(중복 코드·잘못된 deprecated_to·영역 코드 불일치), `frame.field_prompt_list() -> str`(한 줄에 `B4 양자 (Quantum)` 형식, deprecated 제외).
- `prompts.CATALOG_BATCH_SYSTEM`의 `{FIELDS}`를 `field_prompt_list()`로 채우는 `prompts.catalog_batch_system() -> str` 추가하고 Task 2의 `learn_batch`가 이를 쓴다.

- [ ] **Step 1: 테스트** `tests/test_frame.py`
  - `test_taxonomy_has_17_areas_and_unique_codes`: 영역 코드 집합 == `set("ABCDEFGHIJKLMNOPZ")`, 전체 분야 코드 유일, 각 분야 코드가 자기 영역 코드로 시작, 영역당 분야 수 6~10.
  - `test_validate_is_clean_on_shipped_file`: `validate() == []`.
  - `test_resolve_follows_deprecated_to(monkeypatch)`: 가짜 데이터로 `B9 → B4` → `resolve_code("B9") == "B4"`; 순환 `X1→X2→X1` → 원래 코드 반환.
  - `test_domain_to_area_mapping`: 위 11개 매핑 전부.
  - `test_field_prompt_list_excludes_deprecated`.
- [ ] **Step 2: 실패 확인** → **Step 3: 구현** → **Step 4: 통과** `pytest tests/test_frame.py tests/test_catalog.py -q`.
- [ ] **Step 5: 커밋** `feat(frame): 17-area taxonomy backbone with add-only codes`

### Task 5: 그래프 저장 `brain/db.py` + `brain/graph.py` + catalog 연결

**Files:**
- Create: `brain/db.py`, `brain/graph.py`
- Modify: `brain/index.py` (`_db()` → `db.connect()`), `brain/catalog.py` (`_after_learn` → `graph.ingest_card`), `api/main.py` (`GET /graph`, `GET /graph/full`, `GET /graph/stats`, `POST /graph/rebuild`)
- Test: `tests/test_graph.py`, `tests/test_catalog.py`(추가)

**Interfaces:**
- Produces:
  - `db.connect() -> sqlite3.Connection`: `data_dir/brain.db`, `PRAGMA journal_mode=WAL`, 스키마: 기존 `docs` FTS5·`vec_meta` + `nodes(id TEXT PRIMARY KEY, kind TEXT, label_ko TEXT, label_en TEXT, wikidata TEXT, field_code TEXT, summary TEXT, created_at TEXT, updated_at TEXT)`, `aliases(alias TEXT PRIMARY KEY, node_id TEXT)`, `node_tags(node_id TEXT, tag TEXT, PRIMARY KEY(node_id, tag))`, `edges(src TEXT, dst TEXT, rel TEXT, weight REAL, reason TEXT, evidence TEXT, created_at TEXT, PRIMARY KEY(src, dst, rel))`, `redirects(old_id TEXT PRIMARY KEY, new_id TEXT)`. 인덱스 `edges(dst)`, `nodes(field_code)`, `nodes(kind)`.
  - `graph.RELS = ("is_a","part_of","requires","related","bridge","contradicts","cites","about","in_book","taught_in","asked")`, `graph.KINDS = ("concept","source","lesson","quest","book","person","place","work","question")`.
  - `graph.append_event(ev: dict)` → `data_dir/graph/events.jsonl` (`{"t": iso, "op": "node|alias|edge|redirect|tag", …}`); 모든 쓰기 함수는 이벤트를 먼저 쓰고 DB에 반영(`_apply(ev, con)` 하나로 통일해 rebuild가 같은 경로를 쓴다).
  - `graph.upsert_node(id: str, kind: str, label_ko: str, label_en: str = "", wikidata: str = "", field_code: str = "", summary: str = "", tags: Iterable[str] = ()) -> dict` (빈 값은 기존 값을 덮지 않음; `label_ko`, `label_en`, `wd:<QID>`를 별칭으로 자동 등록).
  - `graph.add_alias(alias: str, node_id: str)`, `graph.add_edge(src, dst, rel, weight=1.0, reason="", evidence="")` (`rel=="related"`면 weight 누적, 그 외 덮어쓰기; `rel not in RELS` → ValueError), `graph.redirect(old_id, new_id)`, `graph.resolve(id) -> str`.
  - `graph.get_node(id) -> dict | None`, `graph.find_alias(alias) -> str | None`(소문자·공백 정규화 비교), `graph.search_labels(q: str, limit=20) -> list[dict]`, `graph.neighbors(id: str, depth: int = 1, rels: Iterable[str] | None = None) -> dict` → `{"center": id, "nodes": [...], "edges": [...]}`, `graph.by_field(code, limit=200)`, `graph.full(limit=2000) -> dict` (`nodes`, `edges`, 간선 많은 노드 우선), `graph.stats() -> dict` (`nodes`, `edges`, `concepts`, `bridges`, `by_area`), `graph.rebuild() -> int` (테이블 비우고 events 재생), `graph.node_ids_in_book(slug) -> list[str]`.
  - `graph.ingest_card(entry: dict) -> list[str]`: learned entry 1건 → 자료 노드 `src:<entry id 앞 16자>`(kind source, label=title, summary) + `in_book` → `book:<slug>`(kind book, 없으면 생성) + 개념마다 `canon.canon(ko, en, field_code)`(Task 6; 이 과제에서는 임시로 `canon.concept_id` 없이 `slugify(en or ko)` 사용하는 `_concept_id_fallback`) → `about` 간선 + 개념 쌍마다 `related` 누적. 반환: 새로 생성된 개념 id 목록.
  - `catalog._after_learn(entries)` → `graph.ingest_card` 호출 결과를 모아 `new_concepts`로 반환.
  - API: `GET /graph?center=&depth=1&field=&kind=`(토큰; center 있으면 neighbors, field 있으면 by_field), `GET /graph/full?limit=`(토큰), `GET /graph/stats`(공개), `POST /graph/rebuild`(토큰).

- [ ] **Step 1: 테스트** `tests/test_graph.py`
  - `test_upsert_node_writes_event_and_row_and_aliases(data_dir)`: 이벤트 파일 1줄, `get_node` 반환, `find_alias("양자 얽힘") == id`, `find_alias("wd:Q215675")`.
  - `test_upsert_does_not_blank_existing_fields`.
  - `test_related_weight_accumulates_other_rels_overwrite`.
  - `test_invalid_rel_raises`.
  - `test_redirect_resolves_in_get_and_neighbors`.
  - `test_neighbors_depth2`.
  - `test_rebuild_from_events_is_identical(data_dir)`: 노드 3·간선 3·리다이렉트 1 → `rebuild()` → `stats()`·`neighbors` 동일.
  - `test_ingest_card_links_source_book_concepts`: learned entry 가짜 → about 2개, related 1개, in_book 1개, 반환 새 개념 2개.
  - `test_catalog_learn_creates_concepts_in_graph(data_dir)`: `learn_pending` 가짜 후 `graph.stats()["concepts"] == 2`, 반환 `new_concepts` 길이 2.
- [ ] **Step 2: 실패 확인** → **Step 3: 구현** (`index.py`는 `db.connect()`만 쓰도록 바꾸고 기존 `test_index.py` 통과 유지) → **Step 4: 통과** `pytest tests/test_graph.py tests/test_index.py tests/test_catalog.py tests/test_api.py -q`.
- [ ] **Step 5: 커밋** `feat(graph): append-only event log + sqlite graph, catalog→graph upsert`

### Task 6: 개념 정규화 `brain/canon.py` (+ `connectors/wikidata.py`)

**Files:**
- Create: `brain/canon.py`, `brain/connectors/__init__.py`, `brain/connectors/base.py`(이 과제에서는 `http_get(url, params, timeout=20) -> httpx.Response`와 `UA` 상수만), `brain/connectors/wikidata.py`
- Modify: `brain/graph.py` (`ingest_card`가 `canon.canon` 사용)
- Test: `tests/test_canon.py`

**Interfaces:**
- Produces:
  - `connectors.base.UA = "2ndBRAIN/0.1 (+https://github.com/CRtheHILLS/2ndBRAIN)"`, `connectors.base.http_get(url: str, params: dict | None = None, timeout: float = 20, headers: dict | None = None) -> httpx.Response`(UA 자동, `follow_redirects=True`).
  - `connectors.wikidata.search_entity(label: str, lang: str) -> dict | None` → `{"id": "Q215675", "label": str, "description": str, "aliases": list[str]}` (`wbsearchentities`, limit 5, 라벨/별칭이 소문자·공백 정규화로 정확히 일치하는 첫 항목만; 없으면 None). `connectors.wikidata.parents(qid: str) -> list[str]`(P279·P31, `wbgetclaims`).
  - `canon.concept_id(label_en: str, label_ko: str, suffix: str = "") -> str`: `slugify(label_en) or slugify(label_ko)`, suffix 있으면 `f"{base}-{suffix.lower()}"`.
  - `canon.canon(label_ko: str, label_en: str = "", field_code: str = "", *, lookup=None) -> str`: 순서 ① `graph.find_alias(label_ko/label_en)` ② `graph.search_labels` 정확 일치 ③ `lookup or wikidata.search_entity`(ko → en; 네트워크 예외는 None 취급) → QID가 이미 다른 노드에 있으면 그 노드 ④ 새 노드: id = `concept_id(en, ko)`; 같은 id가 있는데 QID가 다르거나 `frame.area_of(field_code)`가 다르면 `concept_id(en, ko, suffix=field_code)`; `graph.upsert_node(id, "concept", label_ko, label_en, wikidata=qid, field_code=…)`. 반환 노드 id.
  - 별칭 정규화 규칙 `canon.norm(s) -> str`: NFC, 소문자, 연속 공백 1개, 양끝 공백 제거, 괄호 안 원어 병기 `"양자 얽힘 (quantum entanglement)"` → 라벨 `양자 얽힘` + 영어 별칭 추출 `split_bilingual(label) -> tuple[str, str]`.

- [ ] **Step 1: 테스트** `tests/test_canon.py` (네트워크 없음: `lookup=` 가짜)
  - `test_split_bilingual`: `"양자 얽힘 (Quantum Entanglement)"` → `("양자 얽힘", "Quantum Entanglement")`; `"블랙홀"` → `("블랙홀", "")`.
  - `test_concept_id_prefers_english`: `("Quantum Entanglement", "양자 얽힘")` → `"quantum-entanglement"`; `("", "양자 얽힘")` → `"양자-얽힘"`.
  - `test_canon_reuses_existing_by_alias(data_dir)`: 먼저 canon 후 `"얽힘"`을 별칭으로 추가 → `canon("얽힘")`이 같은 id.
  - `test_canon_attaches_qid_from_lookup(data_dir)`: lookup이 `{"id":"Q215675",…}` → 노드 `wikidata == "Q215675"`, `find_alias("wd:Q215675")`.
  - `test_canon_disambiguates_same_slug_different_area(data_dir)`: `canon("스핀", "Spin", "B4")` → `"spin"`, 그 뒤 `canon("스핀", "Spin", "N3", lookup=다른 QID)` → `"spin-n3"`.
  - `test_canon_survives_lookup_exception`.
  - `test_wikidata_search_entity_parses(respx)`: 가짜 응답으로 정확 일치만 채택.
- [ ] **Step 2: 실패 확인** → **Step 3: 구현** (`graph.ingest_card`의 임시 id 함수를 `canon.canon`으로 교체; catalog 테스트는 `lookup` 없이 네트워크를 타지 않도록 `canon.canon`의 기본 lookup을 `settings.canon_wikidata: bool = True`로 끄고 테스트 conftest에서 `CANON_WIKIDATA=0` 설정) → **Step 4: 통과** `pytest tests/test_canon.py tests/test_graph.py tests/test_catalog.py -q`.
- [ ] **Step 5: 커밋** `feat(canon): canonical concept ids with wikidata anchors and disambiguation`

### Task 7: M2 배포 + 백로그 분류 계속 (지휘자 수동 과제)

- [ ] `railway up` → `POST /graph/rebuild` → `/catalog/learn?limit=25` 반복(양자역학 책 우선: `book=양자역학`) → `/graph/stats`의 `concepts > 0`, `GET /graph?center=<양자 개념 id>` 확인.

# M3 — 연결기와 수집기

### Task 8: 연결기 기반·레지스트리·백과/학술 연결기

**Files:**
- Modify: `brain/connectors/base.py`
- Create: `brain/connectors/registry.py`, `wikipedia.py`, `openalex.py`, `arxiv.py`, `pubmed.py`, `semanticscholar.py`
- Test: `tests/test_connectors.py` (respx)

**Interfaces:**
- Produces:
  - `base.Candidate` (pydantic): `url: str, title: str, kind: Literal["official","encyclopedia","paper","textbook","video","web","forum","book"], snippet: str = "", year: int | None = None, authority: float = 0.5, connector: str, lang: str = "", extra: dict = {}`.
  - `base.Doc`: `url, title, text, lang, kind, connector, meta: dict`.
  - `base.normalize_url(url: str) -> str`: 소문자 scheme/host, `http→https`, `m.`·`mobile.` 호스트 접두 제거, `www.` 제거, fragment 제거, `utm_*`·`fbclid` 쿼리 제거, 꼬리 `/` 제거.
  - `base.Connector` Protocol: `name: str`, `search(query: str, lang: str, limit: int) -> list[Candidate]`, `fetch(c: Candidate) -> Doc | None`.
  - `registry.all_connectors() -> dict[str, Connector]`(이 과제: wikipedia, openalex, arxiv, pubmed, semanticscholar; Task 9에서 추가), `registry.search_all(query: str, lang: str, limit_per: int = 5, names: Iterable[str] | None = None, timeout: float = 25) -> tuple[list[Candidate], dict[str, str]]` → (후보들, `{connector: "ok:3" | "error:<msg>"}`), ThreadPoolExecutor(8).
  - `wikipedia`: `search` = `w/api.php list=search`(ko/en 선택), kind `encyclopedia`, authority 0.9; `fetch` = `prop=extracts&explaintext` 전문 + `links` 상위 30개를 `meta["links"]`. `fetch_title(title, lang)` 보조.
  - `openalex`: `search` = `/works?search=&per-page=`; `Candidate.extra = {"cited_by": int, "oa_pdf": str|None, "doi": str}`; `fetch` = 초록(`abstract_inverted_index` 복원) + oa_pdf가 있으면 Task 9의 `webpage.fetch_pdf` 사용(없으면 초록만). authority = `min(1.0, 0.7 + log10(cited+1)/10)`.
  - `arxiv`: `https://export.arxiv.org/api/query` Atom 파싱(`xml.etree`), kind paper, fetch = 요약(+PDF는 webpage 경유, 선택).
  - `pubmed`: `esearch`(json) → `efetch`(xml) 초록, kind paper.
  - `semanticscholar`: `graph/v1/paper/search`; 429/5xx면 빈 결과 + status "error:429".

- [ ] **Step 1: 테스트** `tests/test_connectors.py`
  - `test_normalize_url_merges_variants`: `http://m.wikipedia.org/wiki/X#a?utm_source=t` 와 `https://wikipedia.org/wiki/X/` 가 같은 값.
  - 연결기마다 `respx` 가짜 응답으로 `search` 1건 파싱(제목·kind·connector) + `fetch` 본문 길이>0.
  - `test_openalex_abstract_from_inverted_index`.
  - `test_search_all_collects_partial_results_when_one_connector_fails`: 한 연결기 예외 → 나머지 결과 반환, status에 `error:` 포함.
- [ ] **Step 2: 실패 확인** → **Step 3: 구현** → **Step 4: 통과** `pytest tests/test_connectors.py -q`.
- [ ] **Step 5: 커밋** `feat(connectors): wikipedia/openalex/arxiv/pubmed/s2 with registry`

### Task 9: 웹·영상·검색·볼트 연결기

**Files:**
- Create: `brain/connectors/webpage.py`, `youtube.py`, `ddgs_web.py`, `xai_search.py`, `vault.py`
- Modify: `brain/connectors/registry.py`, `pyproject.toml`(deps `ddgs>=9`, `trafilatura>=2`, `youtube-transcript-api>=1`), `Dockerfile`(변경 없음 확인)
- Test: `tests/test_connectors.py`(추가)

**Interfaces:**
- Produces:
  - `webpage.download(url: str, max_bytes: int = 15_000_000) -> tuple[bytes, str]`(content, content-type), `webpage.extract_html(html: bytes | str, url: str) -> tuple[str, str]`(trafilatura → (title, text)), `webpage.extract_pdf(data: bytes, max_pages: int) -> str`(pymupdf), `webpage.fetch_url(url: str, max_pages: int | None = None) -> Doc | None`(content-type/확장자로 분기; `settings.quest_max_pdf_pages`), `webpage.search` = 빈 목록(검색 아님).
  - `youtube.video_id(url) -> str | None`, `youtube.fetch(c) -> Doc | None`(`YouTubeTranscriptApi().fetch(id, languages=["ko","en"])`, 실패 None), kind video.
  - `ddgs_web.search(query, lang, limit)`: `DDGS().text(query, max_results=limit, region="kr-kr" if lang=="ko" else "wt-wt")`; 예외/빈 결과 → `[]`; kind는 호스트로 추정(`youtube.com→video`, `.gov/.go.kr/.edu/.ac.kr→official`, `blog./tistory/brunch/reddit→forum`, 그 외 `web`).
  - `xai_search.search(query, lang, limit)`: 키 없으면 `[]`; `POST /v1/responses` with `tools=[{"type":"web_search"}]`, 입력 "다음 주제의 좋은 출처 URL {limit}개를 JSON 배열 [{url,title,kind}]로만" → 파싱; kind 매핑 동일.
  - `vault.search(query, lang, limit)`: `index.search(query, k=limit)` 결과를 Candidate(`url=f"vault://{slug}/{path}"`, kind `textbook`, connector `vault`, authority 0.95)로; `vault.fetch` = 파일 본문 읽기.
  - `registry.all_connectors()`에 `webpage, youtube, ddgs, xai, vault` 추가; `registry.fetch(c: Candidate) -> Doc | None`: youtube URL → youtube, `vault://` → vault, 그 외 `c.connector`의 fetch가 None이면 `webpage.fetch_url` 폴백.

- [ ] **Step 1: 테스트**
  - `test_extract_html_uses_trafilatura_on_local_string`(네트워크 없음), `test_extract_pdf_caps_pages`(pymupdf로 3쪽 PDF 생성 후 max_pages=2 → `<!-- page 3 -->` 없음).
  - `test_ddgs_kind_guess_and_empty_on_exception(monkeypatch)`.
  - `test_xai_search_returns_empty_without_key`, `test_xai_search_parses_json(respx)`.
  - `test_vault_search_wraps_index_hits(data_dir)`.
  - `test_registry_fetch_routes_youtube_vault_and_fallback(monkeypatch)`.
- [ ] **Step 2–4:** 실패 확인 → 구현 → `pytest tests/test_connectors.py -q`.
- [ ] **Step 5: 커밋** `feat(connectors): webpage/pdf, youtube transcript, ddgs, xai search, vault`

### Task 10: 수집기 `brain/collect.py` + 퀘스트 모델·생성

**Files:**
- Create: `brain/collect.py`
- Modify: `brain/models.py`(퀘스트 스키마 추가), `brain/quest.py`(신규: 생성·저장 부분만), `brain/prompts.py`(`PLAN_SYSTEM`)
- Test: `tests/test_collect.py`, `tests/test_quest.py`(생성 부분)

**Interfaces:**
- Produces (models):
  - `Dot(concept_ko: str, concept_en: str = "", why_one_line: str = "", queries_ko: list[str] = [], queries_en: list[str] = [], prefer_kinds: list[str] = [], evidence_grade_hint: str = "확립됨")`
  - `DayPlan(n: int, big_idea: str, dots: list[Dot])`
  - `Honesty(learnable_by_reading: list[str] = [], needs_practice: list[str] = [], hype_warning: list[str] = [])`
  - `SpecialSource(name: str, url: str = "", why: str = "")`, `BridgeHint(target: str, why: str = "")`
  - `QuestPlan(kind: Literal["skill","topic","question"], title_ko: str, title_en: str = "", one_line_goal: str, honesty: Honesty = Honesty(), prerequisites: list[str] = [], days: list[DayPlan], special_sources: list[SpecialSource] = [], bridge_hints: list[BridgeHint] = [])`
  - `SourceRecord(url: str, title: str, kind: str, connector: str, score: float, day: int, dot: str, lang: str, why_picked: str, fetched: bool, reason: str = "", raw_file: str = "", chars: int = 0)`
  - `SourceLedger(sources: list[SourceRecord] = [], connector_status: dict[str, dict[str, int]] = {}, special_tried: list[dict] = [], vault_hits: list[dict] = [], new_connectors_tried: list[str] = [])`
- Produces (collect):
  - `collect.score(c: Candidate, lang_wanted: str, prefer_kinds: list[str]) -> float`: `KIND_W = {"official":1.0,"textbook":0.9,"encyclopedia":0.9,"paper":0.9,"book":0.85,"video":0.6,"web":0.5,"forum":0.4}` × `c.authority` × (lang 일치 1.0 / 불일치 0.8) × (kind in prefer_kinds ? 1.1 : 1.0).
  - `collect.dedup(cands: list[Candidate]) -> list[Candidate]`(normalize_url + 제목 유사도 `difflib.SequenceMatcher ≥ 0.9`, 점수 높은 것 유지).
  - `collect.pick_for_dot(cands: list[Candidate], quota: int) -> list[Candidate]`: 점수순, 할당 규칙 — 가능하면 encyclopedia 1 + (paper|official) 1, 한국어 ≥1(있을 때), video ≤1, 총 ≤ quota.
  - `collect.run_dot(slug: str, day: int, dot: Dot, quota: int, ledger: SourceLedger, used_urls: set[str]) -> int`: 쿼리(ko+en, 각 최대 2개)로 `registry.search_all`(names 기본 전체) → dedup·score·pick → `registry.fetch` → 본문 `settings.quest_max_doc_chars`로 자름 → `store.write_md(store.raw_dir(slug)/f"src-d{day:02d}-{sha8}.md", meta, text)` (meta: `book, source=url, sha256, kind, connector, score, day, dot, lang, title, fetched_at`) → `catalog.register(slug, filename, path, sha)` → 장부 기록. 반환 저장 건수. 볼트 히트(`connector=="vault"`)는 파일을 쓰지 않고 `ledger.vault_hits`에만 기록.
  - `collect.run_special(slug: str, specials: list[SpecialSource], ledger)`: `webpage.fetch_url` 시도, 성공 시 day 0으로 저장, `special_tried`에 결과.
  - `collect.collect_quest(slug: str, plan: QuestPlan) -> SourceLedger`: 예산(`quest_max_sources`)까지, 점당 `quest_quota_per_dot`; 끝나면 `index.rebuild()`; 장부는 `quest.save_ledger`.
- Produces (quest 생성 부분):
  - `quest.quest_dir(slug) -> Path`(`data_dir/quests/<slug>`), `quest.slug_for(sentence: str) -> str`(`quest-YYYYMMDD-` + `slugify(sentence)[:40]`), `quest.normalize_sentence(s) -> str`(공백·문장부호·"나 "·"싶어"류 어미 제거, 소문자), `quest.find_existing(sentence) -> str | None`, `quest.create(sentence: str, days: int | None = None, level: str = "초등", started_by: str = "cli") -> dict`(문장에서 "N일"/"하루"/"오늘 안에"→days, "전문가"/"일반"→level 추출; `quest.json` 초기 `{"slug","sentence","days_requested","level","status":"queued","stage_done":[],"plan":None,"created_at","updated_at","started_by","error":None,"summary":{},"budget":{"think_calls":0,"sources":0,"seconds":0.0}}`), `quest.load(slug)`, `quest.save(slug, q)`, `quest.list_quests() -> list[dict]`, `quest.log(slug, **fields)`(`log.jsonl`), `quest.save_ledger(slug, ledger)`, `quest.load_ledger(slug)`.
  - `prompts.PLAN_SYSTEM`: 스펙 5.4의 규칙을 한국어로 고정. `{DAYS}`, `{FIELDS}` 자리표시자. `prompts.plan_system(days: int) -> str`.

- [ ] **Step 1: 테스트**
  - `tests/test_collect.py`: `test_score_weights`(official > encyclopedia > video), `test_dedup_by_url_and_title`, `test_pick_for_dot_quota_rules`(백과 1 + 논문 1 + 영상 ≤1, quota 2면 백과+논문), `test_run_dot_writes_raw_and_registers(data_dir, monkeypatch)`(registry.search_all/fetch 가짜 → raw 파일 frontmatter 확인, catalog pending 1, 장부 1), `test_run_dot_respects_used_urls`, `test_collect_quest_stops_at_max_sources(monkeypatch settings)`.
  - `tests/test_quest.py`: `test_create_extracts_days_and_level`("3일 만에 전문가 수준으로 헬리콥터" → days 3, level 전문), `test_create_defaults`(7, 초등), `test_slug_safe_for_quotes_emoji_long`(200자+이모지 → 슬러그 ≤ 60자, 정규식 `^[0-9a-z가-힣-]+$`), `test_same_sentence_returns_existing`("나 헬리콥터 운전 배우고 싶어" vs "헬리콥터 운전 배우고 싶어!").
- [ ] **Step 2–4:** 실패 확인 → 구현 → `pytest tests/test_collect.py tests/test_quest.py -q`.
- [ ] **Step 5: 커밋** `feat(collect): scored multi-connector collection into quest book; quest create/state files`

# M4 — 퀘스트 러너, 수업, CLI, 스킬

### Task 11: 러너 상태 기계 + 과제 프로토콜 + plan/classify 단계

**Files:**
- Modify: `brain/quest.py`
- Test: `tests/test_quest.py`(추가)

**Interfaces:**
- Produces:
  - `quest.STAGES = ("plan","collect","classify","teach","bridge","archive")`, 상태 문자열 `queued, running, waiting_thinker, failed, done` (+ `summary["stage"]`에 현재 단계).
  - `class Parked(Exception)` (`task_id`).
  - `quest.task_path(slug, task_id)`, `quest.open_tasks(slug) -> list[dict]`(status open; `{"task_id","kind","schema","system","user","context","created_at","error"}`), `quest.task_result(slug, task_id) -> dict | None`.
  - `quest.think_or_cached(slug: str, task_id: str, kind: str, system: str, user: str, schema: type[BaseModel], context: dict | None = None) -> dict`: 결과 캐시가 있으면 반환; 아니면 예산(`quest_max_think_calls`) 확인 → `think(kind, …, schema, log_path=quest_dir/log.jsonl)` → `tasks/<task_id>.json`에 `status done, result` 저장, `budget.think_calls += 1`; `ThinkUnavailable` → 과제 파일 `status open`(system/user/schema 이름 포함) → `raise Parked(task_id)`.
  - `quest.submit_task(slug: str, task_id: str, output: dict) -> dict`: 과제의 `schema` 이름으로 `models` 클래스를 찾아 검증(`models.SCHEMAS: dict[str, type[BaseModel]]`) → 실패 시 과제 `error`에 사유 기록·`open` 유지·`ValueError`; 성공 시 `done`+result 저장 → 반환 `{"accepted": True, "task_id"}` (재개는 API 계층이 백그라운드로 `run` 호출).
  - `quest.run(slug: str) -> dict`: `status=running`; `for stage in STAGES: if stage in stage_done: continue; t0; STAGE_FUNCS[stage](slug) ; stage_done.append; budget.seconds += ; save`; `Parked` → `status=waiting_thinker`, `summary["waiting_task"]`; 다른 예외 → `status=failed`, `error=str(e)`, `log`; 전부 끝나면 `status=done`, `summary` 채움(`pages`, `n_sources`, `n_concepts`, `bridges`, `cost_estimate`). 예산 `quest_max_minutes` 초과 시 다음 단계로 넘어가지 않고 `summary["budget_exceeded"]=True`로 `done` 처리(단, teach가 안 끝났으면 `failed`).
  - `stage_plan(slug)`: user = 문장 + 볼륨 관련 제목 20개(`index.search(sentence, 20)`) + 관련 개념 20개(`graph.search_labels`) → `think_or_cached(slug, "plan", "plan", prompts.plan_system(days), user, QuestPlan)` → `q["plan"]` 저장, `levels.set_level(f"quest:{slug}", level)`, `store.upsert_book(slug, plan.title_ko)`, 그래프 `quest:<slug>` 노드(kind quest).
  - `stage_collect(slug)`: `collect.collect_quest`.
  - `stage_classify(slug)`: `catalog.learn_pending(limit=200, book=slug, batch_size=5)`를 pending이 0이 되거나 `failed`가 연속 2회 ≥ 전체일 때까지 반복(최대 3회). 분류 묶음의 생각 호출은 `think`를 직접 쓰므로 `ThinkUnavailable`이 나오면 `Parked`로 바꾼다: 묶음 과제 id `classify-<batch index>`로 `think_or_cached`를 쓰도록 `catalog.learn_pending(..., complete=…)`에 `complete` 콜백을 넘긴다(콜백 안에서 `think_or_cached` 호출). 끝에 `summary["n_concepts"]`.
  - `stage_teach`, `stage_bridge`, `stage_archive`는 이 과제에서 자리만(각각 Task 12·15·13에서 구현; 지금은 `pass`).

- [ ] **Step 1: 테스트** `tests/test_quest.py` (가짜 think: `monkeypatch.setattr(think, "complete_text", fake)` 또는 `quest.think_or_cached`를 가짜 결과 사전으로)
  - `test_run_plan_then_collect_then_classify_with_fakes(data_dir, monkeypatch)`: 가짜 plan(2일×2점), 가짜 registry → `stage_done == ["plan","collect","classify","teach","bridge","archive"]`, status done, `quest.json["plan"]["days"]` 길이 2, raw 파일 ≥1, `graph.stats()["concepts"] ≥ 1`.
  - `test_think_unavailable_parks_and_submit_resumes(data_dir, monkeypatch)`: think가 `ThinkUnavailable` → status `waiting_thinker`, `open_tasks` 1건(kind plan, schema "QuestPlan"); `submit_task`에 올바른 plan → `run` 재호출 → collect 이후 진행.
  - `test_submit_invalid_output_keeps_task_open_with_error`: 잘못된 JSON(`days` 누락) → `ValueError`, 과제 `error` 비어있지 않음, status 그대로.
  - `test_run_is_resumable_and_skips_done_stages(data_dir, monkeypatch)`: plan·collect 완료 상태로 저장 후 `run` → collect 가짜가 호출되지 않음, raw 파일 수 변화 없음.
  - `test_budget_think_calls_exceeded_parks`: `QUEST_MAX_THINK_CALLS=0` → 첫 think에서 Parked.
- [ ] **Step 2–4:** 실패 확인 → 구현 → `pytest tests/test_quest.py -q`.
- [ ] **Step 5: 커밋** `feat(quest): resumable stage runner with thinker-agnostic task protocol`

### Task 12: teach 단계 + 수업 템플릿 + 렌더

**Files:**
- Modify: `brain/quest.py`(`stage_teach`), `brain/models.py`(`DotCard, QuizItem, DayLesson`), `brain/prompts.py`(`TEACH_SYSTEM`, `teach_system(level)`), `brain/render.py`, `brain/static/brain.css`, `brain/templates/shelf.html.j2`
- Create: `brain/retrieve.py`(`excerpts`만), `brain/templates/quest_index.html.j2`, `brain/templates/quest_day.html.j2`
- Test: `tests/test_retrieve.py`, `tests/test_render_quest.py`, `tests/test_quest.py`(추가)

**Interfaces:**
- Produces:
  - `DotCard(concept_id: str = "", concept_ko: str, one_line: str, picture_svg: str = "", emoji: str = "", analogy: str = "", real_example: str = "", why_it_matters: str = "", evidence_grade: Literal["확립됨","연구중","추측","상술"] = "확립됨", sources: list[str] = [])`, `QuizItem(q: str, a: str, why: str = "")`, `DayLesson(n: int, big_idea_one_line: str, story_opening: str, dots: list[DotCard], quiz: list[QuizItem] = [], say_it_yourself: str = "", link_yesterday: str = "", clair_one_liner: str = "")`. `evidence_grade` 검증기: 공백 제거·`연구 중→연구중` 보정, 그래도 아니면 `"연구중"`.
  - `retrieve.excerpts(query: str, slug: str | None = None, k: int = 3, chars: int = 400) -> list[dict]` → `[{"text","slug","path","title"}]` (FTS `index.search`, slug 필터, 스니펫 주변 `chars`자).
  - `prompts.teach_system(level: str) -> str`: 스펙 5.7의 초등 규칙(수식·기호 금지, 용어 옆 일상 그림, 한 문장 한 생각, 섹션마다 한 줄 요약, 음악 비유 환영, Clair 말투)과 `DayLesson` JSON 스키마 설명; `picture_svg`는 200×120 viewBox 단순 도형만, 외부 리소스 금지.
  - `quest.stage_teach(slug)`: 날짜마다 user = 그날 DayPlan + 점별 `excerpts(concept, slug)` 3개 + 어제 DayLesson 요약(점 one_line들) + `plan.bridge_hints` + 장부에서 그 점의 URL → `think_or_cached(slug, f"teach-day-{n}", "teach", teach_system(level), user, DayLesson, context={"day": n})` → `days/day-N.json` 저장(`concept_id`는 `canon.canon(concept_ko, concept_en)`로 채워 그래프 `lesson:<slug>:day-N` 노드(kind lesson) + `taught_in` 간선) → `render.render_quest_day(slug, n)`; 끝에 `render.render_quest(slug)`.
  - `render.render_quest_day(slug: str, n: int) -> Path`(`site/quests/<slug>/day-N.html`; SVG는 `<script`·`on*=`·`href`가 들어 있으면 버리고 emoji로 대체), `render.render_quest(slug: str) -> Path`(`site/quests/<slug>/index.html`: 목표·정직 상자·일자 경로 SVG·진행·출처 장부·다리 목록(`bridge.bridges_for` 가 있으면, 없으면 빈 섹션)), `render.render_shelf()`에 퀘스트 구역(`quest.list_quests()`; 제목·상태·시작일·링크).
  - 템플릿 구조(스펙 5.7): day 페이지 = 헤더(퀘스트 제목·Day N/총·어제/내일 링크) → 큰 생각 한 줄 → 이야기 → 점 카드 그리드(그림·한 줄·비유·진짜 예·왜 중요·증거 배지·원문 링크) → 퀴즈(`<details>`) → 내 말로 → 어제와 잇기 → 다른 때 배운 것과 잇기(`bridges` 변수, 비어 있으면 "아직 없어요") → 클레어의 한마디. CSS: 모바일 우선, 기존 토큰(`--bg --ink --accent --card --muted`) 유지 + 배지 색 4종, 카드 그리드 `minmax(260px,1fr)`.
  - `quest.json["summary"]["pages"] = {"index": "/site/quests/<slug>/index.html", "days": [...]}`.

- [ ] **Step 1: 테스트**
  - `tests/test_retrieve.py::test_excerpts_filters_slug_and_trims`.
  - `tests/test_render_quest.py`: `test_render_day_contains_sections_and_single_level`(가짜 day json → HTML에 "오늘의 퀴즈", `<details>`, 증거 배지 클래스, 레벨 탭 없음), `test_svg_sanitizer_drops_script`, `test_render_quest_index_lists_days_honesty_sources`, `test_shelf_shows_quests`.
  - `tests/test_quest.py::test_stage_teach_writes_day_json_and_pages_and_lesson_nodes`(가짜 think가 유효한 DayLesson 반환 → `days/day-1.json` 존재, `site/quests/<slug>/day-1.html` 존재, 그래프 `lesson:` 노드와 `taught_in` 간선).
  - `tests/test_quest.py::test_day_lesson_grade_coercion`(`"연구 중"` → `"연구중"`).
- [ ] **Step 2–4:** 실패 확인 → 구현 → `pytest tests/test_retrieve.py tests/test_render_quest.py tests/test_quest.py tests/test_render.py -q`.
- [ ] **Step 5: 커밋** `feat(teach): one-level 초등 day lessons with dot cards, quiz, bridges section`

### Task 13: archive 단계 + 스케줄러 + API 라우트

**Files:**
- Modify: `brain/quest.py`(`stage_archive`), `api/main.py`
- Create: `brain/scheduler.py`
- Test: `tests/test_scheduler.py`, `tests/test_api_quests.py`

**Interfaces:**
- Produces:
  - `quest.stage_archive(slug)`: `index.rebuild()`, `render.render_quest(slug)`, `render.render_shelf()`, 요약 채움(`n_sources`=장부 fetched 수, `n_concepts`=`graph.node_ids_in_book(slug)` 중 concept 수, `cost_estimate`=log.jsonl 토큰 합×단가표 `{"anthropic": (3, 15), "gemini": (0, 0), "xai": (0.2, 0.5)}` $/M).
  - `quest.start_background(slug) -> bool`(모듈 전역 `_running: set`, 스레드 daemon; 이미 실행 중이면 False), `quest.resume(slug) -> dict`(status가 `waiting_thinker|failed|queued|running(스레드 없음)`이면 `start_background`).
  - `scheduler.tick(now: datetime | None = None) -> dict`: ① `status == running`인데 `_running`에 없으면 resume(서버 재시작 복구) ② `waiting_thinker`이고 `updated_at`이 `think_retry_minutes` 이전이며 `created_at`이 `think_retry_hours` 안이면 resume → `{"resumed": [...], "skipped": [...]}`; `scheduler.start()`(스레드, 60초마다 조건 확인), `scheduler.stop()`.
  - API(모두 토큰, 조회 포함): `POST /quests` body `{"sentence": str, "days": int | None, "level": str = "초등"}` → `{"slug","status","existing": bool,"url": "/site/quests/<slug>/index.html"}` + `start_background`; `GET /quests`; `GET /quests/{slug}`(quest.json + `open_tasks` 수); `GET /quests/{slug}/tasks`; `POST /quests/{slug}/tasks/{task_id}` body `{"output": {...}}` → `submit_task` 후 `start_background` → `{"accepted", "status"}`(ValueError→400); `POST /quests/{slug}/resume`; `POST /quests/{slug}/rerender?level=` → `levels.set_level`, `tasks/teach-*.json`·`days/*.json` 삭제, `stage_done`에서 teach·bridge·archive 제거, `start_background`. lifespan에서 `scheduler.start()`.

- [ ] **Step 1: 테스트**
  - `tests/test_scheduler.py`: `test_tick_resumes_stale_waiting_quest(data_dir, monkeypatch)`(resume 가짜 호출 확인), `test_tick_skips_recent_and_expired`, `test_tick_recovers_running_without_thread`.
  - `tests/test_api_quests.py`(TestClient, `quest.start_background`를 동기 가짜로): `test_post_quest_creates_and_returns_url`, `test_post_same_sentence_returns_existing`, `test_tasks_roundtrip`(waiting 상태 만들고 GET tasks → POST 제출 → 200, 잘못된 제출 → 400), `test_requires_token_on_all_quest_routes`, `test_rerender_resets_teach_stage`.
- [ ] **Step 2–4:** 실패 확인 → 구현 → `pytest tests/test_scheduler.py tests/test_api_quests.py tests/test_api.py -q`.
- [ ] **Step 5: 커밋** `feat(api): quest routes, task protocol endpoints, retry scheduler`

### Task 14: CLI `brain-learn` + 프로젝트 CLAUDE.md + 스킬

**Files:**
- Create: `sync/learn_cli.py`, `CLAUDE.md`(프로젝트 루트), `.claude/skills/learn/SKILL.md`
- Modify: `pyproject.toml`(`brain-learn = "sync.learn_cli:main"`), `README.md`(퀘스트 사용법 절, 한국어)
- Test: `tests/test_learn_cli.py`

**Interfaces:**
- Produces:
  - `learn_cli.main(argv=None)`; 공통 옵션 `--url`(기본 `BRAIN_URL`), `--token`(기본 `BRAIN_TOKEN`); 서브커맨드 `start "<문장>" [--days N] [--level 초등|일반|전문] [--no-watch]`, `status <slug>`, `watch <slug> [--interval 10]`, `tasks <slug> --out DIR`, `submit <slug> <task_id> <file>`, `list`, `resume <slug>`, `rerender <slug> --level`. 한국어 출력: 단계 변화 시 `▶ 자료 모으는 중 (collect)`처럼 한 줄; done이면 지도 링크·요약; waiting이면 `⏸ 생각 담당이 필요해요: brain-learn tasks <slug> --out <dir>` 안내; failed면 사유.
  - `tasks --out DIR`: 과제마다 `<task_id>.json`(전체) + `<task_id>.prompt.md`(system/user를 사람이 읽기 좋게) + `README.md`(제출 방법).
  - 종료 코드: done 0, waiting 3, failed 1.
  - `learn_cli.fetch_json(method, path, **kw)` 얇은 httpx 래퍼(테스트에서 monkeypatch).
- `CLAUDE.md`(한국어, 짧게): 세션 시작 시 NEXT.md + `brain-learn list`로 진행 중/대기 퀘스트 확인; "배우고 싶어/이해하고 싶어/알고 싶어/공부하자/가르쳐 줘" 문장 → 되묻지 말고 `/learn` 스킬; 기본 초등·7일; 작은 수정 직접, 큰 공사 위임(기존 전역 규칙 참조); 비용 보고.
- `SKILL.md`(frontmatter `name: learn`, `description:` 트리거 문구 포함; 본문 한국어): ① `brain-learn start "<문장>"` ② watch ③ `waiting_thinker`면 `tasks --out`으로 받아 과제별 심부름꾼(plan/teach = opus, classify/bridge = sonnet, 한 번에 병렬)에게 `.prompt.md`를 그대로 주고 JSON만 받아 `submit` → 다시 watch ④ done이면 보고 양식: 지도 링크, 목표 한 줄, Day 1 핵심 한 줄, 예전 지식과 이어진 다리 3개(없으면 "아직 없음"), 새로 시도한 출처, 비용 추정 ⑤ 실패 시 사유와 `resume`.

- [ ] **Step 1: 테스트** `tests/test_learn_cli.py`(fetch_json 가짜): `test_start_posts_and_prints_url`, `test_watch_exits_3_on_waiting_and_prints_hint`, `test_tasks_writes_prompt_files(tmp_path)`, `test_submit_reads_file_and_posts`, `test_env_defaults_for_url_token(monkeypatch)`.
- [ ] **Step 2–4:** 실패 확인 → 구현 → `pytest tests/test_learn_cli.py -q`; `pip install -e .` 후 `brain-learn --help` 한국어 확인.
- [ ] **Step 5: 커밋** `feat(cli): brain-learn + project CLAUDE.md + /learn skill`

### Task 14b: M4 배포 + 수용 1 (지휘자 수동 과제)

- [ ] 전체 테스트 `pytest -q` 통과 → `railway up` → `/health`.
- [ ] `brain-learn start "나 헬리콥터 운전 배우고 싶어"` → watch. `waiting_thinker`면 스킬 절차대로 Clair가 과제 대행. done까지.
- [ ] 지도·Day 1~7 페이지를 열어 섹션·배지·링크 확인. 초등 규칙 위반(수식·기호)이 있으면 `prompts.teach_system` 보강 후 `rerender`.
- [ ] 결과(링크·비용·걸린 시간)를 NEXT.md에 기록.

# M5 — 점-대-점 다리

### Task 15: `brain/bridge.py` + 퀘스트 단계 + catalog 후크 + 재렌더

**Files:**
- Create: `brain/bridge.py`
- Modify: `brain/models.py`(`BridgeVerdict, BridgeBatch`), `brain/prompts.py`(`BRIDGE_SYSTEM`), `brain/quest.py`(`stage_bridge`), `brain/catalog.py`(`_after_learn` → `bridge.rebridge`), `brain/render.py`(day/index에 `bridges` 주입), `api/main.py`(`POST /graph/rebridge`)
- Test: `tests/test_bridge.py`, `tests/test_quest.py`(추가)

**Interfaces:**
- Produces:
  - `BridgeVerdict(src: str, dst: str, connects: bool, rel: Literal["bridge","requires","is_a","related"] = "bridge", reason: str = "")`, `BridgeBatch(verdicts: list[BridgeVerdict])`.
  - `bridge.candidates(node_id: str, limit: int = 8) -> list[dict]` → `[{"id","label_ko","label_en","field_code","why": "same_field|alias|wikidata_parent|vector|cooccur","books": [...]}]`; 후보는 **다른 책/퀘스트에 속한 개념만**(`graph.node_ids_in_book`로 소속 판정; `in_book`/`about` 간선 추적). 벡터 후보는 `vec.similar_nodes`가 있으면 사용(Task 17 전에는 import 실패 시 건너뜀).
  - `bridge.rebridge(node_ids: list[str], *, complete=None, task_id: str | None = None, slug: str | None = None) -> list[dict]`: 후보 묶음(최대 40쌍) → `think("bridge", BRIDGE_SYSTEM, user, BridgeBatch)`(퀘스트 안에서는 `quest.think_or_cached(slug, task_id or "bridge", …)` 경유) → `connects`인 것만 `graph.add_edge(src, dst, rel, reason=, evidence="bridge")` → 반환 새 다리 목록. 후보가 0이면 생각 호출 없이 `[]`. `ThinkUnavailable`은 퀘스트 밖(catalog 후크)에서는 삼키고 `[]`(로그), 퀘스트 안에서는 Parked로 전파.
  - `bridge.bridges_for(node_ids: list[str]) -> list[dict]`(`rel in (bridge, requires, is_a)` 간선 중 다른 책으로 가는 것; `{"src","dst","rel","reason","src_label","dst_label","dst_books"}`).
  - `bridge.affected_quests(node_ids) -> list[str]`(그 개념이 `taught_in`으로 들어간 lesson 노드의 퀘스트 slug), `bridge.rerender_affected(node_ids)` → `render.render_quest_day`/`render_quest` 재실행(생각 호출 없음).
  - `prompts.BRIDGE_SYSTEM`: "억지로 잇지 마라. 진짜 같은 원리/같은 수학/같은 부품/선행 관계일 때만 connects=true. reason은 초등 눈높이 한 문장."
  - `quest.stage_bridge(slug)`: `node_ids = 이 퀘스트의 concept 노드` → `rebridge(…, slug=slug, task_id="bridge")` → `summary["bridges"] = len` → 해당 day 재렌더.
  - `catalog._after_learn`: 새 개념 id에 대해 `bridge.rebridge` → `bridge.rerender_affected`.
  - `POST /graph/rebridge?field=&limit=`(토큰): 대상 개념(분야 필터 또는 전체 최근 N) rebridge → `{"bridges": n}`.
  - 렌더: day 페이지 "다른 때 배운 것과 잇기"에 `bridges_for(그날 concept_ids)`, index 페이지에 전체.

- [ ] **Step 1: 테스트** `tests/test_bridge.py`
  - `test_candidates_only_from_other_books(data_dir)`: 같은 책 개념은 제외, 같은 분야 다른 책 개념은 포함(`why == "same_field"`), 별칭 일치 포함.
  - `test_rebridge_adds_only_confirmed_edges(fake think)`: 3후보 중 1만 connects → 간선 1, reason 저장.
  - `test_rebridge_no_candidates_skips_think`.
  - `test_affected_quests_and_rerender(data_dir)`: lesson 노드·taught_in 구성 후 → slug 반환, 렌더 함수 호출됨.
  - `tests/test_quest.py::test_full_run_creates_bridge_to_prior_book`: 미리 `양자역학` 책에 개념 `angular-momentum`(각운동량) 넣고, 퀘스트 가짜 plan에 `자이로스코프` 점 + 가짜 bridge think가 connects → done 후 `graph.neighbors("gyroscope")`에 `bridge` 간선, day HTML에 "각운동량" 포함.
  - `tests/test_catalog.py::test_after_learn_triggers_rebridge(monkeypatch)`.
- [ ] **Step 2–4:** 실패 확인 → 구현 → `pytest tests/test_bridge.py tests/test_quest.py tests/test_catalog.py -q`.
- [ ] **Step 5: 커밋** `feat(bridge): cross-book concept bridges as a standalone re-runnable service`

### Task 15b: M5 배포 + 수용 2 (지휘자 수동 과제)

- [ ] `railway up`. 분류 백로그(특히 `book=양자역학`) 완료 확인 → `POST /graph/rebridge` → 헬리콥터 퀘스트 day 페이지의 "다른 때 배운 것과 잇기"에 양자역학 쪽 개념과 이유 문장이 보이는지 확인. 없으면 후보 생성 로직·프롬프트를 점검하고 기록(억지 다리를 만들지는 않는다).

# M6 — 꺼내기: 벡터·RAG·볼트·그래프 뷰

### Task 16: 임베딩 + sqlite-vec + RRF 검색

**Files:**
- Create: `brain/embed.py`, `brain/vec.py`
- Modify: `brain/retrieve.py`(`hybrid`), `brain/db.py`(vec 테이블), `brain/quest.py`(`stage_archive`에서 색인), `brain/catalog.py`(학습 후 개념 색인), `brain/bridge.py`(벡터 후보 사용), `api/main.py`(`/search`가 `hybrid` 사용, `mode=fts|hybrid`)
- Test: `tests/test_vec.py`, `tests/test_retrieve.py`(추가)

**Interfaces:**
- Produces:
  - `embed.embed(texts: list[str]) -> list[list[float]] | None`(Gemini `batchEmbedContents`, `outputDimensionality=768`, 키 없음/실패 → None, 100개씩 묶음).
  - `vec.ensure_tables(con)`(`sqlite_vec.load(con)`; `node_vec(node_id TEXT PRIMARY KEY, embedding float[768])`, `chunk_vec(chunk_id TEXT PRIMARY KEY, slug TEXT, path TEXT, start INT, embedding float[768])`, `chunk_text(chunk_id PRIMARY KEY, text)`), `vec.index_nodes(node_ids: list[str]) -> int`, `vec.index_doc(slug: str, path: str, text: str, chunk_chars: int = 800) -> int`, `vec.similar_nodes(text: str | None = None, node_id: str | None = None, k: int = 5) -> list[tuple[str, float]]`, `vec.similar_chunks(text: str, k: int = 8) -> list[dict]`. 임베딩이 None이면 모두 0/[] 반환(예외 없음).
  - `retrieve.hybrid(query: str, k: int = 10, slug: str | None = None) -> list[dict]`: FTS 순위 + 벡터 청크 순위 + 그래프 이웃(쿼리로 `graph.search_labels` 상위 3 → `neighbors` 1홉의 lesson/source 노드) → RRF(`1/(60+rank)`) 합산 → `[{"text","slug","path","title","score","via": ["fts","vec","graph"]}]`.
- `GET /search?q=&k=&mode=hybrid|fts`(공개, 기존 호환).

- [ ] **Step 1: 테스트** `tests/test_vec.py`(embed 가짜: 결정적 해시 벡터): `test_index_and_similar_nodes_roundtrip`, `test_no_embedding_provider_is_silent`, `tests/test_retrieve.py::test_hybrid_rrf_merges_three_sources_and_dedups_paths`.
- [ ] **Step 2–4:** → `pytest tests/test_vec.py tests/test_retrieve.py tests/test_api.py -q`.
- [ ] **Step 5: 커밋** `feat(retrieve): gemini embeddings in sqlite-vec + RRF hybrid search`

### Task 17: `/ask` RAG + Obsidian 볼트 zip

**Files:**
- Create: `brain/ask.py`, `brain/vault_export.py`
- Modify: `brain/models.py`(`Citation, AskAnswer`), `brain/prompts.py`(`ASK_SYSTEM`), `api/main.py`(`POST /ask`, `GET /vault.zip`), `sync/learn_cli.py`(`ask "<질문>"`)
- Test: `tests/test_ask.py`, `tests/test_vault_export.py`

**Interfaces:**
- Produces:
  - `Citation(title: str, url: str = "", slug: str = "", path: str = "")`, `AskAnswer(answer_html: str, citations: list[Citation] = [], used_vault_ratio: float = 1.0, follow_up_quest: str = "")`.
  - `ask.ask(q: str, mode: Literal["auto","vault","web"] = "auto", level: str = "초등") -> dict`: `retrieve.hybrid(q, 8)`; `mode=="web"` 또는 (`auto`이고 히트 < 3 또는 최고 score 낮음)이면 `registry.search_all(q, "ko", 3, names=["wikipedia","ddgs","xai"])` 상위 3 fetch 요약 포함; `think("ask", ASK_SYSTEM(level), user, AskAnswer)` → 질문 노드 `q:<sha8>`(kind question, label=q) + `asked` 간선(매칭 개념 상위 3) → 반환 `AskAnswer` dict + `{"hits": n, "web_used": bool}`.
  - `vault_export.build_zip() -> bytes`: `vault/<영역이름>/<분야이름>/<label_ko>.md`(frontmatter `id, tags[area,field,…], wikidata, aliases`; 본문: summary, `## 이어진 개념` `[[라벨]]` 목록(rel 표기), `## 자료`, `## 수업`), `vault/퀘스트/<slug>/day-N.md`(점 카드 텍스트 + `[[개념]]`), `vault/자료/<src id>.md`(제목·URL·요약), 파일명 충돌 시 `-<field_code>` 접미사; `vault/README.md`(한국어 안내).
  - API: `POST /ask` body `{"q","mode","level"}`(토큰), `GET /vault.zip`(토큰, `application/zip`).
- [ ] **Step 1: 테스트** `test_ask_vault_only_when_hits_enough`, `test_ask_falls_to_web_when_thin(monkeypatch)`, `test_ask_records_question_node`; `test_vault_zip_has_concept_quest_source_files_and_wikilinks(data_dir)`, `test_vault_filename_collision_suffix`.
- [ ] **Step 2–4:** → `pytest tests/test_ask.py tests/test_vault_export.py -q`.
- [ ] **Step 5: 커밋** `feat(ask,vault): RAG answers with citations; Obsidian vault export`

### Task 18: 그래프 뷰 페이지 + 서재 마무리

**Files:**
- Create: `brain/templates/brain_graph.html.j2`
- Modify: `brain/render.py`(`render_brain_page()`), `brain/quest.py`(archive에서 호출), `api/main.py`(lifespan에서 1회 렌더), `brain/static/brain.css`
- Test: `tests/test_render_quest.py`(추가)

**Interfaces:**
- `render.render_brain_page() -> Path`(`site/brain/index.html`): d3 v7 (`https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js`) force graph; 페이지 로드 시 `?t=` 토큰을 `localStorage["brain_token"]`에 저장 후 `GET /graph/full?limit=2000` (헤더 `X-Brain-Token`) → 영역별 색(17색 팔레트 CSS 변수), 노드 크기 = 간선 수, `bridge` 간선 점선 강조, 상단 검색(라벨 포함 필터)·영역 체크박스·"다리만 보기" 토글, 노드 클릭 → 옆 패널(라벨·요약·분야·자료/수업 링크·다리 목록; `GET /graph?center=&depth=1`), 토큰 없으면 한국어 안내 문구. 다크 모드 토큰 유지, 폰 폭에서 패널은 아래로.
- 서재 상단에 "🧠 두뇌 그래프" 링크(`/site/brain/index.html`).

- [ ] **Step 1: 테스트** `test_brain_page_renders_with_token_hint_and_d3`.
- [ ] **Step 2–4:** → `pytest tests/test_render_quest.py -q`.
- [ ] **Step 5: 커밋** `feat(site): Obsidian-style dot-to-dot graph view`

### Task 19: M6 배포 + 수용 3 + 문서·메모리 (지휘자 수동 과제)

- [ ] `pytest -q` 전체 통과 → `railway up`.
- [ ] `brain-learn start "양자역학을 이용해서 줄기세포 관련 노화방지에 대해 확실히 이해하고 싶어"` → done. 점 카드에 증거 등급이 섞여 있고(특히 `상술`/`추측` 존재), 정직 상자에 과장 경고가 있는지 확인.
- [ ] `GET /vault.zip` 내려받아 압축 안에 개념·퀘스트·자료 md와 `[[링크]]` 확인. 그래프 페이지를 토큰 링크로 열어 다리 점선 확인.
- [ ] 문서: `README.md`(한국어: 퀘스트 한 문장 사용법, 그래프 보기, Obsidian 내보내기, 생각 제공자 설정), `NEXT.md`(수용 결과·CR 확인 항목 §10), 메모리 `learn-quest-trigger.md` + `MEMORY.md` 한 줄, `notebooklm-access.md`는 변경 없음.
- [ ] 아키텍트 검증(큰 공사 규칙): 테스트 결과·배포 로그·수용 페이지 링크를 증거로 제시.

---

## 자기 점검 결과 (작성 후)

- **스펙 대응:** 5.1 → T14, 5.2 → T1, 5.3 → T10·T11·T13, 5.4 → T11, 5.5 → T8·T9·T10, 5.6 → T2·T5·T6, 5.7 → T12, 5.8 → T4·T5·T6·T15·T16·T18, 5.9 → T17, 5.10 → T13·T18, §6 비용 → T1(상한)·T13(추정), §7 테스트 → 각 과제, §8 이정표 → T3·T7·T14b·T15b·T19.
- **형 일관성:** `Candidate/Doc`(T8) ↔ `collect`(T10) ↔ `registry.fetch`(T9); `QuestPlan/DayLesson`(T10·T12) ↔ `models.SCHEMAS`(T11) ↔ CLI 제출(T14); `graph.add_edge(src,dst,rel,weight,reason,evidence)` 전 과제 동일; `think_or_cached(slug, task_id, kind, system, user, schema, context)` T11·T12·T15 동일.
- **Review Focus 매핑:** 1→T1, 2→T8, 3→T10, 4→T11, 5→T11(`test_run_is_resumable…`).
- **비율:** 코드 본문 없이 서명·테스트명·값만 적었다. 스펙 5.5의 "점당 ≤4"는 전체 상한 45와 충돌해 기본 `quota_per_dot=2`로 정했다(빌더 재량 범위, 설정으로 조정 가능).
