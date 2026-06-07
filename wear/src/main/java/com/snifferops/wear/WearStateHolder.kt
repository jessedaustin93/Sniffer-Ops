package com.snifferops.wear

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

data class WearState(
    val wifiCount: Int = 0,
    val btCount: Int = 0,
    val cellCount: Int = 0,
    val sdrCount: Int = 0,
    val alertCount: Int = 0,
    val awarenessCount: Int = 0,
    val scanning: Boolean = false,
    val sdrConnected: Boolean = false,
    val wifiItems: List<WearSignalItem> = emptyList(),
    val btItems: List<WearSignalItem> = emptyList(),
    val cellItems: List<WearSignalItem> = emptyList(),
    val sdrItems: List<WearSignalItem> = emptyList(),
    val alertItems: List<WearSignalItem> = emptyList(),
    val awarenessItems: List<WearSignalItem> = emptyList()
)

data class WearSignalItem(
    val title: String,
    val detail: String,
    val value: String
)

object WearStateHolder {
    private val _state = MutableStateFlow(WearState())
    val state: StateFlow<WearState> = _state

    fun update(
        wifi: Int, bt: Int, cell: Int, sdr: Int,
        alerts: Int,
        awareness: Int = 0,
        scanning: Boolean,
        sdrConnected: Boolean,
        wifiItems: List<WearSignalItem> = emptyList(),
        btItems: List<WearSignalItem> = emptyList(),
        cellItems: List<WearSignalItem> = emptyList(),
        sdrItems: List<WearSignalItem> = emptyList(),
        alertItems: List<WearSignalItem> = emptyList(),
        awarenessItems: List<WearSignalItem> = emptyList()
    ) {
        _state.value = WearState(
            wifiCount = wifi,
            btCount = bt,
            cellCount = cell,
            sdrCount = sdr,
            alertCount = alerts,
            awarenessCount = awareness,
            scanning = scanning,
            sdrConnected = sdrConnected,
            wifiItems = wifiItems,
            btItems = btItems,
            cellItems = cellItems,
            sdrItems = sdrItems,
            alertItems = alertItems,
            awarenessItems = awarenessItems
        )
    }
}
