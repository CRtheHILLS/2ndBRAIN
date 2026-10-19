# 2nd BRAIN

CR의 두 번째 뇌예요. 책이나 자료 사진을 폴더에 넣어두기만 하면, Clair가 알아서 읽고 정리해서
초등/일반/전문 세 가지 눈높이로 요약 페이지를 만들어 드려요. 백업(Phase 1)이 붙기 전까지는
로컬 원본을 지우지 마세요 — 서재 페이지에서 업로드 확인 후에만.

## 폴더 워크플로우

1. 바탕화면에 `2ndBRAIN` 폴더를 만들고, 그 아래에 책마다 폴더를 하나씩 만들어요.

   ```
   ~/Desktop/2ndBRAIN/
     불편한 편의점/
       IMG_001.jpg
       IMG_002.jpg
     사피엔스/
       사피엔스_표지.jpg
       ...
   ```

2. `brain-sync`를 실행해두면 폴더에 새 사진이 들어올 때마다 자동으로 서버에 업로드돼요.
3. 업로드가 끝나면 API로 "처리해줘" 요청을 보내서 정리(distill) + 페이지 생성을 시켜요.
4. `/site/<책이름>/index.html`을 열면 완성된 학습 페이지가 보여요.

폴더 이름 = 책 이름이 돼요 (자동으로 slug로 변환됩니다). 백업(Phase 1)이 붙기 전까지는
로컬 원본을 지우지 마세요 — 서재 페이지에서 업로드 확인 후에만. 서버 볼륨
(`/data/books/<slug>/raw`)에 원본이 보관되고, 정리된 노트는 `/data/books/<slug>/notes`에 남아요.

## brain-sync 사용법

```bash
pip install -e .   # 최초 1회, 로컬 개발 환경에서

# 한 번만 동기화 (새로 추가된 파일만 업로드)
brain-sync --url https://<app>.up.railway.app --token <BRAIN_TOKEN> --once

# 계속 감시하면서 자동 업로드
brain-sync --url https://<app>.up.railway.app --token <BRAIN_TOKEN>

# 감시할 폴더를 바꾸고 싶으면
brain-sync --root "~/Desktop/2ndBRAIN" --url ... --token ...
```

지원하는 파일 형식: `.jpg .jpeg .png .webp .heic .pdf .txt .md`

## 처리 요청 (레벨 선택)

업로드가 끝나면 원하는 눈높이(초등 / 일반 / 전문)로 처리 요청을 보내요. Clair는 항상
먼저 CR에게 어떤 레벨로 만들지 물어봐요.

```bash
curl -X POST -H "X-Brain-Token: <BRAIN_TOKEN>" \
  "https://<app>.up.railway.app/books/<slug>/process?level=초등"
```

## 학습 퀘스트 — 한 문장으로 배우기

Clair에게 "나 헬리콥터 운전 배우고 싶어"처럼 한 문장만 말하면 돼요. 서버가 계획 → 자료 모으기 →
분류 → 수업 만들기 → 예전 지식과 잇기 → 보관까지 알아서 하고, 초등 눈높이 7일 코스를 만들어 줘요.

```bash
brain-learn start "나 헬리콥터 운전 배우고 싶어" [--days 3] [--level 일반]   # 시작 + 진행 지켜보기
brain-learn list                       # 퀘스트 목록
brain-learn status <slug>              # 상태 한 번 확인
brain-learn watch <slug>               # 끝날 때까지 지켜보기 (완료 0 · 실패 1 · 생각 담당 필요 3)
brain-learn tasks <slug> --out DIR     # 기다리는 생각 과제 내려받기
brain-learn submit <slug> <task_id> 답.json
brain-learn resume <slug>              # 멈춘 퀘스트 다시 시작
brain-learn rerender <slug> --level 일반
brain-learn ask "질문"                  # 내 지식 창고에서 먼저 찾아 답하기
```

`--url`/`--token`을 생략하면 환경변수 `BRAIN_URL`, `BRAIN_TOKEN`을 써요. 설치 없이 쓰려면
`.venv/Scripts/python -m sync.learn_cli ...`로 실행해요. 프로젝트 루트에서는 `.env`의 `BRAIN_URL`, `BRAIN_TOKEN`을 자동으로 읽어서 따로 설정할 게 없어요. `--url`/`--token`은 명령 앞에 써요. 예: `brain-learn --url https://<app>.up.railway.app --token <토큰> list`

결과 페이지는 `/site/quests/<slug>/index.html`(지도)와 그 아래 Day 1~7 페이지에 생겨요.

서버에 쓸 수 있는 모델 키가 없으면 퀘스트가 `waiting_thinker`로 멈추는데, 이때는 Clair가
`tasks`로 과제를 받아 직접 풀고 `submit`으로 돌려줘요. 세션이 끊겨도 서버가 30분마다 다시 시도해요.

서버 환경변수: `GEMINI_API_KEY`, `XAI_API_KEY`(생각을 맡길 모델 키), `THINK_PROVIDERS`(쓸 순서, 예: `gemini,xai`).

## 텔레그램으로 책 사진 보내기

텔레그램에서 **@SexyClair_bot**에게 책 사진을 보내면 바로 서재에 쌓여요.

1. 먼저 **책 제목**을 보내요. (예: `코스모스`) 비슷한 책이 있으면 버튼으로 골라요.
2. 그다음 **사진**을 보내요. 여러 장을 앨범으로 한꺼번에 보내도 순서대로 받아요.
3. 메뉴 버튼으로 "다른 책으로 옮기기 / 지우기 / 지금 학습 시작" 같은 일을 할 수 있어요.
   마지막 사진이 틀렸으면 버튼으로 바로 옮기거나 지워요.

규칙:
- 같은 책으로 보는 시간은 **6시간**이에요. 6시간이 지나거나 날짜가 바뀌면 제목을 다시 물어봐요.
- 사진 설명(캡션)에 쓸 수 있어요: `p.123`(쪽수), `#3장`(장), `#태그`. 앨범은 한 장에만 써도 전부에 적용돼요.
- **파일로 보내면** 사진이 압축되지 않아 글자가 더 선명해요.
- 글자 읽기(OCR)는 무료 모델이 해요. 막히면 대기 목록에 쌓이고 Clair가 직접 읽어요.
- 순서: 도착 순서대로 처리해요(대기 중인 것만 번호순 정렬). 앨범은 2초 창이 닫힌 뒤 첫 장 자리에서 한 덩어리로 나가고, 창 뒤에 도착한 사진은 별도 묶음이 돼요.
- 헷갈리면 `/help`.

서버 설정: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_ID`, `TELEGRAM_WEBHOOK_SECRET`, `BRAIN_PUBLIC_URL`.
서버가 켜질 때 웹훅을 자동 등록하고, 수동으로는 `POST /telegram/setup`(토큰 필요)을 불러요.

## API 엔드포인트

| Method | Path | 인증 | 설명 |
|---|---|---|---|
| GET | `/health` | - | 헬스체크 (`{"ok": true}`) |
| POST | `/upload` | `X-Brain-Token` | 파일 업로드 (`book`, `file` 폼 데이터) |
| POST | `/books/{slug}/process?level=` | `X-Brain-Token` | 증류(distill) + 렌더링 + 검색 인덱스 재구축 |
| GET | `/books` | - | 등록된 책 목록 |
| GET | `/search?q=&k=&mode=` | `X-Brain-Token` | 전체 책·수업에서 검색 (임베딩 비용이 들어 토큰 필요) |
| GET | `/site/*` | - | 생성된 정적 HTML 페이지 (뷰어) |

## Railway 배포

Docker 빌드(`Dockerfile`)로 배포하고, `/data`에 영구 볼륨을 마운트해요. 필요한 환경 변수:

| 변수 | 설명 |
|---|---|
| `BRAIN_TOKEN` | 업로드/처리 API를 보호하는 토큰 (`openssl rand -hex 24`로 생성) |
| `ANTHROPIC_API_KEY` | Claude API 키 (distill/summarize에 사용) |
| `DATA_DIR` | 데이터 저장 경로, 기본값 `/data` (볼륨 마운트 경로와 일치해야 함) |

```bash
railway link --project <project-id>
railway volume add --mount-path /data
railway variables set BRAIN_TOKEN=... ANTHROPIC_API_KEY=... DATA_DIR=/data
railway up
```

---

## Technical overview (English)

**2nd BRAIN** is a small self-hosted pipeline that turns photographed book pages / PDFs
into level-adjusted (elementary / general / expert) HTML study pages, searchable via
SQLite FTS5.

- **`brain/`** — core library: ingest (image/PDF → text), distill (Claude-powered
  concept extraction), levels (per-topic reading level), render (Jinja2 → static HTML,
  `templates/page.html.j2` + `templates/shelf.html.j2`, styled by `static/brain.css`),
  index (FTS5 search), store (filesystem layout under `DATA_DIR`).
- **`api/`** — FastAPI app (`api.main:app`) exposing `/upload`, `/books/{slug}/process`,
  `/books`, `/search`, `/health`, and a static `/site` mount serving the rendered pages.
- **`sync/`** — `brain-sync` CLI (watchdog-based folder watcher + one-shot mode) that
  uploads new files from `~/Desktop/2ndBRAIN/<book>/` to the API.
- **Deploy** — `Dockerfile` + `railway.json` (Railway, Dockerfile builder, healthcheck at
  `/health`, `ON_FAILURE` restart policy). Data persists on a Railway volume mounted at
  `/data`; local source photos can be deleted after sync since the volume keeps the
  originals under `/data/books/<slug>/raw` (distilled notes under `.../notes`).

Run locally:

```bash
pip install -e .[dev]
uvicorn api.main:app --reload
pytest
```
