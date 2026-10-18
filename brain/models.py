"""Pydantic models shared by the think() callers."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ConceptPair(BaseModel):
    ko: str
    en: str = ""


class CatalogCard(BaseModel):
    index: int
    title: str
    summary: str
    domain: str
    field_code: str = ""
    tags: list[str] = Field(default_factory=list)
    concepts: list[str] = Field(default_factory=list)
    concept_pairs: list[ConceptPair] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)


class CatalogBatch(BaseModel):
    cards: list[CatalogCard]


# ---------------------------------------------------------------------------
# learn-quest
# ---------------------------------------------------------------------------

KINDS = ("official", "encyclopedia", "paper", "textbook", "video", "web", "forum", "book")


class Dot(BaseModel):
    concept_ko: str
    concept_en: str = ""
    why_one_line: str = ""
    queries_ko: list[str] = Field(default_factory=list)
    queries_en: list[str] = Field(default_factory=list)
    prefer_kinds: list[str] = Field(default_factory=list)
    evidence_grade_hint: Literal["확립됨", "연구중", "추측", "상술"] = "연구중"

    @field_validator("prefer_kinds")
    @classmethod
    def _known_kinds(cls, v: list[str]) -> list[str]:
        return [k for k in v if k in KINDS]


class DayPlan(BaseModel):
    n: int
    big_idea: str
    dots: list[Dot]


class Honesty(BaseModel):
    learnable_by_reading: list[str] = Field(default_factory=list)
    needs_practice: list[str] = Field(default_factory=list)
    hype_warning: list[str] = Field(default_factory=list)


class SpecialSource(BaseModel):
    name: str
    url: str = ""
    why: str = ""


class BridgeHint(BaseModel):
    target: str
    why: str = ""


class QuestPlan(BaseModel):
    kind: Literal["skill", "topic", "question"]
    title_ko: str
    title_en: str = ""
    one_line_goal: str
    honesty: Honesty = Field(default_factory=Honesty)
    prerequisites: list[str] = Field(default_factory=list)
    days: list[DayPlan]
    special_sources: list[SpecialSource] = Field(default_factory=list)
    bridge_hints: list[BridgeHint] = Field(default_factory=list)


class SourceRecord(BaseModel):
    url: str
    title: str
    kind: str
    connector: str
    score: float
    day: int
    dot: str
    lang: str
    why_picked: str
    fetched: bool
    reason: str = ""
    raw_file: str = ""
    chars: int = 0


class SourceLedger(BaseModel):
    sources: list[SourceRecord] = Field(default_factory=list)
    connector_status: dict[str, dict[str, int]] = Field(default_factory=dict)
    special_tried: list[dict] = Field(default_factory=list)
    vault_hits: list[dict] = Field(default_factory=list)
    new_connectors_tried: list[str] = Field(default_factory=list)


GRADES = ("확립됨", "연구중", "추측", "상술")


class DotCard(BaseModel):
    concept_id: str = ""
    concept_ko: str
    one_line: str
    picture_svg: str = ""
    emoji: str = ""
    analogy: str = ""
    real_example: str = ""
    why_it_matters: str = ""
    evidence_grade: Literal["확립됨", "연구중", "추측", "상술"] = "확립됨"
    sources: list[str] = Field(default_factory=list)

    @field_validator("evidence_grade", mode="before")
    @classmethod
    def _coerce_grade(cls, v):
        g = "".join(str(v).split())  # "연구 중" -> "연구중"
        return g if g in GRADES else "연구중"


class QuizItem(BaseModel):
    q: str
    a: str
    why: str = ""


class DayLesson(BaseModel):
    n: int
    big_idea_one_line: str
    story_opening: str
    dots: list[DotCard]
    quiz: list[QuizItem] = Field(default_factory=list)
    say_it_yourself: str = ""
    link_yesterday: str = ""
    clair_one_liner: str = ""


class BridgeVerdict(BaseModel):
    src: str
    dst: str
    connects: bool
    rel: Literal["bridge", "requires", "is_a", "related"] = "bridge"
    reason: str = ""


class BridgeBatch(BaseModel):
    verdicts: list[BridgeVerdict] = Field(default_factory=list)
class Citation(BaseModel):
    title: str
    url: str = ""
    slug: str = ""
    path: str = ""


class AskAnswer(BaseModel):
    answer_html: str
    citations: list[Citation] = Field(default_factory=list)
    used_vault_ratio: float = 1.0
    follow_up_quest: str = ""


# schema name (as stored in a quest task file) -> model class
SCHEMAS: dict[str, type[BaseModel]] = {
    "QuestPlan": QuestPlan,
    "CatalogBatch": CatalogBatch,
    "DayLesson": DayLesson,
    "BridgeBatch": BridgeBatch,
    "AskAnswer": AskAnswer,
}
