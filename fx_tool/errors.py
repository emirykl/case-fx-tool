from __future__ import annotations


class ServiceError(Exception):
    """An expected failure that is safe to expose through the API."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def invalid_amount(message: str) -> ServiceError:
    return ServiceError(422, "invalid_amount", message)


def invalid_currency(message: str) -> ServiceError:
    return ServiceError(422, "invalid_currency", message)


def invalid_date(message: str) -> ServiceError:
    return ServiceError(422, "invalid_date", message)


def unsupported_currency() -> ServiceError:
    return ServiceError(
        422, "unsupported_currency", "One or both currency codes are not supported."
    )


def rate_not_available() -> ServiceError:
    return ServiceError(
        404,
        "rate_not_available",
        "No exchange rate is available for the requested currencies and date.",
    )


def upstream_error(message: str) -> ServiceError:
    return ServiceError(502, "upstream_error", message)


def invalid_upstream_response(
    message: str = "The exchange-rate provider returned invalid data.",
) -> ServiceError:
    return ServiceError(502, "invalid_upstream_response", message)
