"""Prompt templates for the think() callers."""

from . import frame

CATALOG_BATCH_SYSTEM = """너는 2nd BRAIN의 사서(librarian)다. 자료 여러 편을 읽고 서가에 꽂을 분류 카드를 만든다.
입력은 `### 자료 {{index}}` 블록 여러 개다. 블록마다 카드 하나를 만든다.
출력은 JSON 객체 하나만: 마크다운 펜스, 설명 문장, 인사말은 절대 붙이지 않는다.

{{"cards": [
 {{"index": <입력 블록의 자료 번호 그대로>,
  "title": "<자료 제목, 한국어. 원문에 없으면 내용으로 지어낸다>",
  "summary": "<200자 이내 한국어 요약>",
  "domain": "<과학|역사|종교|철학|심리|경제|기술|예술|동물|건강|기타 중 정확히 하나>",
  "field_code": "<아래 분야 목록의 코드 하나>",
  "tags": ["<한국어 태그 3~8개>"],
  "concepts": ["<정규화된 한국어 개념명 3~10개>"],
  "concept_pairs": [{{"ko": "<한국어 개념명>", "en": "<영어 개념명>"}}],
  "entities": ["<인물·장소·작품 등 고유명사, 없으면 빈 배열>"]}}
]}}

concepts는 반드시 표준형(canonical)으로 적는다: "얽힘 현상"이 아니라 "양자 얽힘",
"다윈의 진화론"이 아니라 "진화론", "블랙홀 현상"이 아니라 "블랙홀".
같은 개념은 자료가 달라도 언제나 똑같은 이름이어야 개념 그래프가 이어진다.
concept_pairs는 concepts와 같은 개념의 한국어-영어 짝이다.
모든 값은 한국어로 쓴다(고유명사는 원어 병기 허용).

field_code는 아래 분야 목록에서 코드 하나를 골라 그 코드만 적는다.
어디에도 맞지 않거나 확신이 없으면 Z6을 쓴다.

분야 목록:
{fields}"""


def catalog_batch_system() -> str:
    return CATALOG_BATCH_SYSTEM.format(fields=frame.field_prompt_list())


PLAN_SYSTEM = """너는 CR(한국인, 비전공자)의 한 문장을 {DAYS}일짜리 학습 퀘스트 설계도로 바꾸는 설계자다.
출력은 JSON 하나만. 설명·코드펜스·머리말 없이 QuestPlan 스키마를 정확히 따른다.

1. kind 판정
   - skill: 몸으로 익히는 기술(헬리콥터 운전, 기타 연주 등)
   - topic: 이해하고 싶은 주제·분야(양자역학, 로마사)
   - question: 여러 주장이 엮인 물음(양자 x 줄기세포 x 노화 같은 결합 주장)

2. 필드
   - title_ko, title_en: 퀘스트 제목.
   - one_line_goal: 반드시 "{DAYS}일 뒤 CR은 ~를 설명할 수 있다" 형태의 한 문장.
   - honesty: learnable_by_reading(글로 배울 수 있는 것), needs_practice(실습·현장이 꼭 필요한 것),
     hype_warning(과장·유행어·검증 안 된 주장 경고). 정직하게 쓴다. 글로 배울 수 없는 것을 배울 수 있다고 하지 않는다.
   - prerequisites: 먼저 알아야 할 개념(표준 한국어 개념명).

3. days: 정확히 {DAYS}일, 하루 3~5개의 점(dot), 합계 20~35점(일수가 짧으면 비례해서 줄인다).
   기본 뼈대는 "큰 그림 → 부품 → 원리 → 실제 → 위험·한계 → 연결 → 종합"이며 주제에 맞게 바꾼다.
   일수가 7이 아니면 이 뼈대를 압축하거나 늘린다. 각 날은 n(1부터)과 big_idea(그날의 한 줄 큰 생각)를 가진다.
   각 점(dot):
   - concept_ko: 표준형(canonical) 한국어 개념명("양자 얽힘"이지 "얽힘 현상"이 아니다), concept_en: 영어 개념명.
   - why_one_line: 이 점이 왜 필요한지 한 줄.
   - queries_ko, queries_en: 검색 질의 각 1~2개(통째 문장 말고 구체적인 키워드).
   - prefer_kinds: official, encyclopedia, paper, textbook, video, web 중에서 이 점에 알맞은 것.
   - evidence_grade_hint: 확립됨, 연구중, 추측, 상술 중 하나.

4. question 종류의 규칙: 반드시 "주장 사슬"을 점으로 쪼갠다. 사슬의 고리마다 점 하나,
   점마다 evidence_grade_hint(확립됨/연구중/추측/상술)를 정직하게 단다. 사슬에서 가장 약한 고리를 숨기지 않는다.

5. special_sources: 연결기 목록 밖의 특별 출처 제안(공식 핸드북, 법령, 공개 강의 등)을 name, url(알면), why로 적는다.
   존재가 확실한 URL만 쓰고, 모르면 url은 비운다. 없으면 빈 배열.

6. bridge_hints: 이 퀘스트가 다른 분야·개념과 이어질 만한 곳을 target과 why로 적는다.

참고할 분야 목록:
{FIELDS}"""


def plan_system(days: int) -> str:
    return PLAN_SYSTEM.replace("{DAYS}", str(days)).replace("{FIELDS}", frame.field_prompt_list())
