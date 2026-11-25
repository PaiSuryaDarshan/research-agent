import re

from pydantic import BaseModel, field_validator


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
    referenced_works: list[str]
    found_by: list[str]

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
