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
import com.snifferops.util.SignalDeviceGroup
import com.snifferops.ui.theme.BackgroundDark
import com.snifferops.ui.theme.OnSurface
import com.snifferops.ui.theme.OnSurfaceMuted
import com.snifferops.ui.theme.SurfaceDark
import com.snifferops.ui.theme.toLabel

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
    SignalDetailRow("Frequency", displayFrequency()),
    SignalDetailRow("Security", if (signalType.name == "WIFI") if (isEncrypted) "Encrypted" else "Open" else ""),
    SignalDetailRow("Raw", notes),
    SignalDetailRow("Alert", threatLevel.toLabel()),
    SignalDetailRow("Seen", seenCount.toString())
)

fun SignalDeviceGroup.detailRows(): List<SignalDetailRow> {
    val ids = devices.joinToString("\n") { device ->
        listOf(
            device.name.ifBlank { device.signalType.name },
            device.address,
            device.channel.takeIf { it > 0 }?.let { "Ch $it" }.orEmpty(),
            device.displayFrequency(),
            "${device.signalStrength} dBm"
        ).filter { it.isNotBlank() }.joinToString("  ")
    }
    val types = devices.map { it.deviceClass.ifBlank { it.signalType.name } }
        .distinct()
        .joinToString(", ")
    val bands = devices.mapNotNull { it.wifiBandLabel() }
        .distinct()
        .joinToString(", ")
    val channels = devices.mapNotNull { it.channel.takeIf { channel -> channel > 0 } }
        .distinct()
        .joinToString(", ")
    return listOf(
        SignalDetailRow("Name", title),
        SignalDetailRow("Type*", typeLabel),
        SignalDetailRow("Definition", groupDefinition()),
        SignalDetailRow("Alert", primary.threatLevel.toLabel()),
        SignalDetailRow("Signals", count.toString()),
        SignalDetailRow("Best", "$strongestSignal dBm"),
        SignalDetailRow("Vendor", primary.manufacturer.takeUnless { it == "Unknown" }.orEmpty()),
        SignalDetailRow("Types*", types),
        SignalDetailRow("Bands", bands),
        SignalDetailRow("Channels", channels),
        SignalDetailRow("Security", if (primary.signalType.name == "WIFI") if (primary.isEncrypted) "Encrypted" else "Open" else ""),
        SignalDetailRow("Raw", primary.notes),
        SignalDetailRow("IDs", ids)
    )
}

private fun SignalDeviceGroup.groupDefinition(): String {
    val label = typeLabel.lowercase()
    return when {
        label.contains("flock") ->
            "Possible Flock Safety camera or related BLE/WiFi component, grouped from matching Flock clues."
        label.contains("camera") || label.contains("surveillance") ->
            "Possible camera, doorbell, surveillance, or related wireless device."
        label.contains("wifi") && primary.signalType.name == "WIFI" ->
            "One WiFi unit grouped by SSID/name; multiple radios may show as separate 2.4/5 GHz signals."
        label.contains("bluetooth") || primary.signalType.name in setOf("BLUETOOTH", "BLE") ->
            "One Bluetooth/BLE unit grouped by matching name/type clues."
        else ->
            "Related signals grouped by matching name, type, vendor, or signal clues."
    }
}

private fun SignalDevice.wifiBandLabel(): String? {
    if (signalType.name != "WIFI") return null
    val mhz = frequency / 1000L
    return when {
        mhz in 2400L..2500L -> "2.4 GHz WiFi"
        mhz in 4900L..5900L -> "5 GHz WiFi"
        mhz in 5925L..7125L -> "6 GHz WiFi"
        channel in 1..14 -> "2.4 GHz WiFi"
        channel in 32..177 -> "5 GHz WiFi"
        channel > 0 -> "WiFi channel $channel"
        else -> null
    }
}

private fun SignalDevice.displayFrequency(): String =
    frequency.takeIf { it > 0 }?.let {
        if (signalType.name == "WIFI") formatSignalFrequency(it * 1000L) else formatSignalFrequency(it)
    }.orEmpty()

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
