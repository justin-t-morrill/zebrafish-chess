"""Atomic, resumable JSON persistence for review jobs."""

from __future__ import annotations

import json
import os
import types
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any, TypeVar, get_args, get_origin, get_type_hints

from .models import GameReview, SCHEMA_VERSION


T = TypeVar("T")


def _construct(cls: type[T], value: Any) -> T:
    if not is_dataclass(cls):
        return value
    hints = get_type_hints(cls)
    kwargs: dict[str, Any] = {}
    for descriptor in fields(cls):
        if descriptor.name not in value:
            continue
        annotation = hints.get(descriptor.name, descriptor.type)
        origin = get_origin(annotation)
        args = get_args(annotation)
        item = value[descriptor.name]
        if is_dataclass(annotation):
            item = _construct(annotation, item)
        elif origin in (types.UnionType,) and item is not None:
            nested = next((candidate for candidate in args
                           if is_dataclass(candidate)), None)
            if nested is not None:
                item = _construct(nested, item)
        elif origin is list and args and is_dataclass(args[0]):
            item = [_construct(args[0], entry) for entry in item]
        elif origin is dict and len(args) == 2 and is_dataclass(args[1]):
            item = {key: _construct(args[1], entry) for key, entry in item.items()}
        kwargs[descriptor.name] = item
    return cls(**kwargs)


def save_review(review: GameReview, path: str | Path) -> None:
    """Write a checkpoint atomically so interruption cannot corrupt it."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(review.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, destination)


def load_review(path: str | Path) -> GameReview:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported review schema {payload.get('schema_version')}; "
            f"expected {SCHEMA_VERSION}"
        )
    return _construct(GameReview, payload)
