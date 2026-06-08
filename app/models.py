from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class PortfolioRecordIn(BaseModel):
    purchase_date: date
    transaction_type: Literal["BUY", "SELL"] = "BUY"
    share_code: str = Field(min_length=1, max_length=32)
    investment_amount: float = Field(ge=0)
    purchase_units: float = Field(gt=0)

    @field_validator("share_code")
    @classmethod
    def clean_share_code(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("transaction_type", mode="before")
    @classmethod
    def clean_transaction_type(cls, value: str) -> str:
        return str(value or "BUY").strip().upper()
