"""V4 lane catalog: read-only lane metadata for the board (docs/RELAY_TOWER_DIRECTION_V4.md, step S4a).

The sealed runtime registry (``config/control_tower_registry.json``) carries an owner-approved DURABLE adoption and
hash-pinned evidence, so V4 does not rewrite it.  This catalog sits beside it: it records the V4 status of every
lane (frozen, active, manual, planned), the Symphony repositories and each lane's state location.  Every
``registry_row`` must name an existing registry row and every registry row must appear in the catalog exactly once,
so the two files cannot drift apart silently.

Pure functions only: nothing here reads or writes GitHub or changes the registry.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

__all__ = ["load_catalog", "validate_catalog", "CatalogError"]

CONFIG_DIR = Path(__file__).resolve().parent / "config"
DEFAULT_CATALOG_PATH = CONFIG_DIR / "lane_catalog_v4.json"
DEFAULT_REGISTRY_PATH = CONFIG_DIR / "control_tower_registry.json"

_TOP_KEYS = {"schema_version", "note", "lanes"}
_REQUIRED = {"lane_id", "display_name_ja", "v4_status", "registry_row", "detail_ref", "state_location", "tower_access"}
_OPTIONAL = {"repositories"}
_STATUSES = {"ACTIVE", "FROZEN", "MANUAL", "PLANNED"}
_LANE_ID = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
_REF = re.compile(r"(issue|pr):[1-9][0-9]{0,6}")
_REPO = re.compile(r"[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}")
_PATH = re.compile(r"[A-Za-z0-9._/-]{1,200}")
_MAX_LANES = 16


class CatalogError(ValueError):
    """The catalog is malformed or disagrees with the registry (fail closed)."""


def _state_location_ok(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    if value == "UNKNOWN" or _REF.fullmatch(value):
        return True
    return bool(_PATH.fullmatch(value)) and ".." not in value and not value.startswith("/")


def validate_catalog(catalog: Mapping[str, Any], registry: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    """Return the lanes in catalog order, or raise ``CatalogError``."""
    if not isinstance(catalog, Mapping) or set(catalog) != _TOP_KEYS or catalog["schema_version"] != 1:
        raise CatalogError("CATALOG_SHAPE")
    lanes = catalog["lanes"]
    if not isinstance(lanes, list) or not 1 <= len(lanes) <= _MAX_LANES:
        raise CatalogError("CATALOG_LANES")
    registry_ids = [row.get("loop_id") for row in registry.get("loops", [])]
    seen: set[str] = set()
    mapped: list[str] = []
    for lane in lanes:
        if not isinstance(lane, dict) or not _REQUIRED <= set(lane) <= _REQUIRED | _OPTIONAL:
            raise CatalogError("LANE_KEYS")
        lane_id = lane["lane_id"]
        if not isinstance(lane_id, str) or not _LANE_ID.fullmatch(lane_id) or lane_id in seen:
            raise CatalogError("LANE_ID")
        seen.add(lane_id)
        if not isinstance(lane["display_name_ja"], str) or not 1 <= len(lane["display_name_ja"]) <= 60:
            raise CatalogError("DISPLAY_NAME")
        if lane["v4_status"] not in _STATUSES:
            raise CatalogError("V4_STATUS")
        if lane["tower_access"] != "READ_ONLY":
            raise CatalogError("TOWER_ACCESS")
        if not isinstance(lane["detail_ref"], str) or not _REF.fullmatch(lane["detail_ref"]):
            raise CatalogError("DETAIL_REF")
        if not _state_location_ok(lane["state_location"]):
            raise CatalogError("STATE_LOCATION")
        row = lane["registry_row"]
        if row is not None:
            if row not in registry_ids:
                raise CatalogError("REGISTRY_ROW_MISSING")
            mapped.append(row)
        if "repositories" in lane:
            repos = lane["repositories"]
            if not isinstance(repos, dict) or "main" not in repos or not set(repos) <= {"main", "trial"} \
                    or not all(isinstance(v, str) and _REPO.fullmatch(v) for v in repos.values()):
                raise CatalogError("REPOSITORIES")
    if sorted(mapped) != sorted(registry_ids) or len(set(mapped)) != len(mapped):
        raise CatalogError("REGISTRY_NOT_COVERED_ONCE")
    return tuple(dict(lane) for lane in lanes)


def load_catalog(catalog_path: Path | str = DEFAULT_CATALOG_PATH,
                 registry_path: Path | str = DEFAULT_REGISTRY_PATH) -> tuple[dict[str, Any], ...]:
    catalog = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    registry = json.loads(Path(registry_path).read_text(encoding="utf-8"))
    return validate_catalog(catalog, registry)
