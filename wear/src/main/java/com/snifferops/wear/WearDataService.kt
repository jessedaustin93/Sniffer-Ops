package com.snifferops.wear

import android.util.Log
import com.google.android.gms.wearable.DataMap
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
                        awareness = dataMap.getInt("awareness", 0),
                        scanning = dataMap.getBoolean("scanning", false),
                        sdrConnected = dataMap.getBoolean("sdr_connected", false),
                        wifiItems = dataMap.readItems("wifi_items"),
                        btItems = dataMap.readItems("bt_items"),
                        cellItems = dataMap.readItems("cell_items"),
                        sdrItems = dataMap.readItems("sdr_items"),
                        alertItems = dataMap.readItems("alert_items"),
                        awarenessItems = dataMap.readItems("awareness_items")
                    )
                }
            }
        }
    }

    override fun onMessageReceived(messageEvent: MessageEvent) {
        // Handle control messages from watch tile
    }
}

fun DataMap.readItems(key: String): List<WearSignalItem> =
    getStringArrayList(key).orEmpty().mapNotNull { encoded ->
        val parts = encoded.split("|", limit = 3)
        if (parts.size == 3) WearSignalItem(parts[0], parts[1], parts[2]) else null
    }
