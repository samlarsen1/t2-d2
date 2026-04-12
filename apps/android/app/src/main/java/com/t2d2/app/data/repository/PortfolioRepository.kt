package com.t2d2.app.data.repository

import com.t2d2.app.data.models.AccountCash
import com.t2d2.app.data.models.Portfolio
import com.t2d2.app.data.models.Position
import com.t2d2.app.data.models.Trade
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Repository for portfolio data.
 *
 * In the initial read-only version the data flows in from FCM push
 * notifications (for trades) and a lightweight backend API (for positions).
 * Replace [fetchPortfolio] with a real API call once the backend exposes
 * a proxy endpoint — the app should never hold the T212 API key directly.
 */
@Singleton
class PortfolioRepository @Inject constructor() {

    private val _portfolio = MutableStateFlow<Portfolio?>(null)
    val portfolio: Flow<Portfolio?> = _portfolio.asStateFlow()

    private val _trades = MutableStateFlow<List<Trade>>(emptyList())
    val recentTrades: Flow<List<Trade>> = _trades.asStateFlow()

    /** Called by FCMService when a new trade notification arrives. */
    fun onTradeReceived(trade: Trade) {
        _trades.value = listOf(trade) + _trades.value.take(49)
    }

    /**
     * Fetch latest portfolio snapshot from the T2-D2 backend proxy.
     * The proxy reads from Trading212 using the server-side API key —
     * the app never contacts Trading212 directly.
     */
    suspend fun fetchPortfolio() {
        // TODO: implement once backend Cloud Run proxy is added
        // For now, show a placeholder so the UI renders
        _portfolio.value = Portfolio(
            cash = AccountCash(free = 0.0, invested = 0.0, ppl = 0.0, result = 0.0),
            positions = emptyList(),
        )
    }
}
