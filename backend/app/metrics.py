from __future__ import annotations

from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest


HTTP_REQUESTS_TOTAL = Counter(
    "booktranslate_http_requests_total",
    "Total HTTP requests handled by the backend.",
    labelnames=("method", "route", "status"),
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "booktranslate_http_request_duration_seconds",
    "Backend HTTP request duration in seconds.",
    labelnames=("method", "route"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)


def route_template(scope: dict[str, Any]) -> str:
    """Return a bounded-cardinality route template, never an arbitrary request path."""
    route = scope.get("route")
    template = getattr(route, "path", None)
    if isinstance(template, str) and template:
        return template
    return "__unmatched__"


def observe_http_request(*, method: str, route: str, status_code: int, duration_seconds: float) -> None:
    """Record request metrics without allowing monitoring failure to affect application traffic."""
    try:
        method_label = method.upper()[:16] or "UNKNOWN"
        route_label = route if route else "__unmatched__"
        status_label = str(int(status_code))
        duration = max(float(duration_seconds), 0.0)

        HTTP_REQUESTS_TOTAL.labels(method=method_label, route=route_label, status=status_label).inc()
        HTTP_REQUEST_DURATION_SECONDS.labels(method=method_label, route=route_label).observe(duration)
    except Exception:
        return


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
