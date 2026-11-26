"""Restore legacy path aliases in a fresh checkout without moving existing data."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def restore() -> list[dict]:
    spec = importlib.util.spec_from_file_location("zebrafish_layout_migration", ROOT / "tools/migration/migrate_layout.py")
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    mappings = json.loads((ROOT / "config/legacy-paths.json").read_text())
    results = []
    for old, new in sorted(mappings.items(), key=lambda row: len(Path(row[0]).parts)):
        alias, target = ROOT / old, ROOT / new
        migration.contained(alias)
        migration.contained(target)
        if alias.exists():
            results.append({"path": old, "status": "retained_existing"})
        elif target.is_dir():
            migration.junction(alias, target)
            results.append({"path": old, "status": "restored"})
        else:
            results.append({"path": old, "status": "optional_target_not_installed"})
    legacy = ROOT / "engine/current"
    legacy.mkdir(parents=True, exist_ok=True)
    for pattern in ("*.c", "*.inc"):
        for source in (ROOT / "engine/src").glob(pattern):
            alias = legacy / source.name
            if not alias.exists():
                alias.hardlink_to(source)
    for folder, pattern in ((ROOT / "resources/networks", "*.bin"), (ROOT / "build/current", "*.exe")):
        for source in folder.glob(pattern):
            alias = legacy / source.name
            if not alias.exists():
                alias.hardlink_to(source)
    return results


if __name__ == "__main__":
    print(json.dumps(restore(), indent=2))
