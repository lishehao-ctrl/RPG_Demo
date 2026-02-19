import time

import httpx

from app.modules.llm.base import LLMProvider


class DoubaoProvider(LLMProvider):
    name = "doubao"

    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def _chat(self, content: str, *, timeout_s: float, model: str):
        started = time.perf_counter()
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.2,
        }
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        choice_content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        usage_raw = data.get("usage", {})
        usage = {
            "provider": self.name,
            "model": model,
            "prompt_tokens": int(usage_raw.get("prompt_tokens", 0) or 0),
            "completion_tokens": int(usage_raw.get("completion_tokens", 0) or 0),
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "status": "success",
            "error_message": None,
        }
        return choice_content, usage

    async def generate(self, prompt: str, *, request_id: str, timeout_s: float, model: str):
        return await self._chat(prompt, timeout_s=timeout_s, model=model)
