package com.t2d2.app.notifications

import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import com.t2d2.app.MainActivity
import com.t2d2.app.R
import com.t2d2.app.data.models.Trade
import com.t2d2.app.data.repository.PortfolioRepository
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import javax.inject.Inject

@AndroidEntryPoint
class T2D2FirebaseMessagingService : FirebaseMessagingService() {

    @Inject
    lateinit var repository: PortfolioRepository

    private val scope = CoroutineScope(Dispatchers.IO)

    override fun onMessageReceived(message: RemoteMessage) {
        val data = message.data
        val action = data["action"] ?: return

        when (action) {
            "BUY", "SELL" -> handleTrade(data, message.notification)
            "REPORT" -> handleReport(data, message.notification)
        }
    }

    private fun handleTrade(data: Map<String, String>, notification: RemoteMessage.Notification?) {
        val trade = Trade(
            id = System.currentTimeMillis(),
            ticker = data["ticker"] ?: return,
            action = data["action"] ?: "BUY",
            valueGbp = data["value_gbp"]?.toDoubleOrNull() ?: 0.0,
            price = data["price"]?.toDoubleOrNull() ?: 0.0,
            dailyChangePct = data["daily_change_pct"]?.toDoubleOrNull() ?: 0.0,
            weeklyChangePct = data["weekly_change_pct"]?.toDoubleOrNull() ?: 0.0,
            session = data["session"] ?: "",
            strategyMode = data["strategy_mode"] ?: "",
            timestamp = System.currentTimeMillis(),
            dryRun = data["dry_run"] == "true",
        )

        scope.launch { repository.onTradeReceived(trade) }

        showNotification(
            id = trade.id.toInt(),
            title = notification?.title ?: "${trade.action} ${trade.ticker}",
            body = notification?.body ?: "£${String.format("%.2f", trade.valueGbp)} @ £${String.format("%.4f", trade.price)}",
        )
    }

    private fun handleReport(data: Map<String, String>, notification: RemoteMessage.Notification?) {
        showNotification(
            id = (System.currentTimeMillis() % Int.MAX_VALUE).toInt(),
            title = notification?.title ?: "T2-D2 Session Report",
            body = notification?.body ?: "Session complete",
        )
    }

    private fun showNotification(id: Int, title: String, body: String) {
        val intent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP
        }
        val pendingIntent = PendingIntent.getActivity(
            this, id, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        val notification = NotificationCompat.Builder(this, "t2d2_trades")
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(title)
            .setContentText(body)
            .setAutoCancel(true)
            .setContentIntent(pendingIntent)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .build()

        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.notify(id, notification)
    }

    override fun onNewToken(token: String) {
        // In a production setup, send this token to your backend to enable
        // direct device targeting in addition to topic messaging.
    }
}
