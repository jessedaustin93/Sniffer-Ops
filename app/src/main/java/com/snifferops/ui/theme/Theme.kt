package com.snifferops.ui.theme

import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

// Dark military/tactical color palette
val RadarGreen = Color(0xFF00FF41)
val TacticalBlue = Color(0xFF0D84FF)
val AlertRed = Color(0xFFFF3131)
val WarningOrange = Color(0xFFFF8C00)
val SafeGreen = Color(0xFF22C55E)
val SuspiciousYellow = Color(0xFFFFD700)
val BackgroundDark = Color(0xFF0A0E1A)
val SurfaceDark = Color(0xFF111827)
val SurfaceVariantDark = Color(0xFF1F2937)
val OnSurface = Color(0xFFE2E8F0)
val OnSurfaceMuted = Color(0xFF94A3B8)

private val DarkColorScheme = darkColorScheme(
    primary = RadarGreen,
    onPrimary = Color.Black,
    primaryContainer = Color(0xFF003311),
    onPrimaryContainer = RadarGreen,
    secondary = TacticalBlue,
    onSecondary = Color.White,
    secondaryContainer = Color(0xFF0A2040),
    onSecondaryContainer = TacticalBlue,
    tertiary = WarningOrange,
    onTertiary = Color.Black,
    background = BackgroundDark,
    onBackground = OnSurface,
    surface = SurfaceDark,
    onSurface = OnSurface,
    surfaceVariant = SurfaceVariantDark,
    onSurfaceVariant = OnSurfaceMuted,
    error = AlertRed,
    onError = Color.White,
    outline = Color(0xFF374151),
    outlineVariant = Color(0xFF1F2937)
)

@Composable
fun SnifferOpsTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = DarkColorScheme,
        typography = Typography(),
        content = content
    )
}
