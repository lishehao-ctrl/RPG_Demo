import time

from app.modules.llm.base import LLMProvider
from app.modules.llm.runtime.chat_completions_client import call_llm_messages


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
        self.base_url = "https://api.xiaocaseai.cloud"
        # Fail-fast proxy mode: always force temperature=0 at request time.
        self.temperature = 0.0
        self.max_tokens = int(max_tokens) if max_tokens is not None else None

    async def _chat(
        self,
        content: str,
        *,
        timeout_s: float | None,
        model: str,
        connect_timeout_s: float | None = None,
        read_timeout_s: float | None = None,
        write_timeout_s: float | None = None,
        pool_timeout_s: float | None = None,
        max_tokens_override: int | None = None,
        temperature_override: float | None = None,
        messages_override: list[dict] | None = None,
    ):
        started = time.perf_counter()
        messages = messages_override if isinstance(messages_override, list) else None
        if not messages:
            messages = [{"role": "user", "content": content}]
        data = await call_llm_messages(api_key=self.api_key, model=model, messages=messages)

        choice_content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        usage_raw = data.get("usage", {})
        usage = {
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
        timeout_s: float | None,
        model: str,
        connect_timeout_s: float | None = None,
        read_timeout_s: float | None = None,
        write_timeout_s: float | None = None,
        pool_timeout_s: float | None = None,
        max_tokens_override: int | None = None,
        temperature_override: float | None = None,
        messages_override: list[dict] | None = None,
    ):
        return await self._chat(
            prompt,
            timeout_s=timeout_s,
            model=model,
            connect_timeout_s=connect_timeout_s,
            read_timeout_s=read_timeout_s,
            write_timeout_s=write_timeout_s,
            pool_timeout_s=pool_timeout_s,
            max_tokens_override=max_tokens_override,
            temperature_override=temperature_override,
            messages_override=messages_override,
        )
