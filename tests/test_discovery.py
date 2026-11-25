import json
import logging
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from research_agent.agents.research.discovery import discover, save_run
from research_agent.agents.research.openalex import OpenAlexClient, OpenAlexError
from research_agent.cli import main

KEY = "fixture-secret+not-a-real-key"


def work(number: int = 1, **fields: object) -> dict[str, object]:
    return {
        "id": f"https://openalex.org/W{number}",
        "display_name": f"Paper {number}",
        **fields,
    }


def client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_maps_work_and_rebuilds_abstract():
    payload = work(
        doi=" HTTPS://DOI.ORG/10.1234/Example ",
        abstract_inverted_index={"evidence": [1, 3], "More": [0], "means": [2]},
        authorships=[{"author": {"display_name": f"Author {i}"}} for i in range(6)],
        primary_location={"source": {"display_name": "Journal"}},
        publication_year=2022,
        type="article",
        cited_by_count=3,
        referenced_works=["https://openalex.org/W20"],
    )
    with client(lambda _: httpx.Response(200, json={"results": [payload, work(2)]})) as http:
        candidate, sparse = OpenAlexClient(http, KEY).search("query", 10)
    assert candidate.abstract == "More evidence means evidence"
    assert candidate.doi == "10.1234/example"
    assert candidate.authors == [f"Author {i}" for i in range(5)]
    assert candidate.venue == "Journal"
    assert (candidate.year, candidate.type, candidate.cited_by_count) == (2022, "article", 3)
    assert candidate.referenced_works == ["https://openalex.org/W20"]
    assert sparse.abstract is sparse.doi is sparse.venue is None


def test_dedup_and_saved_run(tmp_path: Path, caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        assert params["api_key"] == KEY
        assert set(params["select"].split(",")) == {
            "id", "doi", "display_name", "publication_year", "type", "authorships",
            "primary_location", "cited_by_count", "abstract_inverted_index", "referenced_works",
        }
        results = (
            [work(1, doi="https://doi.org/10.1234/First"), work(3)]
            if params["search"] == "first"
            else [work(2, doi="10.1234/first"), work(3)]
        )
        return httpx.Response(200, json={"results": results})

    caplog.set_level(logging.INFO, logger="httpx")
    queries = ["first", "second"]
    with client(handler) as http:
        candidates, stats = discover("A topic!", queries, 50, client=OpenAlexClient(http, KEY))
    assert [item.found_by for item in candidates] == [queries, queries]
    assert stats.model_dump() == {
        "per_query_hits": {"first": 2, "second": 2},
        "total_before_dedup": 4,
        "total_after_dedup": 2,
        "api_calls": 2,
    }

    folder = save_run("A topic!", queries, 50, candidates, stats, runs_dir=tmp_path)
    assert folder.name.endswith("_a-topic")
    candidates_text = (folder / "candidates.jsonl").read_text(encoding="utf-8")
    metadata_text = (folder / "run.json").read_text(encoding="utf-8")
    assert [json.loads(line) for line in candidates_text.splitlines()] == [
        item.model_dump() for item in candidates
    ]
    assert json.loads(metadata_text)["stats"] == stats.model_dump()
    assert json.loads(metadata_text)["timestamp"].endswith("+00:00")
    for content in (candidates_text, metadata_text, caplog.text):
        assert KEY not in content
        assert "api_key" not in content
        assert "fixture-secret" not in content


def test_paging_stops_at_requested_limit():
    cursors = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        assert params["per_page"] == "100"
        cursors.append(params["cursor"])
        start = 1 if len(cursors) == 1 else 101
        return httpx.Response(200, json={
            "results": [work(number) for number in range(start, start + 100)],
            "meta": {"next_cursor": "next"},
        })

    with client(handler) as http:
        alex = OpenAlexClient(http, KEY)
        results = alex.search("query", 105)
    assert len(results) == 105
    assert results[-1].title == "Paper 105"
    assert alex.api_calls == 2
    assert cursors == ["*", "next"]


def test_retries_rate_limit_then_succeeds(monkeypatch):
    delays = []
    monkeypatch.setattr("research_agent.agents.research.openalex.sleep", delays.append)
    responses = iter([httpx.Response(429), httpx.Response(200, json={"results": [work()]})])
    with client(lambda _: next(responses)) as http:
        alex = OpenAlexClient(http, KEY)
        assert len(alex.search("query", 25)) == 1
    assert alex.api_calls == 2
    assert delays == [1]


def test_retry_exhaustion_omits_api_key(monkeypatch):
    delays = []
    monkeypatch.setattr("research_agent.agents.research.openalex.sleep", delays.append)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text=str(request.url))

    with client(handler) as http, pytest.raises(OpenAlexError) as error:
        alex = OpenAlexClient(http, KEY)
        alex.search("query", 10)
    assert alex.api_calls == 4
    assert delays == [1, 2, 4]
    assert str(error.value) == "OpenAlex returned HTTP 503."


def test_transport_error_omits_request_url():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(str(request.url), request=request)

    with client(handler) as http, pytest.raises(OpenAlexError) as error:
        OpenAlexClient(http, KEY).search("query", 10)
    assert str(error.value) == "Could not reach OpenAlex."
    assert error.value.__context__ is None


def test_cli_missing_key_exits_two(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    assert main(["discover", "topic"]) == 2
    assert "Set OPENALEX_API_KEY in .env" in capsys.readouterr().err
    assert not (tmp_path / "data").exists()
