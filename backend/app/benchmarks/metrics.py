from __future__ import annotations

import math
from typing import Iterable


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = max(0.0, min(1.0, pct))
    index = rank * (len(ordered) - 1)
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return float(ordered[lower])
    fraction = index - lower
    return float(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction)


def round_metric(value: float, digits: int = 4) -> float:
    return round(float(value), digits)


def summarize_case_metrics(rows: Iterable[dict[str, object]]) -> dict[str, float | int]:
    processed = list(rows)
    if not processed:
        return {
            "case_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "success_rate": 0.0,
            "failure_rate": 0.0,
            "average_latency_ms": 0.0,
            "p50_latency_ms": 0.0,
            "p95_latency_ms": 0.0,
            "p99_latency_ms": 0.0,
            "throughput_cases_per_minute": 0.0,
            "average_qa_score": 0.0,
            "qa_pass_rate": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "total_estimated_cost_usd": 0.0,
            "cost_per_successful_case_usd": 0.0,
        }

    latencies = [float(item.get("latency_ms") or 0.0) for item in processed]
    success_count = sum(1 for item in processed if str(item.get("status") or "").lower() == "completed")
    failure_count = sum(1 for item in processed if str(item.get("status") or "").lower() in {"failed", "cancelled"})
    case_count = len(processed)
    avg_qa_score = sum(float(item.get("qa_score") or 0.0) for item in processed) / max(1, case_count)
    qa_passed = sum(1 for item in processed if bool(item.get("qa_passed")))
    total_tokens = sum(int(item.get("total_tokens") or 0) for item in processed)
    total_cost = sum(float(item.get("estimated_cost_usd") or 0.0) for item in processed)

    metrics = {
        "case_count": case_count,
        "success_count": success_count,
        "failure_count": failure_count,
        "success_rate": round_metric((success_count / case_count) * 100.0 if case_count else 0.0),
        "failure_rate": round_metric((failure_count / case_count) * 100.0 if case_count else 0.0),
        "average_latency_ms": round_metric(sum(latencies) / max(1, case_count)),
        "p50_latency_ms": round_metric(percentile(latencies, 0.50)),
        "p95_latency_ms": round_metric(percentile(latencies, 0.95)),
        "p99_latency_ms": round_metric(percentile(latencies, 0.99)),
        "throughput_cases_per_minute": round_metric((success_count / max(1.0, sum(latencies) / 60000.0)) if sum(latencies) else 0.0),
        "average_qa_score": round_metric(avg_qa_score),
        "qa_pass_rate": round_metric((qa_passed / case_count) * 100.0 if case_count else 0.0),
        "input_tokens": sum(int(item.get("input_tokens") or 0) for item in processed),
        "output_tokens": sum(int(item.get("output_tokens") or 0) for item in processed),
        "total_tokens": total_tokens,
        "total_estimated_cost_usd": round_metric(total_cost),
        "cost_per_successful_case_usd": round_metric((total_cost / success_count) if success_count else 0.0),
    }
    return metrics
