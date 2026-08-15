"""Consistency validation for native-format data.

validate_data(data) returns a list of human-readable issue strings
(empty when everything is coherent). It never raises: structural errors
are reported as issues. Used by the editor on Apply and before saving.

Checks:
- model_count / weapon count are positive integers
- weapon type is Ranged or Melee, with BS xor WS matching the type
- characteristics parse as int / dice notation (A, S, AP, D, RNG,
  M, T, Sv, W, LD, OC)
- invuln / fnp are None or in 2..6
- keywords are lists of strings; unit-level leadership too
- LEADER units should declare a non-empty leadership list
- duplicate unit names within an army
- abilities have a dict effect and a list of conditions, with
  registered types (unregistered ones are reported)
"""

from characteristics import Characteristic
import condition_specs
import effect_specs

_MODEL_CHARS = ("M", "T", "Sv", "W", "LD", "OC")
_WEAPON_CHARS = ("RNG", "A", "S", "AP", "D")


def _parseable(value) -> bool:
    try:
        Characteristic(value)
        return True
    except (ValueError, TypeError):
        return False


def _is_str_list(v) -> bool:
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def _check_abilities(abilities, where, issues):
    for i, ab in enumerate(abilities or []):
        tag = f"{where} > ability {i + 1}"
        if not isinstance(ab, dict):
            issues.append(f"{tag}: ability is not a dict")
            continue
        eff = ab.get("effect")
        if not isinstance(eff, dict):
            issues.append(f"{tag}: missing/invalid 'effect'")
        elif eff.get("type") not in effect_specs.EFFECT_SPECS:
            issues.append(f"{tag}: unregistered effect type "
                          f"{eff.get('type')!r}")
        conds = ab.get("conditions")
        if not isinstance(conds, list):
            issues.append(f"{tag}: missing/invalid 'conditions'")
        else:
            for c in conds:
                if not isinstance(c, dict) or c.get("type") \
                        not in condition_specs.CONDITION_SPECS:
                    issues.append(f"{tag}: unregistered condition type "
                                  f"{(c or {}).get('type')!r}")


def validate_data(data) -> list:
    """Return a list of human-readable problems with 'data' (empty if valid): per-unit checks on types, characteristics and ability structure."""
    issues = []
    if not isinstance(data, dict) or not isinstance(data.get("armies"), list):
        return ["file: missing 'armies' list (wrong format?)"]
    for army in data["armies"]:
        aname = army.get("name", "?")
        units = army.get("units")
        if not isinstance(units, list):
            issues.append(f"{aname}: 'units' is not a list")
            continue
        seen_names = set()
        for u in units:
            uname = f"{aname} > {u.get('name', '?')}"
            if u.get("name") in seen_names:
                issues.append(f"{uname}: duplicate unit name in the army")
            seen_names.add(u.get("name"))
            if not _is_str_list(u.get("keywords", [])):
                issues.append(f"{uname}: keywords must be a list of strings")
            if not _is_str_list(u.get("leadership", [])):
                issues.append(f"{uname}: leadership must be a list of strings")
            if not _is_str_list(u.get("support", [])):
                issues.append(f"{uname}: support must be a list of strings")
            if not isinstance(u.get("damageable", False), bool):
                issues.append(f"{uname}: damageable must be a boolean")
            for slot in ("leader_slots", "support_slots"):
                n = u.get(slot, 1)
                if not isinstance(n, int) or isinstance(n, bool) or n < 0:
                    issues.append(f"{uname}: {slot} must be a non-negative "
                                  f"integer (got {n!r})")
            if "LEADER" in u.get("keywords", []) and not u.get("leadership"):
                issues.append(f"{uname}: LEADER unit with empty "
                              "'leadership' list")
            _check_abilities(u.get("abilities"), uname, issues)
            _check_abilities(u.get("core_abilities"),
                             f"{uname} (core_abilities)", issues)
            _check_abilities(u.get("faction_abilities"),
                             f"{uname} (faction_abilities)", issues)
            _check_abilities(u.get("leader_effects"),
                             f"{uname} (leader_effects)", issues)
            for m in u.get("models", []):
                mname = f"{uname} > {m.get('name', '?')}"
                mc = m.get("model_count")
                if not isinstance(mc, int) or mc < 1:
                    issues.append(f"{mname}: model_count must be a positive "
                                  f"integer (got {mc!r})")
                for ch in _MODEL_CHARS:
                    if not _parseable(m.get(ch)):
                        issues.append(f"{mname}: invalid characteristic "
                                      f"{ch}={m.get(ch)!r}")
                for fld in ("invuln", "fnp"):
                    v = m.get(fld)
                    if v is not None and (not isinstance(v, int)
                                          or not 2 <= v <= 6):
                        issues.append(f"{mname}: {fld} must be null or an "
                                      f"integer in 2..6 (got {v!r})")
                if not _is_str_list(m.get("keywords", [])):
                    issues.append(f"{mname}: keywords must be a list "
                                  "of strings")
                _check_abilities(m.get("abilities"), mname, issues)
                for w in m.get("weapons", []):
                    wname = f"{mname} > {w.get('name', '?')}"
                    wtype = w.get("type")
                    if wtype not in ("Ranged", "Melee"):
                        issues.append(f"{wname}: type must be Ranged or "
                                      f"Melee (got {wtype!r})")
                    else:
                        skill, other = (("WS", "BS") if wtype == "Melee"
                                        else ("BS", "WS"))
                        if skill not in w:
                            issues.append(f"{wname}: {wtype} weapon missing "
                                          f"{skill}")
                        if other in w:
                            issues.append(f"{wname}: {wtype} weapon must "
                                          f"not define {other}")
                        if skill in w and not _parseable(w.get(skill)):
                            issues.append(f"{wname}: invalid {skill}="
                                          f"{w.get(skill)!r}")
                    for ch in _WEAPON_CHARS:
                        if not _parseable(w.get(ch)):
                            issues.append(f"{wname}: invalid characteristic "
                                          f"{ch}={w.get(ch)!r}")
                    cnt = w.get("count", 1)
                    if not isinstance(cnt, int) or cnt < 1:
                        issues.append(f"{wname}: count must be a positive "
                                      f"integer (got {cnt!r})")
                    _check_abilities(w.get("abilities"), wname, issues)
    return issues
