from __future__ import annotations

from app.benchmarks.types import PricingSnapshot


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


def get_pricing_snapshot(provider: str, model: str | None = None) -> PricingSnapshot:
    provider_name = (provider or "openai").strip().lower()
    model_name = (model or "gpt-4o").strip()
    key = f"{provider_name}:{model_name}"
    snapshot = DEFAULT_PRICING_SNAPSHOTS.get(key)
    if snapshot is not None:
        return snapshot
    if provider_name == "openai":
        return DEFAULT_PRICING_SNAPSHOTS["openai:gpt-4o"]
    if provider_name == "anthropic":
        return DEFAULT_PRICING_SNAPSHOTS["anthropic:claude-3-5-sonnet-20240620"]
    if provider_name == "deepl":
        return DEFAULT_PRICING_SNAPSHOTS["deepl:free"]
    return PricingSnapshot(
        provider=provider_name,
        model=model_name,
        currency="USD",
        input_cost_per_1k_tokens=0.0,
        output_cost_per_1k_tokens=0.0,
        effective_date="2026-08-15",
        version="2026.08.15",
        source="fallback benchmark snapshot",
    )


def estimate_cost_usd(snapshot: PricingSnapshot, *, input_tokens: int, output_tokens: int) -> float:
    input_cost = (input_tokens / 1000.0) * snapshot.input_cost_per_1k_tokens
    output_cost = (output_tokens / 1000.0) * snapshot.output_cost_per_1k_tokens
    return round(input_cost + output_cost, 6)
