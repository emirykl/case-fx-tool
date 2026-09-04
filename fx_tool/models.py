from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class ConversionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    amount: Decimal
    from_: str = Field(alias="from")
    to: str
    rate: Decimal
    result: Decimal
    rate_date: date
    asked_date: Optional[date]
    source: str

    @field_serializer("amount", "rate", "result", when_used="json")
    def serialize_decimal(self, value: Decimal) -> float:
        """Keep Decimal arithmetic internally while honoring the JSON contract."""
        return float(value)

class ErrorResponse(BaseModel):
    error: str
    message: str


class RateQuote(BaseModel):
    rate: Decimal
    rate_date: date
