package com.snifferops.ui.screen

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Divider
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import com.snifferops.model.CellTower
import com.snifferops.model.SdrSignal
import com.snifferops.model.SignalDevice
import com.snifferops.ui.theme.BackgroundDark
import com.snifferops.ui.theme.OnSurface
import com.snifferops.ui.theme.OnSurfaceMuted
import com.snifferops.ui.theme.SurfaceDark

data class SignalDetailRow(val label: String, val value: String)

@Composable
fun EstimatedInfoFooter(modifier: Modifier = Modifier) {
    Text(
        "* type/info is estimated",
        color = OnSurfaceMuted,
        fontSize = 11.sp,
        fontFamily = FontFamily.Monospace,
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 10.dp)
    )
}

@Composable
fun SignalDetailDialog(
    title: String,
    subtitle: String,
    rows: List<SignalDetailRow>,
    onDismiss: () -> Unit
) {
    Dialog(onDismissRequest = onDismiss) {
        Surface(
            shape = RoundedCornerShape(12.dp),
            color = BackgroundDark,
            tonalElevation = 8.dp,
            modifier = Modifier.fillMaxWidth()
        ) {
            Column(modifier = Modifier.padding(16.dp)) {
                Text(
                    title.uppercase(),
                    color = OnSurface,
                    fontWeight = FontWeight.Bold,
                    fontSize = 16.sp,
                    fontFamily = FontFamily.Monospace
                )
                if (subtitle.isNotBlank()) {
                    Text(
                        subtitle,
                        color = OnSurfaceMuted,
                        fontSize = 12.sp,
                        fontFamily = FontFamily.Monospace,
                        modifier = Modifier.padding(top = 2.dp)
                    )
                }
                Spacer(Modifier.heightIn(min = 12.dp))
                LazyColumn(
                    modifier = Modifier.heightIn(max = 420.dp),
                    contentPadding = PaddingValues(vertical = 4.dp),
                    verticalArrangement = Arrangement.spacedBy(0.dp)
                ) {
                    items(rows.filter { it.value.isNotBlank() }) { row ->
                        DetailRow(row)
                    }
                }
                EstimatedInfoFooter(modifier = Modifier.padding(top = 8.dp))
            }
        }
    }
}

@Composable
private fun DetailRow(row: SignalDetailRow) {
    Column {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 6.dp)
        ) {
            Text(
                row.label,
                color = OnSurfaceMuted,
                fontSize = 11.sp,
                fontFamily = FontFamily.Monospace,
                modifier = Modifier.width(112.dp)
            )
            Text(
                row.value,
                color = OnSurface,
                fontSize = 12.sp,
                fontFamily = FontFamily.Monospace,
                modifier = Modifier.weight(1f)
            )
        }
        Divider(color = SurfaceDark)
    }
}

fun SignalDevice.detailRows(): List<SignalDetailRow> = listOf(
    SignalDetailRow("Name", name.ifBlank { signalType.name }),
    SignalDetailRow("Type*", deviceClass.ifBlank { signalType.name }),
    SignalDetailRow("Signal", "$signalStrength dBm"),
    SignalDetailRow("ID", address),
    SignalDetailRow("Vendor", manufacturer.takeUnless { it == "Unknown" }.orEmpty()),
    SignalDetailRow("Channel", channel.takeIf { it > 0 }?.toString().orEmpty()),
    SignalDetailRow("Frequency", frequency.takeIf { it > 0 }?.let { formatSignalFrequency(it) }.orEmpty()),
    SignalDetailRow("Security", if (signalType.name == "WIFI") if (isEncrypted) "Encrypted" else "Open" else ""),
    SignalDetailRow("Raw", notes),
    SignalDetailRow("Threat", threatLevel.name),
    SignalDetailRow("Seen", seenCount.toString())
)

fun CellTower.detailRows(): List<SignalDetailRow> = listOf(
    SignalDetailRow("Type*", "$technology cell tower"),
    SignalDetailRow("Signal", "$signalStrength dBm"),
    SignalDetailRow("Carrier", carrier),
    SignalDetailRow("CID/NCI", cid.toString()),
    SignalDetailRow("LAC/TAC", lac.toString()),
    SignalDetailRow("MCC", mcc.toString()),
    SignalDetailRow("MNC", mnc.toString()),
    SignalDetailRow("Frequency", frequency.takeIf { it > 0 }?.toString().orEmpty())
)

fun SdrSignal.detailRows(): List<SignalDetailRow> = listOf(
    SignalDetailRow("Type*", label.ifBlank { "RF signal" }),
    SignalDetailRow("Frequency", formatSignalFrequency(frequency)),
    SignalDetailRow("Signal", "${power.toInt()} dB"),
    SignalDetailRow("Mode", modulation),
    SignalDetailRow("Bandwidth", bandwidth.takeIf { it > 0 }?.let { formatSignalFrequency(it) }.orEmpty())
)

fun formatSignalFrequency(hz: Long): String = when {
    hz >= 1_000_000_000L -> "${"%.3f".format(hz / 1_000_000_000.0)} GHz"
    hz >= 1_000_000L -> "${"%.3f".format(hz / 1_000_000.0)} MHz"
    hz >= 1_000L -> "${"%.1f".format(hz / 1_000.0)} kHz"
    else -> "$hz Hz"
}
