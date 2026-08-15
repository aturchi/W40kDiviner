"""Node templates and collectors (native format).

Factories for empty units / models / weapons, and collectors that list
existing nodes across a native-format dict for the "copy existing"
picker. Copies are plain deep copies: the native format has no
cross-references that need fixing up.
"""

import copy
import re

import effect_specs
import condition_specs


def new_ability() -> dict:
    """Ability template: profileRole=Attacker condition + a default
    modifyRelative effect, both editable in the Abilities tab."""
    return {
        "name": "New ability",
        "description": "",
        "enabled": True,
        "share_with_unit": False,
        "conditions": [condition_specs.new_condition("profileRole")],
        "effect": effect_specs.new_effect("modifyRelative"),
    }


# ---------- duplicate naming ----------

_SUFFIX_RE = re.compile(r"^(.*)-(\d{2,})$")


def split_suffix(name: str):
    """'Rifle-02' -> ('Rifle', 2); 'Rifle' -> ('Rifle', None)."""
    m = _SUFFIX_RE.match(name or "")
    return (m.group(1), int(m.group(2))) if m else (name or "", None)


def duplicate_name_pair(name: str, sibling_names) -> tuple:
    """Names for duplicating a model/weapon: returns
    (new_original_name, copy_name).

    - 'Rifle'    -> ('Rifle-01', 'Rifle-02')
    - 'Rifle-02' -> ('Rifle-02', 'Rifle-03')
    Numbers already used by siblings sharing the base name are skipped
    to avoid collisions."""
    base, num = split_suffix(name)
    used = {n for s in sibling_names
            for b, n in [split_suffix(s)] if b == base and n is not None}
    if num is None:
        orig_n = 1
        while orig_n in used:
            orig_n += 1
        used.add(orig_n)
        copy_n = orig_n + 1
        while copy_n in used:
            copy_n += 1
        return f"{base}-{orig_n:02d}", f"{base}-{copy_n:02d}"
    copy_n = num + 1
    while copy_n in used:
        copy_n += 1
    return name, f"{base}-{copy_n:02d}"


def new_unit() -> dict:
    """A new empty unit dict at the current schema, with all required fields defaulted."""
    return {
        "name": "New unit", "profile_name": "New unit", "points": 0,
        "keywords": [], "abilities": [],
        "core_abilities": [], "faction_abilities": [],
        "leadership": [],
        "support": [],
        "leader_slots": 1, "support_slots": 1,
        "leader_effects": [], "apply_leader_effects_to_self": False,
        "damageable": False,
        "unit_composition": "", "wargear_options": "", "notes": "",
        "models": [],
    }


def new_model() -> dict:
    """A new empty model dict with default characteristics."""
    return {
        "name": "New model", "model_count": 1,
        "M": None, "T": 4, "Sv": 4, "W": 1, "LD": None, "OC": None,
        "invuln": None, "fnp": None,
        "keywords": [], "abilities": [], "weapons": [],
    }


def new_weapon(wtype: str = "Ranged") -> dict:
    """A new empty weapon dict of the given type with default characteristics."""
    w = {
        "name": "New weapon", "type": wtype, "RNG": None,
        "A": 1, "S": 4, "AP": 0, "D": 1, "count": 1,
        "keywords": [], "abilities": [],
    }
    w["WS" if wtype == "Melee" else "BS"] = 4
    return w


def clone(node: dict) -> dict:
    """Deep copy of an existing node (no id fix-up needed)."""
    return copy.deepcopy(node)


# ---------- collectors for the picker ----------

def _armies(data: dict):
    return data.get("armies", [])


def collect_units(data: dict):
    """[(label, node)] of all units across all armies."""
    return [(f"{a.get('name', '?')} > {u.get('name', '?')}", u)
            for a in _armies(data) for u in a.get("units", [])]


def collect_models(data: dict):
    """[(label, node)] of all models, labelled with army and unit."""
    return [(f"{a.get('name', '?')} > {u.get('name', '?')} > "
             f"{m.get('name', '?')}", m)
            for a in _armies(data)
            for u in a.get("units", [])
            for m in u.get("models", [])]


def collect_weapons(data: dict):
    """[(label, node)] of all weapons, labelled with army, unit, model."""
    return [(f"{a.get('name', '?')} > {u.get('name', '?')} > "
             f"{m.get('name', '?')} > {w.get('name', '?')} "
             f"({w.get('type', '?')})", w)
            for a in _armies(data)
            for u in a.get("units", [])
            for m in u.get("models", [])
            for w in m.get("weapons", [])]
