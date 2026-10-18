# 학습 퀘스트 (Learn Quest) + 20년 지식 프레임 — 설계 문서

**날짜:** 2026-10-18
**주인:** CR (작곡가, 비개발자). **설계·구현:** Clair.
**결정 방식:** CR이 외출 중이라 질문 없이 진행. 아래 "Clair의 결정" 표시가 붙은 항목은 CR이 돌아와서 뒤집을 수 있다.
**기존 설계 위에 쌓는다:** `docs/superpowers/specs/2026-08-22-2ndbrain-design.md` (Phase 0 기반: ingest·distill·render·search·catalog). 이 문서는 그 Phase 1~2 항목(1.1 임베딩, 1.2 연결기, 1.5 개념 페이지, 2.1 개념 그래프, 2.7 질문 주도 연구)을 한 덩어리로 앞당겨 구현하는 설계다.

---

## 0. 한 문장 요약

CR이 **"나 헬리콥터 운전 배우고 싶어"** 또는 **"양자역학을 이용해서 줄기세포 관련 노화방지에 대해 확실히 이해하고 싶어"** 한 마디만 하면, Clair가 (1) NotebookLM보다 넓고 깊게 자료를 모으고, (2) 7일짜리 초등 눈높이 수업 페이지를 만들고, (3) 그 지식을 20년짜리 점-대-점(dot-to-dot) 두뇌에 영구히 꽂아 넣어, 나중에 헬리콥터의 어떤 요소가 예전에 배운 양자역학의 특정 부분과 저절로 이어지게 한다.

## 1. 왜 지금, 무엇이 성공인가

- **왜:** CR의 북극성은 "무엇이든 하루아침에 배울 수 있게"(memory: learning-north-star). 지금은 NotebookLM 노트 7권을 볼륨에 옮겼지만, 분류 대기 1,085건·학습 0건·개념 0개 — 지식이 쌓이기만 하고 이어지지 않는다.
- **성공 기준 (수용 테스트):**
  1. 문장 하나 → 질문 없이 → 수집·수업·그래프 연결까지 자동으로 끝나고, 결과 링크 하나가 CR에게 온다.
  2. 수업은 **초등 눈높이 한 레벨만**, 하루 한 페이지, 7일. 첫 페이지를 읽고 5분 안에 "아, 이게 그거구나"가 나와야 한다.
  3. 헬리콥터 퀘스트가 끝나면 그래프에 **양자역학 쪽 개념과 이어진 다리(bridge) 간선**이 이유 문장과 함께 생겨 있다 (예: 로터의 자이로 효과 ↔ 각운동량 ↔ 스핀).
  4. Anthropic 크레딧이 0이어도 파이프라인이 멈추지 않는다 (대체 모델 또는 Clair 본인이 생각 작업을 대신 수행).
  5. 20년 뒤에도 깨지지 않는 식별자·분류 체계: 노드 id는 영구, 병합은 리다이렉트로만, 분류 코드는 추가만 가능.

## 2. 목표 / 비목표 / 반(反)목표

**목표**
- 한 문장 트리거, 무질문, 기본값(초등·7일) 자동.
- 수집: 다중 출처 자동 발견 + 품질 점수 + 원문 전문 저장 + 출처 장부(왜 골랐는지).
- 수업: 빠른 이해에 최적화된 페이지 구조(큰 그림 → 점 카드 → 퀴즈 → 내 말로 → 잇기).
- 두뇌: 영구 개념 그래프(타입 있는 간선), 태그·전문검색·벡터·그래프 이웃으로 꺼내기, Obsidian 내보내기, 웹 그래프 뷰.
- 정직성: 모든 점(dot)에 증거 등급(확립됨/연구 중/추측/상술). "양자 × 줄기세포 × 노화" 같은 질문에서 과장 마케팅과 진짜 과학을 갈라 보여준다.

**비목표 (이번에 안 함)**
- 다중 사용자, 로그인 UI, 결제 (Phase 3).
- 모바일 앱, 음성.
- 자체 LLM 학습.

**반목표 (이렇게 되면 실패)**
- 질문을 되묻는 것. 레벨을 묻는 것.
- 요약문 나열(= NotebookLM 수준). 수업은 요약이 아니라 "이해 엔진"이어야 한다.
- 출처 없는 주장. 링크 없는 인용.
- 개념 이름이 자료마다 달라 그래프가 끊기는 것("얽힘" vs "양자 얽힘").
- 크레딧이 없다고 아무것도 안 하고 멈추는 것.

## 3. 제약

| 항목 | 값 |
|---|---|
| 예산 | 월 $20~50 전체. 퀘스트 1회 목표 비용 ≤ $1 (Claude API 기준), Gemini 무료 경로면 ≈ $0 |
| 지금 상태 (2026-10-18 확인) | **Anthropic API 크레딧 0** (모든 호출 400). Gemini 무료: `gemini-3.5-flash`·`gemini-3.1-flash-lite` 생성 OK, `gemini-embedding-001` 768차원 OK, Google 검색 그라운딩은 429(유료). xAI: `grok-4.3` 생성·`web_search` 도구 OK (유료, 소액). |
| 키 없는 연결기 (확인됨) | Wikipedia ko/en, Wikidata, OpenAlex, arXiv(https), PubMed, DDGS 웹검색(불안정), trafilatura 본문 추출(위키·네이버 블로그 OK), YouTube 자막(영상 따라 자주 실패 → 선택적) |
| 서버 | Railway 단일 인스턴스, 볼륨 `/data` 5GB(현재 ~50MB 사용), 배포 `railway up` |
| 언어 | CR용 산출물·페이지·CLI 메시지 전부 한국어. 코드·식별자 영어 |
| 기존 규칙 | 기본 초등·한 레벨만·항상 HTML(memory: level-adaptive-output-rule); 모든 학습 산출물 영구 보관(lesson-pages-archive); 모든 자료 분류 큐 통과(knowledge-pipeline-rules); 새 출처 적극 시도·기록(source-expansion-autonomy) |

## 4. 전체 그림

```
CR: "나 헬리콥터 운전 배우고 싶어"
 │  (Claude Code 세션, Clair)
 ▼
brain-learn start "<문장>"  ──POST /quests──▶  서버 퀘스트 러너 (상태 기계, 재개 가능)
                                               │
   ┌───────────────────────────────────────────┼─────────────────────────────┐
   │ 1 plan     [생각]  문장 → 퀘스트 설계도(종류·목표·7일 점 지도·검색어·정직 경계)  │
   │ 2 collect  [자동]  연결기 병렬 검색 → 점수·중복제거 → 전문 수집 → books/<quest>/raw │
   │ 3 classify [생각]  자료 분류 카드(묶음) → 개념 정규화 → 그래프 upsert           │
   │ 4 teach    [생각]  하루 1장 × N일, 초등 한 레벨, 점 카드 데이터 + HTML           │
   │ 5 bridge   [자동+생각] 새 개념 ↔ 기존 개념 후보 → 진짜 다리만 이유와 함께 간선  │
   │ 6 archive  [자동]  FTS·벡터 색인, Obsidian 볼트 갱신, 서재/그래프 페이지 갱신     │
   └──────────────────────────────────────────────────────────────────────────┘
                                               │
          [생각] 단계 = think() 제공자 사슬: Anthropic → Gemini → xAI → (전부 실패) 열린 과제
                                               │
                     열린 과제가 생기면 상태 = waiting_thinker ──▶ Clair가 세션에서 직접 풀어 제출
                                                                  (GET/POST /quests/{slug}/tasks)
 ▼
CR에게: 지도 페이지 링크 1개 + 한 줄 요약 + "예전 지식과 이어진 점" 3개
```

핵심 아이디어: **서버는 결정론적 두뇌(저장·수집·그래프·검색·상태 기계)**, **"생각"은 꽂아 쓰는 부품**이다. 생각 부품은 API 모델이든 Clair 본인이든 같은 과제 규격(JSON 입출력)을 만족하면 된다. 그래서 크레딧이 0이어도, 모델이 바뀌어도, 20년 뒤에도 파이프라인은 그대로다.

## 5. 구성 요소 (Clair의 결정 포함)

### 5.1 트리거 표면

| 표면 | 내용 |
|---|---|
| 프로젝트 `CLAUDE.md` (신규) | "X 배우고 싶어 / 이해하고 싶어 / 알고 싶어 / 공부하자 / 가르쳐 줘" 류의 문장이 오면 되묻지 말고 `brain-learn start` → `watch` → 결과 보고. 기본 초등·7일. 레벨/일수는 문장에 있을 때만 바꾼다("3일 만에", "전문가 수준으로"). |
| `.claude/skills/learn/SKILL.md` (신규) | 위 절차의 상세 + `waiting_thinker`일 때 Clair가 과제를 풀어 제출하는 방법(심부름꾼 배분: plan/teach = opus 1명, classify/bridge = sonnet 묶음) + 최종 보고 양식. |
| CLI `brain-learn` (`sync/learn_cli.py`) | `start "<문장>" [--days N] [--level 초등]`, `status <slug>`, `watch <slug>`(한국어 진행 표시), `tasks <slug> --out DIR`(열린 과제를 파일로), `submit <slug> <task_id> <file>`, `list`, `ask "<질문>"`. |
| HTTP | `POST /quests`, `GET /quests`, `GET /quests/{slug}`, `GET /quests/{slug}/tasks`, `POST /quests/{slug}/tasks/{task_id}`, `POST /quests/{slug}/resume`, `POST /quests/{slug}/rerender?level=`. |
| 공개 범위 (Clair의 결정) | 데이터 API(`/quests*`, `/graph*`, `/ask`, `/vault.zip`)는 **전부 토큰 필요**(CLI·Clair는 토큰 보유). 정적 페이지 `/site/**`는 Phase 0 결정대로 "링크를 아는 사람만, 검색엔진 차단(noindex)" 유지 — CR이 폰에서 링크로 열어야 하므로. 그래프 뷰 페이지는 `?t=<토큰>`을 한 번 받아 localStorage에 저장한 뒤 데이터 API를 부른다. 사이트 전체 잠금은 §10 CR 확인 항목. |
| 메모리 | `learn-quest-trigger.md` 한 줄: 문장 → 스킬. |

### 5.2 생각 부품 `brain/think.py` (Clair의 결정)

- `think(kind, system, user, schema) -> dict`: 제공자 사슬을 순서대로 시도. 기본 순서 `THINK_PROVIDERS=anthropic,gemini,xai`.
- 과제 종류별 모델 등급: `plan`·`teach`·`bridge_confirm` = smart, `classify`·`canon` = fast.
  - Anthropic: smart `claude-sonnet-5-5`, fast `claude-haiku-5-5` (config 기본값 갱신; 현재 `claude-sonnet-5`/`haiku-4-5`는 구형).
  - Gemini: smart `gemini-3.5-flash`, fast `gemini-3.1-flash-lite` (무료 등급, 429 시 다음 제공자).
  - xAI: smart `grok-4.3`, fast `grok-4-1-fast-non-reasoning`.
- 출력은 JSON만. 파싱은 기존 `catalog._parse_json`식 바깥 중괄호 구제 + pydantic 검증. 실패 시 같은 제공자 1회 재시도 후 다음 제공자.
- 모든 호출의 제공자·모델·토큰·소요시간을 `quests/<slug>/log.jsonl`에 기록 → 비용 추정.
- 전부 실패 → `ThinkUnavailable` → 러너가 과제를 `quests/<slug>/tasks/<task_id>.json`(kind, system, user, schema, created_at)으로 저장하고 상태 `waiting_thinker`.
- 외부 사고자(Clair)가 `POST /quests/{slug}/tasks/{task_id}`로 JSON을 내면 같은 검증을 통과시키고 러너를 재개한다. **같은 과제 규격을 모델과 사람이 공유**하는 것이 이 설계의 핵심.
- **세션이 없어도 스스로 재시도한다 (Clair의 결정, 빌더 검토 반영).** 서버의 가벼운 스케줄러 스레드가 `THINK_RETRY_MINUTES`(기본 30)마다 `waiting_thinker` 퀘스트의 열린 과제를 제공자 사슬로 다시 시도한다(무료 한도가 풀리거나 크레딧이 충전되면 저절로 이어짐). 최대 `THINK_RETRY_HOURS`(기본 48). 기다린 시간은 30분 실행 예산에 넣지 않는다(예산은 실제 계산 시간). Clair 세션이 열려 있으면 기다리지 않고 바로 대행한다. 세션 시작 규칙(프로젝트 `CLAUDE.md`)에 "진행 중·대기 중 퀘스트 확인"을 넣어, 다음 세션에서 CR에게 결과나 대기 사유를 먼저 보고한다.
- `/catalog/learn`(기존 분류 큐)도 `think()`로 갈아탄다 → 대기 1,085건을 Gemini 무료 경로로 비운다.

### 5.3 퀘스트 러너 `brain/quest.py`

- 저장: `/data/quests/<slug>/quest.json`(스펙·상태·단계별 결과 요약), `log.jsonl`, `tasks/`, `sources.json`(출처 장부), `days/day-N.json`(점 카드 데이터). 수집 원문은 **기존 책 구조 재사용**: `books/<quest-slug>/raw/*.md` (frontmatter에 url·kind·connector·score·dot·lang) → 기존 catalog 큐·FTS·서재에 그대로 올라탄다.
- 슬러그: `quest-YYYYMMDD-<slugify(제목)>`. 같은 문장을 다시 말하면 새 퀘스트가 아니라 기존 퀘스트 링크를 돌려준다(제목 정규화 일치 시).
- 실행: FastAPI 백그라운드 스레드 1개(단일 인스턴스). 단계마다 `quest.json`에 체크포인트 → 서버 재시작 후 `POST /quests/{slug}/resume`로 이어서. 러너 시작 시 `running` 상태였던 퀘스트는 자동 재개.
- 상태: `queued → planning → collecting → classifying → teaching → bridging → archiving → done`, 어느 단계에서든 `waiting_thinker` 또는 `failed(reason)`.
- 예산 가드(퀘스트당 기본): 생각 호출 ≤ 40, 수집 자료 ≤ 45건, 자료 1건 본문 ≤ 60k자, PDF ≤ 40쪽, 총 실행 ≤ 30분. 초과 시 그 단계는 있는 것으로 마무리하고 장부에 기록.

### 5.4 1단계 plan — 퀘스트 설계도 (생각)

입력: CR 문장 + 볼륨에 이미 있는 관련 자료 제목 20개(FTS) + 이미 아는 개념 목록(그래프에서 관련 20개).
출력 스키마 `QuestPlan`:
```
kind: skill | topic | question          # 헬리콥터=skill, 양자×줄기세포×노화=question
title_ko, title_en, one_line_goal       # "7일 뒤 CR은 ~를 설명할 수 있다"
honesty: { learnable_by_reading: [...], needs_practice: [...], hype_warning: [...] }
prerequisites: [concept]
days: [ { n, big_idea, dots: [ { concept_ko, concept_en, why_one_line,
          queries: { ko: [...], en: [...] }, prefer_kinds: [official|encyclopedia|paper|textbook|video|web],
          evidence_grade_hint } ] } ]   # 하루 3~5점, 합계 20~35점
special_sources: [ { name, url?, why } ] # 연결기 목록 밖의 특별 출처 시도 (FAA 핸드북, 법령, Khan Academy 등)
bridge_hints: [ { domain_or_concept, why_might_connect } ]
```
규칙(프롬프트에 고정): 개념명은 정규형(canonical) 한국어 + 영어 병기. question 종류는 반드시 "주장 사슬"을 점으로 쪼개고 각 점에 증거 등급 힌트를 단다. 7일 구조는 "큰 그림 → 부품 → 원리 → 실제 → 위험·한계 → 연결 → 종합"을 기본 뼈대로 하되 주제에 맞게 바꾼다.

### 5.5 2단계 collect — 수집 (자동) · "NotebookLM보다 나은 점"

NotebookLM은 사용자가 넣은 자료만 본다(+웹 발견 버튼). 우리는 **점마다 자동으로 찾고, 종류 할당량을 채우고, 점수로 고르고, 전문을 영구 저장하고, 왜 골랐는지 장부를 남긴다.**

연결기 인터페이스 `brain/connectors/base.py`:
```
search(query, lang, limit) -> [Candidate{url, title, kind, snippet, year, authority, connector, extra}]
fetch(candidate) -> Doc{text, title, lang, meta}   # 실패 시 None, 사유 기록
```
v1 연결기(모두 키 없음 또는 이미 있는 키):

| 연결기 | 역할 | 비고 |
|---|---|---|
| `wikipedia` | ko/en 검색·전문·링크(이웃 개념) | 기본 백과 1건/점 |
| `wikidata` | 개념 정규 ID(QID)·다국어 라벨·상위 개념(P279) | 그래프 정규화에 사용 |
| `openalex` | 논문 검색, 인용수, OA PDF | 학술 기본 |
| `arxiv` | 물리·CS·수학 프리프린트 | https |
| `pubmed` | 생의학 초록 | 줄기세포·노화에 필수 |
| `semanticscholar` | 보조(429 시 건너뜀) | 키 없음 |
| `ddgs` | 일반 웹(kr-kr, wt-wt) | 불안정 → 결과 0이면 조용히 통과 |
| `xai_search` | 웹 발견(URL 목록 요청) | XAI 키 있을 때만, 점당 1회 |
| `webpage` | 임의 URL 본문(trafilatura), PDF(pymupdf ≤40쪽) | special_sources·발견 URL 수집 |
| `youtube` | 발견된 유튜브 URL의 자막 | 실패 잦음, 선택 |
| `vault` | 우리 볼륨 FTS(기존 책·노트북LM·수업 페이지) | **vault-first 규칙** |

점수 `score = kind_w × lang_w × recency_w × dup_penalty` — kind_w: official/standard 1.0, textbook/encyclopedia 0.9, paper 0.9×(1+log10(인용+1)/4), video 0.6, web 0.5, forum/blog 0.4. 할당량(점당, 가능할 때): 백과 ≥1, 논문 또는 공식 문서 ≥1, 한국어 ≥1, 영상 ≤1, 총 ≤4. 중복: URL 정규화 + 제목 유사도(≥0.9).
출처 장부 `sources.json`: 자료별 {url, kind, connector, score, dot, why_picked, fetched(ok/실패 사유)} + 연결기별 시도/성공 수 + `special_sources` 시도 결과(usefulness). 지도 페이지에 "이번에 새로 시도한 출처" 섹션으로 노출(source-expansion-autonomy 규칙).

### 5.6 3단계 classify — 분류·정규화 (생각, 묶음)

- 기존 `CATALOG_SYSTEM` 카드(제목·요약·도메인·태그·개념·고유명사)를 유지하되 **5건 묶음 1호출**로 비용 1/5. 출력에 `field_code`(5.8 분류표 코드)와 `concept_pairs`(ko/en) 추가.
- 개념 정규화 `brain/canon.py`: 별칭표 → 그래프 기존 라벨 일치 → Wikidata 검색(ko→en, 라벨/별칭 근접 일치 시 QID 채택) → 새 노드. 정규화 결과는 `aliases`에 누적되어 다음부터 즉시 일치.
- 그래프 upsert: 자료 노드(`source`) + 개념 노드 + 간선 `about`(source→concept), `in_book`(source→quest/book), 개념 공출현 `related`(가중치 누적).

### 5.7 4단계 teach — 수업 (생각, 하루 1호출)

입력(하루치): 그날 점 목록 + 점별 상위 발췌(FTS로 자료에서 뽑은 400자 × 3) + 어제 점 요약 + 다리 후보(5단계 전이면 plan의 bridge_hints) + 레벨 규칙.
출력 스키마 `DayLesson`:
```
big_idea_one_line, story_opening(3~5문장, 음악·일상 비유 환영)
dots: [ { concept_id, one_line, picture_svg(간단 inline SVG, 없으면 emoji), analogy, real_example,
          why_it_matters, evidence_grade: 확립됨|연구중|추측|상술, sources: [url...] } ]
quiz: [ { q, a, why } ] × 3            # 클릭해서 정답 보기
say_it_yourself: "내 말로 설명해 보기" 질문 1개
link_yesterday: 2~3문장
clair_one_liner
```
초등 규칙(프롬프트 고정, memory 보정 반영): 수식·기호 금지, 전문용어는 바로 옆에 일상 그림으로 풀기, 한 문장 한 생각, 짧은 문장, 섹션마다 "한 줄 요약". 의심스러우면 더 쉽게.
렌더: `quest_day.html.j2`(점 카드 그리드, `<details>` 퀴즈, 증거 등급 배지, 원문 링크, "어제와 잇기", "다른 때 배운 것과 잇기"(5단계 후 채움), "클레어의 한마디") + `quest_index.html.j2`(목표 한 줄, 정직 상자 "읽어서 되는 것/몸으로 해야 하는 것/과장 주의", 7일 지도(세로 경로 SVG), 진행 체크, 출처 장부, 다리 목록). 공용 `brain.css` 확장(모바일 우선, 다크 모드 토큰 유지). 레벨은 `profile/levels.json`에 `quest:<slug>`로 저장, 기본 초등 한 레벨만. `POST .../rerender?level=일반`으로 다시 생성.

### 5.8 20년 프레임 — 분류표·그래프 `brain/frame.py`, `brain/graph.py`

**분류표(backbone)** `brain/frame/taxonomy.json` (저장소에 버전 관리, 추가만 허용, 코드 재사용 금지, 병합은 `deprecated_to`):
- 1단계 17개 영역(코드 한 글자): A 수학 · B 물리·우주 · C 화학·재료 · D 생명·의학 · E 지구·환경 · F 기술·공학 · G 정보·컴퓨팅 · H 인간·마음·뇌 · I 사회·경제·경영 · J 역사·고고 · K 철학·종교 · L 언어·문학 · M 예술·음악 · N 생활·건강·운동 · O 동물·반려 · P 법·정치·교육 · Z 메타(학습법·도구·2nd BRAIN 자체)
- **동결 규칙의 정확한 뜻 (Clair의 결정, 빌더 검토 반영):** "코드를 재사용하지 않는다"이지 "다시 배치할 수 없다"가 아니다. 2단계 분야는 빌더가 Dewey/UDC·OpenAlex 개념 상위 계층을 참고해 영역당 6~10개(총 ≈130)를 초안으로 넣고 `taxonomy.json`에 `status: draft`를 표시한다. 잘못 나눈 분야는 `deprecated_to`로 새 코드로 보내고, 노드의 `field_code`는 마이그레이션 한 줄(`UPDATE ... WHERE field_code=old`)로 옮긴다. 개념은 Wikidata QID와 원래 `domain`도 함께 갖고 있어 재배치 근거가 남는다. CR 검토 뒤 `status: v1`로 바꾼다(§10).
- 2단계 분야(영역당 6~10개, 코드 `B3` 식) 초기 씨앗을 넣는다(예: B1 고전역학, B2 열·통계, B3 전자기, B4 양자, B5 상대성·우주, B6 유체·음향 …; F1 기계, F2 항공·우주공학, F3 전기전자, F4 토목·건축 …; D1 세포·분자, D2 유전, D3 생리·해부, D4 의학·치료, D5 노화·장수 …).
- 3단계 이하는 열림: 개념 노드가 분야 코드에 매달린다. 기존 `DOMAINS`(과학·역사·…)는 호환 매핑표로 유지.
- **외부 닻:** 가능하면 개념마다 Wikidata QID. 언어·시대에 독립적인 20년짜리 식별자. 없어도 동작.

**그래프 저장** (`brain.db` 테이블 + 진실은 `graph/events.jsonl` 추가 전용 로그, `brain rebuild`로 DB 재생성):
- `nodes(id PK, kind, label_ko, label_en, wikidata, field_code, summary, created_at, updated_at)` — kind: concept, source, lesson, quest, book, person, place, work, question
- `aliases(alias PK, node_id)`; `node_tags(node_id, tag)`; `edges(src, dst, rel, weight, reason, evidence, created_at, PK(src,dst,rel))`
- rel: `is_a, part_of, requires, related, bridge, contradicts, cites, about, in_book, taught_in, asked`
- 노드 id = 정규형 슬러그(영구). 병합 시 `redirects(old_id → new_id)`; 모든 조회는 리다이렉트를 따른다.

**임베딩**: Gemini `gemini-embedding-001`(768) → `sqlite-vec` 테이블 `node_vec`(개념 라벨+요약), `chunk_vec`(자료 800자 청크). 실패해도 파이프라인은 계속(FTS·그래프만으로 동작). Anthropic 임베딩이 없으므로 Gemini 고정(Clair의 결정); 키 없으면 건너뜀.

**꺼내기 방법 4가지**: 태그/분야 코드(`GET /graph?field=B4`), 전문검색(FTS5, 기존 `/search` 확장: 자료·수업·개념 통합), 벡터 유사도, 그래프 이웃(`GET /graph?center=<id>&depth=2`). `brain/retrieve.py`가 RRF(역순위 융합)로 합친다 → `/ask`와 teach 단계가 공용.

**5단계 bridge — 점-대-점 다리**: 새 개념마다 후보 = 같은 노드(정확 일치) ∪ 별칭 일치 ∪ 같은 2단계 분야 ∪ Wikidata 상위 1홉 공유 ∪ 벡터 상위 5(다른 퀘스트/책 소속만). 후보를 생각 1호출(퀘스트당 묶음)에 넘겨 "진짜 이어지는가, 어떤 관계(rel)인가, 한 줄 이유"를 받아 `bridge`/`requires`/`is_a` 간선으로 저장(증거 = 양쪽 자료 id). 결과는 (a) 그날 수업의 "다른 때 배운 것과 잇기"에 재렌더, (b) 지도 페이지의 다리 목록, (c) 그래프 뷰 강조. 억지 다리는 거절해도 된다고 프롬프트에 명시(정직성).

**다리는 퀘스트 단계가 아니라 독립 서비스다 (Clair의 결정, 빌더 검토 반영).** `brain/bridge.py`의 `rebridge(node_ids)`는 세 곳에서 불린다: (a) 퀘스트 5단계, (b) `/catalog/learn` 묶음이 새 개념을 만들 때마다(그 개념들만 대상), (c) 수동 `POST /graph/rebridge`(전체 또는 분야). 새 다리가 과거 퀘스트의 개념을 건드리면 그 퀘스트의 해당 day 페이지와 지도 페이지를 다시 렌더한다(수업 HTML은 `days/day-N.json` 데이터에서 재생성하므로 생각 호출 없이 가능). 그래서 "헬리콥터를 먼저 배우고 양자역학을 나중에 분류해도" 다리는 사후에 생긴다.

**노드 id 규칙 (Clair의 결정).** 개념 id = `slugify(영어 정규 라벨)`(ASCII, 언어 중립), 영어 라벨이 없으면 `slugify(한국어 라벨)`. Wikidata QID는 속성이자 별칭(`wd:Q215675`)으로도 저장해 QID로도 찾는다. **동명이의어**: 정규화 때 QID가 다르거나 1단계 영역이 다르면 다른 개념으로 보고 id 뒤에 분야 코드를 붙인다(`spin` 물리 = `spin`, 운동의 spin = `spin-n3`; 먼저 생긴 쪽이 접미사 없음). Obsidian 파일명은 한국어 라벨, 충돌 시 분야 코드 접미사, frontmatter에 id.

**Obsidian 내보내기** `GET /vault.zip`(토큰): `vault/<영역>/<분야>/<개념>.md`(frontmatter: tags, wikidata, field, aliases; 본문: 요약 + `[[개념]]` 링크 + 자료·수업 링크), `vault/퀘스트/<quest>/day-N.md`, `vault/자료/<source-id>.md`. CR이 Obsidian에서 열면 그래프 뷰가 그대로 보인다.

**웹 그래프 뷰** `site/brain/index.html`(정적, d3-force cdnjs): 영역별 색, 태그·영역 필터, 검색, 노드 클릭 → 옆 패널(요약·자료·수업·다리), 다리 간선은 점선 강조. 데이터는 `GET /graph/full?limit=2000`.

### 5.9 질문 답하기 `/ask` (RAG)

`POST /ask {q, mode: auto|vault|web}` → `retrieve`(FTS+벡터+그래프 이웃, RRF) → 모드 auto면 볼륨 히트가 약할 때만 연결기 웹 보강 → 생각 1호출로 인용 포함 답(JSON: answer_html, citations[], used_vault_ratio) → 질문을 `question` 노드로 기록(간선 `asked`→개념). Clair는 세션에서 이걸 먼저 부르고, 부족하면 자기 WebSearch로 보강한다(vault-first 규칙 코드화).

### 5.10 보관·갱신 (6단계 archive)

- 수업 HTML·점 카드 JSON·출처 장부는 전부 볼륨(`quests/`, `site/quests/`)에 남고, 수업 페이지는 `lesson` 노드로 그래프·FTS에 올라간다(= "클레어-학습페이지" 규칙을 구조적으로 충족).
- 서재(`site/index.html`)에 "퀘스트" 구역 추가, `site/brain/` 그래프 페이지 갱신, `index.rebuild()`.
- 볼륨 레이아웃 추가분:
```
/data/quests/<slug>/{quest.json, log.jsonl, sources.json, tasks/, days/}
/data/graph/events.jsonl           # 진실(append-only)
/data/site/quests/<slug>/{index.html, day-N.html}
/data/site/brain/index.html
/data/brain.db                     # FTS + 그래프 테이블 + sqlite-vec (재생성 가능)
```

## 6. 비용·운영

- Claude 경로 추정(7일 퀘스트): plan 1 + classify 9(45건/5) + teach 7 + bridge 1 = 18 호출, 입력 ≈ 150k·출력 ≈ 40k 토큰 → Sonnet 5.5 기준 약 $0.6~1.0. Gemini 무료 경로 ≈ $0(일일 한도 내). xAI 검색은 점당 1회 ≤ 35회.
- 일일 상한 `THINK_DAILY_CAP`(기본 200 호출) — 초과 시 `waiting_thinker`로 전환(멈추지 않고 Clair에게 넘김).
- Railway 환경변수 추가: `GEMINI_API_KEY`, `XAI_API_KEY`, `THINK_PROVIDERS`. 배포 `railway up`.
- 대기 1,085건 분류: 배포 후 `/catalog/learn?limit=50` 반복(묶음 5 → 호출 ≈ 220). Gemini 무료 한도 넘으면 다음 날 이어서.

## 7. 테스트 (pytest, 외부 호출은 전부 가짜)

- 분류표 무결성(코드 유일·추가만·deprecated_to 유효), 그래프 upsert/별칭/리다이렉트/재생성, 정규화(별칭→기존→Wikidata 가짜→신규).
- 연결기 각각(가짜 HTTP), 점수·할당량·중복 제거, 본문 수집 실패 내성.
- 러너: 가짜 thinker로 7일 퀘스트 전 과정 오프라인 통과; thinker 전부 실패 → 열린 과제 생성 → 제출 → 재개 → done. 재시작 후 resume.
- 템플릿 렌더(초등 한 레벨, 퀴즈·배지·다리 섹션), 볼트 zip 내용, `/ask` 융합 순위, CLI 인자.
- 기존 테스트 전부 유지.

## 8. 단계별 출시와 수용 실행 (Clair의 결정: 한 번에 다 말고 이정표마다 배포)

| 이정표 | 내용 | 배포 후 확인 |
|---|---|---|
| M1 | `think.py` 제공자 사슬 + config 모델 갱신 + `/catalog/learn`을 think로 전환(묶음 5) | 대기 1,085건이 Gemini 무료 경로로 줄어들기 시작 |
| M2 | 분류표 + 그래프 저장(events.jsonl·DB·rebuild) + 정규화(canon) + catalog→그래프 upsert | `/catalog/stats`의 concepts > 0, `GET /graph?center=` 동작 |
| M3 | 연결기 11종 + 점수·할당량·중복 제거 + 수집기 | 한 점(dot)에 대해 오프라인 테스트 + 실서버 1회 수집 |
| M4 | 퀘스트 러너(plan·collect·classify·teach·archive) + 과제 프로토콜 + 재시도 스케줄러 + 템플릿 + CLI + 스킬 + 프로젝트 CLAUDE.md | **수용 1:** "나 헬리콥터 운전 배우고 싶어" → done, 지도+7일 페이지 |
| M5 | bridge 서비스(퀘스트 단계 + catalog 후크 + 수동) + 영향 페이지 재렌더 | **수용 2:** 양자역학 97건 분류 완료 상태에서 헬리콥터 ↔ 양자 다리 간선 + 이유 확인 |
| M6 | retrieve(RRF) + `/ask` + `vault.zip` + 그래프 뷰 + 서재 퀘스트 구역 + README·NEXT·메모리 | **수용 3:** "양자역학 × 줄기세포 × 노화" question 퀘스트 → 증거 등급 분리; Obsidian zip 열림 |

순서 메모: 수용 2는 **분류 백로그(양자역학 포함)를 먼저 비운 뒤** 다리를 확인한다. 다리는 독립 서비스라 순서가 바뀌어도 사후에 생긴다(5.8).

## 9. 빌더에게 맡기는 것

- 모듈 내부 구조와 함수 분할, 스레드/큐 구현 세부, 템플릿의 세부 시각 디자인(단, 5.7의 섹션 구성과 브랜드 토큰은 지킨다), 연결기별 재시도·타임아웃 값, 점수 가중치의 미세 조정, 테스트용 가짜 서버 방식.

## 10. 미해결 — CR 확인 필요 (돌아오면)

1. xAI 유료 검색을 켜 둘지(소액이지만 과금). 기본은 **켬**(점당 1회 상한).
2. Anthropic 크레딧 충전 시점. 충전 전까지 수업 품질은 Gemini 3.5 Flash 또는 Clair 대행 기준.
3. 7일 기본값 유지? ("하루아침" 북극성에 맞춰 `--days 1` 압축 모드도 지원함.)
4. 분류표 2단계(≈130개 분야) 초안 검토 → `status: v1` 승인. 승인 전에도 코드는 쓰이지만 재배치는 가능(5.8).
5. 수업 페이지(`/site/**`)를 "링크 아는 사람만"에서 "토큰 필요"로 올릴지. 지금은 Phase 0과 같음.

## 11. 빌더 검토에서 Clair가 내린 결정 요약 (CR 확인용)

| 질문 | 결정 |
|---|---|
| 나중에 분류된 개념과도 다리가 생기나 | 예. bridge는 독립 서비스, catalog 학습 때마다 새 개념만 대상으로 돌고 과거 페이지를 재렌더 |
| 노드 id는 무엇의 슬러그인가 | 영어 정규 라벨(없으면 한국어). QID는 속성+별칭. 동명이의어는 분야 코드 접미사 |
| 제공자 전부 실패 + 세션 없음 | 30분마다 자동 재시도(최대 48시간). 세션 있으면 Clair 즉시 대행 |
| 공개 범위 | 데이터 API 토큰 필수, 정적 페이지는 기존처럼 링크 공개+noindex |
| 한 번에 출시? | 아니오. M1~M6 이정표마다 배포·확인 |
| 분류표 동결 | 코드 재사용 금지일 뿐 재배치 가능. 초안 `draft`, CR 검토 후 `v1` |
