import time

from app.modules.llm.base import LLMProvider


class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self):
        self.generate_calls = 0
        self.fail_generate = False
        self.invalid_generate_once = False

    async def generate(self, prompt: str, *, request_id: str, timeout_s: float, model: str):
        started = time.perf_counter()
        self.generate_calls += 1
        if self.fail_generate:
            raise RuntimeError("fake generate failure")
        prompt_lower = (prompt or "").lower()
        if self.invalid_generate_once:
            self.invalid_generate_once = False
            payload = {"narrative": "bad schema"}
        elif "story selection task" in prompt_lower:
            selected_choice_id = None
            if "study" in prompt_lower and "\"c1\"" in prompt:
                selected_choice_id = "c1"
            elif "date" in prompt_lower and "\"c2\"" in prompt:
                selected_choice_id = "c2"
            elif "work" in prompt_lower and "\"c3\"" in prompt:
                selected_choice_id = "c3"
            elif "rest" in prompt_lower and "\"c4\"" in prompt:
                selected_choice_id = "c4"

            if selected_choice_id and "nonsense" not in prompt_lower and "???" not in prompt_lower:
                payload = {
                    "choice_id": selected_choice_id,
                    "use_fallback": False,
                    "confidence": 0.8,
                    "intent_id": None,
                    "notes": "fake_selector_match",
                }
            else:
                payload = {
                    "choice_id": None,
                    "use_fallback": True,
                    "confidence": 0.0,
                    "intent_id": None,
                    "notes": "fake_selector_fallback",
                }
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
