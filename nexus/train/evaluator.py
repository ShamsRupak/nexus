"""Before/after benchmark for fine-tuned models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BenchmarkResult:
    model: str
    accuracy: float
    latency_ms: float
    samples_evaluated: int


class ModelEvaluator:
    """Evaluates model quality before and after fine-tuning."""

    async def evaluate(self, model_path: str, test_data: list[dict]) -> BenchmarkResult:
        raise NotImplementedError("Model evaluation requires GPU environment")
