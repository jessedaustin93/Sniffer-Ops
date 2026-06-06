package com.snifferops.ui.theme

import androidx.compose.ui.graphics.Color
import com.snifferops.model.ThreatLevel

fun ThreatLevel.toColor(): Color = when (this) {
    ThreatLevel.SAFE -> SafeGreen
    ThreatLevel.UNKNOWN -> SafeGreen
    ThreatLevel.SUSPICIOUS -> SuspiciousYellow
    ThreatLevel.ALERT -> AlertRed
}

fun ThreatLevel.toLabel(): String = when (this) {
    ThreatLevel.SAFE -> "SAFE"
    ThreatLevel.UNKNOWN -> "NOTICED"
    ThreatLevel.SUSPICIOUS -> "WATCH"
    ThreatLevel.ALERT -> "ALERT"
}
