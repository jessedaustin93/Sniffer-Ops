package com.snifferops.data

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.TypeConverter
import androidx.room.TypeConverters
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase
import com.snifferops.model.SignalDevice
import com.snifferops.model.SignalSighting
import com.snifferops.model.SignalType
import com.snifferops.model.ThreatLevel

class Converters {
    @TypeConverter
    fun fromSignalType(value: SignalType): String = value.name

    @TypeConverter
    fun toSignalType(value: String): SignalType = SignalType.valueOf(value)

    @TypeConverter
    fun fromThreatLevel(value: ThreatLevel): String = value.name

    @TypeConverter
    fun toThreatLevel(value: String): ThreatLevel = ThreatLevel.valueOf(value)
}

@Database(entities = [SignalDevice::class, SignalSighting::class], version = 2, exportSchema = false)
@TypeConverters(Converters::class)
abstract class AppDatabase : RoomDatabase() {
    abstract fun signalDeviceDao(): SignalDeviceDao

    companion object {
        @Volatile private var INSTANCE: AppDatabase? = null

        private val MIGRATION_1_2 = object : Migration(1, 2) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL(
                    """
                    CREATE TABLE IF NOT EXISTS signal_sightings (
                        id TEXT NOT NULL PRIMARY KEY,
                        deviceId TEXT NOT NULL,
                        capturedAt INTEGER NOT NULL,
                        latitude REAL,
                        longitude REAL,
                        accuracyMeters REAL,
                        signalStrength INTEGER NOT NULL,
                        syncedAt INTEGER
                    )
                    """.trimIndent()
                )
                db.execSQL("CREATE INDEX IF NOT EXISTS index_signal_sightings_deviceId ON signal_sightings(deviceId)")
                db.execSQL("CREATE INDEX IF NOT EXISTS index_signal_sightings_capturedAt ON signal_sightings(capturedAt)")
                db.execSQL("CREATE INDEX IF NOT EXISTS index_signal_sightings_syncedAt ON signal_sightings(syncedAt)")
                db.execSQL(
                    """
                    INSERT INTO signal_sightings (
                        id, deviceId, capturedAt, latitude, longitude,
                        accuracyMeters, signalStrength, syncedAt
                    )
                    SELECT
                        'legacy-' || id || '-' || lastSeen,
                        id,
                        lastSeen,
                        CASE WHEN latitude = 0.0 THEN NULL ELSE latitude END,
                        CASE WHEN longitude = 0.0 THEN NULL ELSE longitude END,
                        NULL,
                        signalStrength,
                        NULL
                    FROM signal_devices
                    """.trimIndent()
                )
            }
        }

        fun getInstance(context: Context): AppDatabase =
            INSTANCE ?: synchronized(this) {
                Room.databaseBuilder(context, AppDatabase::class.java, "snifferops.db")
                    .addMigrations(MIGRATION_1_2)
                    .build()
                    .also { INSTANCE = it }
            }
    }
}
