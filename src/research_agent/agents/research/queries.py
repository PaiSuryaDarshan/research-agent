import json
import logging
import re
from hashlib import sha256
from pathlib import Path
from typing import TypedDict

from research_agent.llm.lmstudio import LMStudioClient, local_client
from .ranking import STOPWORDS

logger = logging.getLogger(__name__)
CACHE_PATH = Path("data/cache/queries.jsonl")
SEED_LIMIT = 5
SYSTEM_PROMPT = (
    "You are an expert literature-search strategist. Write research questions that a rigorous "
    "review of the topic must answer. Return an anchor of 1 to 3 words naming the system or "
    "material at the core of the topic, using its terms. Write exactly five scholarly search "
    "queries, each covering a different aspect of the topic. Prefer concrete techniques and named "
    "models over general phrases. Use 3 to 10 words per query, "
    "including the anchor when useful. Do not repeat the topic verbatim or use Boolean "
    "operators, quotes, or years. Return only the JSON object."
)
SCHEMA = {
    "type": "object",
    "properties": {
        "anchor": {"type": "string"},
        "questions": {"type": "array", "items": {"type": "string"}, "minItems": 4, "maxItems": 5},
        "queries": {"type": "array", "items": {"type": "string"}, "minItems": 5, "maxItems": 5},
    },
    "required": ["anchor", "questions", "queries"],
    "additionalProperties": False,
}


class QueryDetail(TypedDict):
    query: str
    branch: str
    anchor_appended: bool


class QueryPlan(TypedDict):
    anchor: str | None
    questions: list[str]
    queries: list[str]
    query_details: list[QueryDetail]


def normalize_query(text: str) -> str:
    return " ".join(re.findall(r"[^\W_]+", text.lower()))


def prepare_query(suggestion: str, anchor: str, earlier: list[set[str]]) -> tuple[str, bool] | None:
    query = normalize_query(suggestion)
    if not query:
        return None
    appended = bool(anchor) and not (set(query.split()) & (set(anchor.split()) - STOPWORDS))
    if appended:
        query = f"{query} {anchor}"
    words = query.split()
    terms = set(words)
    if not 3 <= len(words) <= 10 or re.search(r"\b(?:AND|OR|NOT)\b", suggestion):
        return None
    if any(re.fullmatch(r"(?:18|19|20)\d{2}", word) for word in words):
        return None
    if any(len(terms & other) / len(terms | other) >= 0.6 for other in earlier):
        return None
    return query, appended


def _select(topic_query: str, anchor: str, suggestions: object) -> list[QueryDetail]:
    selected: list[QueryDetail] = [{"query": topic_query, "branch": "topic", "anchor_appended": False}]
    if not isinstance(suggestions, list):
        return selected
    earlier = [set(topic_query.split())]
    for suggestion in suggestions[:SEED_LIMIT]:
        prepared = prepare_query(suggestion, anchor, earlier) if isinstance(suggestion, str) else None
        if prepared is None:
            continue
        query, appended = prepared
        selected.append({"query": query, "branch": "free-form", "anchor_appended": appended})
        earlier.append(set(query.split()))
        if len(selected) == SEED_LIMIT:
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
                anchor, details = row.get("anchor"), row.get("query_details")
                if (isinstance(anchor, str) and isinstance(details, list) and len(details) == len(queries)
                        and 4 <= len(questions) <= 5 and 4 <= len(queries) <= SEED_LIMIT and queries[0] == topic_query):
                    return {"anchor": anchor, "questions": questions, "queries": queries, "query_details": details}
    return None


def generate(
    topic: str,
    n_questions: int = 4,
    *,
    client: LMStudioClient | None = None,
    cache_path: Path = CACHE_PATH,
) -> QueryPlan:
    topic_query = normalize_query(topic)
    if not topic_query:
        raise ValueError("Topic must contain at least one word.")
    if not 4 <= n_questions <= 5:
        raise ValueError("Request 4–5 research questions.")
    if client is None:
        with local_client() as local:
            return generate(topic, n_questions, client=local, cache_path=cache_path)

    prompt = json.dumps({
        "topic": topic, "question_count": n_questions,
    }, ensure_ascii=False)
    fingerprint = json.dumps([topic, client.model, SYSTEM_PROMPT, prompt, SCHEMA], sort_keys=True)
    key = sha256(fingerprint.encode("utf-8")).hexdigest()
    cached = _cached(cache_path, key, topic_query)
    if cached is not None:
        return cached

    questions = []
    anchor = None
    fallback_details = _select(topic_query, "", None)
    for _ in range(2):
        response = client.chat_json(SYSTEM_PROMPT, prompt, SCHEMA)
        proposed_questions = _strings(response.get("questions"))[:n_questions]
        if len(proposed_questions) >= 4:
            questions = proposed_questions
        raw_anchor = response.get("anchor")
        proposed_anchor = normalize_query(raw_anchor) if isinstance(raw_anchor, str) else ""
        if not 1 <= len(proposed_anchor.split()) <= 3 or not (set(proposed_anchor.split()) - STOPWORDS):
            continue
        anchor = proposed_anchor
        details = _select(topic_query, anchor, response.get("queries"))
        if len(details) >= 4 and len(questions) >= 4:
            result: QueryPlan = {
                "anchor": anchor, "questions": questions,
                "queries": [detail["query"] for detail in details], "query_details": details,
            }
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
    return {"anchor": anchor, "questions": questions, "queries": [topic_query], "query_details": fallback_details}
