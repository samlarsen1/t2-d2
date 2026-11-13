"""Smoke tests for AlgoEngine decision logic."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from t2d2_algo.engine import AlgoEngine, TradeExecutor, load_strategy_configs
from t2d2_algo.strategies.base import StrategyConfig, TradeDecision
from t2d2_client.models import TimeValidity
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
        min_trade_floor_gbp=0.0,
        limit_order_expiry_days=30,
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

    assert set(configs) == {"deep_value", "mild", "moderate", "aggressive"}
    for mode, cfg in configs.items():
        assert cfg.mode == mode
    assert configs["mild"].min_daily_dip_pct != configs["aggressive"].min_daily_dip_pct
    # Global limits are shared across modes
    assert len({cfg.max_trades_per_run for cfg in configs.values()}) == 1


def test_deep_value_config_is_weekly_and_below_mild() -> None:
    configs = load_strategy_configs(REPO_ROOT / "config")
    deep, mild = configs["deep_value"], configs["mild"]

    assert deep.trigger == "long_term_downtrend"
    assert deep.trade_weekday == "wednesday"
    assert deep.needs_long_history and not mild.needs_long_history
    assert deep.max_cash_deploy_pct < mild.max_cash_deploy_pct
    assert deep.max_position_increase_pct < mild.max_position_increase_pct
    assert deep.max_portfolio_weight_pct < mild.max_portfolio_weight_pct


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
    assert kwargs["time_validity"] == TimeValidity.GTC


def test_weekly_gate_applies_when_mode_requires_both() -> None:
    engine = AlgoEngine(make_config(require_both_timeframes=True, min_weekly_dip_pct=-5.0))
    decision = engine.evaluate(
        signal=make_signal(daily_change_pct=-5.0, weekly_change_pct=-2.0),
        position=None,
        available_cash=1000.0,
        total_portfolio_value=5000.0,
        fx_rate=1.0,
    )
    assert not decision.should_trade
    assert "Weekly change -2.00% above threshold -5.00%" in decision.reason


def test_weekly_gate_passes_on_deep_weekly_dip() -> None:
    engine = AlgoEngine(make_config(require_both_timeframes=True, min_weekly_dip_pct=-5.0))
    decision = engine.evaluate(
        signal=make_signal(daily_change_pct=-5.0, weekly_change_pct=-8.0),
        position=None,
        available_cash=1000.0,
        total_portfolio_value=5000.0,
        fx_rate=1.0,
    )
    assert decision.should_trade


def test_weekly_gate_ignored_without_flag() -> None:
    engine = AlgoEngine(make_config(require_both_timeframes=False, min_weekly_dip_pct=None))
    decision = engine.evaluate(
        signal=make_signal(daily_change_pct=-5.0, weekly_change_pct=+3.0),
        position=None,
        available_cash=1000.0,
        total_portfolio_value=5000.0,
        fx_rate=1.0,
    )
    assert decision.should_trade


def test_require_both_without_weekly_threshold_rejected() -> None:
    with pytest.raises(ValueError, match="needs min_weekly_dip_pct"):
        make_config(require_both_timeframes=True, min_weekly_dip_pct=None)


def test_repo_strategy_config_weekly_settings() -> None:
    configs = load_strategy_configs(REPO_ROOT / "config")
    for cfg in configs.values():
        if cfg.require_both_timeframes:
            assert cfg.min_weekly_dip_pct is not None


def test_repo_strategy_config_loads_trade_floor() -> None:
    configs = load_strategy_configs(REPO_ROOT / "config")
    assert {cfg.min_trade_floor_gbp for cfg in configs.values()} == {100.0}


def test_repo_strategy_config_loads_limit_order_expiry() -> None:
    configs = load_strategy_configs(REPO_ROOT / "config")
    assert {cfg.limit_order_expiry_days for cfg in configs.values()} == {7}


def evaluate_with_floor(
    available_cash: float, position: Any = None, **overrides: object
) -> TradeDecision:
    engine = AlgoEngine(make_config(min_trade_floor_gbp=100.0, **overrides))
    return engine.evaluate(
        signal=make_signal(),
        position=position,
        available_cash=available_cash,
        total_portfolio_value=50000.0,
        fx_rate=1.0,
    )


def test_floor_raises_small_percentage_trade() -> None:
    decision = evaluate_with_floor(available_cash=1000.0)  # 5% = £50
    assert decision.should_trade
    assert decision.trade_value_gbp == 100.0
    assert decision.quantity > 0


def test_floor_leaves_larger_percentage_trade_unchanged() -> None:
    decision = evaluate_with_floor(available_cash=5000.0)  # 5% = £250
    assert decision.trade_value_gbp == 250.0


def test_floor_overrides_position_increase_limit() -> None:
    position = SimpleNamespace(market_value=200.0)  # 10% = £20
    decision = evaluate_with_floor(available_cash=5000.0, position=position)
    assert decision.trade_value_gbp == 100.0


def test_floor_overrides_portfolio_weight_limit() -> None:
    decision = evaluate_with_floor(available_cash=1000.0, max_portfolio_weight_pct=0.1)  # £50
    assert decision.trade_value_gbp == 100.0


def test_floor_skips_trade_that_would_use_cash_reserve() -> None:
    decision = evaluate_with_floor(available_cash=149.0)  # £99 left above the £50 reserve
    assert not decision.should_trade
    assert "below minimum £100.00" in decision.reason


def test_floor_allows_trade_leaving_exactly_the_reserve() -> None:
    decision = evaluate_with_floor(available_cash=150.0)
    assert decision.should_trade
    assert decision.trade_value_gbp == 100.0


def test_min_trade_gbp_still_applies_above_floor() -> None:
    decision = evaluate_with_floor(available_cash=1000.0, min_trade_gbp=120.0)
    assert not decision.should_trade
    assert "below minimum £120.00" in decision.reason


def test_preserves_cash_reserve_accounts_for_earlier_trades() -> None:
    engine = AlgoEngine(make_config(min_cash_reserve_gbp=100.0))
    decision = TradeDecision(
        ticker="NET",
        should_trade=True,
        trade_value_gbp=100.0,
        reason="",
        daily_change_pct=-5.0,
        weekly_change_pct=-8.0,
        rsi=35.0,
        current_price=100.0,
    )
    assert engine.preserves_cash_reserve(decision, available_cash=200.0)
    assert not engine.preserves_cash_reserve(decision, available_cash=199.99)


# --- long_term_downtrend trigger ---


def make_long_term_config(**overrides: object) -> StrategyConfig:
    defaults: dict[str, object] = dict(
        mode="deep_value",
        trigger="long_term_downtrend",
        min_daily_dip_pct=None,
        max_pct_above_52w_low=2.0,
        min_quarter_change_pct=-20.0,
        min_half_year_change_pct=-30.0,
    )
    defaults.update(overrides)
    return make_config(**defaults)


def make_long_term_signal(
    pct_above_52w_low: float | None = 15.0,
    quarter_change_pct: float | None = -5.0,
    half_year_change_pct: float | None = -8.0,
    is_below_sma50: bool = True,
    daily_change_pct: float = 1.5,
) -> TrendSignal:
    signal = make_signal(daily_change_pct=daily_change_pct, weekly_change_pct=0.5)
    signal.pct_above_52w_low = pct_above_52w_low
    signal.quarter_change_pct = quarter_change_pct
    signal.half_year_change_pct = half_year_change_pct
    signal.is_below_sma50 = is_below_sma50
    return signal


def evaluate_long_term(signal: TrendSignal, **config: object) -> TradeDecision:
    return AlgoEngine(make_long_term_config(**config)).evaluate(
        signal=signal,
        position=None,
        available_cash=1000.0,
        total_portfolio_value=5000.0,
        fx_rate=1.0,
    )


def test_long_term_buys_near_52w_low_despite_daily_gain() -> None:
    decision = evaluate_long_term(make_long_term_signal(pct_above_52w_low=1.0))

    assert decision.should_trade
    assert decision.reason.startswith("Near 52w low")


@pytest.mark.parametrize(
    ("quarter", "half_year", "expected"),
    [(-25.0, -8.0, "Quarter downtrend"), (-5.0, -35.0, "Half-year downtrend")],
)
def test_long_term_buys_on_sustained_slide(quarter: float, half_year: float, expected: str) -> None:
    decision = evaluate_long_term(
        make_long_term_signal(quarter_change_pct=quarter, half_year_change_pct=half_year)
    )

    assert decision.should_trade
    assert decision.reason.startswith(expected)


def test_long_term_ignores_sharp_daily_drop() -> None:
    # A big one-day fall alone isn't a long-term downtrend
    decision = evaluate_long_term(make_long_term_signal(daily_change_pct=-9.0))

    assert not decision.should_trade
    assert decision.reason.startswith("No long-term downtrend")


def test_long_term_slide_ignored_once_price_back_above_sma50() -> None:
    decision = evaluate_long_term(
        make_long_term_signal(quarter_change_pct=-25.0, is_below_sma50=False)
    )

    assert not decision.should_trade
    assert "above SMA50" in decision.reason


def test_long_term_skips_without_enough_history() -> None:
    signal = make_long_term_signal(
        pct_above_52w_low=None, quarter_change_pct=None, half_year_change_pct=None
    )

    decision = evaluate_long_term(signal)

    assert not decision.should_trade
    assert "n/a above 52w low" in decision.reason


def test_long_term_threshold_can_be_disabled() -> None:
    decision = evaluate_long_term(
        make_long_term_signal(pct_above_52w_low=1.0), max_pct_above_52w_low=None
    )

    assert not decision.should_trade


def test_long_term_still_applies_rsi_gate() -> None:
    signal = make_long_term_signal(pct_above_52w_low=1.0)
    signal.rsi = 70.0

    decision = evaluate_long_term(signal)

    assert not decision.should_trade
    assert decision.reason.startswith("RSI")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"trigger": "sometimes"}, "unknown trigger"),
        ({"trigger": "daily_dip", "min_daily_dip_pct": None}, "needs min_daily_dip_pct"),
        (
            {
                "max_pct_above_52w_low": None,
                "min_quarter_change_pct": None,
                "min_half_year_change_pct": None,
            },
            "needs at least one",
        ),
        ({"trade_weekday": "wed"}, "trade_weekday"),
    ],
)
def test_invalid_long_term_config_rejected(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        make_long_term_config(**overrides)


@pytest.mark.parametrize(
    ("session", "day", "active"),
    [
        ("us_morning", date(2026, 11, 18), True),  # Wednesday
        ("us_afternoon", date(2026, 11, 18), False),  # Wrong session
        ("us_morning", date(2026, 11, 17), False),  # Tuesday
    ],
)
def test_is_active_respects_weekday_and_sessions(session: str, day: date, active: bool) -> None:
    cfg = make_long_term_config(trade_weekday="wednesday", trade_sessions=["us_morning"])

    assert cfg.is_active(session, day) is active


def test_unrestricted_mode_is_always_active() -> None:
    assert make_config().is_active("eu_afternoon", date(2026, 11, 17))


def test_long_term_buy_outranks_daily_dip_despite_daily_gain() -> None:
    # A quarter-long slide should win a scarce slot even though the stock rose today
    dip_engine = AlgoEngine(make_config(max_trades_per_run=1))
    dip = dip_engine.evaluate(
        make_signal("DIP", daily_change_pct=-5.0, weekly_change_pct=-10.0),
        position=None,
        available_cash=1000.0,
        total_portfolio_value=5000.0,
        fx_rate=1.0,
    )
    slide = evaluate_long_term(make_long_term_signal(quarter_change_pct=-25.0))
    assert dip.should_trade and slide.should_trade

    ranked = dip_engine.rank_decisions([dip, slide])

    assert [d.strategy for d in ranked] == ["deep_value"]
    assert slide.downtrend_score == -25.0


def test_long_term_score_uses_dip_blend_when_shallower_than_long_moves() -> None:
    signal = make_long_term_signal(
        pct_above_52w_low=1.0,
        quarter_change_pct=None,
        half_year_change_pct=None,
        daily_change_pct=-4.0,
    )
    signal.weekly_change_pct = -6.0

    decision = evaluate_long_term(signal)

    assert decision.downtrend_score == pytest.approx(-4.0 * 0.4 + -6.0 * 0.6)
