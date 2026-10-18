"""Pydantic models shared by the think() callers."""

from pydantic import BaseModel, Field


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
