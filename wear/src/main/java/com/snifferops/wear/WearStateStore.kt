package com.snifferops.wear

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

object WearStateStore {
    private const val PREFS = "snifferops_wear_state"
    private const val KEY_STATE = "last_state"

    fun save(context: Context, state: WearState) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_STATE, state.toJson().toString())
            .apply()
    }

    fun load(context: Context): WearState? {
        val raw = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getString(KEY_STATE, null)
            ?: return null
        return runCatching { JSONObject(raw).toWearState() }.getOrNull()
    }

    private fun WearState.toJson(): JSONObject = JSONObject().apply {
        put("wifi", wifiCount)
        put("bt", btCount)
        put("cell", cellCount)
        put("sdr", sdrCount)
        put("alerts", alertCount)
        put("awareness", awarenessCount)
        put("scanning", scanning)
        put("sdrConnected", sdrConnected)
        put("wifiItems", wifiItems.toJson())
        put("btItems", btItems.toJson())
        put("cellItems", cellItems.toJson())
        put("sdrItems", sdrItems.toJson())
        put("alertItems", alertItems.toJson())
        put("awarenessItems", awarenessItems.toJson())
    }

    private fun JSONObject.toWearState(): WearState = WearState(
        wifiCount = optInt("wifi", 0),
        btCount = optInt("bt", 0),
        cellCount = optInt("cell", 0),
        sdrCount = optInt("sdr", 0),
        alertCount = optInt("alerts", 0),
        awarenessCount = optInt("awareness", 0),
        scanning = optBoolean("scanning", false),
        sdrConnected = optBoolean("sdrConnected", false),
        wifiItems = optJSONArray("wifiItems").toWearItems(),
        btItems = optJSONArray("btItems").toWearItems(),
        cellItems = optJSONArray("cellItems").toWearItems(),
        sdrItems = optJSONArray("sdrItems").toWearItems(),
        alertItems = optJSONArray("alertItems").toWearItems(),
        awarenessItems = optJSONArray("awarenessItems").toWearItems()
    )

    private fun List<WearSignalItem>.toJson(): JSONArray = JSONArray().apply {
        forEach { item ->
            put(JSONObject().apply {
                put("title", item.title)
                put("detail", item.detail)
                put("value", item.value)
            })
        }
    }

    private fun JSONArray?.toWearItems(): List<WearSignalItem> {
        if (this == null) return emptyList()
        return buildList {
            for (index in 0 until length()) {
                val item = optJSONObject(index) ?: continue
                add(
                    WearSignalItem(
                        title = item.optString("title"),
                        detail = item.optString("detail"),
                        value = item.optString("value")
                    )
                )
            }
        }
    }
}
