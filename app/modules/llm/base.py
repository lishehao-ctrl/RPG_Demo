from abc import ABC, abstractmethod


class LLMProvider(ABC):
    name: str

    @abstractmethod
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
        pass
