"""Native profile format (schema ``w40k-sim/6``).

This is the only data format the GUI and the engine speak; it mirrors the
object model in :mod:`unit_model` 1:1. Files from external tools (e.g.
UnitCrunch) are converted to this format first (see :mod:`uc_convert`);
ArmyFetcher writes it directly.

Top-level shape (JSON)::

    {
      "format": "w40k-sim/6",
      "armies": [
        {
          "name": str,                 # army/faction name (also shown in
          #                              the army picker of every GUI)
          "units": [ <unit>, ... ]
        }, ...
      ]
    }

A ``<unit>``::

    {
      "name": str, "profile_name": str, "points": int,
      "keywords": [str],
      "abilities": [ <ability> ],       # unit-scope datasheet abilities
      "core_abilities":    [ <ability> ],  # core abilities (Deep Strike,
      #                                      Stealth, ...); separate list for
      #                                      display, but the engine treats
      #                                      them like unit abilities
      "faction_abilities": [ <ability> ],  # faction abilities (Oath of
      #                                      Moment, ...); same handling.
      #   Both may arrive from ArmyFetcher as bare name strings; load()
      #   normalises them into ability dicts (see _normalize_extra_abilities).
      "leadership": [str],   # unit-level: names/keywords of the units this
      #                        unit can LEAD (non-empty => it is a leader)
      "support":    [str],   # unit-level: names/keywords of the units this
      #                        unit can SUPPORT (non-empty => it is a
      #                        support). Independent of leadership: a unit
      #                        may carry one leader AND one support.
      "leader_effects": [ <ability> ],  # abilities a leader/support applies
      #                                   to the whole combined unit
      "apply_leader_effects_to_self": bool,
      "damageable": bool,    # unit-level: has a "Damaged 1-X" bracket; the
      #                        per-session damaged state is NOT stored here
      "unit_composition": str,          # display-only source text
      "wargear_options": str,           # display-only source text
      "notes": str,                     # display-only free text (also holds
      #                                   the "[DAMAGED]" bracket text and
      #                                   other unhandled datasheet sections)
      "models": [
        {
          "name": str, "model_count": int,
          "M": int|str|null, "T": ..., "Sv": ..., "W": ...,
          "LD": ..., "OC": ...,         # characteristics (dice notation ok)
          "invuln": int|null, "fnp": int|null,
          # NOTE: a legacy per-model "damage_reduction" int may appear in
          # older files; it is ignored on load. Damage reduction is now a
          # defender ability (damageReduction / damageSetZero), not a
          # static characteristic.
          "keywords": [str],
          "abilities": [ <ability> ],
          "weapons": [
            {
              "name": str, "type": "Ranged"|"Melee",
              "RNG": int|null, "A": ..., "BS"|"WS": ...,
              "S": ..., "AP": ...,       # AP: datasheet convention (<= 0)
              "D": ..., "count": int,
              "keywords": [str], "abilities": [ <ability> ]
            } ] } ] }

An ``<ability>`` is the declarative dict edited in the GUI::

    {"name": str, "description": str, "enabled": bool,
     "conditions": [ <condition> ], "effect": { <effect> }}

Version history (see :func:`migrate` for the upgrade steps):

* v1 -> v2  top-level ``units`` wrapped into ``armies``.
* v2 -> v3  (structural cleanup of the armies wrapper).
* v3 -> v4  per-model ``damage_reduction`` defaulted.
* v4 -> v5  unit-level ``damageable`` flag added.
* v5 -> v6  unit-level ``support`` list added.

Older files load transparently: :func:`load` migrates them to the current
tag, so callers always receive ``w40k-sim/6``.
"""

import json
import os

FORMAT_TAG = "w40k-sim/6"
_FORMAT_V1 = "w40k-sim/1"
_FORMAT_V2 = "w40k-sim/2"
_FORMAT_V3 = "w40k-sim/3"
_FORMAT_V4 = "w40k-sim/4"
_FORMAT_V5 = "w40k-sim/5"


# ---------- load / save ----------

def load(path: str) -> dict:
    """Read one native JSON file, migrate it to the current schema and
    validate it. Returns the ``w40k-sim/6`` dict; raises ValueError if the
    file is not a recognised native profile."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    data = migrate(data)
    validate(data)
    return data


def load_many(paths) -> dict:
    """Load several native JSON files and return their union: a single
    dict whose 'armies' is the concatenation of every file's armies (each
    file migrated + validated as by load()). Armies sharing a name are
    merged - their units combined and de-duplicated by unit name, first
    occurrence kept - so overlapping selections don't create duplicate
    army entries. Any file that fails to load raises, tagged with its
    name, so the caller can report which one."""
    merged, by_name = [], {}
    for path in paths:
        try:
            data = load(path)
        except Exception as exc:
            raise ValueError(f"{os.path.basename(path)}: {exc}") from exc
        for army in data.get("armies", []):
            name = army.get("name", "")
            if name in by_name:
                tgt = by_name[name]
                seen = {u.get("name") for u in tgt.get("units", [])}
                for unit in army.get("units", []):
                    if unit.get("name") not in seen:
                        tgt.setdefault("units", []).append(unit)
                        seen.add(unit.get("name"))
            else:
                by_name[name] = army
                merged.append(army)
    return {"format": FORMAT_TAG, "armies": merged}


def split_armies(paths) -> list:
    """Load several native JSON files and return a list of single-army
    native dicts, one per army found (each migrated + validated). This is
    the raw material for the load/join dialog, which lets the user pick a
    subset and optionally join them via join_raw before importing."""
    out = []
    for path in paths:
        try:
            data = load(path)
        except Exception as exc:
            raise ValueError(f"{os.path.basename(path)}: {exc}") from exc
        for army in data.get("armies", []):
            out.append({"format": FORMAT_TAG, "armies": [army]})
    return out


def join_raw(datasets, new_name) -> dict:
    """Merge several native dicts into ONE single-army file named 'new_name'.

    Each dataset is migrated + validated once. Source army names must be
    unique across all datasets (duplicates are rejected - rename before
    joining). Units keep their original name, EXCEPT a unit whose name also
    appears in another source army: every colliding unit is renamed
    '<unit>_<source-army>' so both survive with a traceable origin (e.g.
    'pippo' from armies 'pluto' and 'topolino' -> 'pippo_pluto' and
    'pippo_topolino'). Uniquely-named units are left unchanged."""
    # First pass: migrate/validate once, collect (army_name, units) and a
    # global count of every unit name to know which ones collide.
    prepared = []                       # [(army_name, [unit_dict, ...])]
    source_names = set()
    name_count = {}
    for d in datasets:
        d = migrate(d)
        validate(d)
        for a in d["armies"]:
            aname = a["name"]
            if aname in source_names:
                raise ValueError(f"duplicate army name: {aname!r}")
            source_names.add(aname)
            units = a.get("units", [])
            prepared.append((aname, units))
            for u in units:
                un = u.get("name", "")
                name_count[un] = name_count.get(un, 0) + 1

    # Second pass: copy units into the single army, suffixing only the names
    # that occur in more than one source (collisions).
    joined = {"name": new_name, "units": []}
    for aname, units in prepared:
        for u in units:
            un = u.get("name", "")
            if name_count.get(un, 0) > 1:
                u = dict(u)             # shallow copy: don't mutate the input
                u["name"] = f"{un}_{aname}"
            joined["units"].append(u)

    out = {"format": FORMAT_TAG, "armies": [joined]}
    validate(out)
    return out


def save(data: dict, path: str) -> None:
    """Validate 'data' against the current schema and write it to 'path' as
    pretty-printed UTF-8 JSON. Raises ValueError if 'data' is not a valid
    ``w40k-sim/6`` dict."""
    validate(data)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)


def migrate(data: dict) -> dict:
    """Upgrade older format versions in place-of (returns a new dict).
    v1 -> v2: single army wrapped into the 'armies' list.
    v2 -> v3: dead fields dropped (unit abilities_selected_ids and
    ability 'id': never consumed by the engine or the GUIs).
    v3 -> v4: leadership lifted from model to unit.
    v4 -> v5: unit-level 'damageable' flag added (default False).
    v5 -> v6: unit-level 'support' list added (default empty)."""
    if isinstance(data, dict) and data.get("format") == _FORMAT_V1:
        data = {"format": _FORMAT_V2,
                "armies": [{"name": data.get("army", "Army"),
                            "units": data.get("units", [])}]}
    if isinstance(data, dict) and data.get("format") == _FORMAT_V2:
        # Drop fields the engine never reads: unit abilities_selected_ids
        # and model captain. The ability 'id' is NOT dropped any more -
        # it is now a live field backing the enable/disable toggle, and
        # is normalised (stamped if missing) on load/save by the editor.
        for army in data.get("armies", []):
            for u in army.get("units", []):
                u.pop("abilities_selected_ids", None)
                for m in u.get("models", []):
                    m.pop("captain", None)
        data = {"format": _FORMAT_V3, "armies": data.get("armies", [])}
    if isinstance(data, dict) and data.get("format") == _FORMAT_V3:
        # v3 -> v4: leadership moves from the model to the UNIT (a unit's
        # ability to lead is a unit-level property; all its models share
        # it). Lift the model leadership lists to the unit; a unit with
        # more than one DISTINCT non-empty model leadership list is
        # malformed (no such case exists in 11th ed.) and is rejected.
        for army in data.get("armies", []):
            for u in army.get("units", []):
                lists = [m.get("leadership") for m in u.get("models", [])
                         if m.get("leadership")]
                distinct = {tuple(lst) for lst in lists}
                if len(distinct) > 1:
                    raise ValueError(
                        f"Unit {u.get('profile_name', u.get('name', '?'))!r}: "
                        "multiple models carry different leadership lists; "
                        "leadership is now a unit-level property and cannot "
                        "be migrated unambiguously")
                if distinct:
                    u["leadership"] = list(distinct.pop())
                u.setdefault("leadership", u.get("leadership", []))
                for m in u.get("models", []):
                    m.pop("leadership", None)
        data = {"format": _FORMAT_V4, "armies": data.get("armies", [])}
    if isinstance(data, dict) and data.get("format") == _FORMAT_V4:
        # v4 -> v5: unit-level 'damageable' flag (11th ed. Damaged
        # bracket). Absent -> False; the per-session "damaged" state is
        # not stored in the profile (it is set in the analyzer/assistant).
        for army in data.get("armies", []):
            for u in army.get("units", []):
                u.setdefault("damageable", bool(u.get("damageable", False)))
        data = {"format": _FORMAT_V5, "armies": data.get("armies", [])}
    if isinstance(data, dict) and data.get("format") == _FORMAT_V5:
        # v5 -> v6: unit-level 'support' list (a support unit attaches like
        # a leader but fills a separate slot). Absent -> empty list.
        for army in data.get("armies", []):
            for u in army.get("units", []):
                u.setdefault("support", list(u.get("support", [])))
        data = {"format": FORMAT_TAG, "armies": data.get("armies", [])}
    # Run on EVERY load, regardless of version: normalise the unit-level
    # core_abilities / faction_abilities lists into structured ability
    # dicts (older files - and older ArmyFetcher output - stored them as
    # bare name strings). Kept as separate lists (organisational marker),
    # but shaped like ordinary abilities so the editor and engine treat
    # them uniformly. Idempotent (a dict entry is left untouched).
    _normalize_extra_abilities(data)
    return data


# Unit-level ability lists beyond 'abilities'/'leader_effects' that the
# datasheet sources fill with just NAMES; wrapped into ability dicts here.
EXTRA_ABILITY_LISTS = ("core_abilities", "faction_abilities")


def wrap_ability(name: str) -> dict:
    """Wrap a bare ability NAME into a native ability dict (disabled, no-op
    effect) - the same shape ArmyFetcher uses for text-only abilities, so
    a core/faction ability can be enabled and structured in the editor and
    then applied by the engine like any other. Shared with unit_model."""
    return {"name": name, "description": "", "enabled": False,
            "share_with_unit": False, "conditions": [],
            "effect": {"type": "special", "data": {}}}


def _normalize_extra_abilities(data) -> None:
    """In place: ensure every unit's core_abilities / faction_abilities is a
    list of ability dicts (string entries wrapped, missing key -> [])."""
    if not isinstance(data, dict):
        return
    for army in data.get("armies", []):
        if not isinstance(army, dict):
            continue
        for u in army.get("units", []):
            for key in EXTRA_ABILITY_LISTS:
                u[key] = [wrap_ability(x) if isinstance(x, str) else x
                          for x in (u.get(key) or [])]


def validate(data) -> None:
    """Raise ValueError if 'data' is not a well-formed ``w40k-sim/6`` dict:
    checks the format tag, the armies/units structure and the per-unit
    field types (delegating unit checks to the validation module's rules).
    Returns None on success."""
    if not isinstance(data, dict) or data.get("format") != FORMAT_TAG:
        raise ValueError(f"Not a {FORMAT_TAG} file ('format' tag missing or "
                         "wrong); convert external exports first")
    armies = data.get("armies")
    if not isinstance(armies, list):
        raise ValueError("'armies' must be a list")
    for a in armies:
        if not isinstance(a, dict) or not isinstance(a.get("units"), list):
            raise ValueError("each army must be a dict with a 'units' list")
        if not str(a.get("name", "")).strip():
            raise ValueError("each army must have a non-empty 'name'")


def join(datasets) -> dict:
    """Merge several native dicts into one multi-army file. Duplicate
    army names are rejected (rename before joining)."""
    armies, seen = [], set()
    for d in datasets:
        d = migrate(d)
        validate(d)
        for a in d["armies"]:
            name = a["name"]
            if name in seen:
                raise ValueError(f"duplicate army name: {name!r}")
            seen.add(name)
            armies.append(a)
    return {"format": FORMAT_TAG, "armies": armies}
