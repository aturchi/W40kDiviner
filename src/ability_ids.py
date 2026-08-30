"""Ability id helpers (shared by the profile editor and the load dialog).

Every ability-like dict (unit/model/weapon abilities and unit
leader_effects) carries a unique 'id' so a persistent per-profile
enable/disable toggle can reference it. Ids are assigned lazily: the
editor stamps missing ones before saving, and the load dialog
guarantees global uniqueness when writing merged files (re-stamping on
collision): ids are only unique per SOURCE file."""

import uuid


def _ability_lists(unit: dict):
    """Yield every ability-like list in a unit dict, in a stable order:
    unit abilities, core_abilities, faction_abilities, leader_effects,
    then per-model abilities and per-weapon abilities."""
    yield unit.setdefault("abilities", [])
    yield unit.setdefault("core_abilities", [])
    yield unit.setdefault("faction_abilities", [])
    yield unit.setdefault("leader_effects", [])
    for m in unit.get("models", []):
        yield m.setdefault("abilities", [])
        for w in m.get("models", []) if False else m.get("weapons", []):
            yield w.setdefault("abilities", [])


def new_id() -> str:
    """A fresh unique id string for a newly-created ability (stable within a session)."""
    return uuid.uuid4().hex


def ensure_ids(data: dict) -> int:
    """Stamp an 'id' on every ability that lacks one (or has a blank/
    duplicate one). Ids are made unique across the whole document.
    Returns the number of ids newly assigned or rewritten."""
    seen = set()
    changed = 0
    for army in data.get("armies", []):
        for unit in army.get("units", []):
            for lst in _ability_lists(unit):
                for ab in lst:
                    aid = ab.get("id")
                    if not aid or aid in seen:
                        ab["id"] = new_id()
                        changed += 1
                    seen.add(ab["id"])
    return changed


def ensure_enabled(data: dict) -> int:
    """Stamp enabled=True on every ability that lacks the field, so
    after one load/save cycle the flag is always present and explicit.
    Returns the number of abilities updated."""
    changed = 0
    for army in data.get("armies", []):
        for unit in army.get("units", []):
            for lst in _ability_lists(unit):
                for ab in lst:
                    if "enabled" not in ab:
                        ab["enabled"] = True
                        changed += 1
    return changed


def normalize(data: dict) -> int:
    """Apply both normalisations (ids + enabled). Returns the total
    number of fields stamped."""
    return ensure_ids(data) + ensure_enabled(data)
