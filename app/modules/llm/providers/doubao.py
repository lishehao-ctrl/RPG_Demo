import time

import httpx

from app.modules.llm.base import LLMProvider


class DoubaoProvider(LLMProvider):
    name = "doubao"

    def __init__(
        self,
        api_key: str,
        base_url: str,
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.temperature = float(temperature)
        self.max_tokens = int(max_tokens) if max_tokens is not None else None

    async def _chat(
        self,
        content: str,
        *,
        timeout_s: float,
        model: str,
        connect_timeout_s: float | None = None,
        read_timeout_s: float | None = None,
        write_timeout_s: float | None = None,
        pool_timeout_s: float | None = None,
    ):
        started = time.perf_counter()
        headers = {"authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "temperature": self.temperature,
        }
        if self.max_tokens is not None and self.max_tokens > 0:
            payload["max_tokens"] = self.max_tokens
        timeout = httpx.Timeout(
            timeout=timeout_s,
            connect=connect_timeout_s if connect_timeout_s is not None else timeout_s,
            read=read_timeout_s if read_timeout_s is not None else timeout_s,
            write=write_timeout_s if write_timeout_s is not None else timeout_s,
            pool=pool_timeout_s if pool_timeout_s is not None else timeout_s,
        )
        async with httpx.AsyncClient(timeout=timeout) as client:
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

    async def generate(
        self,
        prompt: str,
        *,
        request_id: str,
        timeout_s: float,
        model: str,
        connect_timeout_s: float | None = None,
        read_timeout_s: float | None = None,
        write_timeout_s: float | None = None,
        pool_timeout_s: float | None = None,
    ):
        return await self._chat(
            prompt,
            timeout_s=timeout_s,
            model=model,
            connect_timeout_s=connect_timeout_s,
            read_timeout_s=read_timeout_s,
            write_timeout_s=write_timeout_s,
            pool_timeout_s=pool_timeout_s,
        )
