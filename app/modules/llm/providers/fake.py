import time

from app.modules.llm.base import LLMProvider


class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self):
        self.classify_calls = 0
        self.generate_calls = 0
        self.fail_classify = False
        self.fail_generate = False
        self.invalid_generate_once = False

    async def classify(self, text: str, *, request_id: str, timeout_s: float, model: str):
        started = time.perf_counter()
        self.classify_calls += 1
        if self.fail_classify:
            raise RuntimeError("fake classify failure")

        tags = ["kind"]
        t = text.lower()
        if "love" in t:
            tags.append("flirt")
        if "hate" in t:
            tags.append("aggressive")

        payload = {
            "intent": "romantic" if "flirt" in tags else "friendly",
            "tone": "warm" if "flirt" in tags else "calm",
            "behavior_tags": sorted(set(tags)),
            "risk_tags": [],
            "confidence": 0.88,
        }
        usage = {
            "provider": self.name,
            "model": model,
            "prompt_tokens": max(1, len(text) // 4),
            "completion_tokens": 32,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "status": "success",
            "error_message": None,
        }
        return payload, usage

    async def generate(self, prompt: str, *, request_id: str, timeout_s: float, model: str):
        started = time.perf_counter()
        self.generate_calls += 1
        if self.fail_generate:
            raise RuntimeError("fake generate failure")
        if self.invalid_generate_once:
            self.invalid_generate_once = False
            payload = {"narrative": "bad schema"}
        else:
            payload = {
                "narrative_text": "[llm] The evening breeze passes and she waits for your response.",
                "choices": [
                    {"id": "c1", "text": "Reply softly", "type": "dialog"},
                    {"id": "c2", "text": "Stay silent", "type": "action"},
                ],
            }
        usage = {
            "provider": self.name,
            "model": model,
            "prompt_tokens": max(1, len(prompt) // 4),
            "completion_tokens": 64,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "status": "success",
            "error_message": None,
        }
        return payload, usage

    async def summarize(self, history: str, *, request_id: str, timeout_s: float, model: str):
        return history[-200:], {
            "provider": self.name,
            "model": model,
            "prompt_tokens": max(1, len(history) // 4),
            "completion_tokens": 24,
            "latency_ms": 1,
            "status": "success",
            "error_message": None,
        }
