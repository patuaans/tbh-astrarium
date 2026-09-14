"""Durable local storage for TBH Astrarium user data.

The database lives outside the application directory so replacing a portable
build cannot replace user data.  Writes use SQLite transactions and a rolling
snapshot preserves the last committed state before a change.
"""

import json
import os
import shutil
import sqlite3
import time
from contextlib import closing
from pathlib import Path


SCHEMA_VERSION = 1
APP_DATA_DIRECTORY = "TBHAstrarium"
DATABASE_FILENAME = "TBHAstrarium.db"
LEGACY_APP_DATA_DIRECTORY = "TBHStargaze"
LEGACY_DATABASE_FILENAME = "TBHStargaze.db"


class StorageError(RuntimeError):
    pass


def default_storage_path():
    root = os.environ.get("LOCALAPPDATA")
    if root:
        return Path(root) / APP_DATA_DIRECTORY / DATABASE_FILENAME
    return Path.home() / ".tbhastrarium" / DATABASE_FILENAME


def legacy_storage_paths():
    root = os.environ.get("LOCALAPPDATA")
    if root:
        return (Path(root) / LEGACY_APP_DATA_DIRECTORY / LEGACY_DATABASE_FILENAME,)
    return (Path.home() / ".tbhstargaze" / LEGACY_DATABASE_FILENAME,)


def atomic_write_json(path, value):
    """Keep the legacy readable copy without risking a half-written file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


class TBHStorage:
    WATCH_MIGRATION = "legacy.watch-list.v1"
    CHEST_MIGRATION = "legacy.chest-cooldowns.v1"
    CUBE_MIGRATION = "legacy.cube-settings.v1"

    def __init__(self, path=None):
        default_path = path is None
        self.path = Path(path) if path is not None else default_storage_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.backup_path = self.path.with_name(f"{self.path.stem}.backup{self.path.suffix}")
        self.recovered_from_backup = False
        if default_path:
            self._migrate_renamed_database()
        self._recover_if_needed()
        self._initialize()

    def _migrate_renamed_database(self):
        """Copy the last valid Stargaze database into the renamed app once."""
        if self.path.exists() or self.backup_path.exists():
            return
        for legacy in legacy_storage_paths():
            legacy_backup = legacy.with_name(f"{legacy.stem}.backup{legacy.suffix}")
            source = next((candidate for candidate in (legacy, legacy_backup)
                           if self._check_file(candidate)), None)
            if source is None:
                continue
            temporary = self.path.with_name(self.path.name + ".rename-migration.tmp")
            try:
                temporary.unlink(missing_ok=True)
                shutil.copy2(source, temporary)
                if not self._check_file(temporary):
                    raise StorageError("The renamed database copy did not pass its integrity check.")
                os.replace(temporary, self.path)
                if self._check_file(legacy_backup):
                    shutil.copy2(legacy_backup, self.backup_path)
                return
            except (OSError, sqlite3.Error) as error:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
                raise StorageError(f"Cannot migrate user data to {self.path}: {error}") from error

    @staticmethod
    def _check_file(path):
        if not Path(path).exists():
            return False
        try:
            with closing(sqlite3.connect(path, timeout=5)) as connection:
                return connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        except sqlite3.Error:
            return False

    def _recover_if_needed(self):
        if not self.path.exists():
            if self._check_file(self.backup_path):
                shutil.copy2(self.backup_path, self.path)
                self.recovered_from_backup = True
            return
        if self._check_file(self.path):
            return
        corrupt = self.path.with_name(
            f"{self.path.stem}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}{self.path.suffix}"
        )
        os.replace(self.path, corrupt)
        if self._check_file(self.backup_path):
            shutil.copy2(self.backup_path, self.path)
            self.recovered_from_backup = True

    def _connect(self):
        try:
            connection = sqlite3.connect(self.path, timeout=5)
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute("PRAGMA synchronous=FULL")
            return connection
        except sqlite3.Error as error:
            raise StorageError(str(error)) from error

    def _initialize(self):
        try:
            with closing(self._connect()) as connection, connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS watch_items (
                        item_id TEXT PRIMARY KEY,
                        created_at REAL NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY,
                        value_json TEXT NOT NULL,
                        updated_at REAL NOT NULL
                    );
                    """
                )
                connection.execute(
                    "INSERT OR REPLACE INTO metadata(key, value) VALUES('schema_version', ?)",
                    (str(SCHEMA_VERSION),),
                )
        except (sqlite3.Error, OSError) as error:
            raise StorageError(f"Cannot initialize {self.path}: {error}") from error

    def backup_current(self):
        """Atomically replace the rolling backup with a valid SQLite snapshot."""
        if not self._check_file(self.path):
            return False
        temporary = self.backup_path.with_name(self.backup_path.name + ".tmp")
        try:
            if temporary.exists():
                temporary.unlink()
            with closing(sqlite3.connect(self.path, timeout=5)) as source:
                with closing(sqlite3.connect(temporary, timeout=5)) as target:
                    source.backup(target)
            if not self._check_file(temporary):
                raise StorageError("The database backup did not pass its integrity check.")
            os.replace(temporary, self.backup_path)
            return True
        except (sqlite3.Error, OSError) as error:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise StorageError(f"Cannot back up {self.path}: {error}") from error

    def _write(self, operation):
        # Preserve the last known-good state before mutating the primary file.
        if self.path.exists():
            self.backup_current()
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                operation(connection)
        except (sqlite3.Error, OSError) as error:
            raise StorageError(f"Cannot save {self.path}: {error}") from error

    def get_metadata(self, key):
        try:
            with closing(self._connect()) as connection:
                row = connection.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
            return row[0] if row else None
        except sqlite3.Error as error:
            raise StorageError(str(error)) from error

    def _mark_migration(self, connection, key):
        connection.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)",
            (key, str(time.time())),
        )

    @staticmethod
    def _first_valid_json(paths, expected_type):
        for path in (Path(value) for value in paths):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
            if isinstance(value, expected_type):
                return value
        return None

    def migrate_legacy(self, watch_paths=(), chest_paths=(), cube_paths=()):
        """Import valid JSON once. Existing database values always win."""
        changed = False
        if self.get_metadata(self.WATCH_MIGRATION) is None:
            values = self._first_valid_json(watch_paths, list)
            if values is not None:
                item_ids = sorted({str(value) for value in values})

                def import_watch(connection):
                    count = connection.execute("SELECT COUNT(*) FROM watch_items").fetchone()[0]
                    if not count:
                        connection.executemany(
                            "INSERT INTO watch_items(item_id, created_at) VALUES(?, ?)",
                            ((item_id, time.time()) for item_id in item_ids),
                        )
                    self._mark_migration(connection, self.WATCH_MIGRATION)

                self._write(import_watch)
                changed = True
        for migration, setting_key, paths in (
            (self.CHEST_MIGRATION, "chest_cooldowns", chest_paths),
            (self.CUBE_MIGRATION, "cube_settings", cube_paths),
        ):
            if self.get_metadata(migration) is not None:
                continue
            value = self._first_valid_json(paths, dict)
            if value is None:
                continue

            def import_setting(connection, migration=migration, setting_key=setting_key, value=value):
                exists = connection.execute("SELECT 1 FROM settings WHERE key=?", (setting_key,)).fetchone()
                if not exists:
                    connection.execute(
                        "INSERT INTO settings(key, value_json, updated_at) VALUES(?, ?, ?)",
                        (setting_key, json.dumps(value, ensure_ascii=False, sort_keys=True), time.time()),
                    )
                self._mark_migration(connection, migration)

            self._write(import_setting)
            changed = True
        if changed:
            self.backup_current()
        return changed

    def get_watch_items(self):
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute("SELECT item_id FROM watch_items ORDER BY item_id").fetchall()
            return {row[0] for row in rows}
        except sqlite3.Error as error:
            raise StorageError(str(error)) from error

    def replace_watch_items(self, item_ids):
        values = sorted({str(value) for value in item_ids})

        def replace(connection):
            connection.execute("DELETE FROM watch_items")
            connection.executemany(
                "INSERT INTO watch_items(item_id, created_at) VALUES(?, ?)",
                ((item_id, time.time()) for item_id in values),
            )

        self._write(replace)

    def get_json(self, key, default=None):
        try:
            with closing(self._connect()) as connection:
                row = connection.execute("SELECT value_json FROM settings WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else default
        except (sqlite3.Error, ValueError, TypeError, json.JSONDecodeError) as error:
            raise StorageError(str(error)) from error

    def set_json(self, key, value):
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)

        def set_value(connection):
            connection.execute(
                """INSERT INTO settings(key, value_json, updated_at) VALUES(?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET
                       value_json=excluded.value_json, updated_at=excluded.updated_at""",
                (key, encoded, time.time()),
            )

        self._write(set_value)
