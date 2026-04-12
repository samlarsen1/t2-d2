package com.t2d2.app.data.models

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class Position(
    val ticker: String,
    val quantity: Double,
    @Json(name = "averagePrice") val averagePrice: Double,
    @Json(name = "currentPrice") val currentPrice: Double,
    val ppl: Double,
) {
    val marketValue: Double get() = quantity * currentPrice
    val pnlPct: Double get() = if (averagePrice == 0.0) 0.0
        else ((currentPrice - averagePrice) / averagePrice) * 100
}

@JsonClass(generateAdapter = true)
data class AccountCash(
    val free: Double,
    val invested: Double,
    val ppl: Double,
    val result: Double,
)

@JsonClass(generateAdapter = true)
data class Trade(
    val id: Long,
    val ticker: String,
    val action: String,        // "BUY" | "SELL"
    val valueGbp: Double,
    val price: Double,
    val dailyChangePct: Double,
    val weeklyChangePct: Double,
    val session: String,
    val strategyMode: String,
    val timestamp: Long,
    val dryRun: Boolean = false,
)

data class Portfolio(
    val cash: AccountCash,
    val positions: List<Position>,
) {
    val totalValue: Double get() = cash.free + cash.invested
    val sortedPositions: List<Position> get() = positions.sortedByDescending { it.marketValue }
}
