"""Smoke tests for AlgoEngine decision logic."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from t2d2_algo.engine import AlgoEngine, TradeExecutor, load_strategy_configs
from t2d2_algo.strategies.base import StrategyConfig, TradeDecision
from t2d2_market_data.analysis import TrendSignal

REPO_ROOT = Path(__file__).parents[3]


def make_config(**overrides: object) -> StrategyConfig:
    defaults = dict(
        mode="mild",
        min_daily_dip_pct=-2.0,
        min_weekly_dip_pct=-3.0,
        max_position_increase_pct=10.0,
        max_cash_deploy_pct=5.0,
        order_type="limit",
        limit_discount_pct=0.5,
        max_portfolio_weight_pct=10.0,
        min_trade_gbp=10.0,
        absolute_max_cash_deploy_pct=20.0,
        min_cash_reserve_gbp=50.0,
        max_trades_per_run=3,
        ticker_cooldown_hours=72,
        require_both_timeframes=False,
        rsi_max_buy=50.0,
        daily_lookback_days=5,
        weekly_lookback_days=20,
    )
    defaults.update(overrides)
    return StrategyConfig(**defaults)  # type: ignore[arg-type]


def make_signal(
    ticker: str = "NET",
    daily_change_pct: float = -5.0,
    weekly_change_pct: float = -8.0,
    rsi: float = 35.0,
    latest_price: float = 100.0,
) -> TrendSignal:
    return TrendSignal(
        ticker=ticker,
        latest_price=latest_price,
        daily_change_pct=daily_change_pct,
        weekly_change_pct=weekly_change_pct,
        monthly_change_pct=-10.0,
        rsi=rsi,
        sma_20=105.0,
        sma_50=110.0,
        is_below_sma20=True,
        is_below_sma50=True,
        volume_ratio=1.2,
    )


def test_should_trade_on_dip() -> None:
    engine = AlgoEngine(make_config())
    decision = engine.evaluate(
        signal=make_signal(daily_change_pct=-5.0, rsi=35.0),
        position=None,
        available_cash=1000.0,
        total_portfolio_value=5000.0,
        fx_rate=1.0,
    )
    assert decision.should_trade


def test_skip_when_daily_dip_insufficient() -> None:
    engine = AlgoEngine(make_config())
    decision = engine.evaluate(
        signal=make_signal(daily_change_pct=-0.5),
        position=None,
        available_cash=1000.0,
        total_portfolio_value=5000.0,
        fx_rate=1.0,
    )
    assert not decision.should_trade
    assert "Daily change" in decision.reason


def test_skip_when_rsi_too_high() -> None:
    engine = AlgoEngine(make_config())
    decision = engine.evaluate(
        signal=make_signal(daily_change_pct=-5.0, rsi=60.0),
        position=None,
        available_cash=1000.0,
        total_portfolio_value=5000.0,
        fx_rate=1.0,
    )
    assert not decision.should_trade
    assert "RSI" in decision.reason


def test_skip_when_insufficient_cash() -> None:
    engine = AlgoEngine(make_config())
    decision = engine.evaluate(
        signal=make_signal(daily_change_pct=-5.0),
        position=None,
        available_cash=40.0,  # below min_cash_reserve_gbp=50
        total_portfolio_value=5000.0,
        fx_rate=1.0,
    )
    assert not decision.should_trade
    assert "cash" in decision.reason.lower()


def test_skip_when_in_cooldown() -> None:
    engine = AlgoEngine(make_config())
    decision = engine.evaluate(
        signal=make_signal(daily_change_pct=-5.0, rsi=35.0),
        position=None,
        available_cash=1000.0,
        total_portfolio_value=5000.0,
        fx_rate=1.0,
        recently_traded={"NET"},
    )
    assert not decision.should_trade
    assert "cooldown" in decision.reason.lower()


def test_rank_decisions_sorts_by_dip() -> None:
    engine = AlgoEngine(make_config())
    signals = [
        make_signal("A", daily_change_pct=-2.5, weekly_change_pct=-3.0),
        make_signal("B", daily_change_pct=-5.0, weekly_change_pct=-10.0),
        make_signal("C", daily_change_pct=-3.0, weekly_change_pct=-5.0),
    ]
    decisions = [
        engine.evaluate(
            s, position=None, available_cash=1000.0, total_portfolio_value=5000.0, fx_rate=1.0
        )
        for s in signals
    ]
    ranked = engine.rank_decisions(decisions)
    assert ranked[0].ticker == "B"


def test_decision_records_strategy_mode() -> None:
    engine = AlgoEngine(make_config(mode="moderate"))
    trade = engine.evaluate(
        signal=make_signal(daily_change_pct=-5.0),
        position=None,
        available_cash=1000.0,
        total_portfolio_value=5000.0,
        fx_rate=1.0,
    )
    skip = engine.evaluate(
        signal=make_signal(daily_change_pct=-0.5),
        position=None,
        available_cash=1000.0,
        total_portfolio_value=5000.0,
        fx_rate=1.0,
    )
    assert trade.strategy == "moderate"
    assert skip.strategy == "moderate"
    assert "[moderate]" in str(trade)


def test_load_strategy_configs_returns_every_mode() -> None:
    configs = load_strategy_configs(REPO_ROOT / "config")

    assert set(configs) == {"mild", "moderate", "aggressive"}
    for mode, cfg in configs.items():
        assert cfg.mode == mode
    assert configs["mild"].min_daily_dip_pct != configs["aggressive"].min_daily_dip_pct
    # Global limits are shared across modes
    assert len({cfg.max_trades_per_run for cfg in configs.values()}) == 1


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def place_limit_order(self, **kwargs: Any) -> None:
        self.calls.append(("limit", kwargs))

    async def place_market_order(self, **kwargs: Any) -> None:
        self.calls.append(("market", kwargs))


@pytest.mark.parametrize(
    ("mode", "order_type", "expected_call"),
    [("mild", "limit", "limit"), ("aggressive", "market", "market")],
)
async def test_executor_order_type_follows_decision_strategy(
    mode: str, order_type: str, expected_call: str
) -> None:
    engine = AlgoEngine(make_config(mode=mode, order_type=order_type))
    decision = engine.evaluate(
        signal=make_signal(daily_change_pct=-5.0),
        position=None,
        available_cash=1000.0,
        total_portfolio_value=5000.0,
        fx_rate=1.0,
    )
    client = _FakeClient()
    executor = TradeExecutor(client=client, dry_run=False)  # type: ignore[arg-type]

    assert await executor.execute(decision)
    assert [call for call, _ in client.calls] == [expected_call]


def _buy(fx_rate: float | None, latest_price: float, **config: object) -> TradeDecision:
    # max_cash_deploy_pct=10 of £1000 cash → £100 budget (under the portfolio-weight cap)
    engine = AlgoEngine(make_config(max_cash_deploy_pct=10.0, **config))
    return engine.evaluate(
        signal=make_signal(daily_change_pct=-5.0, latest_price=latest_price),
        position=None,
        available_cash=1000.0,
        total_portfolio_value=5000.0,
        fx_rate=fx_rate,
    )


def test_pence_quote_converts_pounds_to_shares() -> None:
    # RIO at 6545p, market order: £100 = 10000p → 1.5278 shares (not 0.0153)
    decision = _buy(fx_rate=100.0, latest_price=6545.0, order_type="market")
    assert decision.should_trade
    assert decision.trade_value_gbp == 100.0
    assert decision.quantity == 1.5278


def test_usd_quote_converts_pounds_to_shares() -> None:
    # HOOD at $98.30 with GBPUSD 1.34: £100 = $134 → 1.3631 shares (not 1.0173)
    decision = _buy(fx_rate=1.34, latest_price=98.30, order_type="market")
    assert decision.quantity == 1.3631


def test_limit_price_rounded_down_to_two_decimals() -> None:
    # 96.5199966 * (1 - 0.3%) = 96.2304366... → 96.23
    decision = _buy(
        fx_rate=1.34, latest_price=96.5199966430664, order_type="limit", limit_discount_pct=0.3
    )
    assert decision.limit_price == 96.23
    # Quantity is sized at the limit price, rounded down: 134 / 96.23
    assert decision.quantity == 1.3924
    assert decision.quantity * decision.limit_price <= 134.0


def test_market_order_has_no_limit_price() -> None:
    decision = _buy(fx_rate=1.0, latest_price=100.0, order_type="market")
    assert decision.limit_price is None


def test_skip_when_fx_rate_unknown() -> None:
    decision = _buy(fx_rate=None, latest_price=100.0)
    assert not decision.should_trade
    assert "FX rate" in decision.reason


async def test_executor_sends_decision_quantity_and_limit() -> None:
    decision = _buy(fx_rate=100.0, latest_price=6545.0, order_type="limit", limit_discount_pct=0.5)
    decision.t212_ticker = "RIOl_EQ"
    client = _FakeClient()
    executor = TradeExecutor(client=client, dry_run=False)  # type: ignore[arg-type]

    assert await executor.execute(decision)
    [(call, kwargs)] = client.calls
    assert call == "limit"
    assert kwargs["ticker"] == "RIOl_EQ"
    assert kwargs["limit_price"] == 6512.27
    assert kwargs["quantity"] == decision.quantity == 1.5355
