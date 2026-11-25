import logging
from collections.abc import Sequence
from datetime import date
from time import sleep
from typing import Any

import httpx

from .models import Candidate

WORKS_URL = "https://api.openalex.org/works"
SELECT_FIELDS = (
    "id,doi,display_name,publication_year,type,authorships,primary_location,"
    "cited_by_count,abstract_inverted_index,referenced_works"
)


def _redact_request_log(record: logging.LogRecord) -> bool:
    # HTTPX includes the complete request URL in its INFO record.
    if isinstance(record.args, tuple):
        record.args = tuple(
            arg.copy_remove_param("api_key") if isinstance(arg, httpx.URL) else arg
            for arg in record.args
        )
    return True


logging.getLogger("httpx").addFilter(_redact_request_log)


class OpenAlexError(Exception):
    """A discovery error safe to report without request or response details."""


def _rebuild_abstract(index: dict[str, list[int]] | None) -> str | None:
    if not index:
        return None
    words = sorted((position, word) for word, positions in index.items() for position in positions)
    return " ".join(word for _, word in words) or None


def _candidate(work: dict[str, Any], query: str | None) -> Candidate:
    authors = [
        author["display_name"]
        for authorship in work.get("authorships") or []
        if (author := authorship.get("author")) and author.get("display_name")
    ]
    source = (work.get("primary_location") or {}).get("source") or {}
    return Candidate(
        openalex_id=work["id"],
        doi=work.get("doi"),
        title=work.get("display_name") or "[Untitled]",
        year=work.get("publication_year"),
        type=work.get("type"),
        authors=authors[:5],
        venue=source.get("display_name"),
        cited_by_count=work.get("cited_by_count", 0),
        abstract=_rebuild_abstract(work.get("abstract_inverted_index")),
        referenced_works=work.get("referenced_works") or [],
        found_by=[query] if query is not None else [],
        via=[f"search:{query}"] if query is not None else [],
    )


class OpenAlexClient:
    def __init__(self, client: httpx.Client, api_key: str) -> None:
        self._client = client
        self._api_key = api_key
        self.api_calls = 0

    def _get_page(self, params: dict[str, str]) -> httpx.Response:
        params = {**params, "select": SELECT_FIELDS, "api_key": self._api_key}
        for attempt in range(4):
            self.api_calls += 1
            try:
                response = self._client.get(WORKS_URL, params=params, follow_redirects=False)
            except httpx.RequestError:
                break
            if response.is_success:
                return response
            status = response.status_code
            if attempt == 3 or (status != 429 and not 500 <= status <= 599):
                raise OpenAlexError(f"OpenAlex returned HTTP {status}.")
            sleep(2 ** attempt)
        raise OpenAlexError("Could not reach OpenAlex.")

    def search(self, query: str, max_results: int) -> list[Candidate]:
        candidates: list[Candidate] = []
        cursor: str | None = "*"
        per_page = min(100, max_results)
        while cursor and len(candidates) < max_results:
            works, cursor = self._read_page(
                {"search": query, "per_page": str(per_page), "cursor": cursor},
                max_results - len(candidates),
                query,
            )
            candidates.extend(works)
        return candidates

    def lookup(self, ids: Sequence[str]) -> list[Candidate]:
        works, _ = self._read_page({"filter": "openalex_id:" + "|".join(ids), "per_page": "50"}, 50)
        return works

    def citers(self, seed: str, since: date, limit: int) -> list[Candidate]:
        works, _ = self._read_page(
            {
                "filter": f"cites:{seed},from_publication_date:{since.isoformat()}",
                "sort": "cited_by_count:desc",
                "per_page": str(limit),
            },
            limit,
        )
        return works

    def _read_page(
        self, params: dict[str, str], limit: int, query: str | None = None
    ) -> tuple[list[Candidate], str | None]:
        response = self._get_page(params)
        try:
            page = response.json()
            works = [_candidate(work, query) for work in page["results"][:limit]]
            cursor = page.get("meta", {}).get("next_cursor") if works else None
            return works, cursor
        except (AttributeError, KeyError, TypeError, ValueError):
            pass
        raise OpenAlexError("OpenAlex returned an invalid works response.")
