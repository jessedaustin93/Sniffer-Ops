package com.ethrox.detect.data

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.TypeConverter
import androidx.room.TypeConverters
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase
import com.ethrox.detect.model.SignalDevice
import com.ethrox.detect.model.SignalSighting
import com.ethrox.detect.model.SignalType
import com.ethrox.detect.model.ThreatLevel

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

@Database(entities = [SignalDevice::class, SignalSighting::class], version = 4, exportSchema = false)
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

        private val MIGRATION_2_3 = object : Migration(2, 3) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE signal_sightings ADD COLUMN movementSessionId TEXT")
                db.execSQL("ALTER TABLE signal_sightings ADD COLUMN speedMetersPerSecond REAL")
                db.execSQL("ALTER TABLE signal_sightings ADD COLUMN bearingDegrees REAL")
                db.execSQL("ALTER TABLE signal_sightings ADD COLUMN locationProvider TEXT")
            }
        }

        private val MIGRATION_3_4 = object : Migration(3, 4) {
            override fun migrate(db: SupportSQLiteDatabase) {
                val syncedExpression = if (columnExists(db, "signal_sightings", "linuxSyncedAt")) {
                    "COALESCE(syncedAt, linuxSyncedAt)"
                } else {
                    "syncedAt"
                }
                db.execSQL(
                    """
                    CREATE TABLE IF NOT EXISTS signal_sightings_room4 (
                        id TEXT NOT NULL PRIMARY KEY,
                        deviceId TEXT NOT NULL,
                        capturedAt INTEGER NOT NULL,
                        latitude REAL,
                        longitude REAL,
                        accuracyMeters REAL,
                        signalStrength INTEGER NOT NULL,
                        syncedAt INTEGER,
                        movementSessionId TEXT,
                        speedMetersPerSecond REAL,
                        bearingDegrees REAL,
                        locationProvider TEXT
                    )
                    """.trimIndent()
                )
                db.execSQL(
                    """
                    INSERT OR IGNORE INTO signal_sightings_room4 (
                        id, deviceId, capturedAt, latitude, longitude,
                        accuracyMeters, signalStrength, syncedAt
                    )
                    SELECT
                        id, deviceId, capturedAt, latitude, longitude,
                        accuracyMeters, signalStrength, $syncedExpression
                    FROM signal_sightings
                    """.trimIndent()
                )
                db.execSQL("DROP TABLE signal_sightings")
                db.execSQL("ALTER TABLE signal_sightings_room4 RENAME TO signal_sightings")
                db.execSQL("CREATE INDEX IF NOT EXISTS index_signal_sightings_deviceId ON signal_sightings(deviceId)")
                db.execSQL("CREATE INDEX IF NOT EXISTS index_signal_sightings_capturedAt ON signal_sightings(capturedAt)")
                db.execSQL("CREATE INDEX IF NOT EXISTS index_signal_sightings_syncedAt ON signal_sightings(syncedAt)")
            }
        }

        private fun columnExists(db: SupportSQLiteDatabase, tableName: String, columnName: String): Boolean {
            db.query("PRAGMA table_info($tableName)").use { cursor ->
                val nameIndex = cursor.getColumnIndex("name")
                while (cursor.moveToNext()) {
                    if (nameIndex >= 0 && cursor.getString(nameIndex) == columnName) return true
                }
            }
            return false
        }

        fun getInstance(context: Context): AppDatabase =
            INSTANCE ?: synchronized(this) {
                Room.databaseBuilder(context, AppDatabase::class.java, "ethrox-detect.db")
                    .addMigrations(MIGRATION_1_2, MIGRATION_2_3, MIGRATION_3_4)
                    .build()
                    .also { INSTANCE = it }
            }
    }
}
