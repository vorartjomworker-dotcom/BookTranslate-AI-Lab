from __future__ import annotations

from urllib.parse import urlsplit


def safe_redis_endpoint(redis_url: str) -> str:
    """Return a credential-free Redis endpoint suitable for application logs.

    User information, passwords, database paths, query strings, and fragments are
    deliberately omitted. Invalid URLs never fall back to returning the raw input.
    """
    try:
        parsed = urlsplit(redis_url)
        scheme = parsed.scheme.lower()
        host = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError):
        return "redis://<configured>"

    if scheme not in {"redis", "rediss"} or not host:
        return "redis://<configured>"

    if ":" in host and not host.startswith("["):
        host = f"[{host}]"

    port_suffix = f":{port}" if port is not None else ""
    return f"{scheme}://{host}{port_suffix}"
