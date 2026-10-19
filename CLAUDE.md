# 2nd BRAIN — 프로젝트 규칙 (Clair용)

전역 규칙(`~/.claude/CLAUDE.md`)이 먼저예요. 여기엔 이 프로젝트에만 필요한 것만 적어요.
CR에게 보이는 말은 전부 한국어로 해요.

## 1. 세션을 시작할 때
1. `NEXT.md`를 읽어요.
2. `.venv/Scripts/python -m sync.learn_cli list`로 진행 중·대기 중인 학습 퀘스트를 확인해요.
3. 텔레그램 OCR 대기(`brain-learn ocr list`)가 있으면 Clair가 읽어서 `ocr submit`을 해요. 대기가 있으면 `/read-page` 스킬로 처리해요(밑줄·표시·쪽수까지).
4. 위 내용을 합쳐서 CR에게 먼저 짧게 보고해요. 작업은 그다음이에요.
   - `waiting_thinker` 퀘스트가 있으면 `/learn` 스킬의 "생각 담당" 절차로 바로 이어서 풀어요.

## 2. "배우고 싶어" 문장이 오면
- "…배우고 싶어 / 이해하고 싶어 / 알고 싶어 / 공부하자 / 가르쳐 줘 / 익히고 싶어" 같은 문장이 오면
  **되묻지 말고** `/learn` 스킬을 바로 실행해요.
- 기본값은 **초등 눈높이 · 7일**이에요. 문장 안에 일수("3일 동안")나 레벨("전문가 수준")이
  들어 있을 때만 그대로 반영해요.

## 3. 결과를 보고할 때
지도 링크 · 목표 한 줄 · Day 1 핵심 한 줄 · 예전 지식과 이어진 다리 3개(없으면 "아직 없음") ·
새로 시도한 출처 · 비용 추정 · 걸린 시간. 자세한 양식은 `.claude/skills/learn/SKILL.md`에 있어요.
**퀘스트마다 `cost_estimate`를 꼭 알려요.**

## 4. 로컬에서 CLI 실행
- editable install이 없을 수 있으니 `.venv/Scripts/python -m sync.learn_cli <명령>`으로 실행해요.
  (설치돼 있으면 `brain-learn <명령>`도 같아요.)
- 서버 주소와 토큰은 CLI가 프로젝트 루트의 `.env`(`BRAIN_URL`, `BRAIN_TOKEN`)에서 직접 읽어요. 프로젝트 루트에서 위 명령만 치면 되고, 따로 불러올 필요가 없어요. 토큰을 채팅이나 파일에 적지 않아요.
- 두뇌 그래프 링크는 `/site/brain/index.html#t=<토큰>` 꼴이에요(`#` 뒤는 서버 기록에 남지 않아요). 한 번 열면 브라우저에 저장돼요.
- 명령: `start · status · watch · tasks · submit · list · resume · rerender · ask`
- 종료 코드: 완료 0 · 실패 1 · 사용법 오류 2 · 생각 담당 필요 3.
- 파이썬은 항상 `python`만 쓰고, 콘솔은 `PYTHONIOENCODING=utf-8`로 해요.

## 5. 비용 원칙 (CR 결정 2026-10-19)
당분간 **유료 API를 쓰지 않아요.** 서버의 생각 담당은 Gemini 무료 등급뿐이고(`THINK_PROVIDERS=gemini`), 그게 막히면 퀘스트는 `waiting_thinker`로 멈춰요. 그때는 Clair가 세션에서 `/learn` 스킬의 "생각 담당" 절차로 직접 풀어 제출해요. 새 유료 키를 켜거나 크레딧을 충전하는 일은 CR이 먼저 말할 때만 해요.

## 6. 일하는 방식
작은 수정은 직접 고치고, 큰 공사만 심부름꾼에게 맡기는 전역 규칙을 그대로 따라요.
