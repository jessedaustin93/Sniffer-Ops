package com.snifferops.data

import androidx.room.*
import com.snifferops.model.SignalDevice
import com.snifferops.model.SignalSighting
import com.snifferops.model.SignalType
import kotlinx.coroutines.flow.Flow

@Dao
interface SignalDeviceDao {
    @Query("SELECT * FROM signal_devices ORDER BY lastSeen DESC")
    fun getAllDevices(): Flow<List<SignalDevice>>

    @Query("SELECT * FROM signal_devices ORDER BY lastSeen DESC")
    suspend fun getAllDevicesOnce(): List<SignalDevice>

    @Query("SELECT * FROM signal_devices WHERE signalType = :type ORDER BY lastSeen DESC")
    fun getDevicesByType(type: SignalType): Flow<List<SignalDevice>>

    @Query("SELECT * FROM signal_devices WHERE id = :id LIMIT 1")
    suspend fun getDeviceById(id: String): SignalDevice?

    @Query("SELECT * FROM signal_devices WHERE threatLevel IN ('UNKNOWN','SUSPICIOUS','ALERT') ORDER BY lastSeen DESC")
    fun getAlerts(): Flow<List<SignalDevice>>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertOrUpdate(device: SignalDevice)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(devices: List<SignalDevice>)

    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insertSightings(sightings: List<SignalSighting>)

    @Query("SELECT * FROM signal_sightings WHERE syncedAt IS NULL ORDER BY capturedAt ASC LIMIT :limit")
    suspend fun getUnsyncedSightings(limit: Int = 2000): List<SignalSighting>

    @Query("UPDATE signal_sightings SET syncedAt = :syncedAt WHERE id IN (:ids)")
    suspend fun markSightingsSynced(ids: List<String>, syncedAt: Long)

    @Query("DELETE FROM signal_sightings WHERE id IN (:ids)")
    suspend fun deleteSightings(ids: List<String>)

    @Query("SELECT COUNT(*) FROM signal_sightings WHERE syncedAt IS NOT NULL")
    suspend fun countConfirmedSightings(): Int

    @Query("DELETE FROM signal_sightings WHERE syncedAt IS NOT NULL")
    suspend fun deleteConfirmedSightings(): Int

    @Query("SELECT COUNT(*) FROM signal_sightings")
    suspend fun countSightings(): Int

    @Transaction
    suspend fun storeDetectionBatch(devices: List<SignalDevice>, sightings: List<SignalSighting>) {
        insertAll(devices)
        insertSightings(sightings)
    }

    @Query("DELETE FROM signal_devices WHERE signalType = :type")
    suspend fun deleteByType(type: SignalType)

    @Query("DELETE FROM signal_devices")
    suspend fun deleteAll()

    @Query("DELETE FROM signal_sightings")
    suspend fun deleteAllSightings()

    @Query("SELECT COUNT(*) FROM signal_devices WHERE signalType = :type")
    suspend fun countByType(type: SignalType): Int
}
