package com.snifferops.wear

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

data class WearState(
    val wifiCount: Int = 0,
    val btCount: Int = 0,
    val cellCount: Int = 0,
    val sdrCount: Int = 0,
    val alertCount: Int = 0,
    val scanning: Boolean = false,
    val sdrConnected: Boolean = false
)

object WearStateHolder {
    private val _state = MutableStateFlow(WearState())
    val state: StateFlow<WearState> = _state

    fun update(
        wifi: Int, bt: Int, cell: Int, sdr: Int,
        alerts: Int, scanning: Boolean, sdrConnected: Boolean
    ) {
        _state.value = WearState(wifi, bt, cell, sdr, alerts, scanning, sdrConnected)
    }
}
