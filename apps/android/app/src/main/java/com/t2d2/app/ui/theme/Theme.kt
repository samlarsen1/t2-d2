package com.t2d2.app.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

// T2-D2 brand palette — blue-grey tech feel with green/red for P&L
val T2D2Blue = Color(0xFF1565C0)
val T2D2BlueLight = Color(0xFF42A5F5)
val T2D2Green = Color(0xFF00C853)
val T2D2Red = Color(0xFFD50000)
val T2D2Surface = Color(0xFF121212)
val T2D2SurfaceVariant = Color(0xFF1E1E2E)

private val DarkColorScheme = darkColorScheme(
    primary = T2D2BlueLight,
    secondary = T2D2Green,
    error = T2D2Red,
    background = T2D2Surface,
    surface = T2D2SurfaceVariant,
)

private val LightColorScheme = lightColorScheme(
    primary = T2D2Blue,
    secondary = T2D2Green,
    error = T2D2Red,
)

@Composable
fun T2D2Theme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    val colorScheme = if (darkTheme) DarkColorScheme else LightColorScheme
    MaterialTheme(
        colorScheme = colorScheme,
        content = content,
    )
}
