import json
from pathlib import Path

import httpx
import pytest

from research_agent.agents.research.queries import generate
from research_agent.cli import main
from research_agent.llm.lmstudio import LMStudioClient

TOPIC = "Kinetic modelling of biomass pyrolysis!"
QUESTIONS = ["Which methods?", "Which feedstocks?", "Which applications?", "Which parameters?"]
SUGGESTIONS = [
    "Isoconversional analysis, thermogravimetry.",
    "Distributed activation energy model",
    "Cellulose lignin decomposition mechanisms",
    "Reactor scale modelling applications",
    "Dynamic thermal reaction methods",
    "Industrial fluidized bed throughput",
    "Classical thermal decomposition methodology",
    "Eighth branch should disappear",
]


def model_response(queries: list[str], anchor: str = "biomass pyrolysis") -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
        "anchor": anchor, "questions": QUESTIONS, "queries": queries,
    })}}]})


def test_generation_filters_and_caches(tmp_path: Path):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        payload = json.loads(request.content)
        assert payload["temperature"] == 0
        schema = payload["response_format"]["json_schema"]["schema"]
        assert schema["required"] == ["anchor", "questions", "queries"]
        assert schema["properties"]["queries"]["minItems"] == schema["properties"]["queries"]["maxItems"] == 5
        assert "branches_in_order" not in json.loads(payload["messages"][1]["content"])
        return model_response([
            "kinetic modelling biomass pyrolysis",
            "one two three four five six seven eight nine",
            "Isoconversional analysis of thermogravimetry.",
            "Biomass fluidized bed thermal conversion reactor pilot scale industrial performance",
            "Dynamic thermal reaction methods",
        ], anchor="Of biomass")

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        model = LMStudioClient(http, "http://localhost:1234", "qwen")
        path = tmp_path / "queries.jsonl"
        result = generate(TOPIC, client=model, cache_path=path)
        assert result == generate(TOPIC, client=model, cache_path=path)
    assert len(calls) == 1
    assert result["anchor"] == "of biomass"
    assert result["questions"] == QUESTIONS
    assert result["queries"] == [
        "kinetic modelling of biomass pyrolysis", "isoconversional analysis of thermogravimetry of biomass",
        "biomass fluidized bed thermal conversion reactor pilot scale industrial performance",
        "dynamic thermal reaction methods of biomass",
    ]
    assert [row["branch"] for row in result["query_details"]] == ["topic", "free-form", "free-form", "free-form"]
    assert [row["anchor_appended"] for row in result["query_details"]] == [False, True, False, True]


def test_generation_retries_then_warns_and_falls_back(tmp_path: Path, caplog):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.content)
        return model_response(["biomass"])

    path = tmp_path / "queries.jsonl"
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        model = LMStudioClient(http, "http://localhost:1234", "qwen")
        assert generate(TOPIC, client=model, cache_path=path)["queries"] == [
            "kinetic modelling of biomass pyrolysis"
        ]
    assert len(calls) == 2 and calls[0] == calls[1]
    assert "Using the topic alone" in caplog.text
    assert not path.exists()


@pytest.mark.parametrize("manual", [False, True])
def test_discover_selects_query_source(tmp_path: Path, monkeypatch, manual: bool):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENALEX_API_KEY", "mock-openalex")
    monkeypatch.setenv("LMSTUDIO_MODEL", "mock-qwen")
    real_client = httpx.Client
    searches = []
    local_calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.openalex.org":
            query = request.url.params["search"]
            searches.append(query)
            assert "keywords" in request.url.params["select"].split(",")
            hit = {"id": "https://openalex.org/W1", "display_name": "Topic paper",
                   "keywords": [{"display_name": "Activation barrier", "score": 0.8}]}
            results = [hit]
            if query == "activation barrier biomass pyrolysis":
                results.append({"id": "https://openalex.org/W2", "display_name": "Extra paper"})
            return httpx.Response(200, json={"results": results})
        local_calls.append(request)
        return model_response(SUGGESTIONS)

    monkeypatch.setattr(httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    args = ["discover", TOPIC, "--no-expand", "--no-abstracts"]
    if manual:
        args += ["--query", "manually supplied search"]
    assert main(args) == 0
    folder, = Path("data/runs").iterdir()
    metadata = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    assert metadata["query_source"] == ("manual" if manual else "auto")
    assert metadata["questions"] == ([] if manual else QUESTIONS)
    assert metadata["queries"] == searches
    assert metadata["anchor"] == (None if manual else "biomass pyrolysis")
    assert [row["query"] for row in metadata["query_details"]] == searches
    assert [row["branch"] for row in metadata["query_details"]] == (
        ["manual"] if manual else ["topic", *(["free-form"] * 4), "feedback"]
    )
    assert len(searches) == (1 if manual else 6)
    assert len(local_calls) == (0 if manual else 1)
    assert searches[0] == ("manually supplied search" if manual else "kinetic modelling of biomass pyrolysis")
    assert sum(metadata["stats"]["per_query_hits"].values()) == (1 if manual else 7)
    assert metadata["stats"]["total_after_dedup"] == (1 if manual else 2)
    if manual:
        assert metadata["feedback_queries"] == []
    else:
        assert metadata["feedback_queries"] == [{
            "query": "activation barrier biomass pyrolysis", "term": "activation barrier",
            "score": 4.0, "source": "keywords", "anchor_appended": True,
        }]
        candidates = [json.loads(line) for line in (folder / "candidates.jsonl").read_text(encoding="utf-8").splitlines()]
        assert all("search:activation barrier biomass pyrolysis" in item["via"] for item in candidates)
