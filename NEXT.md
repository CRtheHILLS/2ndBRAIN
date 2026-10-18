# NEXT.md — 2nd BRAIN (Clair)

## 2026-10-18 학습 퀘스트 시스템 완성 — 다음 세션에 먼저 할 일
- [ ] **CR 확인 5가지** (스펙 §10): ① xAI 유료 검색 켜 둘지(현재 켬, 소액) ② Anthropic 크레딧 충전 시점(지금 0 → Gemini 무료 + xAI가 일함) ③ 7일 기본값 유지? ④ 분류표 2단계(156개 분야, `brain/frame/taxonomy.json` status: draft) 검토 → v1 ⑤ 수업 페이지(/site/**)를 토큰 필요로 올릴지
- [ ] **첫 퀘스트 피드백 받기:** 창세기 1장 창조론 7일 — 지도: https://2ndbrain-production-4ab7.up.railway.app/site/quests/quest-20261018-창세기-1장-창조론을-과학-고고학-역사-증거와-현재까지의-모든-논란-이슈/index.html (45 자료 · 29 점 · 162 개념 · 비용 ≈ $0.01 · 16분). 수동 `POST /graph/rebridge?limit=100` 후 다리 39개 — 예: Day 3 '열역학 창조론 논증 ↔ 열역학(양자역학에서 배움)', Day 4 '빅뱅 우주론 ↔ 우주론'. 어느 부분이 아직 어려웠는지 → `rerender` 또는 프롬프트 보강
  - 알려진 다듬을 점: 날마다 말투가 "~요"/"~이다"로 섞임 → teach 프롬프트에 존댓말 한 가지로 고정; 출처 링크가 "[1]"로만 보임 → 제목 표시
- [ ] **분류 백로그 958건** (비숑 272·손자병법 300·장수마을 138·인간관계론 154·THE-MIND 86…): `POST /catalog/learn?limit=25&book=<책>` 반복. Gemini 무료 한도·일일 상한(THINK_DAILY_CAP=200) 안에서 하루 2~3권씩. 분류될수록 다리(bridge)가 저절로 늘어남
- [ ] **두뇌 그래프 링크 CR에게 주기:** `/site/brain/index.html?t=<BRAIN_TOKEN>` (한 번 열면 브라우저에 저장). Obsidian: `GET /vault.zip` (토큰) → 압축 풀고 Obsidian에서 폴더 열기
- [ ] Railway `railway.json` config-as-code 2026-12-01까지 마이그레이션(`railway config migrate`)
- [ ] 로컬: `pip install -e .`를 다시 해 두었음(`brain-sync`, `brain-learn` 명령 사용 가능). 깃 `main`에 병합했으나 **origin에 push는 안 함**(CR 결정 필요)
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
