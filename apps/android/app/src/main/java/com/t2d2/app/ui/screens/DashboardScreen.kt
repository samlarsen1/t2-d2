package com.t2d2.app.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.TrendingDown
import androidx.compose.material.icons.filled.TrendingUp
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.t2d2.app.data.models.Position
import com.t2d2.app.data.models.Trade
import com.t2d2.app.ui.theme.T2D2Green
import com.t2d2.app.ui.theme.T2D2Red
import com.t2d2.app.ui.viewmodel.DashboardViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DashboardScreen(viewModel: DashboardViewModel = hiltViewModel()) {
    val portfolio by viewModel.portfolio.collectAsState()
    val recentTrades by viewModel.recentTrades.collectAsState()
    val isLoading by viewModel.isLoading.collectAsState()

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text("T2-D2", fontWeight = FontWeight.Bold)
                },
                subtitle = { Text("ISA Trading Monitor", style = MaterialTheme.typography.bodySmall) },
            )
        }
    ) { padding ->
        if (isLoading) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
            return@Scaffold
        }

        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            // Cash summary card
            portfolio?.let { p ->
                item {
                    Spacer(Modifier.height(8.dp))
                    CashSummaryCard(
                        freeCash = p.cash.free,
                        totalValue = p.totalValue,
                        pnl = p.cash.ppl,
                    )
                }

                // Positions
                if (p.sortedPositions.isNotEmpty()) {
                    item {
                        Text(
                            "Positions",
                            style = MaterialTheme.typography.titleMedium,
                            modifier = Modifier.padding(top = 8.dp),
                        )
                    }
                    items(p.sortedPositions) { position ->
                        PositionCard(position)
                    }
                }
            }

            // Recent trades
            if (recentTrades.isNotEmpty()) {
                item {
                    Text(
                        "Recent Trades",
                        style = MaterialTheme.typography.titleMedium,
                        modifier = Modifier.padding(top = 8.dp),
                    )
                }
                items(recentTrades) { trade ->
                    TradeCard(trade)
                }
            }

            item { Spacer(Modifier.height(16.dp)) }
        }
    }
}

@Composable
fun CashSummaryCard(freeCash: Double, totalValue: Double, pnl: Double) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text("Portfolio Value", style = MaterialTheme.typography.labelMedium)
            Text(
                "£${String.format("%.2f", totalValue)}",
                style = MaterialTheme.typography.headlineMedium,
                fontWeight = FontWeight.Bold,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                Column {
                    Text("Available Cash", style = MaterialTheme.typography.labelSmall)
                    Text("£${String.format("%.2f", freeCash)}", style = MaterialTheme.typography.bodyMedium)
                }
                Column {
                    Text("P&L", style = MaterialTheme.typography.labelSmall)
                    Text(
                        "${if (pnl >= 0) "+" else ""}£${String.format("%.2f", pnl)}",
                        style = MaterialTheme.typography.bodyMedium,
                        color = if (pnl >= 0) T2D2Green else T2D2Red,
                    )
                }
            }
        }
    }
}

@Composable
fun PositionCard(position: Position) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier.padding(16.dp).fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column {
                Text(position.ticker, fontWeight = FontWeight.SemiBold)
                Text(
                    "${String.format("%.4f", position.quantity)} shares",
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            Column(horizontalAlignment = Alignment.End) {
                Text(
                    "£${String.format("%.2f", position.marketValue)}",
                    fontWeight = FontWeight.Medium,
                )
                val pnlColor = if (position.pnlPct >= 0) T2D2Green else T2D2Red
                val icon = if (position.pnlPct >= 0) Icons.Default.TrendingUp else Icons.Default.TrendingDown
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(icon, contentDescription = null, tint = pnlColor, modifier = Modifier.size(16.dp))
                    Spacer(Modifier.width(4.dp))
                    Text(
                        "${if (position.pnlPct >= 0) "+" else ""}${String.format("%.2f", position.pnlPct)}%",
                        color = pnlColor,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }
        }
    }
}

@Composable
fun TradeCard(trade: Trade) {
    val isDryRun = trade.dryRun
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = if (isDryRun)
                MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f)
            else
                MaterialTheme.colorScheme.surfaceVariant,
        ),
    ) {
        Row(
            modifier = Modifier.padding(12.dp).fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Column {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(trade.ticker, fontWeight = FontWeight.SemiBold)
                    if (isDryRun) {
                        Badge { Text("DRY") }
                    }
                }
                Text(trade.session, style = MaterialTheme.typography.bodySmall)
                Text(
                    "1d: ${if (trade.dailyChangePct >= 0) "+" else ""}${String.format("%.2f", trade.dailyChangePct)}% | " +
                    "5d: ${if (trade.weeklyChangePct >= 0) "+" else ""}${String.format("%.2f", trade.weeklyChangePct)}%",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Column(horizontalAlignment = Alignment.End) {
                Text(
                    "£${String.format("%.2f", trade.valueGbp)}",
                    color = T2D2Green,
                    fontWeight = FontWeight.Medium,
                )
                Text(
                    "@ £${String.format("%.4f", trade.price)}",
                    style = MaterialTheme.typography.bodySmall,
                )
                Text(
                    trade.strategyMode,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}
