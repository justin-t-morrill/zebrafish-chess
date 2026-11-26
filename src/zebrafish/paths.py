"""Resolve project resources without depending on the working directory."""
from __future__ import annotations

import json
import os
from pathlib import Path


def project_root(start: Path | None = None) -> Path:
    candidate = Path(start or __file__).resolve()
    if candidate.is_file():
        candidate = candidate.parent
    for folder in (candidate, *candidate.parents):
        if (folder / ".chess-project").is_file():
            return folder
    raise RuntimeError("Cannot find the Zebrafish project marker (.chess-project).")


ROOT = project_root()


def resource(name: str, *, root: Path = ROOT) -> Path:
    settings = json.loads((root / "config/paths.json").read_text(encoding="utf-8"))
    value = os.environ.get("ZEBRAFISH_LOCAL_DIR", settings[name]) if name == "local" else settings[name]
    result = (root / value).resolve()
    if not result.is_relative_to(root.resolve()):
        raise ValueError(f"Configured resource {name!r} must remain inside the project.")
    return result


def python_environment() -> dict[str, str]:
    environment = os.environ.copy()
    paths = [str(ROOT / "src"), str(resource("review_vendor"))]
    if environment.get("PYTHONPATH"):
        paths.append(environment["PYTHONPATH"])
    environment["PYTHONPATH"] = os.pathsep.join(paths)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def project_reference(path: Path) -> str:
    """New review records use portable paths; existing records stay unchanged."""
    resolved = path.resolve()
    return resolved.relative_to(ROOT).as_posix() if resolved.is_relative_to(ROOT) else str(resolved)


def resolve_saved_path(value: str, *, root: Path = ROOT, allow_external=False) -> Path:
    """Resolve legacy absolute PGN references after relocation or restoration."""
    original = Path(value)
    candidate = original if original.is_absolute() else root / original
    if candidate.is_file() and (allow_external or candidate.resolve().is_relative_to(root.resolve())):
        return candidate.resolve()
    normalized = value.replace("\\", "/")
    for old, new in (("analysis/game_review/reviews/", "local/reviews/"), ("local/reviews/", "local/reviews/")):
        position = normalized.lower().find(old.lower())
        if position >= 0:
            remapped = (root / new / normalized[position + len(old):]).resolve()
            if remapped.is_relative_to(root.resolve()) and remapped.is_file():
                return remapped
    if candidate.resolve().is_relative_to(root.resolve()):
        return candidate
    raise ValueError("The original source PGN is unavailable inside this project.")
