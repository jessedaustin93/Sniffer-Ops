package com.snifferops.scanner

import android.content.Context
import android.app.PendingIntent
import android.content.Intent
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbEndpoint
import android.hardware.usb.UsbConstants
import android.hardware.usb.UsbManager
import android.os.Build
import com.snifferops.model.SdrSignal
import com.snifferops.util.DeviceClassifier
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import kotlin.math.ln
import kotlin.math.sqrt
import kotlin.random.Random

class RtlSdrScanner(private val context: Context) {

    companion object {
        const val ACTION_USB_PERMISSION = "com.snifferops.USB_PERMISSION"

        // RTL-SDR USB vendor/product IDs
        private val RTL_DEVICES = mapOf(
            Pair(0x0BDA, 0x2838) to "RTL-SDR Blog V4 / RTL2838",
            Pair(0x0BDA, 0x2832) to "RTL2832",
            Pair(0x0BDA, 0x2840) to "RTL2840 (R820T)",
            Pair(0x0BDA, 0x2836) to "RTL2836 (ezcap)"
        )

        // Well-known frequencies to scan (MHz)
        val SCAN_FREQUENCIES = longArrayOf(
            88_000_000L,   // FM Radio center
            108_500_000L,  // Aviation
            137_500_000L,  // NOAA Weather Sat
            154_000_000L,  // Public Safety VHF
            162_400_000L,  // NOAA Weather Radio
            433_920_000L,  // ISM 433 (Car keys, garage doors)
            462_562_500L,  // GMRS/FRS
            851_000_000L,  // P25 Public Safety
            915_000_000L,  // ISM 915 (LoRa, ZigBee)
            978_000_000L,  // ADS-B Mode S
            1_090_000_000L // ADS-B 1090MHz
        )

        private const val DETECTION_PROMINENCE_DB = 10f
    }

    private val usbManager = context.getSystemService(Context.USB_SERVICE) as UsbManager

    fun findRtlDevice(): UsbDevice? {
        val devices = usbManager.deviceList ?: return null
        return devices.values.firstOrNull { device ->
            RTL_DEVICES.containsKey(Pair(device.vendorId, device.productId))
        }
    }

    fun isConnected(): Boolean = findRtlDevice() != null

    fun hasPermission(): Boolean {
        val device = findRtlDevice() ?: return false
        return usbManager.hasPermission(device)
    }

    fun requestPermission(): Boolean {
        val device = findRtlDevice() ?: return false
        if (usbManager.hasPermission(device)) return true

        val flags = PendingIntent.FLAG_UPDATE_CURRENT or
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) PendingIntent.FLAG_MUTABLE else 0
        val permissionIntent = PendingIntent.getBroadcast(
            context,
            0,
            Intent(ACTION_USB_PERMISSION).setPackage(context.packageName),
            flags
        )
        usbManager.requestPermission(device, permissionIntent)
        return false
    }

    fun getDeviceName(): String {
        val device = findRtlDevice() ?: return "Not Connected"
        return RTL_DEVICES[Pair(device.vendorId, device.productId)] ?: "RTL-SDR"
    }

    fun scanSpectrum(
        centerFrequency: Long = 100_000_000L,
        sampleRate: Long = 2_048_000L,
        gain: Int = 20
    ): Flow<List<SdrSignal>> = flow {
        val device = findRtlDevice() ?: return@flow
        if (!usbManager.hasPermission(device)) return@flow

        val connection = usbManager.openDevice(device) ?: return@flow

        try {
            val iface = device.getInterface(0)
            val endpoint = getBulkInEndpoint(device) ?: return@flow
            connection.claimInterface(iface, true)

            // RTL2832U control commands via USB control transfer
            // Reset device
            rtlWrite(connection, 0x01, 0x0000, byteArrayOf(0x00))
            delay(50)

            // Set sample rate
            setSampleRate(connection, sampleRate)

            // Set center frequency
            setCenterFrequency(connection, centerFrequency)

            // Set gain
            setGain(connection, gain)

            // Start streaming
            while (true) {
                val buffer = ByteArray(16384)
                val read = connection.bulkTransfer(endpoint, buffer, buffer.size, 1000)
                if (read > 0) {
                    val signals = processIqSamples(buffer, read, centerFrequency, sampleRate)
                    emit(signals)
                }
                delay(100)
            }
        } finally {
            runCatching { connection.releaseInterface(device.getInterface(0)) }
            connection.close()
        }
    }.flowOn(Dispatchers.IO)

    // Sweep through predefined frequencies
    fun sweepFrequencies(): Flow<List<SdrSignal>> = flow {
        val device = findRtlDevice() ?: return@flow
        if (!usbManager.hasPermission(device)) return@flow

        val measured = mutableListOf<Pair<Long, Float>>()

        for (freq in SCAN_FREQUENCIES) {
            samplePowerAtFrequency(freq)?.let { power ->
                measured += freq to power
                emit(detectionsFromSweep(measured))
            }
            delay(200)
        }
    }.flowOn(Dispatchers.IO)

    private suspend fun samplePowerAtFrequency(frequency: Long): Float? {
        val device = findRtlDevice() ?: return null
        val connection = usbManager.openDevice(device) ?: return null

        try {
            val iface = device.getInterface(0)
            val endpoint = getBulkInEndpoint(device) ?: return null
            connection.claimInterface(iface, true)
            setCenterFrequency(connection, frequency)
            delay(50)

            val buffer = ByteArray(16384)
            val read = connection.bulkTransfer(endpoint, buffer, buffer.size, 500)
            if (read > 0) {
                return calculatePower(buffer, read)
            }
        } finally {
            runCatching { connection.releaseInterface(device.getInterface(0)) }
            connection.close()
        }

        return null
    }

    private fun detectionsFromSweep(measured: List<Pair<Long, Float>>): List<SdrSignal> {
        if (measured.size < 3) return emptyList()
        val floor = median(measured.map { it.second })
        val cutoff = floor + DETECTION_PROMINENCE_DB
        return measured
            .filter { it.second >= cutoff }
            .sortedByDescending { it.second }
            .map { (frequency, power) ->
                val (label, modulation) = DeviceClassifier.classifySdrSignal(frequency)
                SdrSignal(
                    frequency = frequency,
                    power = power,
                    modulation = modulation,
                    label = label
                )
            }
    }

    private fun median(values: List<Float>): Float {
        if (values.isEmpty()) return -120f
        val sorted = values.sorted()
        val mid = sorted.size / 2
        return if (sorted.size % 2 == 1) sorted[mid] else (sorted[mid - 1] + sorted[mid]) / 2f
    }

    private fun getBulkInEndpoint(device: UsbDevice): UsbEndpoint? {
        for (i in 0 until device.interfaceCount) {
            val iface = device.getInterface(i)
            for (e in 0 until iface.endpointCount) {
                val endpoint = iface.getEndpoint(e)
                if (endpoint.type == UsbConstants.USB_ENDPOINT_XFER_BULK &&
                    endpoint.direction == UsbConstants.USB_DIR_IN
                ) {
                    return endpoint
                }
            }
        }
        return null
    }

    private fun processIqSamples(
        buffer: ByteArray,
        length: Int,
        centerFreq: Long,
        sampleRate: Long
    ): List<SdrSignal> {
        // Simple FFT-based peak detection
        val signals = mutableListOf<SdrSignal>()
        val power = calculatePower(buffer, length)
        if (power > -80f) {
            val (label, modulation) = DeviceClassifier.classifySdrSignal(centerFreq)
            signals.add(SdrSignal(
                frequency = centerFreq,
                bandwidth = sampleRate,
                power = power,
                modulation = modulation,
                label = label
            ))
        }
        return signals
    }

    private fun calculatePower(buffer: ByteArray, length: Int): Float {
        var sumSq = 0.0
        val pairs = length / 2
        for (i in 0 until pairs) {
            val i_sample = (buffer[i * 2].toInt() and 0xFF) - 127.5
            val q_sample = (buffer[i * 2 + 1].toInt() and 0xFF) - 127.5
            sumSq += i_sample * i_sample + q_sample * q_sample
        }
        val rms = sqrt(sumSq / pairs)
        return if (rms > 0) (20 * ln(rms) / ln(10.0)).toFloat() else -120f
    }

    // RTL-SDR USB control transfer helpers
    private fun rtlWrite(connection: android.hardware.usb.UsbDeviceConnection, index: Int, value: Int, data: ByteArray) {
        connection.controlTransfer(0x40, 0x00, value, index, data, data.size, 1000)
    }

    private fun demodWrite(connection: android.hardware.usb.UsbDeviceConnection, reg: Int, value: Int, length: Int) {
        val data = when (length) {
            1 -> byteArrayOf(value.toByte())
            2 -> byteArrayOf((value shr 8).toByte(), value.toByte())
            else -> byteArrayOf(value.toByte())
        }
        connection.controlTransfer(0x40, 0x00, value, reg or 0x3000, data, data.size, 1000)
    }

    private fun setSampleRate(connection: android.hardware.usb.UsbDeviceConnection, rate: Long) {
        val rsamp_ratio = (28800000L * (1L shl 22) / rate).toInt() and 0x0FFFFFFC
        val real_rsamp_ratio = rsamp_ratio or (rsamp_ratio and 0x08000000 shl 1)
        val real_rate = (28800000L * (1L shl 22) / real_rsamp_ratio).toLong()
        demodWrite(connection, 0x19, (rsamp_ratio shr 16), 2)
        demodWrite(connection, 0x1A, rsamp_ratio and 0xFFFF, 2)
    }

    private fun setCenterFrequency(connection: android.hardware.usb.UsbDeviceConnection, freq: Long) {
        // Simplified tuner frequency set (R820T tuner)
        val freqKhz = (freq / 1000).toInt()
        connection.controlTransfer(0x40, 0x01, freqKhz and 0xFFFF, (freqKhz shr 16) and 0xFFFF,
            null, 0, 1000)
    }

    private fun setGain(connection: android.hardware.usb.UsbDeviceConnection, gain: Int) {
        demodWrite(connection, 0x04, gain, 1)
    }
}
