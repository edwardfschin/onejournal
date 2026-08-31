"""Public API contracts for the synthetic WEB-W05 fixture boundary.

These models deliberately describe only committed demonstration data. They do
not read a database, raw evidence, credentials, or a provider response.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


DECIMAL_STRING = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")


class ApiModel(BaseModel):
    """Reject undeclared fields so the fixture contract cannot drift silently."""

    model_config = ConfigDict(extra="forbid")


class QualityState(ApiModel):
    status: Literal["demo", "unavailable"]
    reason: str = Field(min_length=1, max_length=240)


class DecimalMetric(ApiModel):
    value: str | None = None
    currency: Literal["USD"] | None = None
    quality: QualityState

    @field_validator("value")
    @classmethod
    def validate_decimal_string(cls, value: str | None) -> str | None:
        if value is not None and DECIMAL_STRING.fullmatch(value) is None:
            raise ValueError("value must be a decimal string")
        return value

    @model_validator(mode="after")
    def require_currency_with_value(self) -> "DecimalMetric":
        if self.value is not None and self.currency is None:
            raise ValueError("currency is required when value is supplied")
        return self


class PreviewMetadata(ApiModel):
    contract_version: Literal["onejournal.web-fixture.v1"]
    mode: Literal["demo"]
    asof: date
    generated_at: datetime
    quality: QualityState

    @field_validator("generated_at")
    @classmethod
    def require_utc_instant(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError("generated_at must be a UTC instant")
        return value


class PreviewResponse(ApiModel):
    metadata: PreviewMetadata
    metrics: dict[str, DecimalMetric]
    notices: list[str]
