from __future__ import annotations

from collections import Counter
from statistics import mean
from threading import Lock

from app.modules.runtime.schemas import StepResponse


class _RuntimeTelemetryStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._success_latencies_ms: list[float] = []
        self.total_step_requests: int = 0
        self.successful_steps: int = 0
        self.failed_steps: int = 0
        self.llm_unavailable_errors: int = 0
        self.fallback_steps: int = 0
        self.ending_distribution: Counter[str] = Counter()

    def reset(self) -> None:
        with self._lock:
            self._success_latencies_ms = []
            self.total_step_requests = 0
            self.successful_steps = 0
            self.failed_steps = 0
            self.llm_unavailable_errors = 0
            self.fallback_steps = 0
            self.ending_distribution = Counter()

    def record_success(self, *, latency_ms: float, step: StepResponse) -> None:
        with self._lock:
            self.total_step_requests += 1
            self.successful_steps += 1
            self._success_latencies_ms.append(float(latency_ms))
            if len(self._success_latencies_ms) > 1000:
                self._success_latencies_ms = self._success_latencies_ms[-1000:]

            if bool(step.fallback_used):
                self.fallback_steps += 1
            if bool(step.run_ended) and step.ending_id:
                self.ending_distribution[str(step.ending_id)] += 1

    def record_failure(self, *, error_code: str) -> None:
        with self._lock:
            self.total_step_requests += 1
            self.failed_steps += 1
            if str(error_code) == "LLM_UNAVAILABLE":
                self.llm_unavailable_errors += 1

    def summary(self) -> dict:
        with self._lock:
            latencies = list(self._success_latencies_ms)
            successful = int(self.successful_steps)
            total = int(self.total_step_requests)
            fallback_rate = 0.0 if successful <= 0 else float(self.fallback_steps) / float(successful)
            llm_ratio = 0.0 if total <= 0 else float(self.llm_unavailable_errors) / float(total)

            avg_latency = float(mean(latencies)) if latencies else 0.0
            p95_latency = 0.0
            if latencies:
                ordered = sorted(latencies)
                idx = max(0, min(len(ordered) - 1, round(0.95 * (len(ordered) - 1))))
                p95_latency = float(ordered[idx])

            return {
                "total_step_requests": total,
                "successful_steps": successful,
                "failed_steps": int(self.failed_steps),
                "avg_step_latency_ms": round(avg_latency, 3),
                "p95_step_latency_ms": round(p95_latency, 3),
                "fallback_rate": round(fallback_rate, 4),
                "ending_distribution": dict(self.ending_distribution),
                "llm_unavailable_errors": int(self.llm_unavailable_errors),
                "llm_unavailable_ratio": round(llm_ratio, 4),
            }


_runtime_telemetry = _RuntimeTelemetryStore()


def reset_runtime_telemetry() -> None:
    _runtime_telemetry.reset()


def record_step_success(*, latency_ms: float, step: StepResponse) -> None:
    _runtime_telemetry.record_success(latency_ms=latency_ms, step=step)


def record_step_failure(*, error_code: str) -> None:
    _runtime_telemetry.record_failure(error_code=error_code)


def get_runtime_telemetry_summary() -> dict:
    return _runtime_telemetry.summary()
