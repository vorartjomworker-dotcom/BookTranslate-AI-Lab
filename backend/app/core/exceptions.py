from __future__ import annotations

from typing import Any, Mapping


class APIError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        http_status: int = 500,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.http_status = http_status
        self.details = dict(details or {})

    def to_dict(self, request_id: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }
        if request_id is not None:
            payload["request_id"] = request_id
        return payload


class NotFoundError(APIError):
    def __init__(self, resource: str, resource_id: Any | None = None) -> None:
        details = {"resource": resource}
        if resource_id is not None:
            details["id"] = resource_id
        super().__init__(
            f"{resource.title()} not found.",
            code="not_found",
            http_status=404,
            details=details,
        )


class ConflictError(APIError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(
            message,
            code="conflict",
            http_status=409,
            details=details or {},
        )


class ValidationError(APIError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(
            message,
            code="validation_error",
            http_status=422,
            details=details or {},
        )


class PayloadTooLargeError(APIError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(
            message,
            code="payload_too_large",
            http_status=413,
            details=details or {},
        )


class UnsupportedMediaTypeError(APIError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(
            message,
            code="unsupported_media_type",
            http_status=415,
            details=details or {},
        )
