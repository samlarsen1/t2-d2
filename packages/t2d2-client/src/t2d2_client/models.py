from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class OrderStatus(StrEnum):
    LOCAL = "LOCAL"
    UNCONFIRMED = "UNCONFIRMED"
    CONFIRMED = "CONFIRMED"
    NEW = "NEW"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    REPLACING = "REPLACING"
    REPLACED = "REPLACED"


class TimeValidity(StrEnum):
    # Good 'til cancelled
    GTC = "GTC"
    # Day order
    DAY = "DAY"


class AccountCash(BaseModel):
    free: Decimal
    invested: Decimal
    ppl: Decimal  # Profit/loss
    result: Decimal
    blocked: Decimal | None = None
    pie_cash: Decimal | None = Field(None, alias="pieCash")

    model_config = {"populate_by_name": True}


class AccountMetadata(BaseModel):
    id: int
    currency_code: str = Field(alias="currencyCode")
    account_type: str = Field(alias="type")

    model_config = {"populate_by_name": True}


class Position(BaseModel):
    ticker: str
    quantity: Decimal
    average_price: Decimal = Field(alias="averagePrice")
    current_price: Decimal = Field(alias="currentPrice")
    ppl: Decimal
    fx_ppl: Decimal | None = Field(None, alias="fxPpl")
    frontend: str | None = None
    max_buy: Decimal | None = Field(None, alias="maxBuy")
    max_sell: Decimal | None = Field(None, alias="maxSell")
    pie_quantity: Decimal | None = Field(None, alias="pieQuantity")

    model_config = {"populate_by_name": True}

    @property
    def market_value(self) -> Decimal:
        return self.quantity * self.current_price

    @property
    def pnl_pct(self) -> Decimal:
        if self.average_price == 0:
            return Decimal(0)
        return ((self.current_price - self.average_price) / self.average_price) * 100


class Order(BaseModel):
    id: int | None = None
    ticker: str
    type: OrderType
    status: OrderStatus | None = None
    quantity: Decimal | None = None
    filled_quantity: Decimal | None = Field(None, alias="filledQuantity")
    limit_price: Decimal | None = Field(None, alias="limitPrice")
    stop_price: Decimal | None = Field(None, alias="stopPrice")
    value: Decimal | None = None  # For value-based orders (£ amount)
    time_validity: TimeValidity = Field(TimeValidity.DAY, alias="timeValidity")
    creation_time: datetime | None = Field(None, alias="createdAt")
    date_modified: datetime | None = Field(None, alias="dateModified")
    taxes: list[Any] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class HistoricalOrder(BaseModel):
    id: int
    ticker: str
    type: OrderType
    status: OrderStatus
    quantity: Decimal | None = None
    filled_quantity: Decimal | None = Field(None, alias="filledQuantity")
    limit_price: Decimal | None = Field(None, alias="limitPrice")
    filled_price: Decimal | None = Field(None, alias="filledPrice")
    value: Decimal | None = None
    creation_time: datetime | None = Field(None, alias="createdAt")
    executor: str | None = None
    taxes: list[Any] = Field(default_factory=list)

    model_config = {"populate_by_name": True}
