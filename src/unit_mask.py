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
* **model row** -> every weapon of that model group at once: the
  sergeant who does not shoot is one gesture, not six. The row carries
  no state of its own - it READS as masked when all its weapons are,
  which is why a model with no weapons is never maskable and why the
  partial case ("2 off") is shown as a count and not as a colour.
* **unit row** -> the same, one level up: every weapon of every model.
  Abilities are deliberately NOT included. Switching a whole datasheet's
  abilities off in one click is not a table situation, and it would
  silently disable the core ones; they are listed individually right
  below and that is where they belong.

Unmasking a model or unit row turns every weapon back ON, including any
the player had switched off one by one beforehand. That information is
not kept: the row is a bulk action, not a saved state, and remembering
it would mean two consecutive unmasks giving different answers. Each
weapon does come back at the COUNT it had (see set_weapon_count).

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
    the count it had two edits ago.

    Typing 0 is the same GESTURE as masking the row, so it has to
    remember the same way: the count being overwritten is saved first.
    Otherwise a squad's ten bolters, switched off by typing 0 and then
    unmasked, would come back as DEFAULT_COUNT - one bolter."""
    n = max(0, int(n))
    if n > 0:
        _SAVED_COUNT[weapon] = n
    else:
        current = weapon_count(weapon)
        if current > 0:
            _SAVED_COUNT[weapon] = current
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
        # set_weapon_count saves the count being overwritten: the rule
        # lives in ONE place, so the button and a hand-typed 0 cannot
        # remember differently.
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


# ---------------- models and units in bulk ----------------


def model_weapons(unit, mi) -> list:
    """The weapons of one model group, or [] when the row is stale."""
    models = unit.models()
    return list(models[mi].weapons) if 0 <= mi < len(models) else []


def masked_count(weapons) -> tuple:
    """(masked, total) over a list of weapons."""
    weapons = list(weapons)
    return (sum(1 for w in weapons if is_weapon_masked(w)), len(weapons))


def is_model_masked(unit, mi) -> bool:
    """A model row reads as masked when EVERY weapon it owns is. A model
    with no weapons is never masked: there would be nothing to undo."""
    off, total = masked_count(model_weapons(unit, mi))
    return total > 0 and off == total


def set_model_masked(unit, mi, masked: bool) -> int:
    """Mask or unmask every weapon of one model group. Returns how many
    weapons actually moved, so the caller can tell a no-op apart."""
    return sum(1 for w in model_weapons(unit, mi)
               if set_weapon_masked(w, masked))


def unit_weapons(unit) -> list:
    return [w for m in unit.models() for w in m.weapons]


def is_unit_masked(unit) -> bool:
    """Every weapon of every model. Abilities are not part of it (see
    the module docstring)."""
    off, total = masked_count(unit_weapons(unit))
    return total > 0 and off == total


def set_unit_masked(unit, masked: bool) -> int:
    return sum(1 for w in unit_weapons(unit) if set_weapon_masked(w, masked))


def off_count_label(n: int) -> str:
    """What a row with switched-off children shows in its value column.
    A count, never a bare word: 'off' on a row whose children are only
    half switched off would be a lie, and the number never is."""
    return f"{n} off" if n else ""


def ability_label(scope, ability) -> str:
    name = (ability.get("name") or "").strip() or "<unnamed ability>"
    return f"[{scope}] {name}"


# ---------------- the row plan ----------------


def unit_plan(unit) -> dict:
    """Everything one unit expands into:

        {"models": [{"mi", "label", "off", "masked",
                     "weapons": [{"wi", "label", "count", "masked"}]}],
         "abilities": [{"key", "label", "masked"}],
         "off": n, "masked": bool}

    'key' is the ability's position in leader_core.ability_dicts_of_unit
    - a Unit object's abilities have no persistent id to key on, and the
    tree is rebuilt from the same call, so the position is the identity.
    'off' counts the masked rows, which is what a COLLAPSED unit row has
    to be able to show: an ability switched off three analyses ago must
    not be invisible."""
    models = []
    for mi, m in enumerate(unit.models()):
        weapons = [{"wi": wi, "label": weapon_label(w),
                    "count": weapon_count(w),
                    "masked": is_weapon_masked(w)}
                   for wi, w in enumerate(m.weapons)]
        off = sum(1 for w in weapons if w["masked"])
        models.append({
            "mi": mi,
            "label": f"{m.name} x{m.model_count}",
            "off": off,
            # Reads as masked only when there is something to mask and
            # all of it is: see is_model_masked.
            "masked": bool(weapons) and off == len(weapons),
            "weapons": weapons})
    abilities = [{"key": str(i), "label": ability_label(scope, ab),
                  "masked": is_ability_masked(ab)}
                 for i, (scope, ab) in
                 enumerate(lc.ability_dicts_of_unit(unit))]
    n_weapons = sum(len(m["weapons"]) for m in models)
    w_off = sum(m["off"] for m in models)
    off = w_off + sum(1 for a in abilities if a["masked"])
    return {"models": models, "abilities": abilities, "off": off,
            # The unit row reads as masked on its WEAPONS only, like
            # the bulk action that sets it (see the module docstring):
            # the abilities are counted in 'off' but do not decide it.
            "masked": n_weapons > 0 and w_off == n_weapons}


def off_label(plan: dict) -> str:
    """What a unit or model row shows in its value column."""
    return off_count_label(plan.get("off") or 0)


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
