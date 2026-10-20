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


class Cash(BaseModel):
    available_to_trade: Decimal = Field(alias="availableToTrade")
    in_pies: Decimal = Field(Decimal(0), alias="inPies")
    reserved_for_orders: Decimal = Field(Decimal(0), alias="reservedForOrders")

    model_config = {"populate_by_name": True}


class Investments(BaseModel):
    current_value: Decimal = Field(alias="currentValue")
    total_cost: Decimal = Field(alias="totalCost")
    realized_profit_loss: Decimal = Field(Decimal(0), alias="realizedProfitLoss")
    unrealized_profit_loss: Decimal = Field(Decimal(0), alias="unrealizedProfitLoss")

    model_config = {"populate_by_name": True}


class AccountSummary(BaseModel):
    """Account cash and investment totals, in the account's primary currency."""

    id: int
    currency: str
    cash: Cash
    investments: Investments
    total_value: Decimal = Field(alias="totalValue")

    model_config = {"populate_by_name": True}


class Instrument(BaseModel):
    ticker: str
    name: str | None = None
    isin: str | None = None
    currency: str | None = None  # Instrument currency (ISO 4217)


class PositionWalletImpact(BaseModel):
    """A position's value and P/L expressed in the account currency."""

    currency: str
    current_value: Decimal = Field(alias="currentValue")
    total_cost: Decimal = Field(alias="totalCost")
    unrealized_profit_loss: Decimal = Field(alias="unrealizedProfitLoss")
    fx_impact: Decimal | None = Field(None, alias="fxImpact")

    model_config = {"populate_by_name": True}


class Position(BaseModel):
    instrument: Instrument
    quantity: Decimal
    # Prices are per share, in the instrument currency
    average_price: Decimal = Field(alias="averagePricePaid")
    current_price: Decimal = Field(alias="currentPrice")
    quantity_available_for_trading: Decimal | None = Field(
        None, alias="quantityAvailableForTrading"
    )
    quantity_in_pies: Decimal | None = Field(None, alias="quantityInPies")
    created_at: datetime | None = Field(None, alias="createdAt")
    wallet_impact: PositionWalletImpact = Field(alias="walletImpact")

    model_config = {"populate_by_name": True}

    @property
    def ticker(self) -> str:
        return self.instrument.ticker

    @property
    def market_value(self) -> Decimal:
        """Current position value in the account currency."""
        return self.wallet_impact.current_value

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
