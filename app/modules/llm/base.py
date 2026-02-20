from abc import ABC, abstractmethod


class LLMProvider(ABC):
    name: str

    @abstractmethod
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
        pass
