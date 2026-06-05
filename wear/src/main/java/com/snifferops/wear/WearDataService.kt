package com.snifferops.wear

import android.util.Log
import com.google.android.gms.wearable.DataEventBuffer
import com.google.android.gms.wearable.MessageEvent
import com.google.android.gms.wearable.WearableListenerService

class WearDataService : WearableListenerService() {

    companion object {
        private const val TAG = "SnifferOpsWearSync"
    }

    override fun onDataChanged(dataEvents: DataEventBuffer) {
        dataEvents.forEach { event ->
            when (event.dataItem.uri.path) {
                "/snifferops/summary" -> {
                    val dataMap = com.google.android.gms.wearable.DataMapItem
                        .fromDataItem(event.dataItem).dataMap
                    Log.d(
                        TAG,
                        "Received summary scanning=${dataMap.getBoolean("scanning", false)} " +
                            "wifi=${dataMap.getInt("wifi", 0)} bt=${dataMap.getInt("bt", 0)} " +
                            "cell=${dataMap.getInt("cell", 0)} sdr=${dataMap.getInt("sdr", 0)} " +
                            "alerts=${dataMap.getInt("alerts", 0)}"
                    )
                    WearStateHolder.update(
                        wifi = dataMap.getInt("wifi", 0),
                        bt = dataMap.getInt("bt", 0),
                        cell = dataMap.getInt("cell", 0),
                        sdr = dataMap.getInt("sdr", 0),
                        alerts = dataMap.getInt("alerts", 0),
                        scanning = dataMap.getBoolean("scanning", false),
                        sdrConnected = dataMap.getBoolean("sdr_connected", false)
                    )
                }
            }
        }
    }

    override fun onMessageReceived(messageEvent: MessageEvent) {
        // Handle control messages from watch tile
    }
}
