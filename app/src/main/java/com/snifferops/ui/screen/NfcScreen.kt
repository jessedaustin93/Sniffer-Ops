package com.snifferops.ui.screen

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.snifferops.model.NfcTag
import com.snifferops.ui.theme.*

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun NfcScreen(
    lastTag: NfcTag?,
    onClear: () -> Unit,
    onBack: () -> Unit
) {
    Scaffold(
        containerColor = BackgroundDark,
        topBar = {
            TopAppBar(
                title = {
                    Text("NFC SCANNER", fontFamily = FontFamily.Monospace,
                        color = OnSurface, letterSpacing = 2.sp)
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.Default.ArrowBack, "Back", tint = OnSurface)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = SurfaceDark),
                actions = {
                    if (lastTag != null) {
                        IconButton(onClick = onClear) {
                            Icon(Icons.Default.Clear, "Clear", tint = AlertRed)
                        }
                    }
                }
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier.fillMaxSize().padding(padding).background(BackgroundDark).padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(24.dp)
        ) {
            // NFC wave animation area
            Box(
                modifier = Modifier.size(140.dp).clip(CircleShape)
                    .background(SurfaceVariantDark),
                contentAlignment = Alignment.Center
            ) {
                Icon(Icons.Default.Nfc, "NFC",
                    tint = if (lastTag != null) RadarGreen else OnSurfaceMuted,
                    modifier = Modifier.size(64.dp))
            }

            Text(
                if (lastTag != null) "TAG DETECTED" else "AWAITING NFC TAG",
                color = if (lastTag != null) RadarGreen else OnSurfaceMuted,
                fontFamily = FontFamily.Monospace,
                fontWeight = FontWeight.Bold,
                fontSize = 16.sp,
                letterSpacing = 3.sp
            )

            Text(
                if (lastTag != null) "Hold NFC tag near back of phone"
                else "Hold any NFC card, tag, or device near the back of your phone",
                color = OnSurfaceMuted,
                fontSize = 13.sp
            )

            if (lastTag != null) {
                Surface(
                    shape = RoundedCornerShape(12.dp),
                    color = SurfaceDark,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Column(
                        modifier = Modifier.padding(16.dp),
                        verticalArrangement = Arrangement.spacedBy(10.dp)
                    ) {
                        NfcInfoRow("TAG ID", lastTag.id)
                        NfcInfoRow("TYPE", lastTag.type)
                        NfcInfoRow("TECH", lastTag.technologies.joinToString(", "))
                        if (lastTag.data.isNotEmpty()) {
                            NfcInfoRow("DATA", lastTag.data)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun NfcInfoRow(label: String, value: String) {
    Column {
        Text(label, color = OnSurfaceMuted, fontSize = 10.sp, fontFamily = FontFamily.Monospace,
            letterSpacing = 2.sp)
        Text(value, color = OnSurface, fontSize = 13.sp, fontFamily = FontFamily.Monospace,
            fontWeight = FontWeight.Medium)
    }
}
