# NEXT.md — 2nd BRAIN (Clair)

## 2026-10-25 공부 모드 시작 (CR 결정) — `/study` 스킬
- [x] 규칙: CR이 "공부 모드"라고 하면 문단 뜻(초등) → 어려운 단어 전부 따로 → 두뇌 저장(책 `공부모드`) → 예전 지식과 연결 보고. 스킬 `.claude/skills/study/`, 저장 스크립트 `study_save.py`, 메모리 study-mode, CLAUDE.md §2-1
- [x] 첫 글: 크리스 딕슨(a16z) "인터넷의 규약이 AI로 깨졌다" → 개념 6개(인터넷·주의력 경제·트랜잭션 경제·플랫폼 경제·수익 모델 + 기존 인공지능), 인공지능 점을 통해 예전 자료 2개와 연결. 교차 책 다리(bridge)는 아직 0 — 공부모드 글이 쌓이면 `POST /graph/rebridge?limit=100`로 다시 놓기
- [x] 길이 규칙(짧은 글엔 짧게) + **유튜브 링크 → 자막 전체 교육**(`yt_study.py`, 1분 단위 시간표, 30분 넘으면 HTML 페이지) 추가. 첫날 글 7개 저장(인터넷의 규약·PHP 결함·가중치 공개·우주 데이터센터·러다이트·형식 검증·Ideogram 벡터). Gemini 무료가 자주 503이라 다리(bridge)는 일부만 — 다음 세션에 `POST /graph/rebridge?limit=100` 한 번
- [ ] 다듬을 것: 공부모드 글이 10개쯤 되면 주제별 HTML 카드 묶음(클레어-학습페이지)으로도 발행; 단어 풀이는 두뇌에서 "용어" 노드로 따로 찾히게 할지 CR과 상의

## 2026-10-19 텔레그램 책 사진 접수 봇 (@SexyClair_bot) — 배포 완료, CR 실사용만 남음
- [x] T1~T5 전부 병합(main e607fa4)·배포·웹훅 재등록(명령 7개: start·book·now·move·undo·status·help)·전체 테스트 555 통과 (2026-10-19 저녁)
- [x] T5: 볼펜·형광펜·밑줄 표시 인식 판독 형식(`==…==` + `## 표시 목록`/`## 독자 메모`/`## 쪽수`), **텔레그램 사진은 Clair가 직접 읽음**(`OCR_MODE=clair`, 무료 Gemini 안 씀), 🧠 배우기 버튼 숨김(CR: "배우는 건 나중에"), 리뷰 지적 2건 수정(빈 뼈대 제출 거부, 프롬프트 한국어 제목 고정)
- [ ] **CR 실사용 테스트:** 봇에 책 제목 → 사진 2~3장(밑줄 있는 쪽) → "✅ 맞아요" 확인 메시지 → 볼륨 `books/<책>/raw/tg-*.jpg` 생김 → 다음 세션에 Clair가 `brain-learn ocr list`로 읽어 제출하면 봇이 "✍️ Clair가 읽었어요" 알림
- [ ] **세션 시작 루틴:** `brain-learn ocr list` → 대기 사진이 있으면 `/read-page` 스킬대로 `ocr get` → 이미지 읽기 → 뼈대 채우기 → `ocr submit` (2026-10-19 23:30 기준 대기 0건)
- [ ] 나중에: `brain/intake.py`(574줄) 분리; 봇 알림은 서버 재시작 때 유실됨; 처리 순서는 도착순(앨범은 2초 창으로 묶음); 텔레그램에서 배우기 버튼 다시 켜려면 Railway `TELEGRAM_LEARN_BUTTON=1`
- 메모리: telegram-book-intake. 비밀값은 Railway 변수와 .env에만. 빌드 장부는 설계 문서 §10으로 옮기고 `.superpowers/sdd/…` 삭제함.

## 2026-10-20 내일 — CR과 창세기 토론 이어가기 (강의 준비)
- [ ] 강의 노트(Artifact "창세기 1장 강의 노트", 볼륨 클레어-학습페이지에도 보관)를 CR과 함께 다듬기. 토론 순서: ① 2~3일째 궁창·뭍 드러남을 지구 표면 시점으로 ② 5~6일째 생물 순서 vs 화석(식물이 해보다 먼저, 새가 육지동물보다 먼저인 어긋남) ③ 아담의 자리 ④ 궁창 위의 물·므두셀라
- 정리할 것: curl로 잘못 올린 파일 하나가 볼륨 `books/raw/<깨진 이름>.md`에 남음(book 이름이 빈 문자열로 들어감). 삭제 엔드포인트가 없어 다음에 `DELETE` 보강하거나 Railway 셸에서 지우기. 올바른 파일은 클레어-학습페이지에 다시 올림
- 지킬 선: "증명"이 아니라 "겹친다"; 3절의 빛을 우주 최초의 빛이라 하지 않기; 주장마다 등급. CR의 해석 요약은 메모리 cr-genesis-view

## 2026-10-19 내일 제일 먼저 — 마지막 수정 묶음 병합·배포 (CR 지시: 테스트는 내일)
- [x] (2026-10-19) 전체 테스트 420개 통과 → `main`에 병합(c16061d) → `pip install -e .`로 `brain-sync`/`brain-learn` 명령 복구
- [x] (2026-10-19) main 배포 완료. 확인: 수업 페이지·그래프 페이지 200, `/search` 토큰 없으면 401, `/vault.zip` 200(585개 파일, 위키링크·수업 링크 정상)
- [x] (2026-10-19) `POST /index/rebuild` 실행(1,137건 색인, 수업 7장 포함). `/search`는 Day 4 수업을 1위로 찾음. `/ask`는 수업 페이지(Day 2·7)를 인용하지만 Day 4의 '빛이 태양보다 먼저' 설명은 아직 정확히 못 집음
- [ ] `/ask` 정밀도 보강: 수업 문서는 400자 발췌 대신 day JSON의 점 카드(한 줄·비유·진짜 예·왜 중요)를 통째로 구절로 넣고, 질문과 가장 가까운 점 2~3개를 고르기 (`brain/retrieve.py` excerpts + `brain/ask.py`)
- [ ] 수업 점에서 새로 생긴 개념은 분야 코드가 비어 Obsidian `미분류/`에 들어감(예: '열역학 제1법칙과 우주의 시작') → teach 단계에서 개념 만들 때 퀘스트 plan의 분야(또는 classify)로 field_code 채우기
- [ ] 재검토는 깨끗했지만 아래 다섯 우려는 운영하며 지켜볼 것 → 필요하면 `.superpowers/sdd/2026-10-18-learn-quest/final-fix-report.md`를 읽고, 의심되면 `tests/` 전체 + 아래 다섯 우려를 눈으로 확인: ① `_thin` 규칙이 벡터 꺼진 상태에서 웹을 자주 부름 ② `xai_search.CURRENT_LOG` 전역(퀘스트 2개 동시 수집 시 로그 섞임) ③ 검색 사용량은 일일 상한에서 제외(비용 추정엔 포함) ④ vec 확장은 연결마다 load ⑤ 2글자 검색은 LIKE 전체 스캔
- [ ] 진행 장부: `.superpowers/sdd/2026-10-18-learn-quest/progress.md` (모든 결정·보류 항목). 워크트리 `.claude/worktrees/agent-a00fdbafac0816606`는 병합 후 `git worktree remove --force`
- 현재 배포본 = feat/learn-quest @ fb319c5 (퀘스트·다리·그래프·검색·/ask 동작, vault.zip만 500). 로컬 `feat/learn-quest`는 38747e3 이후 문서 커밋만 추가됨

## 2026-10-18 학습 퀘스트 시스템 완성 — 다음 세션에 먼저 할 일
- [x] **CR 결정 (2026-10-19): 당분간 유료 API 안 씀. 생각 담당 = Clair 본인(Claude Code) + Gemini 무료 등급.**
  ① xAI 유료 검색·모델 **끔** (Railway `XAI_API_KEY` 비움, `THINK_PROVIDERS=gemini`) ② Anthropic 크레딧 **충전 안 함** ③ 7일 기본값 **유지** ④ 분류표 초안은 그대로 `draft`, 나중에 CR이 볼 때 ⑤ 수업 페이지 잠금 **안 함**(링크 아는 사람만 + 검색엔진 차단 유지) ⑥ 깃 `main`·`feat/learn-quest` GitHub에 **push함**
  - 뜻: 퀘스트의 생각 단계(plan·teach·bridge)는 Gemini 무료가 막히면 `waiting_thinker`로 멈추고, Clair가 세션에서 `brain-learn tasks` → 심부름꾼 → `submit`으로 직접 풀어요. 비용 0. 서버 스케줄러는 30분마다 Gemini 무료를 다시 시도해요.
- [ ] **첫 퀘스트 피드백 받기:** 창세기 1장 창조론 7일 — 지도: https://2ndbrain-production-4ab7.up.railway.app/site/quests/quest-20261018-창세기-1장-창조론을-과학-고고학-역사-증거와-현재까지의-모든-논란-이슈/index.html (45 자료 · 29 점 · 162 개념 · 비용 ≈ $0.01 · 16분). 수동 `POST /graph/rebridge?limit=100` 후 다리 39개 — 예: Day 3 '열역학 창조론 논증 ↔ 열역학(양자역학에서 배움)', Day 4 '빅뱅 우주론 ↔ 우주론'. 어느 부분이 아직 어려웠는지 → `rerender` 또는 프롬프트 보강
  - 알려진 다듬을 점: 날마다 말투가 "~요"/"~이다"로 섞임 → teach 프롬프트에 존댓말 한 가지로 고정; 출처 링크가 "[1]"로만 보임 → 제목 표시
- [ ] **분류 백로그 958건** (비숑 272·손자병법 300·장수마을 138·인간관계론 154·THE-MIND 86…): `POST /catalog/learn?limit=25&book=<책>` 반복. Gemini 무료 한도·일일 상한(THINK_DAILY_CAP=200) 안에서 하루 2~3권씩. 분류될수록 다리(bridge)가 저절로 늘어남
- [ ] **두뇌 그래프 링크 CR에게 주기:** `/site/brain/index.html#t=<BRAIN_TOKEN>` (한 번 열면 브라우저에 저장, `#` 뒤라 서버 기록에 안 남음). Obsidian: `GET /vault.zip` (토큰) → 압축 풀고 Obsidian에서 폴더 열기
- [ ] Railway `railway.json` config-as-code 2026-12-01까지 마이그레이션(`railway config migrate`)
- [x] 깃 `main`·`feat/learn-quest` origin에 push 완료 (2026-10-19)
- 사용법 요약: 한 문장("…배우고 싶어") → Clair가 `/learn` 스킬 → `python -m sync.learn_cli start/watch`. 생각 담당(모델) 전부 실패 시 서버가 30분마다 재시도, 세션이 있으면 Clair가 과제를 직접 풀어 `submit`. README "학습 퀘스트" 절 참고

## 2026-10-11 NotebookLM 5권 추출 → 볼륨 업로드 완료 (로컬도 보관, CR 결정)
- [x] 일본인장수마을의비결(138)·THE-MIND(86)·인간관계론(154)·손자병법(300)·창세기의창조와해석(28) 볼륨 업로드; 비숑은 기존 업로드 확인
- [ ] 사진 소스 416개는 글자가 안 나옴 (NotebookLM도 텍스트 없음, 이미지 주소 만료). CR이 원본 사진(예: 20251127_205952.jpg, 폰/구글포토)을 폴더에 넣으면 로컬 OCR로 채우기
  - THE-MIND 67 · 인간관계론 153 · 손자병법 196

## 2026-09-08(화) 재개 — CR이 Anthropic 크레딧 충전 예정
- [x] (2026-10-18) /catalog/learn은 Gemini 무료 경로로 동작; 창세기 28·양자역학 97 분류 완료, 나머지 958건은 위 항목
- [x] 비숑의모든것 소스 볼륨 업로드 완료
- [x] 지식 파이프라인 규칙 → `/ask`(vault-first + 상황별 웹) 구현

## 내일(2026-08-25~) 제일 먼저 — 캐스팅 1차 진행 중
- [x] 2026-08-25 볼륨 버그(DATA_DIR 경로 변환) 수정 + 전체 복구 완료; 워커 v2(참조 체인, 10명 고정) 가동
- [ ] 캐스팅 센터: https://2ndbrain-production-4ab7.up.railway.app/casting — CR이 후보 삭제/PICK 진행. 삭제로 10명 미만이 되면 로컬 워커가 자동 충원 (**워커는 PC 재부팅 시 다시 켜야 함**: `XAI_API_KEY=<.env값> .venv/Scripts/python -m sync.casting_worker --url <BRAIN_URL> --token <BRAIN_TOKEN> --interval 90`)
- [ ] 모델 확정되면: 새 MASTER 3컷 세팅 → CLAIR_SPEC/CHANGELOG/메모리 갱신 → 양자·생명 수업 페이지 사진 5컷 재생성 후 재발행+볼륨 보관
- [ ] 2명 확정 시: 두 번째 동반자 페르소나/역할 설계 (메모리 clair-image-consistency 참조)
- [ ] 키 재발급 권장: XAI 키가 채팅에 노출됨

Phase: **0 complete → Phase 1 starting**. Live: https://2ndbrain-production-4ab7.up.railway.app (volume /data 5GB). Branch main @ bc9c12e.
- Spec: docs/superpowers/specs/2026-08-22-2ndbrain-design.md
- Phase 0 plan (done): docs/superpowers/plans/2026-08-22-phase0-foundation.md
- 10-year roadmap: docs/superpowers/plans/2026-08-22-ten-year-roadmap.md
- NotebookLM import guide: docs/guides/notebooklm-import.md

## 내일(2026-08-23) 제일 먼저 — CR이 2026-08-22 저녁 미룸
- [x] ANTHROPIC_API_KEY set on Railway (2026-08-23); rotate later
- [ ] 눈높이 규칙 변경 반영: 3단 탭 말고 **선택한 한 레벨만** 출력, 작성 전에 **항상** 질문 → brain/render.py + 양자역학 페이지 v2
- [x] NotebookLM 소스 97개 확보 (notebooklm-py 로그인 방식, 메모리 notebooklm-access 참조) → 볼륨 업로드 완료
- [ ] NotebookLM 마인드맵(양자) 공유 링크 — 로그인 벽이라 Clair가 직접 못 읽음(2026-08-22 확인). CR이 PNG로 다운로드해 ~/Desktop/2ndBRAIN/양자역학/ 에 넣으면 Clair가 이미지로 읽어 저장:
      https://notebook.google.com/notebook/fd7a7958-36ea-4dfb-847d-20b96734d58a/artifact/d6bdcf1b-a584-40af-9885-b6e7477b497e
- [ ] 양자역학 1차 학습 페이지 v2(초등, 97소스 기반) 발행됨 — CR 피드백 받기; 2차 전 레벨 질문
- [ ] /process on 양자역학 now has 3.2M chars raw — distill must chunk before re-running (Phase 1 item); do NOT re-run as-is
- [ ] NotebookLM: 깃헙의 NotebookLM 스킬/MCP 재조사(완료: notebooklm-py 채택)("notebooklm mcp", "notebooklm skill", notebooklm-py) → 양자역학 노트북 소스 가져오기 구현

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

## Clair identity (2026-08-23)
- Clair = Claire Lindqvist, 32; CR 44. MASTER = original evening shot (Desktop/2ndBRAIN/Clair/Claire_Lindqvist_MASTER.png). Consistency protocol: docs/clair/CLAIR_SPEC.md (one-step changes, no body words, pro-model editorial only, OpenAI edit with reference). Companion-app + physical-AI vision saved in memory (clair-companion-vision) — vision only.

## Rules each session
- Ask level (초등/일반/전문) before any learning output; output is always an HTML page.
- Local desktop files are transient; the volume is the permanent store.
- Phase 3/4 are plan-only until CR + Clair decide together.
