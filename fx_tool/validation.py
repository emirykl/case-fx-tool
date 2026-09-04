from __future__ import annotations

import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

from .errors import ServiceError, invalid_amount, invalid_currency, invalid_date


AMOUNT_PATTERN = re.compile(r"^(?:0|[1-9]\d*)(?:\.\d{1,2})?$")
CURRENCY_PATTERN = re.compile(r"^[A-Za-z]{3}$")
MAX_AMOUNT = Decimal("1000000000000")


def parse_amount(raw: Optional[str]) -> Decimal:
    if raw is None:
        raise invalid_amount("The amount query parameter is required.")
    if len(raw) > 24 or not AMOUNT_PATTERN.fullmatch(raw):
        raise invalid_amount(
            "Amount must be a positive decimal number with at most two decimal places."
        )
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        raise invalid_amount("Amount must be a valid decimal number.")
    if amount <= 0:
        raise invalid_amount("Amount must be greater than zero.")
    if amount > MAX_AMOUNT:
        raise invalid_amount("Amount must not exceed 1000000000000.")
    return amount


def parse_currency(raw: str, field: str) -> str:
    if not CURRENCY_PATTERN.fullmatch(raw):
        raise invalid_currency(f"{field} must be a three-letter currency code.")
    return raw.upper()


def parse_requested_date(raw: Optional[str]) -> Optional[date]:
    if raw is None:
        return None
    try:
        requested = date.fromisoformat(raw)
    except ValueError:
        raise invalid_date("Date must use the YYYY-MM-DD format.")
    today_utc = datetime.now(timezone.utc).date()
    if requested > today_utc:
        raise invalid_date("Date must not be in the future.")
    return requested


def validate_pair(base: str, target: str) -> None:
    if base == target:
        raise ServiceError(
            422,
            "same_currency",
            "Source and target currencies must be different.",
        )
