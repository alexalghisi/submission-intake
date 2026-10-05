"""A minimal OpenAI-compatible chat client for LLMExtractor. Standard library only."""

from __future__ import annotations

import json
import os
import urllib.request


class OpenAIClient:
    def __init__(
        self, model: str = "gpt-4o-mini", base_url: str = "https://api.openai.com/v1", timeout: float = 60
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.api_key = os.environ["OPENAI_API_KEY"]

    def complete_json(self, system: str, user: str) -> str:
        body = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read())
        return str(payload["choices"][0]["message"]["content"])
