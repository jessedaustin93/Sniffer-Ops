package com.snifferops.data

import androidx.room.*
import com.snifferops.model.SignalDevice
import com.snifferops.model.SignalType
import kotlinx.coroutines.flow.Flow

@Dao
interface SignalDeviceDao {
    @Query("SELECT * FROM signal_devices ORDER BY lastSeen DESC")
    fun getAllDevices(): Flow<List<SignalDevice>>

    @Query("SELECT * FROM signal_devices WHERE signalType = :type ORDER BY lastSeen DESC")
    fun getDevicesByType(type: SignalType): Flow<List<SignalDevice>>

    @Query("SELECT * FROM signal_devices WHERE threatLevel IN ('SUSPICIOUS','ALERT') ORDER BY lastSeen DESC")
    fun getAlerts(): Flow<List<SignalDevice>>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertOrUpdate(device: SignalDevice)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(devices: List<SignalDevice>)

    @Query("DELETE FROM signal_devices WHERE signalType = :type")
    suspend fun deleteByType(type: SignalType)

    @Query("DELETE FROM signal_devices")
    suspend fun deleteAll()

    @Query("SELECT COUNT(*) FROM signal_devices WHERE signalType = :type")
    suspend fun countByType(type: SignalType): Int
}
