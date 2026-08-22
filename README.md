# 2nd BRAIN

CR의 두 번째 뇌예요. 책이나 자료 사진을 폴더에 넣어두기만 하면, Clair가 알아서 읽고 정리해서
초등/일반/전문 세 가지 눈높이로 요약 페이지를 만들어 드려요. 나중에 원본 사진을 지워도
괜찮아요 — 서버 볼륨에 원본이 그대로 남아있으니까요.

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

폴더 이름 = 책 이름이 돼요 (자동으로 slug로 변환됩니다). 로컬 원본 사진은 나중에 지워도
괜찮아요. 서버 볼륨(`/data/books/<slug>/raw`)에 원본이 보관되고, 정리된 노트는
`/data/books/<slug>/notes`에 남아요.

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

## API 엔드포인트

| Method | Path | 인증 | 설명 |
|---|---|---|---|
| GET | `/health` | - | 헬스체크 (`{"ok": true}`) |
| POST | `/upload` | `X-Brain-Token` | 파일 업로드 (`book`, `file` 폼 데이터) |
| POST | `/books/{slug}/process?level=` | `X-Brain-Token` | 증류(distill) + 렌더링 + 검색 인덱스 재구축 |
| GET | `/books` | - | 등록된 책 목록 |
| GET | `/search?q=&k=` | - | 전체 책에서 검색 |
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
