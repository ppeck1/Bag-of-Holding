"""Logical library views derived from indexed document paths.

Logical libraries are browsing scopes inside the existing BOH_LIBRARY boundary.
They are not filesystem roots, corpus partitions, or governance authority. Display
metadata is operator-managed presentation state layered over the derived scopes.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from typing import Any

from app.db import connection as db

ALL_LIBRARY_ID = "all"
UNFILED_LIBRARY_ID = "unfiled"
OVERRIDES_CONFIG_KEY = "logical_library_overrides_v1"
MAX_DISPLAY_NAME_CHARS = 80
MAX_SORT_ORDER = 10000
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


class InvalidLibraryId(ValueError):
    """Raised when a caller names a non-existent logical library."""


@dataclass(frozen=True)
class LogicalLibrary:
    id: str
    name: str
    count: int
    prefix: str | None = None
    derived_name: str | None = None
    hidden: bool = False
    sort_order: int | None = None
    editable: bool = True
    hideable: bool = True
    orderable: bool = True
    overridden: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "count": self.count,
            "prefix": self.prefix,
            "derived_name": self.derived_name or self.name,
            "hidden": self.hidden,
            "sort_order": self.sort_order,
            "editable": self.editable,
            "hideable": self.hideable,
            "orderable": self.orderable,
            "overridden": self.overridden,
        }


def _library_id_for_segment(segment: str) -> str:
    digest = hashlib.sha256(segment.encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"lib-{digest}"


def _split_path(path: str | None) -> tuple[str | None, bool]:
    rel = str(path or "").replace("\\", "/").strip("/")
    if not rel:
        return None, True
    parts = [p for p in rel.split("/") if p]
    if len(parts) <= 1:
        return None, True
    return parts[0], False


def _visible_doc_paths() -> list[str]:
    from app.core import promoted_exposure

    rows = db.fetchall(
        "SELECT path FROM docs WHERE 1=1"
        + promoted_exposure.exclusion_sql("", show_promoted=promoted_exposure.env_gate_open())
    )
    return [r.get("path") for r in rows if r.get("path")]


def _derive_logical_libraries() -> list[LogicalLibrary]:
    """Return all visible logical libraries derived from docs.path."""
    paths = _visible_doc_paths()
    segment_counts: dict[str, int] = {}
    unfiled = 0
    for path in paths:
        segment, is_unfiled = _split_path(path)
        if is_unfiled:
            unfiled += 1
        elif segment:
            segment_counts[segment] = segment_counts.get(segment, 0) + 1

    libraries = [LogicalLibrary(
        ALL_LIBRARY_ID, "All libraries", len(paths), None,
        derived_name="All libraries", hideable=False, orderable=False,
    )]
    if unfiled:
        libraries.append(LogicalLibrary(UNFILED_LIBRARY_ID, "Unfiled", unfiled, None, derived_name="Unfiled"))
    for segment in sorted(segment_counts, key=lambda s: s.lower()):
        libraries.append(
            LogicalLibrary(_library_id_for_segment(segment), segment, segment_counts[segment], segment, derived_name=segment)
        )
    return libraries


def _load_override_map() -> dict[str, dict[str, Any]]:
    row = db.fetchone("SELECT value FROM system_config WHERE key = ?", (OVERRIDES_CONFIG_KEY,))
    if not row:
        return {}
    try:
        payload = json.loads(row.get("value") or "{}")
    except (TypeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    libraries = payload.get("libraries", payload)
    if not isinstance(libraries, dict):
        return {}
    clean: dict[str, dict[str, Any]] = {}
    for lib_id, value in libraries.items():
        if isinstance(lib_id, str) and isinstance(value, dict):
            clean[lib_id] = value
    return clean


def _save_override_map(overrides: dict[str, dict[str, Any]]) -> None:
    payload = {"version": 1, "libraries": overrides}
    db.execute(
        "INSERT OR REPLACE INTO system_config (key, value, updated_ts) VALUES (?, ?, ?)",
        (OVERRIDES_CONFIG_KEY, json.dumps(payload, sort_keys=True, separators=(",", ":")), int(time.time())),
    )


def _normalize_display_name(value: str) -> str:
    name = str(value or "").strip()
    if not name:
        raise ValueError("display_name must not be empty")
    if len(name) > MAX_DISPLAY_NAME_CHARS:
        raise ValueError(f"display_name must be {MAX_DISPLAY_NAME_CHARS} characters or fewer")
    if _CONTROL_CHARS.search(name):
        raise ValueError("display_name must not contain control characters")
    return name


def _normalize_sort_order(value: int | None) -> int | None:
    if value is None:
        return None
    order = int(value)
    if order < -MAX_SORT_ORDER or order > MAX_SORT_ORDER:
        raise ValueError(f"sort_order must be between {-MAX_SORT_ORDER} and {MAX_SORT_ORDER}")
    return order


def _override_is_empty(override: dict[str, Any]) -> bool:
    return not any(
        key in override
        for key in ("display_name", "hidden", "sort_order")
    )


def _apply_overrides(libraries: list[LogicalLibrary], include_hidden: bool = False) -> list[LogicalLibrary]:
    overrides = _load_override_map()
    indexed: list[tuple[int, LogicalLibrary]] = []
    for idx, library in enumerate(libraries):
        override = overrides.get(library.id, {})
        display_name = override.get("display_name")
        name = library.name
        if isinstance(display_name, str) and display_name.strip() and not _CONTROL_CHARS.search(display_name):
            name = display_name.strip()[:MAX_DISPLAY_NAME_CHARS]
        hidden = bool(override.get("hidden", False)) and library.hideable
        sort_order = override.get("sort_order")
        if not isinstance(sort_order, int):
            sort_order = None
        if not library.orderable:
            sort_order = None
        next_library = LogicalLibrary(
            id=library.id,
            name=name,
            count=library.count,
            prefix=library.prefix,
            derived_name=library.derived_name or library.name,
            hidden=hidden,
            sort_order=sort_order,
            editable=library.editable,
            hideable=library.hideable,
            orderable=library.orderable,
            overridden=not _override_is_empty(override),
        )
        if include_hidden or not hidden:
            indexed.append((idx, next_library))

    def sort_key(item: tuple[int, LogicalLibrary]) -> tuple[int, int, str, int]:
        idx, library = item
        if library.id == ALL_LIBRARY_ID:
            return (-1, 0, "", idx)
        if library.sort_order is not None:
            return (0, library.sort_order, "", idx)
        return (1, 0, "", idx)

    return [library for _idx, library in sorted(indexed, key=sort_key)]


def list_logical_libraries(include_hidden: bool = False, apply_overrides: bool = True) -> list[LogicalLibrary]:
    """Return logical libraries derived from docs.path with optional presentation state."""
    libraries = _derive_logical_libraries()
    if not apply_overrides:
        return libraries
    return _apply_overrides(libraries, include_hidden=include_hidden)


def get_logical_library(library_id: str | None, include_hidden: bool = True) -> LogicalLibrary:
    lib_id = (library_id or ALL_LIBRARY_ID).strip() or ALL_LIBRARY_ID
    for library in list_logical_libraries(include_hidden=include_hidden):
        if library.id == lib_id:
            return library
    raise InvalidLibraryId(f"Unknown logical library: {lib_id}")


def update_logical_library_override(
    library_id: str,
    *,
    display_name: str | None = None,
    hidden: bool | None = None,
    sort_order: int | None = None,
    clear_display_name: bool = False,
    clear_sort_order: bool = False,
) -> LogicalLibrary:
    library = get_logical_library(library_id, include_hidden=True)
    overrides = _load_override_map()
    override = dict(overrides.get(library.id, {}))
    if clear_display_name:
        override.pop("display_name", None)
    elif display_name is not None:
        name = _normalize_display_name(display_name)
        if name == (library.derived_name or library.name):
            override.pop("display_name", None)
        else:
            override["display_name"] = name
    if hidden is not None:
        if library.id == ALL_LIBRARY_ID and hidden:
            raise ValueError("all cannot be hidden")
        if not library.hideable:
            override.pop("hidden", None)
        elif hidden:
            override["hidden"] = True
        else:
            override.pop("hidden", None)
    if clear_sort_order:
        override.pop("sort_order", None)
    elif sort_order is not None:
        order = _normalize_sort_order(sort_order)
        if library.orderable and order is not None:
            override["sort_order"] = order
        else:
            override.pop("sort_order", None)
    override["updated_ts"] = int(time.time())
    if _override_is_empty(override):
        overrides.pop(library.id, None)
    else:
        overrides[library.id] = override
    _save_override_map(overrides)
    return get_logical_library(library.id, include_hidden=True)


def set_logical_library_order(library_ids: list[str]) -> list[LogicalLibrary]:
    seen: set[str] = set()
    ordered = []
    available = {lib.id: lib for lib in list_logical_libraries(include_hidden=True)}
    for lib_id in library_ids:
        if lib_id in seen:
            raise ValueError(f"Duplicate logical library: {lib_id}")
        if lib_id not in available:
            raise InvalidLibraryId(f"Unknown logical library: {lib_id}")
        seen.add(lib_id)
        if available[lib_id].orderable:
            ordered.append(lib_id)
    overrides = _load_override_map()
    for order, lib_id in enumerate(ordered):
        override = dict(overrides.get(lib_id, {}))
        override["sort_order"] = order
        override["updated_ts"] = int(time.time())
        overrides[lib_id] = override
    _save_override_map(overrides)
    return list_logical_libraries(include_hidden=True)


def reset_logical_library_override(library_id: str) -> LogicalLibrary:
    library = get_logical_library(library_id, include_hidden=True)
    overrides = _load_override_map()
    overrides.pop(library.id, None)
    _save_override_map(overrides)
    return get_logical_library(library.id, include_hidden=True)


def resolve_logical_library(library_id: str | None) -> LogicalLibrary:
    return get_logical_library(library_id, include_hidden=True)


def _escape_like(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def docs_where_clause(
    library_id: str | None,
    alias: str = "",
) -> tuple[str, list[str], LogicalLibrary]:
    """Return a safe SQL predicate for docs.path scoped to a logical library."""
    library = resolve_logical_library(library_id)
    if library.id == ALL_LIBRARY_ID:
        return "", [], library
    col = f"{alias}.path" if alias else "path"
    if library.id == UNFILED_LIBRARY_ID:
        return f" AND ({col} IS NULL OR {col} NOT LIKE '%/%')", [], library
    prefix = _escape_like(library.prefix or "")
    return f" AND {col} LIKE ? ESCAPE '\\'", [f"{prefix}/%"], library
