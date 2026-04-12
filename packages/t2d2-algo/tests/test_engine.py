"""Smoke tests for AlgoEngine decision logic."""
from __future__ import annotations

import pytest

from t2d2_algo.engine import AlgoEngine
from t2d2_algo.strategies.base import StrategyConfig
from t2d2_market_data.analysis import TrendSignal


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
    )
    assert decision.should_trade


def test_skip_when_daily_dip_insufficient() -> None:
    engine = AlgoEngine(make_config())
    decision = engine.evaluate(
        signal=make_signal(daily_change_pct=-0.5),
        position=None,
        available_cash=1000.0,
        total_portfolio_value=5000.0,
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
        engine.evaluate(s, position=None, available_cash=1000.0, total_portfolio_value=5000.0)
        for s in signals
    ]
    ranked = engine.rank_decisions(decisions)
    assert ranked[0].ticker == "B"
