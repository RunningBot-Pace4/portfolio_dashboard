from datetime import date

from pydantic import BaseModel, Field, field_validator


class PortfolioRecordIn(BaseModel):
    purchase_date: date
    share_code: str = Field(min_length=1, max_length=32)
    investment_amount: float = Field(ge=0)
    purchase_units: float = Field(gt=0)

    @field_validator("share_code")
    @classmethod
    def clean_share_code(cls, value: str) -> str:
        return value.strip().upper()
