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

