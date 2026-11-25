import json
import logging
import re
from typing import Any
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger(__name__)
THINK_BLOCK = re.compile(r"<think>.*?</think>", flags=re.I | re.S)


class LMStudioError(Exception):
    """A reportable LM Studio error without request or response contents."""


class LMStudioClient:
    def __init__(self, client: httpx.Client, base_url: str, model: str) -> None:
        self._client = client
        base = base_url.rstrip("/")
        self._url = base + ("/v1" if not urlsplit(base).path else "") + "/chat/completions"
        self.model = model
        self.tokens_in = 0
        self.tokens_out = 0

    def chat_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        self.tokens_in = self.tokens_out = 0
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0,
            "chat_template_kwargs": {"enable_thinking": False},
            "reasoning_effort": "none",
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "response", "strict": True, "schema": schema},
            },
        }
        for _ in range(2):
            response = self._request(payload)
            try:
                body = response.json()
                self._record_usage(body.get("usage"))
                content = body["choices"][0]["message"]["content"]
                result = json.loads(THINK_BLOCK.sub("", content))
                if isinstance(result, dict):
                    return result
            except (AttributeError, IndexError, KeyError, TypeError, ValueError):
                continue
        return {"error": "LM Studio returned invalid JSON after a retry."}

    def _request(self, payload: dict[str, Any]) -> httpx.Response:
        for _ in range(2):
            try:
                response = self._client.post(self._url, json=payload, timeout=120, follow_redirects=False)
            except (httpx.ConnectError, httpx.ConnectTimeout):
                continue
            except httpx.RequestError:
                break
            if not response.is_success:
                raise LMStudioError(f"LM Studio returned HTTP {response.status_code}. Check the server and model configuration.")
            return response
        raise LMStudioError("Could not reach LM Studio. Check that its local server is running.")

    def _record_usage(self, usage: object) -> None:
        if isinstance(usage, dict):
            tokens_in = usage.get("prompt_tokens", 0)
            tokens_out = usage.get("completion_tokens", 0)
            tokens_in = tokens_in if isinstance(tokens_in, int) and tokens_in >= 0 else 0
            tokens_out = tokens_out if isinstance(tokens_out, int) and tokens_out >= 0 else 0
            self.tokens_in += tokens_in
            self.tokens_out += tokens_out
            logger.info("LM Studio usage: %d tokens in, %d tokens out", tokens_in, tokens_out)
