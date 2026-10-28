from datetime import datetime

from pydantic import BaseModel, Field


class BarCreate(BaseModel):
    symbol: str = Field(min_length=1, max_length=10)
    timestamp: datetime
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    minute_count: int = Field(ge=1, le=60)


class BarUpdate(BaseModel):
    symbol: str | None = Field(default=None, min_length=1, max_length=10)
    timestamp: datetime | None = None
    open_price: float | None = None
    high_price: float | None = None
    low_price: float | None = None
    close_price: float | None = None
    volume: float | None = None
    minute_count: int | None = Field(default=None, ge=1, le=60)


class BarResponse(BaseModel):
    bar_id: int | str
    symbol: str
    timestamp: datetime
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    minute_count: int
