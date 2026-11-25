import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

AbstractSource = Literal["openalex", "semantic_scholar", "s2_tldr", "crossref", "none"]


class Candidate(BaseModel):
    openalex_id: str
    doi: str | None = None
    title: str
    year: int | None
    type: str | None
    authors: list[str]
    venue: str | None
    cited_by_count: int
    abstract: str | None
    abstract_source: AbstractSource = Field(
        default_factory=lambda data: "openalex" if data["abstract"] else "none"
    )
    referenced_works: list[str]
    found_by: list[str]
    via: list[str] = Field(default_factory=list)
    graph: float = 0.0
    cites_per_year: float = 0.0
    recency: float = 0.0
    keyword: float = 0.0
    score: float = 0.0
    rank: int = 0

    @property
    def dedup_key(self) -> tuple[str, str]:
        if self.doi:
            return "doi", self.doi
        return "id", work_id(self.openalex_id)

    @field_validator("doi")
    @classmethod
    def normalize_doi(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value.strip().lower()) or None


class DiscoveryStats(BaseModel):
    per_query_hits: dict[str, int]
    total_before_dedup: int
    total_after_dedup: int
    api_calls: int
    backward_added: int = 0
    forward_added: int = 0
    kept: int = 0
    abstracts_before: int = 0
    abstracts_after: int = 0
    abstract_sources: dict[AbstractSource, int] = Field(default_factory=dict)
    calls_per_api: dict[str, int] = Field(default_factory=dict)
    abstract_lookup_failures: dict[str, int] = Field(default_factory=dict)


def work_id(value: str) -> str:
    return value.rstrip("/").rsplit("/", 1)[-1].upper()
