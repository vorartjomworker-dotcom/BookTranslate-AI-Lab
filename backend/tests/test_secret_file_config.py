from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import _MAX_SECRET_FILE_BYTES, _read_secret_file_values, load_settings


_TEST_JWT_SECRET = "mounted-jwt-secret-at-least-32-characters-long"


def _write_secret(path: Path, value: str) -> Path:
    path.write_text(value, encoding="utf-8")
    return path


def test_read_secret_file_values_supports_runtime_secrets_and_strips_only_newline(tmp_path: Path) -> None:
    jwt_file = _write_secret(tmp_path / "jwt", _TEST_JWT_SECRET + "\n")
    redis_value = "rediss://:redis-secret@cache.example:6380/0"
    redis_file = _write_secret(tmp_path / "redis-url", redis_value + "\r\n")
    provider_value = " provider-secret-with-spaces "
    provider_file = _write_secret(tmp_path / "openai", provider_value + "\n")

    values = _read_secret_file_values(
        {
            "JWT_SECRET_FILE": str(jwt_file),
            "REDIS_URL_FILE": str(redis_file),
            "OPENAI_API_KEY_FILE": str(provider_file),
        }
    )

    assert values == {
        "jwt_secret": _TEST_JWT_SECRET,
        "redis_url": redis_value,
        "openai_api_key": provider_value,
    }


def test_load_settings_reads_mounted_secret_files(monkeypatch, tmp_path: Path) -> None:
    jwt_file = _write_secret(tmp_path / "jwt", _TEST_JWT_SECRET + "\n")
    redis_file = _write_secret(
        tmp_path / "redis-url",
        "rediss://:redis-secret@cache.example:6380/0\n",
    )
    metrics_file = _write_secret(
        tmp_path / "metrics",
        "metrics-secret-at-least-32-characters-long\n",
    )

    for name in ("JWT_SECRET", "REDIS_URL", "METRICS_BEARER_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("JWT_SECRET_FILE", str(jwt_file))
    monkeypatch.setenv("REDIS_URL_FILE", str(redis_file))
    monkeypatch.setenv("METRICS_BEARER_TOKEN_FILE", str(metrics_file))
    monkeypatch.setenv("REDIS_TLS_REQUIRED", "true")
    monkeypatch.setenv("METRICS_ENABLED", "true")

    loaded = load_settings()

    assert loaded.jwt_secret == _TEST_JWT_SECRET
    assert loaded.redis_url == "rediss://:redis-secret@cache.example:6380/0"
    assert loaded.redis_tls_required is True
    assert loaded.metrics_bearer_token == "metrics-secret-at-least-32-characters-long"
    assert loaded.metrics_enabled is True


def test_direct_and_file_backed_secret_are_mutually_exclusive(tmp_path: Path) -> None:
    secret_file = _write_secret(tmp_path / "jwt", "file-secret-value")

    with pytest.raises(RuntimeError, match="JWT_SECRET and JWT_SECRET_FILE cannot both be set"):
        _read_secret_file_values(
            {
                "JWT_SECRET": "direct-secret-value",
                "JWT_SECRET_FILE": str(secret_file),
            }
        )


def test_missing_secret_file_fails_without_echoing_path_or_secret_name_content(tmp_path: Path) -> None:
    missing = tmp_path / "sensitive-filename-do-not-echo-secret-value"

    with pytest.raises(RuntimeError, match="JWT_SECRET_FILE could not be read") as exc_info:
        _read_secret_file_values({"JWT_SECRET_FILE": str(missing)})

    assert str(missing) not in str(exc_info.value)
    assert "do-not-echo-secret-value" not in str(exc_info.value)


def test_empty_secret_file_is_rejected(tmp_path: Path) -> None:
    empty = _write_secret(tmp_path / "empty", "\r\n")

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY_FILE references an empty secret"):
        _read_secret_file_values({"OPENAI_API_KEY_FILE": str(empty)})


def test_secret_file_size_is_bounded(tmp_path: Path) -> None:
    oversized = _write_secret(tmp_path / "oversized", "x" * (_MAX_SECRET_FILE_BYTES + 1))

    with pytest.raises(RuntimeError, match="DEEPL_API_KEY_FILE exceeds the maximum supported secret size"):
        _read_secret_file_values({"DEEPL_API_KEY_FILE": str(oversized)})


def test_secret_file_must_be_regular_file(tmp_path: Path) -> None:
    directory = tmp_path / "secret-directory"
    directory.mkdir()

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY_FILE must reference a regular file"):
        _read_secret_file_values({"ANTHROPIC_API_KEY_FILE": str(directory)})
