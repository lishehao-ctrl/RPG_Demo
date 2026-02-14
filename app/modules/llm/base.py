from abc import ABC, abstractmethod


class LLMProvider(ABC):
    name: str

    @abstractmethod
    async def classify(self, text: str, *, request_id: str, timeout_s: float, model: str):
        pass

    @abstractmethod
    async def generate(self, prompt: str, *, request_id: str, timeout_s: float, model: str):
        pass

    @abstractmethod
    async def summarize(self, history: str, *, request_id: str, timeout_s: float, model: str):
        pass
