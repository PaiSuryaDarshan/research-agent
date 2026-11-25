import csv
import json
from pathlib import Path

import httpx

from research_agent.agents.research.screening import DECISION_SCHEMA, screen_run
from research_agent.cli import main
from research_agent.llm.lmstudio import LMStudioClient


def response(content: str) -> httpx.Response:
    return httpx.Response(200, json={
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 4},
    })


def make_run(folder: Path, count: int = 3) -> None:
    (folder / "run.json").write_text('{"topic":"Biomass","queries":["pyrolysis"]}', encoding="utf-8")
    with (folder / "candidates.jsonl").open("w", encoding="utf-8") as output:
        for i in range(1, count + 1):
            output.write(json.dumps({
                "openalex_id": f"W{i}", "title": f"Paper {i}", "year": 2025, "venue": "Journal",
                "type": "article", "cited_by_count": 0, "abstract": "Biomass" if i == 1 else None,
                "authors": [], "referenced_works": [], "found_by": [], "rank": i,
            }) + "\n")


def test_chat_strips_think_block_and_tracks_usage():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.extensions["timeout"]["read"] == 120
        payload = json.loads(request.content)
        assert payload["temperature"] == 0
        assert payload["chat_template_kwargs"] == {"enable_thinking": False}
        assert payload["response_format"]["json_schema"]["schema"] == DECISION_SCHEMA
        return response('<think>line one\nline two</think>{"decision":"include","reason":"Relevant."}')

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = LMStudioClient(http, "http://localhost:1234", "qwen")
        assert client.chat_json("system", "user", DECISION_SCHEMA)["decision"] == "include"
        assert (client.tokens_in, client.tokens_out) == (10, 4)


def test_invalid_json_retries_and_is_kept(tmp_path: Path):
    make_run(tmp_path, 1)
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            assert request.url.path == "/api/v0/models"
            return httpx.Response(404)
        requests.append(request.content)
        return response("broken JSON")

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        stats = screen_run(tmp_path, LMStudioClient(http, "http://localhost:1234/v1", "qwen"))
    assert len(requests) == 2 and requests[0] == requests[1]
    assert stats["decisions"] == {"include": 0, "exclude": 0, "unsure": 1}
    assert stats["kept"] == stats["errors"] == 1
    assert stats["total_tokens"] == 28
    assert (stats["tokens_in"], stats["tokens_out"]) == (20, 8)
    assert stats["model_info"] == "unavailable"
    assert json.loads((tmp_path / "screened.jsonl").read_text(encoding="utf-8"))["decision"] == "unsure"


def test_screen_routes_decisions_and_resumes_by_prompt(tmp_path: Path):
    make_run(tmp_path)
    questions = ["How do pyrolysis rates vary with feedstock?"]
    metadata_path = tmp_path / "run.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata_path.write_text(json.dumps({**metadata, "questions": questions}), encoding="utf-8")
    prompts = []
    decisions = {"Paper 1": "include", "Paper 2": "exclude", "Paper 3": "unsure"}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"data": [
                {"id": "qwen", "state": "loaded", "quantization": "Q4_K_M",
                 "loaded_context_length": 4096, "max_context_length": 32768},
            ]})
        body = json.loads(request.content)
        prompt = json.loads(body["messages"][1]["content"])
        prompts.append(prompt)
        return response(json.dumps({"decision": decisions[prompt["paper"]["title"]], "reason": "Test reason."}))

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = LMStudioClient(http, "http://localhost:1234", "qwen")
        screen_run(tmp_path, client, limit=1)
        stats = screen_run(tmp_path, client)
        assert len(prompts) == 3 and stats["cache_hits"] == 1
        assert stats["decisions"] == dict.fromkeys(decisions.values(), 1)
        assert stats["model_info"] == {"id": "qwen", "quantization": "Q4_K_M",
                                       "context_length": 4096, "max_context_length": 32768}
        assert (stats["tokens_in"], stats["tokens_out"]) == (30, 12)
        assert stats["by_abstract_source"]["none"] == {"include": 0, "exclude": 1, "unsure": 1}
        kept = (tmp_path / "screened.jsonl").read_text(encoding="utf-8").splitlines()
        assert [json.loads(row)["decision"] for row in kept] == ["include", "unsure"]
        with (tmp_path / "screening_excluded.csv").open(encoding="utf-8", newline="") as file:
            assert list(csv.DictReader(file))[0]["title"] == "Paper 2"
        assert prompts[0]["paper"]["abstract"] == "[openalex] Biomass"
        assert prompts[0]["research_questions"] == questions
        assert prompts[1]["paper"]["abstract"] == "NO ABSTRACT"
        assert json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))["screening"] == stats
        assert screen_run(tmp_path, client, criteria="New scope", limit=1)["cache_hits"] == 0
        assert len(prompts) == 4


def test_cli_limit_and_unreachable(tmp_path: Path, monkeypatch, capsys):
    make_run(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LMSTUDIO_MODEL", "qwen")
    requested = []
    real_client = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(404)
        requested.append(request)
        if len(requested) > 1:
            raise httpx.ConnectError("hidden request details", request=request)
        return response('{"decision":"include","reason":"Relevant."}')

    monkeypatch.setattr(httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    assert main(["screen", str(tmp_path), "--limit", "1"]) == 0
    assert len(requested) == 1
    assert main(["screen", str(tmp_path), "--limit", "1", "--criteria", "Changed"]) == 2
    assert len(requested) == 3
    output = capsys.readouterr()
    assert "Could not reach LM Studio" in output.err
    assert "hidden request details" not in output.err
    assert "Tokens in: 10 | Tokens out: 4" in output.out


def test_missing_abstract_cannot_be_included(tmp_path: Path):
    make_run(tmp_path, 2)
    transport = httpx.MockTransport(
        lambda request: response('{"decision":"include","reason":"The title is relevant."}')
    )
    with httpx.Client(transport=transport) as http:
        stats = screen_run(tmp_path, LMStudioClient(http, "http://localhost:1234", "qwen"))
    assert stats["decisions"] == {"include": 1, "exclude": 0, "unsure": 1}
    assert stats["by_abstract_source"]["none"] == {"include": 0, "exclude": 0, "unsure": 1}


def test_foundational_paper_is_included_without_model_call(tmp_path: Path):
    make_run(tmp_path, 2)
    path = tmp_path / "candidates.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[1].update(foundational=True, foundational_count=4)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    posts = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(404)
        posts.append(request)
        return response('{"decision":"exclude","reason":"Off-topic."}')

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        stats = screen_run(tmp_path, LMStudioClient(http, "http://localhost:1234", "qwen"))
    kept = json.loads((tmp_path / "screened.jsonl").read_text(encoding="utf-8"))
    assert len(posts) == stats["foundational_included"] == 1
    assert (kept["rank"], kept["decision"], kept["reason"]) == (
        2, "include", "foundational: cited by 4 search hits"
    )
    assert stats["decisions"] == {"include": 1, "exclude": 1, "unsure": 0}
    assert stats["total_tokens"] == 14
