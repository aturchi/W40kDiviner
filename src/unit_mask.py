"""What the analyzer's unit tree shows, and what masking a row means.

The analyzer used to switch abilities off inside the Inspect window and
weapon counts inside a second section of it, while the game assistant
did both by masking rows of its table. Two mental models for one idea.
This module holds the half of the shared model that has no widgets in
it: the ROWS a unit expands into, and what masking one of them does to
the live objects the next analysis reads.

Masking means:

* **weapon row** -> its count goes to 0, which the analyzer already
  treats as "weapon not fired" (it reports it as skipped). Unmasking
  restores the count the weapon had, not 1: a squad's ten bolters must
  come back as ten. The previous count is kept in a WEAK map keyed by
  the Weapon object, so it follows the weapon rather than a row
  position, and disappears with the roster.
* **ability row** -> its 'enabled' flag goes to False, exactly as the
  Inspect checkbox did.

Both act on the objects the engine reads, and a Unit joined to a leader
SHARES those objects with the plain unit it was built from (see
Unit._attach). Masking a weapon in one row therefore masks it in every
row showing the same weapon - which is correct, and the reason the
caller must refresh every tree after a change rather than only the one
that was clicked.

No tkinter here: the row plan and the masking rules are testable
headless, and the widget file stays a renderer.
"""

import weakref

import leader_core as lc
from unit_model import native_weapon_dict

# Weapon -> the count it had before being masked. Weak, so a roster that
# is dropped takes its saved counts with it.
_SAVED_COUNT = weakref.WeakKeyDictionary()

# What a weapon comes back as when it was masked before this module ever
# saw its count (a session reloaded with a count already at 0).
DEFAULT_COUNT = 1


# ---------------- weapons ----------------


def weapon_count(weapon) -> int:
    try:
        return max(0, int(weapon.count))
    except (TypeError, ValueError):
        return 0


def set_weapon_count(weapon, n: int):
    """Write a weapon count on the live object AND on the native dict
    behind it, so the edit is also what a saved session carries.

    A count typed by hand also becomes what an unmask restores: without
    that, a weapon set to 0 by hand and then unmasked would come back as
    the count it had two edits ago."""
    n = max(0, int(n))
    if n > 0:
        _SAVED_COUNT[weapon] = n
    weapon.count = n
    native = native_weapon_dict(weapon)
    if native is not None:
        native["count"] = n
    return n


def is_weapon_masked(weapon) -> bool:
    return weapon_count(weapon) <= 0


def set_weapon_masked(weapon, masked: bool) -> bool:
    """Mask (count 0) or unmask (previous count) one weapon. Returns
    True when something actually moved."""
    if bool(masked) == is_weapon_masked(weapon):
        return False
    if masked:
        _SAVED_COUNT[weapon] = weapon_count(weapon)
        set_weapon_count(weapon, 0)
    else:
        set_weapon_count(weapon, _SAVED_COUNT.get(weapon, DEFAULT_COUNT))
    return True


def weapon_label(weapon) -> str:
    """'[R] Fusion collider' - type initial plus name, as everywhere
    else in the two programs."""
    return f"[{str(weapon.type or '?')[0]}] {weapon.name}"


# ---------------- abilities ----------------


def is_ability_masked(ability) -> bool:
    return not ability.get("enabled", True)


def set_ability_masked(ability, masked: bool) -> bool:
    if bool(masked) == is_ability_masked(ability):
        return False
    ability["enabled"] = not bool(masked)
    return True


def ability_label(scope, ability) -> str:
    name = (ability.get("name") or "").strip() or "<unnamed ability>"
    return f"[{scope}] {name}"


# ---------------- the row plan ----------------


def unit_plan(unit) -> dict:
    """Everything one unit expands into:

        {"models": [{"mi", "label", "weapons": [{"wi", "label",
                                                 "count", "masked"}]}],
         "abilities": [{"key", "label", "masked"}],
         "off": n}

    'key' is the ability's position in leader_core.ability_dicts_of_unit
    - a Unit object's abilities have no persistent id to key on, and the
    tree is rebuilt from the same call, so the position is the identity.
    'off' counts the masked rows, which is what a COLLAPSED unit row has
    to be able to show: an ability switched off three analyses ago must
    not be invisible."""
    models = []
    for mi, m in enumerate(unit.models()):
        models.append({
            "mi": mi,
            "label": f"{m.name} x{m.model_count}",
            "weapons": [{"wi": wi, "label": weapon_label(w),
                         "count": weapon_count(w),
                         "masked": is_weapon_masked(w)}
                        for wi, w in enumerate(m.weapons)]})
    abilities = [{"key": str(i), "label": ability_label(scope, ab),
                  "masked": is_ability_masked(ab)}
                 for i, (scope, ab) in
                 enumerate(lc.ability_dicts_of_unit(unit))]
    off = sum(1 for m in models for w in m["weapons"] if w["masked"]) \
        + sum(1 for a in abilities if a["masked"])
    return {"models": models, "abilities": abilities, "off": off}


def off_label(plan: dict) -> str:
    """What the unit row shows in its value column."""
    return f"{plan['off']} off" if plan.get("off") else ""


# ---------------- row -> object ----------------


def weapon_at(unit, mi, wi):
    """The Weapon a (model, weapon) row stands for, or None when the row
    is stale (the unit changed shape under it)."""
    models = unit.models()
    if 0 <= mi < len(models):
        weapons = models[mi].weapons
        if 0 <= wi < len(weapons):
            return weapons[wi]
    return None


def ability_at(unit, key):
    """The ability dict a row stands for, or None."""
    try:
        i = int(key)
    except (TypeError, ValueError):
        return None
    pairs = lc.ability_dicts_of_unit(unit)
    return pairs[i][1] if 0 <= i < len(pairs) else None
