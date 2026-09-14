import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tbhastrarium import storage as tbh_storage
from tbhastrarium.storage import TBHStorage


def test_reopen_preserves_all_data(root):
    root.mkdir(parents=True, exist_ok=True)
    path = root / "TBHAstrarium.db"
    storage = TBHStorage(path)
    storage.replace_watch_items({"535041", "535042"})
    storage.set_json("cube_settings", {"categoryTiers": {"0": 9}})
    storage.set_json("future.feature", {"enabled": True, "rules": [1, 2, 3]})
    storage.backup_current()

    reopened = TBHStorage(path)
    assert reopened.get_watch_items() == {"535041", "535042"}
    assert reopened.get_json("cube_settings") == {"categoryTiers": {"0": 9}}
    assert reopened.get_json("future.feature")["rules"] == [1, 2, 3]


def test_legacy_migration_is_idempotent(root):
    root.mkdir(parents=True, exist_ok=True)
    watch = root / "watch.json"
    chest = root / "chest.json"
    cube = root / "cube.json"
    watch.write_text(json.dumps([535041, "535042"]), encoding="utf-8")
    chest.write_text(json.dumps({"seen": {"0": ["7"], "1": []}, "started_at": {}}), encoding="utf-8")
    cube.write_text(json.dumps({"combineExcludedIds": [140002]}), encoding="utf-8")
    storage = TBHStorage(root / "migrated.db")
    assert storage.migrate_legacy((watch,), (chest,), (cube,))
    assert storage.get_watch_items() == {"535041", "535042"}
    assert storage.get_json("chest_cooldowns")["seen"]["0"] == ["7"]
    assert storage.get_json("cube_settings")["combineExcludedIds"] == [140002]

    watch.write_text(json.dumps(["999999"]), encoding="utf-8")
    assert not storage.migrate_legacy((watch,), (chest,), (cube,))
    assert storage.get_watch_items() == {"535041", "535042"}


def test_corrupt_primary_recovers_previous_snapshot(root):
    root.mkdir(parents=True, exist_ok=True)
    path = root / "recover.db"
    storage = TBHStorage(path)
    storage.replace_watch_items({"first"})
    # Every mutation snapshots the preceding committed state.
    storage.replace_watch_items({"second"})
    path.write_bytes(b"not a sqlite database")

    recovered = TBHStorage(path)
    assert recovered.recovered_from_backup
    assert recovered.get_watch_items() == {"first"}
    assert list(root.glob("recover.corrupt-*.db"))


def test_product_rename_preserves_existing_database(root):
    legacy_path = root / "TBHStargaze" / "TBHStargaze.db"
    legacy = TBHStorage(legacy_path)
    legacy.replace_watch_items({"535041", "535042"})
    legacy.set_json("ui_preferences", {"theme": "light"})
    legacy.backup_current()

    with patch.dict(os.environ, {"LOCALAPPDATA": str(root)}):
        renamed = TBHStorage()
    assert renamed.path == root / "TBHAstrarium" / "TBHAstrarium.db"
    assert renamed.get_watch_items() == {"535041", "535042"}
    assert renamed.get_json("ui_preferences") == {"theme": "light"}
    assert legacy_path.exists(), "Rename migration must keep the old database as a rollback copy"


with tempfile.TemporaryDirectory(prefix="tbh-storage-") as directory:
    root = Path(directory)
    test_reopen_preserves_all_data(root / "reopen")
    test_legacy_migration_is_idempotent(root / "migration")
    test_corrupt_primary_recovers_previous_snapshot(root / "recovery")
    test_product_rename_preserves_existing_database(root / "rename")
    print("PASS durable SQLite storage, JSON migration, product rename migration and backup recovery")
