package com.snifferops.scanner

import com.snifferops.model.SdrSignal
import com.snifferops.util.DeviceClassifier
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import java.io.OutputStream
import java.net.InetSocketAddress
import java.net.Socket
import kotlin.math.ln
import kotlin.math.sqrt

class NetworkRtlSdrScanner {

    companion object {
        private const val CONNECT_TIMEOUT_MS = 1500
        private const val READ_TIMEOUT_MS = 1200
        private const val DEFAULT_SAMPLE_RATE = 1_024_000
        private const val DEFAULT_GAIN = 0
    }

    fun sweepFrequencies(host: String, port: Int): Flow<List<SdrSignal>> = flow {
        if (host.isBlank()) return@flow

        Socket().use { socket ->
            socket.connect(InetSocketAddress(host.trim(), port), CONNECT_TIMEOUT_MS)
            socket.soTimeout = READ_TIMEOUT_MS

            val input = socket.getInputStream()
            val output = socket.getOutputStream()
            writeCommand(output, 0x02, DEFAULT_SAMPLE_RATE)
            writeCommand(output, 0x03, 0)
            writeCommand(output, 0x04, DEFAULT_GAIN)

            val allSignals = mutableListOf<SdrSignal>()
            for (frequency in RtlSdrScanner.SCAN_FREQUENCIES) {
                writeCommand(output, 0x01, frequency.toInt())
                delay(120)

                val buffer = ByteArray(16_384)
                val read = input.read(buffer)
                if (read > 0) {
                    val power = calculatePower(buffer, read)
                    if (power > -80f) {
                        val (label, modulation) = DeviceClassifier.classifySdrSignal(frequency)
                        allSignals.add(
                            SdrSignal(
                                frequency = frequency,
                                bandwidth = DEFAULT_SAMPLE_RATE.toLong(),
                                power = power,
                                modulation = modulation,
                                label = label
                            )
                        )
                        emit(allSignals.toList())
                    }
                }
            }
        }
    }.flowOn(Dispatchers.IO)

    private fun writeCommand(output: OutputStream, command: Int, parameter: Int) {
        output.write(
            byteArrayOf(
                command.toByte(),
                ((parameter ushr 24) and 0xFF).toByte(),
                ((parameter ushr 16) and 0xFF).toByte(),
                ((parameter ushr 8) and 0xFF).toByte(),
                (parameter and 0xFF).toByte()
            )
        )
        output.flush()
    }

    private fun calculatePower(buffer: ByteArray, length: Int): Float {
        var sumSq = 0.0
        val pairs = length / 2
        if (pairs == 0) return -120f

        for (i in 0 until pairs) {
            val iSample = (buffer[i * 2].toInt() and 0xFF) - 127.5
            val qSample = (buffer[i * 2 + 1].toInt() and 0xFF) - 127.5
            sumSq += iSample * iSample + qSample * qSample
        }

        val rms = sqrt(sumSq / pairs)
        return if (rms > 0) (20 * ln(rms) / ln(10.0)).toFloat() else -120f
    }
}
