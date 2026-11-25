import re
from collections.abc import Sequence
from html import unescape
from time import monotonic, sleep
from urllib.parse import quote

import httpx

from .models import AbstractSource, Candidate

S2_BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"
CROSSREF_WORKS_URL = "https://api.crossref.org/works/"


def clean_abstract(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = re.sub(r"</?(?:[\w.-]+:)?(?:p|div|title|sec|br|abstract)\b[^>]*>", " ", value, flags=re.I)
    text = unescape(re.sub(r"</?\w[^>]*>", "", text))
    text = re.sub(r"^abstract\b\s*[:.\u2013\u2014-]?\s*", "", " ".join(text.split()), flags=re.I)
    return text or None


class AbstractLookup:
    def __init__(
        self, s2: httpx.Client, crossref: httpx.Client, *,
        s2_key: str | None = None, email: str | None = None,
    ) -> None:
        self._s2 = s2
        self._crossref = crossref
        self._s2_key = s2_key
        self._email = email
        self.calls = {"semantic_scholar": 0, "crossref": 0}
        self.failures = {"semantic_scholar": 0, "crossref": 0}
        self._last_call: dict[str, float] = {}

    def _count_call(self, api: str, interval: float) -> None:
        if api in self._last_call:
            remaining = interval - (monotonic() - self._last_call[api])
            if remaining > 0:
                sleep(remaining)
        self._last_call[api] = monotonic()
        self.calls[api] += 1

    def _fill(self, candidate: Candidate, value: object, source: AbstractSource) -> None:
        text = clean_abstract(value)
        if text and (not self._s2_key or self._s2_key not in text):
            candidate.abstract = text
            candidate.abstract_source = source

    def fill_from_s2(self, candidates: Sequence[Candidate]) -> None:
        pending = [candidate for candidate in candidates if candidate.doi and not candidate.abstract]
        for start in range(0, len(pending), 500):
            batch = pending[start : start + 500]
            papers = self._s2_batch([f"DOI:{candidate.doi}" for candidate in batch])
            if not isinstance(papers, list) or len(papers) != len(batch):
                self.failures["semantic_scholar"] += 1
                continue
            for candidate, paper in zip(batch, papers, strict=True):
                if not isinstance(paper, dict):
                    continue
                self._fill(candidate, paper.get("abstract"), "semantic_scholar")
                tldr = paper.get("tldr")
                if not candidate.abstract and isinstance(tldr, dict):
                    self._fill(candidate, tldr.get("text"), "s2_tldr")

    def _s2_batch(self, ids: list[str]) -> object:
        headers = {"x-api-key": self._s2_key} if self._s2_key else {}
        for delay in (2, 4, 8, None):
            self._count_call("semantic_scholar", 0 if self._s2_key else 1.1)
            try:
                response = self._s2.post(
                    S2_BATCH_URL,
                    params={"fields": "externalIds,abstract,tldr"},
                    json={"ids": ids},
                    headers=headers,
                    follow_redirects=False,
                )
                if response.is_success:
                    return response.json()
            except (httpx.HTTPError, ValueError):
                return None
            status = response.status_code
            if delay is None or (status != 429 and not 500 <= status <= 599):
                break
            sleep(delay)
        return None

    def fill_from_crossref(self, candidates: Sequence[Candidate]) -> None:
        for candidate in candidates:
            if candidate.doi and not candidate.abstract:
                self._fill(candidate, self._crossref_abstract(candidate.doi), "crossref")

    def _crossref_abstract(self, doi: str) -> object:
        params = {"mailto": self._email} if self._email else {}
        for attempt in range(4):
            self._count_call("crossref", 0.2)
            try:
                response = self._crossref.get(
                    CROSSREF_WORKS_URL + quote(doi, safe="/"),
                    params=params,
                    follow_redirects=False,
                )
                if response.is_success:
                    return response.json().get("message", {}).get("abstract")
            except (httpx.HTTPError, AttributeError, ValueError):
                break
            status = response.status_code
            if status == 404:
                return None
            if attempt == 3 or (status != 429 and not 500 <= status <= 599):
                break
            retry_after = response.headers.get("Retry-After", "")
            sleep(max(2 ** attempt, int(retry_after)) if retry_after.isdecimal() else 2 ** attempt)
        self.failures["crossref"] += 1
        return None
