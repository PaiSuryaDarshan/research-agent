import csv
import json
from pathlib import Path

import httpx
import pytest

from research_agent.agents.research.openalex import OpenAlexClient
from research_agent.benchmark_tools.recall import measure_recall
from research_agent.cli import main

KEY = "fixture-recall-credential"


def write_rows(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def api_work(id_: str, **fields: object) -> dict:
    return {"id": f"https://openalex.org/{id_}", "display_name": f"Paper {id_}", **fields}


@pytest.mark.parametrize("with_screening", [False, True])
def test_recall_matches_id_first_and_falls_back_to_doi(tmp_path: Path, with_screening: bool):
    (tmp_path / "run.json").write_text('{"search_work_ids":["W1"]}', encoding="utf-8")
    first = {"openalex_id": "https://openalex.org/W1", "rank": 3}
    second = {"openalex_id": "W9", "doi": " HTTPS://DOI.ORG/10.1/MATCH ", "rank": 5}
    write_rows(tmp_path / "candidates.jsonl", [first, second])
    if with_screening:
        write_rows(tmp_path / "screened.jsonl", [second])

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["api_key"] == KEY
        if request.url.path == "/works/doi:10.1/review":
            assert request.url.params["select"] == "id,doi,display_name,referenced_works"
            return httpx.Response(200, json=api_work("W42", referenced_works=["W1", "W2", "W3", "W4"]))
        assert request.url.params["filter"] == "openalex_id:W1|W2|W3|W4"
        return httpx.Response(200, json={"results": [
            api_work("W1"), api_work("W2", doi="10.1/match"),
            api_work("W3", cited_by_count=5), api_work("W4", cited_by_count=10),
        ]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        result, missed = measure_recall(tmp_path, "HTTPS://doi.org/10.1/REVIEW", OpenAlexClient(http, KEY))
    assert result.n_references == 4
    assert result.recall_candidates == 0.5
    assert result.recall_kept == (0.25 if with_screening else None)
    assert not result.leakage
    assert [row.id for row in missed] == ["W4", "W3"]
    csv_text = (tmp_path / "recall_W42.csv").read_text(encoding="utf-8")
    rows = list(csv.DictReader(csv_text.splitlines()))
    assert [row["rank"] for row in rows] == ["3", "5", "", ""]
    assert rows[1]["found_in_kept"] == ("True" if with_screening else "")
    metadata = (tmp_path / "run.json").read_text(encoding="utf-8")
    assert json.loads(metadata)["recall"] == result.model_dump()
    assert KEY not in csv_text + metadata


@pytest.mark.parametrize("source", ["candidates", "search"])
def test_recall_cli_warns_about_leakage(tmp_path: Path, monkeypatch, capsys, source: str):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENALEX_API_KEY", KEY)
    (tmp_path / "run.json").write_text(json.dumps(
        {"search_work_ids": ["W42"] if source == "search" else []}
    ), encoding="utf-8")
    write_rows(tmp_path / "candidates.jsonl", [{"openalex_id": "W42"}] if source == "candidates" else [])
    http = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=api_work("W42", referenced_works=[]))
    ))
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: http)
    assert main(["recall", str(tmp_path), "--reference", "W42"]) == 0
    output = capsys.readouterr()
    assert "Leakage: yes" in output.out
    assert "WARNING: Reference review" in output.err
    assert ("ranked candidates" if source == "candidates" else "search hits before ranking") in output.err


def test_discover_excludes_search_seed_and_expansion_results(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENALEX_API_KEY", KEY)
    filters = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if "search" in params:
            results = [
                api_work("W42", cited_by_count=100, referenced_works=["W7"]),
                api_work("W1", referenced_works=["W7", "W42", "W8"]),
                api_work("W2", referenced_works=["W42", "W8"]),
            ]
        else:
            filter_ = params["filter"].split(",")[0]
            filters.append(filter_)
            results = [api_work("W8")] if filter_.startswith("openalex_id:") else [
                api_work("W42"), api_work("W50"), api_work("W10"),
            ]
        return httpx.Response(200, json={"results": results})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: http)
    assert main(["discover", "topic", "--exclude", "w42", "--exclude", "W50", "--no-abstracts"]) == 0
    assert filters == ["openalex_id:W8", "cites:W1", "cites:W2"]
    folder, = Path("data/runs").iterdir()
    rows = [json.loads(line) for line in (folder / "candidates.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {row["openalex_id"].rsplit("/", 1)[-1] for row in rows} == {"W1", "W2", "W8", "W10"}
    metadata = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    assert metadata["excluded_ids"] == ["W42", "W50"]
    assert metadata["search_work_ids"] == ["W1", "W2"]
