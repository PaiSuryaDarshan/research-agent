import json
import logging
from collections.abc import Callable
from datetime import date
from math import log1p
from pathlib import Path

import httpx
import pytest

from research_agent.agents.research.abstracts import AbstractLookup
from research_agent.agents.research.discovery import discover, save_run
from research_agent.agents.research.expansion import backward, forward
from research_agent.agents.research.models import Candidate
from research_agent.agents.research.openalex import OpenAlexClient, OpenAlexError
from research_agent.agents.research.ranking import RANKING_WEIGHTS, rank_candidates
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
    sparse_payload = work(2, display_name=None)
    with client(lambda _: httpx.Response(200, json={"results": [payload, sparse_payload]})) as http:
        candidate, sparse = OpenAlexClient(http, KEY).search("query", 10)
    assert candidate.abstract == "More evidence means evidence"
    assert candidate.abstract_source == "openalex"
    assert candidate.doi == "10.1234/example"
    assert candidate.authors == [f"Author {i}" for i in range(5)]
    assert candidate.venue == "Journal"
    assert (candidate.year, candidate.type, candidate.cited_by_count) == (2022, "article", 3)
    assert candidate.referenced_works == ["https://openalex.org/W20"]
    assert sparse.abstract is sparse.doi is sparse.venue is None
    assert sparse.title == "[Untitled]"


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
        candidates, stats = discover(
            "A topic!", queries, 50, client=OpenAlexClient(http, KEY),
            expand=False, fill_abstracts=False,
        )
    assert [item.found_by for item in candidates] == [queries, queries]
    assert [item.via for item in candidates] == [["search:first", "search:second"]] * 2
    assert stats.model_dump() == {
        "per_query_hits": {"first": 2, "second": 2},
        "total_before_dedup": 4,
        "total_after_dedup": 2,
        "api_calls": 2,
        "backward_added": 0,
        "forward_added": 0,
        "kept": 2,
        "abstracts_before": 0,
        "abstracts_after": 0,
        "abstract_sources": dict.fromkeys(("openalex", "semantic_scholar", "s2_tldr", "crossref"), 0) | {"none": 2},
        "calls_per_api": {"openalex": 2, "semantic_scholar": 0, "crossref": 0},
        "abstract_lookup_failures": {},
    }

    folder = save_run("A topic!", queries, 50, candidates, stats, runs_dir=tmp_path)
    assert folder.name.endswith("_a-topic")
    candidates_text = (folder / "candidates.jsonl").read_text(encoding="utf-8")
    metadata_text = (folder / "run.json").read_text(encoding="utf-8")
    assert [json.loads(line) for line in candidates_text.splitlines()] == [
        item.model_dump() for item in candidates
    ]
    assert json.loads(metadata_text)["stats"] == stats.model_dump()
    assert json.loads(metadata_text)["ranking_weights"] == RANKING_WEIGHTS
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


def candidate(number: int, **fields: object) -> Candidate:
    return Candidate.model_validate({
        "openalex_id": f"https://openalex.org/W{number}",
        "title": f"Paper {number}",
        "year": None,
        "type": None,
        "authors": [],
        "venue": None,
        "cited_by_count": 0,
        "abstract": None,
        "referenced_works": [],
        "found_by": [],
        **fields,
    })


def test_backward_batches_only_cocited_ids():
    shared = [f"W{number}" for number in range(10, 61)]
    seeds = [
        candidate(1, referenced_works=[*shared, "W2", "W99", "W99"]),
        candidate(2, referenced_works=[*shared, "W2"]),
        candidate(1, referenced_works=["W99"]),
    ]
    batches = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        field, ids = params["filter"].split(":")
        assert field == "openalex_id"
        assert params["per_page"] == "50"
        batch = ids.split("|")
        batches.append(batch)
        return httpx.Response(200, json={"results": [work(int(id_[1:])) for id_ in batch]})

    with client(handler) as http:
        expanded = backward(seeds, OpenAlexClient(http, KEY))
    assert batches == [shared[:50], shared[50:]]
    assert len(expanded) == 51
    assert all(item.via == ["ref_of:W1", "ref_of:W2"] for item in expanded)


def test_forward_queries_most_cited_seed_and_uses_date():
    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        assert params["filter"] == "cites:W2,from_publication_date:2023-02-28"
        assert params["sort"] == "cited_by_count:desc"
        assert params["per_page"] == "50"
        assert params["api_key"] == KEY
        return httpx.Response(200, json={"results": [work(3)]})

    seeds = [candidate(1, cited_by_count=3), candidate(2, cited_by_count=5)]
    with client(handler) as http:
        alex = OpenAlexClient(http, KEY)
        expanded = forward(seeds, alex, top_k=1, today=date(2028, 2, 29))
    assert alex.api_calls == 1
    assert expanded[0].via == ["cites:W2"]


def test_discovery_merges_all_provenance_and_expands_only_search_seeds():
    seed = work(1, doi="10.1/a", referenced_works=["W3"], cited_by_count=6)
    other_seed = work(2, referenced_works=["W3"])
    filters = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if "search" in params:
            results = [seed, other_seed] if params["search"] == "first" else [seed]
        else:
            filters.append(params["filter"])
            if params["filter"] == "openalex_id:W3":
                results = [work(3, doi="10.1/a")]
            else:
                results = [seed, work(4)]
        return httpx.Response(200, json={"results": results})

    with client(handler) as http:
        candidates, stats = discover(
            "Topic", ["first", "second"], 25, client=OpenAlexClient(http, KEY), fill_abstracts=False
        )
    assert len(filters) == 3
    assert [filter_.split(",")[0] for filter_ in filters] == ["openalex_id:W3", "cites:W1", "cites:W2"]
    merged = next(item for item in candidates if item.doi == "10.1/a")
    assert merged.found_by == ["first", "second"]
    assert merged.via == ["search:first", "search:second", "ref_of:W1", "ref_of:W2", "cites:W1", "cites:W2"]
    assert stats.total_before_dedup == 8
    assert (stats.backward_added, stats.forward_added, stats.total_after_dedup, stats.kept) == (0, 1, 3, 3)
    assert stats.api_calls == 5


def test_ranking_components_order_and_cut():
    first = candidate(1, title="BIOMASS", year=2024, cited_by_count=30,
                      referenced_works=["W1", "W2", "W2", "W3", "W4"])
    second = candidate(2, title="Biomass", abstract="Pyrolysis", year=2025,
                       cited_by_count=2, referenced_works=["W1"])
    third = candidate(3, year=2026)
    inputs = [third, second, first]
    ranked = rank_candidates(inputs, "The biomass", ["biomass and pyrolysis"], 2026, 2)
    assert [item.openalex_id for item in ranked] == [first.openalex_id, second.openalex_id]
    assert [item.rank for item in ranked] == [1, 2]
    assert (ranked[0].graph, ranked[0].cites_per_year, ranked[0].recency, ranked[0].keyword) == (1, 1, 0, 0.5)
    assert ranked[0].score == pytest.approx(0.725)
    assert ranked[1].graph == ranked[1].recency == 0.5
    assert ranked[1].keyword == 1
    assert ranked[1].cites_per_year == pytest.approx(log1p(1) / log1p(10))
    assert [item.rank for item in inputs] == [0, 0, 0]


def test_cli_no_expand_and_no_abstracts_skip_extra_calls(tmp_path: Path, monkeypatch, capsys):
    references = ["W3"]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.openalex.org"
        assert "filter" not in request.url.params
        return httpx.Response(200, json={"results": [
            work(1, doi="10.1/x", referenced_works=references), work(2, referenced_works=references),
        ]})

    http = client(handler)
    monkeypatch.setattr("research_agent.agents.research.discovery.httpx.Client", lambda **_: http)
    monkeypatch.setenv("OPENALEX_API_KEY", KEY)
    monkeypatch.chdir(tmp_path)
    assert main(["discover", "topic", "--no-expand", "--no-abstracts", "--max-candidates", "1"]) == 0
    output = capsys.readouterr().out
    assert "API calls: 1" in output
    assert "After de-dup: 2" in output
    assert "Kept: 1" in output


def test_s2_batches_nulls_and_tldr_priority(monkeypatch):
    batches = []
    waits = []
    monkeypatch.setattr("research_agent.agents.research.abstracts.monotonic", lambda: 0.0)
    monkeypatch.setattr("research_agent.agents.research.abstracts.sleep", waits.append)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.params["fields"] == "externalIds,abstract,tldr"
        assert "x-api-key" not in request.headers
        ids = json.loads(request.content)["ids"]
        batches.append(ids)
        papers = [None] * len(ids)
        if len(batches) == 1:
            papers[1] = {"abstract": "<p>Abstract: Actual text.</p>", "tldr": {"text": "Ignored."}}
            papers[2] = {"abstract": None, "tldr": {"text": "Short summary."}}
        return httpx.Response(200, json=papers)

    candidates = [candidate(i, doi=f"10.1/{i}") for i in range(501)]
    no_doi = candidate(502)
    with client(handler) as http:
        AbstractLookup(http, http).fill_from_s2([*candidates, no_doi])
    assert [len(batch) for batch in batches] == [500, 1]
    assert batches[1] == ["DOI:10.1/500"]
    assert waits == [1.1]
    assert (candidates[0].abstract, candidates[0].abstract_source) == (None, "none")
    assert (candidates[1].abstract, candidates[1].abstract_source) == ("Actual text.", "semantic_scholar")
    assert (candidates[2].abstract, candidates[2].abstract_source) == ("Short summary.", "s2_tldr")
    assert (no_doi.abstract, no_doi.abstract_source) == (None, "none")


def test_crossref_retries_and_cleans_jats(monkeypatch):
    delays = []
    monkeypatch.setattr("research_agent.agents.research.abstracts.monotonic", lambda: 0.0)
    monkeypatch.setattr("research_agent.agents.research.abstracts.sleep", delays.append)
    responses = iter([429, 503, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/works/10.1/find"
        assert request.url.params["mailto"] == "reader@example.org"
        assert "x-api-key" not in request.headers
        return httpx.Response(next(responses), json={"message": {"abstract": (
            "<jats:title>Abstract</jats:title><jats:p>First &amp; second.</jats:p>"
            "<jats:p>CO<jats:sub>2</jats:sub>  observed.</jats:p>"
        )}})

    filled = candidate(1, doi="10.1/skip", abstract="Existing text", abstract_source="s2_tldr")
    pending = candidate(2, doi="10.1/find")
    with client(handler) as http:
        lookup = AbstractLookup(http, http, email="reader@example.org")
        lookup.fill_from_crossref([filled, pending, candidate(3)])
    assert delays == [1, 0.2, 2, 0.2]
    assert lookup.calls["crossref"] == 3
    assert (pending.abstract, pending.abstract_source) == ("First & second. CO2 observed.", "crossref")
    assert filled.abstract == "Existing text"


def test_fallback_runs_after_cut_and_keeps_key_out_of_outputs(tmp_path: Path, caplog):
    def search(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [
            work(1, display_name="Topic result", doi="10.1/keep"),
            work(2, doi="10.1/discard"),
        ]})

    def lookup(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.semanticscholar.org":
            assert request.headers["x-api-key"] == KEY
            assert json.loads(request.content) == {"ids": ["DOI:10.1/keep"]}
            raise httpx.ConnectError(f"x-api-key={KEY}", request=request)
        assert request.url.path == "/works/10.1/keep"
        assert "x-api-key" not in request.headers
        return httpx.Response(200, json={"message": {"abstract": "<p>Fallback text.</p>"}})

    with client(search) as http, client(lookup) as fallback:
        candidates, stats = discover(
            "Topic", [], 2, client=OpenAlexClient(http, "openalex-test-key"),
            expand=False, max_candidates=1, abstract_lookup=AbstractLookup(fallback, fallback, s2_key=KEY),
        )
    assert (stats.abstracts_before, stats.abstracts_after) == (0, 1)
    assert stats.abstract_sources["crossref"] == 1
    assert stats.calls_per_api == {"openalex": 1, "semantic_scholar": 1, "crossref": 1}
    assert stats.abstract_lookup_failures == {"semantic_scholar": 1}
    folder = save_run("Topic", [], 2, candidates, stats, runs_dir=tmp_path)
    for output in [caplog.text, *(file.read_text(encoding="utf-8") for file in folder.iterdir())]:
        assert KEY not in output
        assert "x-api-key" not in output
