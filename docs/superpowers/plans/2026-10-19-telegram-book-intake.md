# 텔레그램 책 사진 접수 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox syntax.

**Goal:** CR이 텔레그램 봇(@SexyClair_bot)에 책 제목과 사진을 보내면 서버가 올바른 책에 붙이고(버튼 확인·보류함·옮기기), 글자를 읽어(Gemini 무료 → Clair 대기열) 서재·분류·그래프에 넣고, "이 책에서 배우기"로 퀘스트를 시작한다.

**Architecture:** FastAPI 웹훅(즉시 200, 백그라운드 처리) → `brain/telegram_bot.py`(파싱·버튼·API) → `brain/intake.py`(책 매칭·묶음·보류함·이동·삭제, 상태 파일) → 기존 `ingest.ingest_file`(+`extra_meta`, OCR 대기) → catalog/graph. OCR은 `brain/ocr.py` 제공자 사슬 + `/data/ocr/pending.jsonl` 대기 큐 + `/ocr/*` 경로 + CLI로 Clair가 직접 읽기.

**Tech Stack:** Python 3.12, FastAPI, httpx(+respx 테스트), Telegram Bot API(webhook, inline/reply keyboards, media groups, getFile), Gemini REST vision.

**Spec:** `docs/superpowers/specs/2026-10-19-telegram-book-intake-design.md` (§9 결정 포함)

## Global Constraints
- 사용자용 문자열 전부 한국어 존댓말("~요"); 식별자 영어. 토큰은 로그·채팅에 남기지 않는다(URL 마스킹).
- 유료 API 금지: OCR 사슬은 `THINK_PROVIDERS`에 든 제공자만(지금 gemini). 사진은 어떤 경우에도 먼저 저장.
- 기본값: 묶음 창 90초(슬라이딩, 최대 10분), 만료 6시간 또는 서울 날짜 변경, 유사도 0.8/0.9, 유예 30분, 최근 묶음 3개 되돌리기, `ocr_daily_cap=300`.
- 설정 키: `telegram_bot_token, telegram_allowed_user_id, telegram_webhook_secret, brain_public_url, ocr_daily_cap`.
- 상태 파일 `/data/telegram/state.json`(원자적 쓰기), OCR 큐 `/data/ocr/pending.jsonl`.
- 테스트는 네트워크 없음(respx로 텔레그램·Gemini 가짜). 기존 테스트 전부 통과(현재 421).
- 커밋 끝: `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Review Focus
1. 같은 사진을 두 번 보내거나 텔레그램이 같은 update를 재전송할 때 → 중복 저장·중복 확인 메시지 없음 (T2/T3 테스트).
2. 자정을 넘기거나 6시간 지난 뒤 첫 사진 → 보류함 + 질문, 어떤 책에도 안 붙음 (T2 테스트).
3. 캡션 제목이 지금 책과 다를 때 → 그 묶음만 그 책, 지금 책은 유지 (T2 테스트).
4. Gemini 429/503 → 사진 저장 + `ocr: pending` + 대기 큐, 봇 안내 (T1/T3 테스트).
5. 이미 분류된 묶음을 옮기기 → 옛 책의 자료 노드·간선 사라지고 새 책에 재등록 (T3 테스트).

## 파일 구조
```
brain/ocr.py            (신규) ocr_image 사슬, OcrUnavailable, pending 큐 함수
brain/ingest.py         (수정) extra_meta, OcrUnavailable → pending md
brain/config.py         (수정) 설정 5개
brain/intake.py         (신규) 상태·책 매칭·묶음·보류함·move/delete·학습 유예
brain/telegram_bot.py   (신규) 업데이트 파서·버튼·텔레그램 API 클라이언트·메시지 문구
brain/catalog.py        (수정) forget(), hold_until 존중
brain/graph.py          (수정) remove_node 묘비 + rebuild 반영
api/main.py             (수정) /telegram/webhook, /telegram/setup, /ocr/*, lifespan setWebhook, /upload ocr 필드
sync/learn_cli.py       (수정) ocr list|get|submit
tests/test_ocr.py, test_intake.py, test_telegram_bot.py, test_api_telegram.py (신규), 기존 테스트 수정
```

---

### Task 1: OCR 사슬 + 대기 큐 + ingest 계약 + `/ocr/*` + CLI
**Files:** Create `brain/ocr.py`, `tests/test_ocr.py`; Modify `brain/config.py`, `brain/ingest.py`, `api/main.py`(`/ocr/pending`, `/ocr/file/{id}`, `POST /ocr/{id}`, `/upload` 응답 `ocr`), `sync/learn_cli.py`(`ocr list|get|submit`), `tests/test_ingest.py`, `tests/test_api.py`, `tests/test_learn_cli.py`.
**Interfaces (Produces):**
- `config.Settings`: `telegram_bot_token: str=""`, `telegram_allowed_user_id: int=0`, `telegram_webhook_secret: str=""`, `brain_public_url: str=""`, `ocr_daily_cap: int=300`.
- `ocr.OcrUnavailable(Exception)` (`reasons: list[str]`); `ocr.ocr_image(data: bytes, mime: str) -> str` (gemini: `generateContent` with `inline_data` + 기존 `llm.OCR_SYSTEM` 지시문, 모델 `gemini_model_fast`, 헤더 `x-goog-api-key`; anthropic: `llm.ocr_image`; 제공자는 `settings.think_providers` 순서·멤버십; 일일 상한 `ocr_daily_count() >= ocr_daily_cap` → Unavailable; 성공 시 `think.record_usage(kind="ocr", …)`).
- `ocr.pending_path()`, `ocr.add_pending(entry: dict)`, `ocr.list_pending() -> list[dict]` (`{"id","book","file","path","image","mime","added_at"}`; `id` = `catalog.make_id(book, file)`), `ocr.remove_pending(id)`, `ocr.complete(id: str, text: str) -> dict` (마크다운 본문 채우고 `ocr: done`, `catalog.register` 재호출, 큐에서 제거), `ocr.ocr_daily_count()`.
- `ingest.ingest_file(slug, filename, data, extra_meta: dict | None = None) -> Path`: frontmatter에 extra_meta 병합; 이미지/스캔 PDF에서 `OcrUnavailable` → 본문 `""` + `ocr: "pending"` + `ocr.add_pending(...)`; 성공 시 `ocr: "done"`; 텍스트류는 `ocr: "none"`. 같은 sha 기존 파일이면 조기 반환(기존 동작).
- API: `GET /ocr/pending`(토큰), `GET /ocr/file/{id}`(토큰, 원본 이미지 `FileResponse`), `POST /ocr/{id}` body `{"text"}`(토큰) → `ocr.complete`; `/upload` 응답에 `"ocr": "done|pending|none"`.
- CLI: `brain-learn ocr list`, `ocr get <id> --out DIR`(이미지 저장 + 안내 txt), `ocr submit <id> <txtfile>`.
- [ ] 테스트 먼저: gemini 성공(respx) → 텍스트; gemini 503 → Unavailable → ingest가 pending md + 큐; providers에 anthropic 없으면 anthropic 호출 안 함; `complete`가 md 채우고 큐 제거하고 catalog에 등록; 일일 상한; `/ocr/*` 토큰·흐름; `/upload` 이미지에서 pending 응답; CLI 3개.
- [ ] 구현 → `pytest tests/test_ocr.py tests/test_ingest.py tests/test_api.py tests/test_learn_cli.py -q` → 전체 → 커밋 `feat(ocr): provider chain + pending queue + clair fallback routes`.

### Task 2: 접수 로직 `brain/intake.py` + 봇 `brain/telegram_bot.py`
**Files:** Create `brain/intake.py`, `brain/telegram_bot.py`, `tests/test_intake.py`, `tests/test_telegram_bot.py`.
**Interfaces (Consumes):** `ingest.ingest_file(slug, filename, data, extra_meta)`(Task 1 계약; 테스트는 가짜), `store.list_books()`, `slug.slugify`, `catalog.register`, `quest.create/start_background`, `settings.*`.
**Interfaces (Produces):**
- `intake.State` 로드/저장(`/data/telegram/state.json`, 원자적, 프로세스 `threading.Lock`): `current_book{slug,title,set_at,last_at}`, `recent_books[]`, `holding[]`(file refs + caption), `batches[]`(최근 10: `{id, slug, files[], created_at, confirmed, learned_hold_until}`), `seen_update_ids`(최근 500), `buttons{key→payload}`.
- `intake.match_title(title: str) -> dict` → `{"kind": "exact"|"similar"|"new", "slug", "title", "candidates": [...]}` (slugify 정확 일치 / difflib ≥0.8 on title·slug / new).
- `intake.set_current(slug, title)`, `intake.current() -> dict | None`(만료 규칙 적용: 마지막 활동 6h 또는 Asia/Seoul 날짜 변경 → None), `intake.recent_books(n=6)`.
- `intake.add_photo(file_bytes, filename, mime, *, caption: str, media_group_id: str | None, now) -> dict` → 캡션 파싱(제목 override ≥0.9, page, chapter, tags, note), 책 결정(캡션 > 현재 책 > 보류함), 묶음 배정(같은 media_group 또는 마지막 사진 뒤 90초, 최대 10분), 중복 sha 건너뜀, `ingest_file(... extra_meta={via:"telegram", batch, uploaded_at, page, chapter, tags, note})`; 반환 `{"status": "attached"|"held", "batch_id", "slug", "count", "dupes", "ocr": "done|pending"}`.
- `intake.resolve_holding(slug, title) -> dict`(보류함 전체 부착), `intake.discard_holding()`.
- `intake.move_batch(batch_id, new_slug) -> dict`, `intake.delete_batch(batch_id) -> dict` (Task 3의 `catalog.forget`/`graph.remove_node`를 `getattr` 가드로 호출; 파일 이동/삭제; 재등록; `index.rebuild`).
- `intake.summary() -> dict`(책별 장 수, OCR 대기, 분류 대기).
- `telegram_bot.TelegramAPI(token)`: `send_message(chat_id, text, reply_markup=None)`, `edit_message_text`, `answer_callback_query`, `get_file(file_id) -> (bytes, filename, mime)`, `set_webhook(url, secret)`, `set_my_commands()`; 토큰 마스킹 로깅; httpx 타임아웃 30s.
- `telegram_bot.handle_update(update: dict, api: TelegramAPI) -> None`: 인증(허용 id 아니면 무시), `update_id` 중복 무시, 텍스트(명령·메뉴·제목), 사진/문서, callback_query 분기; 메시지 문구와 키보드(하단 메뉴 6개, 책 고르기 버튼, 묶음 확인 버튼, 보류함 질문 버튼, 옮기기·지우기 버튼, 배우기 확인 버튼); 만료 버튼 → "만료됐어요".
- `telegram_bot.keyboards.*` 순수 함수(테스트 용이).
- [ ] 테스트 먼저(가짜 API 기록기): 제목 정확/유사/신규 분기와 버튼; 사진 1장→확인 1개; 앨범 3장→확인 1개; 90초 묶음; 만료 뒤 보류함+질문→버튼 선택→부착; 캡션 override; 중복 sha; 옮기기·지우기(가짜 forget/remove 호출 확인); 비허용 사용자 무시; update_id 중복; 배우기 버튼→`quest.create` 호출(가짜); 만료 버튼 문구.
- [ ] 구현 → `pytest tests/test_intake.py tests/test_telegram_bot.py -q` → 전체 → 커밋 `feat(telegram): intake state machine + bot handlers with buttons`.

### Task 3: 웹훅·셋업·학습 유예·묘비 + 배포 준비
**Files:** Modify `api/main.py`(`POST /telegram/webhook`, `POST /telegram/setup`, lifespan setWebhook), `brain/catalog.py`(`hold_until` 존중: `pending()`은 `hold_until`이 미래인 항목 제외; `forget(book, filename)`), `brain/graph.py`(`remove_node(id)` 묘비 이벤트 `{"op":"remove","id"}` → 노드·간선·별칭 삭제, rebuild 반영), `brain/intake.py`(가드 제거, 실제 호출), tests.
**Interfaces (Produces):** `POST /telegram/webhook`(헤더 `X-Telegram-Bot-Api-Secret-Token` == settings → 아니면 403; 토큰 미설정 → 404; 즉시 `{"ok": true}` 반환 후 `threading.Thread(handle_update)`), `POST /telegram/setup`(토큰) → `set_webhook(brain_public_url + "/telegram/webhook")` + `set_my_commands` 결과; lifespan에서 토큰·public_url 있으면 1회 시도(실패 무시). `catalog.register(..., hold_until: str | None = None)`; `catalog.forget(book, filename) -> bool`; `graph.remove_node(id) -> bool`.
- [ ] 테스트 먼저: 웹훅 403/404/200+스레드(동기 가짜), setup 호출 페이로드; `pending()`이 hold_until 미래 항목 제외·과거 포함; `forget`이 큐·카드 제거; `remove_node` 후 `get_node None`, 간선 없음, `rebuild` 동일; `move_batch`/`delete_batch` 실제 경로(파일·큐·그래프).
- [ ] 구현 → 전체 테스트 → 커밋 `feat(telegram): webhook + setup, learn grace, tombstones`.

### Task 4: 배포·웹훅 등록·실사용 확인 (지휘자)
- [ ] `railway up`, `/health`, `POST /telegram/setup` → `getWebhookInfo` 확인.
- [ ] CR이 봇에 제목 + 사진 2장 → 확인 메시지, 볼륨 파일, OCR 결과/대기, `🧠 이 책에서 배우기` 동작.
- [ ] README 한국어 절 "텔레그램으로 책 사진 보내기", NEXT.md, 메모리.
