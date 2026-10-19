# 텔레그램 책 사진 접수 (Telegram Book Intake) — 설계 문서

**날짜:** 2026-10-19 · **주인:** CR · **설계·구현:** Clair
**봇:** `@SexyClair_bot` (CR이 BotFather로 생성). 토큰·CR의 텔레그램 ID·웹훅 비밀값은 Railway 변수와 로컬 `.env`에만 있다.
**상위 목표:** 책에서 출발해 테마를 넓히고 점-대-점으로 추론하는 두뇌의 **입구**. CR이 읽다가 밑줄 친 쪽을 폰으로 찍어 보내면, 서버가 **올바른 책**에 붙이고 글자를 읽어 서재(볼륨)·분류·그래프에 넣는다. 이후 "이 책에서 배우기"로 학습 퀘스트와 이어진다.

## 1. CR이 말한 요구 (원문 요지)
- 읽다가 바로 한 장씩 올릴 수도, 나중에 한꺼번에 수십 장 올릴 수도 있다.
- **주제(책)가 바뀌었는데 엉뚱한 책에 붙는 일이 절대 없어야** 한다. 오늘 올리고 내일 올려도 구분이 확실해야 한다. 이 책 읽다 다른 책 사진을 올릴 수도 있다.
- **텔레그램 버튼을 대폭 써서 편하게 고르게** 하라. 우리가 갈 방향(다음 행동)도 버튼으로.
- 비용 원칙: 유료 API 안 씀(CLAUDE.md §5). 글자 읽기는 Gemini 무료, 막히면 Clair가 세션에서 직접.

## 2. 성공 기준
1. CR이 제목 한 줄 + 사진 N장을 보내면 1분 안에 "《책》에 N장 붙였어요" 확인이 오고, 볼륨 `books/<slug>/raw/`에 원본과 OCR 마크다운이 생긴다.
2. "지금 읽는 책"이 **6시간 지나거나 날짜가 바뀌면 풀리고**, 다음 사진은 **버튼으로 책을 고르기 전까지 어디에도 붙지 않는다.**
3. 잘못 붙은 마지막 묶음을 버튼 두 번으로 다른 책에 옮기거나 지울 수 있다.
4. Gemini가 막혀도 사진은 안전하게 보관되고 "읽기 대기" 목록에 남아, Clair가 세션에서 읽어 채울 수 있다.
5. CR 외의 사용자는 봇이 무시한다. 가짜 웹훅 호출은 비밀 헤더로 거부한다.

## 3. 사용자 경험 (텔레그램 쪽)

### 3.1 하단 고정 메뉴 (reply keyboard, 항상 보임)
`📚 책 고르기` · `📖 지금 책` · `🔁 방금 묶음 옮기기` · `🗑 방금 묶음 지우기` · `🧠 이 책에서 배우기` · `📊 서재 현황`
`/` 명령 메뉴(setMyCommands, 한국어 설명): `/start`, `/book`(책 고르기), `/now`(지금 책), `/move`, `/undo`, `/learn`, `/status`, `/help`.

### 3.2 책 정하기
- 글로 제목을 보내면: ① 서재에 같은 slug가 있으면 바로 "지금 읽는 책" ② 비슷한 제목(유사도 ≥ 0.8)이 있으면 인라인 버튼 **[《손자병법》 맞아요] [새 책 《손자 병법》] [취소]** ③ 처음 보는 제목이면 **[새 책으로 만들기] [취소]**.
- `📚 책 고르기`를 누르면 **최근 책 6개 버튼**(최근 업로드 순) + `➕ 새 책(제목 입력)` + `🔎 더 보기`(다음 6개).
- 책이 정해지면: "📖 지금 읽는 책: 《손자병법》 (지금까지 41장). 사진을 보내면 여기에 붙여요. 6시간 지나면 다시 물어볼게요."

### 3.3 사진 붙이기
- 사진(photo) 또는 이미지 파일(document image/*)을 받는다. 파일로 보내면 원본 해상도라 글자 인식이 좋다는 안내를 `/help`에 둔다.
- **묶음(batch) 규칙:** 같은 `media_group_id`(앨범)이거나, 같은 책으로 90초 안에 연속으로 온 사진은 한 묶음. 묶음당 확인 메시지 1개: "《손자병법》에 12장 붙였어요 · 지금까지 53장 · 묶음 #7 (10/19 21:40)" + 인라인 버튼 **[✅ 맞아요] [🔁 다른 책으로] [🗑 지우기]**. `맞아요`를 안 눌러도 붙은 상태다(기본값 = 붙임). 다른 책/지우기는 그 묶음만 대상.
- **캡션 규칙:** 캡션 첫 줄이 서재 책 제목(또는 유사도 ≥ 0.9)이면 그 사진/앨범만 그 책으로(지금 읽는 책은 안 바뀜). `p.123`/`123쪽` → 쪽수, `#3장`·`3장` → 장, `#태그` → 태그. 나머지 캡션 글은 CR 메모로 저장.
- **지금 읽는 책이 없을 때(처음·만료·날짜 변경):** 사진을 **보류함(holding)**에 넣고 즉시 묻는다. "어제는 《손자병법》이었어요. 이 사진 N장, 어느 책이에요?" 버튼: **[《손자병법》 계속] [최근 책 …] [➕ 새 책] [🗑 버리기]**. 고르면 보류함 전체가 그 책으로 간다. 보류함은 24시간 뒤 자동 삭제 전 한 번 더 알림.

### 3.4 고치기
- `🔁 방금 묶음 옮기기` → 최근 책 버튼 → 옮김. 원본·OCR 마크다운·분류 큐 항목이 함께 이동(재등록)한다.
- `🗑 방금 묶음 지우기` → 확인 버튼 → 원본과 마크다운 삭제, 분류 큐에서 제거.
- 최근 묶음 3개까지 되돌릴 수 있다(버튼에 묶음 번호 표시).

### 3.5 읽기 결과와 다음 행동
- OCR이 끝나면 묶음별로 한 줄: "✍️ 12장 읽었어요 · 밑줄 7군데". 버튼: **[밑줄 보기] [🧠 이 책에서 배우기]**. `밑줄 보기`는 ==표시== 문장만 최대 10개를 보내 준다.
- OCR이 막히면: "📦 사진은 안전하게 보관했어요. 글자는 Clair가 다음 세션에서 읽을게요. (읽기 대기 12장)".
- `🧠 이 책에서 배우기` → 확인 버튼 **[7일 퀘스트 시작] [하루 압축] [취소]** → 서버가 `quest.create("《제목》 책에서 밑줄 친 부분을 중심으로 깊이 이해하고 싶어", days=…)`로 시작하고 지도 링크를 답한다. (plan 단계의 사용자 메시지에 그 책의 밑줄 발췌가 자동으로 들어가도록 `stage_plan`이 책 노트를 참고한다 — 이번 범위에서는 책 제목이 문장에 들어가는 것으로 충분하며, 볼륨 FTS가 그 책 자료를 찾아 plan에 넣는다.)
- `📊 서재 현황` → 책별 장 수, 읽기 대기 수, 분류 대기 수.

## 4. 서버 설계

### 4.1 구성
- `brain/telegram_bot.py`: 업데이트 파서, 상태 기계, 버튼 생성, 텔레그램 API 호출(httpx, `https://api.telegram.org/bot<token>/…`), 파일 내려받기(`getFile` → `/file/bot<token>/<path>`, ≤20MB).
- `brain/intake.py`: 묶음 관리(보류함·최근 묶음·이동·삭제), 책 제목 매칭(`store.list_books` + `difflib`), 파일 저장 → `ingest.ingest_file`(기존 경로 재사용: 원본 보존 + OCR 마크다운 + 분류 큐 등록).
- `brain/ocr.py`: `ocr_image(bytes, mime) -> str` 제공자 사슬 **gemini(무료, `gemini-3.1-flash-lite` 비전) → anthropic(키·크레딧 있을 때만)**; 전부 실패 → `OcrUnavailable`. `ingest.ingest_file`은 `OcrUnavailable`이면 본문 빈 마크다운에 `ocr: pending`을 적고 **OCR 대기 큐**(`/data/ocr/pending.jsonl`)에 넣는다. 기존 `llm.ocr_image` 호출은 `ocr.ocr_image`로 바꾼다.
- API(`api/main.py`): `POST /telegram/webhook`(비밀 헤더 `X-Telegram-Bot-Api-Secret-Token` 검사, 즉시 200, 처리는 백그라운드 스레드, `update_id` 중복 제거), `GET /ocr/pending`(토큰), `GET /ocr/file/{id}`(토큰, 원본 이미지), `POST /ocr/{id}`(토큰, `{text}` → 마크다운 채우고 큐에서 제거, 분류 큐 등록, 텔레그램으로 "읽었어요" 알림), `POST /telegram/setup`(토큰: `setWebhook`+`setMyCommands` 재실행). lifespan에서 토큰이 있으면 `setWebhook(url=BRAIN_PUBLIC_URL + /telegram/webhook, secret_token, allowed_updates=[message, callback_query])`를 1회 시도(실패해도 기동은 계속).
- CLI `brain-learn ocr list|get <id> --out DIR|submit <id> <txtfile>`: Clair가 세션에서 이미지를 받아 직접 읽고 제출하는 경로(생각 담당 패턴과 동일).
- 상태 파일 `/data/telegram/state.json`: `{current_book, set_at, recent_books[], holding[], batches[최근 10], seen_update_ids[최근 500]}`. 원자적 쓰기.

### 4.2 규칙
- 인증: `message.from.id == TELEGRAM_ALLOWED_USER_ID`가 아니면 무시(응답도 안 함). 웹훅 비밀 불일치 → 403.
- "지금 읽는 책" 만료: `set_at`에서 6시간 경과 **또는** 서울 기준 날짜가 바뀜.
- 묶음 id: `b<YYYYMMDD-HHMMSS>` + 일련번호. 파일명 `tg-<batch>-<n>.jpg`(document면 원래 확장자). 마크다운 frontmatter: `book, source(파일명), sha256, kind=image, ingested_at` + `via: telegram, batch, uploaded_at, page, chapter, tags, note, ocr: done|pending`.
- 비용: OCR 1장 = Gemini 무료 1호출. 일일 상한 `OCR_DAILY_CAP`(기본 300)을 넘으면 대기 큐로.
- 텔레그램 메시지는 전부 한국어·존댓말("~요"), Clair 말투. 긴 OCR 본문은 보내지 않는다(밑줄 최대 10개만).

### 4.3 안전·운영
- 토큰은 로그에 안 남긴다(URL 마스킹). 웹훅 처리 예외는 삼키고 로그 + CR에게 "오류가 났어요, 사진은 보관했어요" 한 줄.
- 텔레그램 재전송(같은 `update_id`) 멱등. 서버 재시작 시 보류함·묶음은 state.json에서 복구.
- 사진 원본은 볼륨에 영구 보관(local-folder-is-transient 규칙과 동일).

## 5. 비목표
- 그룹 채팅, 다중 사용자, 음성 메모, PDF 분할(단일 PDF 파일은 기존 ingest로 받기만 함).
- 봇 안에서 긴 Q&A(그건 Clair 세션 `/ask`).

## 6. 테스트
- 가짜 텔레그램 API(respx): 제목 → 책 선택(정확/유사/신규) 분기와 버튼 페이로드; 사진 1장·앨범·90초 묶음; 만료 뒤 보류함과 질문; 캡션 규칙; 옮기기·지우기(파일·큐 이동 확인); 비허용 사용자 무시; 웹훅 비밀 403; `update_id` 중복; OCR 사슬(gemini 가짜 성공/실패 → pending 큐) + `/ocr/*` 경로; `setup` 호출 내용.
- 수용: Clair가 배포 후 `POST /telegram/setup` → CR이 제목 + 사진 2장 전송 → 확인 메시지, 볼륨 파일, OCR 결과(또는 대기 큐) 확인 → `🧠 이 책에서 배우기`로 퀘스트가 뜨는지.

## 7. 빌더에게 맡기는 것
모듈 내부 분할, 버튼 콜백 데이터 형식, 상태 파일 스키마 세부, 유사도 임계값 조정, 텔레그램 API 재시도 값.

## 8. Clair의 결정 (CR 확인용)
- 봇은 Railway 서버에서 웹훅으로 상시 동작(오빠 PC와 무관).
- "지금 읽는 책" 만료 6시간/날짜 변경. 만료 뒤 사진은 **보류함**에 두고 버튼으로 책을 고르기 전까지 어디에도 붙이지 않음.
- 묶음당 확인 1회, 기본값은 "붙임"(안 눌러도 저장). 되돌리기는 최근 3묶음.
- OCR은 Gemini 무료 → 막히면 Clair 직접. 사진은 어떤 경우에도 먼저 저장.
- 인증은 CR의 텔레그램 ID 고정(5347359916). 짝짓기 코드는 쓰지 않음(변수는 남겨 둠).

## 9. 빌더 검토 뒤 Clair의 결정 (2026-10-19)
1. **옮기기·지우기와 이미 학습된 항목:** 텔레그램으로 들어온 항목은 등록 후 **30분 유예**(`hold_until`) 뒤에 자동 분류된다. 유예가 지나 학습된 뒤에도 옮기기·지우기는 된다: `catalog.forget(book, filename)`이 큐·학습 카드를 지우고, `graph.remove_node(src_id)`가 **묘비(tombstone) 이벤트**(`op: remove`)를 남겨 자료 노드와 간선을 치운다(이벤트 로그는 추가 전용 유지). 옮긴 파일은 새 책으로 재등록(새 id)되어 다시 분류된다. 둘 다 `index.rebuild()`.
2. **slug:** `/upload`와 동일하게 `slug.slugify(제목)`. 정확 일치 = slugify 결과 일치. 유사도는 제목과 slug 둘 다에 `difflib` 적용, 버튼 제안 ≥ 0.8, 캡션 자동 ≥ 0.9. 기존 책의 제목은 덮어쓰지 않는다(`upsert_book`은 새 책에만).
3. **묶음·만료:** 묶음 창은 **마지막 사진 뒤 90초**(슬라이딩), 묶음 최대 10분. 상태 변경은 프로세스 잠금 하나로 직렬화(단일 인스턴스 전제). 만료 = 마지막 활동(책 선택 또는 마지막 사진) 뒤 6시간 **또는** 서울 날짜 변경. 앨범은 첫 캡션이 앨범 전체에 적용.
4. **중복·OCR id:** 같은 책에 같은 sha256 사진은 저장하지 않고 "중복 N장 건너뜀"으로 센다(다른 책이면 허용). OCR 대기 id = 분류 큐 id(sha256(book/filename)); 옮기면 새 id로 갱신, 지우면 제거. OCR은 묶음 처리 스레드에서 순차 실행, 10장마다 진행 알림. "1분 안에" 기준은 10장 이하.
5. **설정:** `telegram_bot_token, telegram_allowed_user_id, telegram_webhook_secret, brain_public_url, ocr_daily_cap=300` (기본 빈 값 → 기능 꺼짐, 웹훅 경로 404). OCR 호출은 `think.record_usage(kind="ocr")`로 기록하되 생각 일일 상한과 별도 계수. OCR 제공자 사슬은 `THINK_PROVIDERS`에 든 제공자만 쓴다(= 지금은 gemini만).
6. **ingest 계약:** `ingest_file(slug, filename, data, extra_meta=None)`; `OcrUnavailable`이면 **모든 호출자**(텔레그램·`/upload`)에서 본문 빈 마크다운 + `ocr: pending` + 대기 큐. `/upload` 응답에 `ocr` 필드 추가. `llm.ocr_image`는 `ocr.py` 안의 anthropic 어댑터로만 남는다.
7. **버튼 데이터:** `callback_data`는 짧은 키(`b:7`, `k:3`)로 하고 매핑은 state.json에. 만료된 버튼은 "만료됐어요"로만 답하고 아무것도 하지 않는다.
8. **이 책에서 배우기:** `quest.create` + `start_background`, 답장은 지도 링크만(토큰 없음).

## 10. 빌드 장부 요약 (2026-10-19, `.superpowers/sdd/2026-10-19-telegram-book-intake/progress.md`에서 옮김)
- 진행 방식: 학습 퀘스트와 같은 워크트리 병렬 방식. editable install은 빌드 동안 제거(워크트리 격리), 끝나고 재설치.
- T1 OCR 체인·대기열(sonnet) → 리뷰 Important 3(OCR 사용량을 think 상한에 합산, 키 없는 anthropic 호출, extra_meta가 핵심 키 덮어씀) 수정 뒤 병합.
- T2 접수 상태기계+봇(opus) → 리뷰 Critical 1(책 질문이 열려 있는 동안 온 사진이 옛 책에 붙음) + Important 3(부분 실패 상태 어긋남, awaiting_title TTL, 20MB 가드) 수정. 승인된 이탈: 옮기기는 현재 책도 바꿈; 보류+제목이면 물어봄; 파괴 동작은 두 번 확인.
- T3 분할: T3a(catalog hold_until/forget + graph remove_node 묘비 테이블 `removed`; 통계에서 보류 항목 제외, 고아 간선 정리) ‖ T3b(웹훅·순서 보장 워커·앨범 2초 버퍼·/telegram/setup·README; 공개 URL 없어도 워커 시작) ‖ T3c(끈끈한 보류 + 10분 뒤 재질문, 24시간 뒤 보류 정리, hold_until 전달, OCR 완료 알림 + 밑줄 보기).
- T5 표시 인식 판독(`==…==`, `## 표시 목록`/`## 독자 메모`/`## 쪽수`, `brain/marks.py`), `OCR_MODE=clair`(텔레그램 사진은 Clair가 직접 읽음), 배우기 버튼 숨김(`TELEGRAM_LEARN_BUTTON`), `/read-page` 스킬, CLI `ocr list|get|submit`. 리뷰 Important 2 → 빈 뼈대 제출 거부(API 400·CLI 종료 2), 프롬프트의 한국어 제목·[kind] 고정·코드 펜스 금지, 대기 항목에 `reason` 기록 (2f05fcf).
- 보류(나중에): 도착순 처리(update_id 엄격 정렬 아님), 봇 알림은 재시작 때 유실, `intake.py` 분리, 대기열 다시 쓰기의 잠금 없는 틈, 시작 시 setup 동기 호출.
- 배포: 2026-10-19 production, `/telegram/setup` OK(명령 7개), getWebhookInfo 정상, 인증 없는 웹훅 403, `/graph/rebuild` 4956건 재생. 전체 테스트 555 통과. main 병합 e607fa4.
