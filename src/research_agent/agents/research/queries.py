import json
import logging
import re
from hashlib import sha256
from pathlib import Path
from typing import TypedDict

from research_agent.llm.lmstudio import LMStudioClient, local_client

logger = logging.getLogger(__name__)
CACHE_PATH = Path("data/cache/queries.jsonl")
SYSTEM_PROMPT = (
    "You are an expert literature-search strategist. Write research questions that a rigorous "
    "review of the topic must answer. Then write scholarly search queries, 3 to 8 words each, "
    "each covering a DIFFERENT branch: methods, models, materials or systems, applications, "
    "and foundational or classic methods of the field. Do not repeat the topic verbatim. "
    "Use no Boolean operators, quotes, or years. Return only the JSON object."
)
SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 5},
        "queries": {"type": "array", "items": {"type": "string"}, "minItems": 5, "maxItems": 8},
    },
    "required": ["questions", "queries"],
    "additionalProperties": False,
}


class QueryPlan(TypedDict):
    questions: list[str]
    queries: list[str]


def _normalize(text: str) -> str:
    return " ".join(re.findall(r"[^\W_]+", text.lower()))


def _select(topic_query: str, suggestions: list[str], limit: int) -> list[str]:
    selected = [topic_query]
    earlier = [set(topic_query.split())]
    for suggestion in suggestions:
        query = _normalize(suggestion)
        words = query.split()
        terms = set(words)
        if not 3 <= len(words) <= 8 or terms & {"and", "or", "not"}:
            continue
        if any(re.fullmatch(r"(?:18|19|20)\d{2}", word) for word in words):
            continue
        if any(len(terms & other) / len(terms | other) >= 0.6 for other in earlier):
            continue
        selected.append(query)
        earlier.append(terms)
        if len(selected) == limit:
            break
    return selected


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _cached(path: Path, key: str, topic_query: str) -> QueryPlan | None:
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as file:
        for line in file:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("key") == key:
                questions = _strings(row.get("questions"))
                queries = _strings(row.get("queries"))
                if 3 <= len(questions) <= 5 and 4 <= len(queries) <= 8 and queries[0] == topic_query:
                    return {"questions": questions, "queries": queries}
    return None


def generate(
    topic: str,
    n_questions: int = 3,
    n_queries: int = 5,
    *,
    client: LMStudioClient | None = None,
    cache_path: Path = CACHE_PATH,
) -> QueryPlan:
    topic_query = _normalize(topic)
    if not topic_query:
        raise ValueError("Topic must contain at least one word.")
    if not 3 <= n_questions <= 5 or not 5 <= n_queries <= 8:
        raise ValueError("Request 3–5 questions and 5–8 queries.")
    if client is None:
        with local_client() as local:
            return generate(topic, n_questions, n_queries, client=local, cache_path=cache_path)

    prompt = json.dumps({
        "topic": topic, "question_count": n_questions, "branch_query_count": n_queries,
    }, ensure_ascii=False)
    fingerprint = json.dumps([topic, client.model, SYSTEM_PROMPT, prompt, SCHEMA], sort_keys=True)
    key = sha256(fingerprint.encode("utf-8")).hexdigest()
    cached = _cached(cache_path, key, topic_query)
    if cached is not None:
        return cached

    questions = []
    for _ in range(2):
        response = client.chat_json(SYSTEM_PROMPT, prompt, SCHEMA)
        proposed_questions = _strings(response.get("questions"))[:n_questions]
        if len(proposed_questions) >= 3:
            questions = proposed_questions
        queries = _select(topic_query, _strings(response.get("queries")), n_queries)
        if len(queries) >= 4 and len(questions) >= 3:
            result: QueryPlan = {"questions": questions, "queries": queries}
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with cache_path.open("a+b") as file:
                file.seek(0, 2)
                if file.tell():
                    file.seek(-1, 2)
                    if file.read() != b"\n":
                        file.write(b"\n")
                file.write((json.dumps({"key": key, **result}, ensure_ascii=False) + "\n").encode("utf-8"))
            return result
    logger.warning("Query generation did not produce a usable plan after two attempts. Using the topic alone.")
    return {"questions": questions, "queries": [topic_query]}
