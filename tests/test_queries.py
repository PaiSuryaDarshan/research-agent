import json
from pathlib import Path

import httpx
import pytest

from research_agent.agents.research.queries import generate
from research_agent.cli import main
from research_agent.llm.lmstudio import LMStudioClient

TOPIC = "Kinetic modelling of biomass pyrolysis!"
QUESTIONS = ["Which methods?", "Which feedstocks?", "Which applications?"]
BRANCHES = [
    "Isoconversional analysis, thermogravimetry.",
    "Distributed activation energy model",
    "Cellulose lignin decomposition mechanisms",
    "Reactor scale modelling applications",
    "Dynamic thermal reaction methods",
]


def model_response(queries: list[str]) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
        "questions": QUESTIONS, "queries": queries,
    })}}]})


def test_generation_filters_and_caches(tmp_path: Path):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        payload = json.loads(request.content)
        assert payload["temperature"] == 0
        assert payload["response_format"]["json_schema"]["schema"]["required"] == ["questions", "queries"]
        return model_response([
            "kinetic modelling biomass pyrolysis",
            "too short",
            "one two three four five six seven eight nine",
            "wood OR plastic pyrolysis",
            "1965 thermal reaction kinetics",
            BRANCHES[0],
            "Isoconversional analysis thermogravimetry techniques",
            *BRANCHES[1:],
        ])

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        model = LMStudioClient(http, "http://localhost:1234", "qwen")
        path = tmp_path / "queries.jsonl"
        result = generate(TOPIC, client=model, cache_path=path)
        assert result == generate(TOPIC, client=model, cache_path=path)
    assert len(calls) == 1
    assert result == {"questions": QUESTIONS, "queries": [
        "kinetic modelling of biomass pyrolysis", "isoconversional analysis thermogravimetry",
        *(query.lower() for query in BRANCHES[1:4]),
    ]}


def test_generation_retries_then_warns_and_falls_back(tmp_path: Path, caplog):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.content)
        return model_response(["too short"])

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
            searches.append(request.url.params["search"])
            return httpx.Response(200, json={"results": []})
        local_calls.append(request)
        return model_response(BRANCHES)

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
    assert len(local_calls) == (0 if manual else 1)
    assert searches[0] == ("manually supplied search" if manual else "kinetic modelling of biomass pyrolysis")
