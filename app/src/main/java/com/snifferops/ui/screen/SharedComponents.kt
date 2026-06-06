package com.snifferops.ui.screen

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.snifferops.model.ThreatLevel
import com.snifferops.ui.theme.*

@Composable
fun ScanControlBar(
    scanning: Boolean,
    count: Int,
    color: Color,
    onStart: () -> Unit,
    onStop: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Text(
            "$count detected",
            color = OnSurfaceMuted,
            fontFamily = FontFamily.Monospace,
            fontSize = 13.sp
        )
        Button(
            onClick = if (scanning) onStop else onStart,
            colors = ButtonDefaults.buttonColors(
                containerColor = if (scanning) AlertRed else color,
                contentColor = Color.Black
            ),
            shape = RoundedCornerShape(6.dp),
            contentPadding = PaddingValues(horizontal = 20.dp, vertical = 8.dp)
        ) {
            Icon(
                if (scanning) Icons.Default.Stop else Icons.Default.PlayArrow,
                null,
                modifier = Modifier.size(16.dp)
            )
            Spacer(Modifier.width(6.dp))
            Text(
                if (scanning) "STOP" else "SCAN",
                fontFamily = FontFamily.Monospace,
                fontWeight = FontWeight.Bold,
                fontSize = 12.sp,
                letterSpacing = 1.sp
            )
        }
    }
}

@Composable
fun ThreatBadge(level: ThreatLevel) {
    if (level == ThreatLevel.SAFE) return
    Surface(
        shape = RoundedCornerShape(4.dp),
        color = level.toColor().copy(alpha = 0.15f)
    ) {
        Text(
            level.toLabel(),
            color = level.toColor(),
            fontSize = 9.sp,
            fontFamily = FontFamily.Monospace,
            fontWeight = FontWeight.Bold,
            letterSpacing = 1.sp,
            modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp)
        )
    }
}

@Composable
fun SignalBars(strength: Int, color: Color) {
    val bars = when {
        strength >= -50 -> 4
        strength >= -65 -> 3
        strength >= -80 -> 2
        strength >= -95 -> 1
        else -> 0
    }
    Row(
        horizontalArrangement = Arrangement.spacedBy(2.dp),
        verticalAlignment = Alignment.Bottom,
        modifier = Modifier.height(24.dp)
    ) {
        (1..4).forEach { i ->
            Box(
                modifier = Modifier
                    .width(4.dp)
                    .height((i * 5 + 4).dp)
                    .background(
                        if (i <= bars) color else OnSurfaceMuted.copy(0.3f),
                        RoundedCornerShape(1.dp)
                    )
            )
        }
    }
}

@Composable
fun EmptyState(title: String, subtitle: String) {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .padding(32.dp),
        contentAlignment = Alignment.Center
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Icon(
                Icons.Default.Search, "Empty",
                tint = OnSurfaceMuted.copy(0.4f),
                modifier = Modifier.size(48.dp)
            )
            Text(
                title,
                color = OnSurfaceMuted,
                fontFamily = FontFamily.Monospace,
                fontSize = 14.sp,
                fontWeight = FontWeight.Medium
            )
            Text(subtitle, color = OnSurfaceMuted.copy(0.6f), fontSize = 12.sp)
        }
    }
}
