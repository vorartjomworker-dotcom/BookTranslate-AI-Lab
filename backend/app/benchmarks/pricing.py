from __future__ import annotations

from app.benchmarks.types import PricingSnapshot
from app.core.exceptions import ValidationError


DEFAULT_PRICING_SNAPSHOTS: dict[str, PricingSnapshot] = {
    "openai:gpt-4o": PricingSnapshot(
        provider="openai",
        model="gpt-4o",
        currency="USD",
        input_cost_per_1k_tokens=0.005,
        output_cost_per_1k_tokens=0.015,
        effective_date="2026-08-15",
        version="2026.08.15",
        source="fixed benchmark snapshot; no live price sync",
    ),
    "anthropic:claude-3-5-sonnet-20240620": PricingSnapshot(
        provider="anthropic",
        model="claude-3-5-sonnet-20240620",
        currency="USD",
        input_cost_per_1k_tokens=0.003,
        output_cost_per_1k_tokens=0.015,
        effective_date="2026-08-15",
        version="2026.08.15",
        source="fixed benchmark snapshot; no live price sync",
    ),
    "deepl:free": PricingSnapshot(
        provider="deepl",
        model="free",
        currency="USD",
        input_cost_per_1k_tokens=0.0,
        output_cost_per_1k_tokens=0.0,
        effective_date="2026-08-15",
        version="2026.08.15",
        source="fixed benchmark snapshot; no live price sync",
    ),
}


def supported_provider_models() -> dict[str, tuple[str, ...]]:
    result: dict[str, list[str]] = {}
    for snapshot in DEFAULT_PRICING_SNAPSHOTS.values():
        result.setdefault(snapshot.provider, []).append(snapshot.model)
    return {provider: tuple(sorted(models)) for provider, models in result.items()}


def get_pricing_snapshot(provider: str, model: str | None = None) -> PricingSnapshot:
    provider_name = (provider or "").strip().lower()
    model_name = (model or "").strip()
    snapshot = DEFAULT_PRICING_SNAPSHOTS.get(f"{provider_name}:{model_name}")
    if snapshot is None:
        supported = supported_provider_models()
        raise ValidationError(
            "Unsupported benchmark provider/model combination.",
            details={
                "supported_provider_models": supported,
            },
        )
    return snapshot


def estimate_cost_usd(snapshot: PricingSnapshot, *, input_tokens: int, output_tokens: int) -> float:
    input_cost = (input_tokens / 1000.0) * snapshot.input_cost_per_1k_tokens
    output_cost = (output_tokens / 1000.0) * snapshot.output_cost_per_1k_tokens
    return round(input_cost + output_cost, 6)
