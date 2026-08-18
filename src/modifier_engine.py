"""Modifier engine: interprets declarative abilities into combat views.

Abilities stay data (the JSON edited in the GUI); this module holds two
registries of small pure functions:

  CONDITION_EVALUATORS[type](data, env) -> True | False | DYNAMIC
  EFFECT_APPLIERS[type](data, env)      -> list of operations

Conditions are STATIC (decidable when the view is built: role, attack
type, keywords, range, ...) or DYNAMIC (decidable only while rolling:
crits, specific roll values). An ability is active when every static
condition holds; its dynamic conditions are compiled as "IF ...:"
prefixes into the effect string, to be honoured by the combat functions.

Operations emitted by appliers:
  ("wdelta", attr, n)   characteristic delta on the weapon in scope
                        (accumulated, then capped per characteristic)
  ("weffect", str)      effect string attached to the weapon in scope
  ("mset", attr, n)     set a model attribute (invuln / fnp): best value wins
  ("ueffect", str)      effect string attached to the unit view
  ("kw", target, op, kw) add/remove a keyword on the unit or weapon view

Effect-string grammar (uppercase tokens, space-separated, one effect per
string, optional "IF X:" prefixes):
  "HIT_ROLL +1" | "WOUND_ROLL -1" | "REROLL HIT_ROLL 1" |
  "REROLL WOUND_ROLL FAILS" | "EXTRA_HITS 1" | "LETHAL_HITS" |
  "MORTAL_WOUNDS 1 END_SEQUENCE" | "OVERRIDE WOUND ALWAYS CRIT" | ...
"""

import copy

import rules_config
from characteristics import Characteristic
from unit_model import Unit

DYNAMIC = "dynamic"


class Context:
    """Free-form combat context: unknown attributes read as None.
    Typical fields: range_half, attacker_stationary, defender_stationary,
    attacker_charged, defender_in_cover, battle_round, ..."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getattr__(self, _name):
        return None


class Env:
    """Evaluation scope handed to evaluators/appliers."""

    def __init__(self, attacker, defender, context, role,
                 model=None, weapon=None):
        self.attacker, self.defender = attacker, defender
        self.context = context or Context()
        self.role = role
        self.model, self.weapon = model, weapon


def _key(v):
    """Normalize a data value that may be a {title,key} dict or a string."""
    return (v.get("key") if isinstance(v, dict) else str(v or "")).lower()


# ---------- condition evaluators ----------

def _c_profile_role(d, env):
    return _key(d.get("profileRole")) == env.role


def _c_attack_type(d, env):
    if env.weapon is None:
        # No weapon in scope (typically defender role): the condition
        # refers to the incoming attack -> defer to roll time
        return DYNAMIC
    return _key(d.get("attackType")) == env.weapon.type.lower()


def _keyword_subject(d, env):
    """The unit whose keywords a keyword condition reads: the target of
    the attack by default, or the ability's own unit when 'who' is
    'self' ("while this model is leading a BLOOD CLAWS unit")."""
    return env.attacker if _key(d.get("who")) == "self" else env.defender


def _c_keywords_only(d, env):
    # At least one of the keywords on the chosen unit.
    subject = _keyword_subject(d, env)
    if subject is None:
        return False
    kws = {str(k).strip().upper() for k in d.get("keywords", [])}
    # Both sides upper-cased: roster keywords are spelled 'Vehicle',
    # 'VEHICLE' or 'vehicle' depending on the source.
    return bool(kws & {str(k).strip().upper()
                       for k in (subject.keywords or ())})


def _c_keywords_excludes(d, env):
    subject = _keyword_subject(d, env)
    if subject is None:
        return True
    kws = {str(k).strip().upper() for k in d.get("keywords", [])}
    return not (kws & {str(k).strip().upper()
                       for k in (subject.keywords or ())})


def _c_range(d, env):
    want = _key(d.get("range"))
    half = env.context.range_half
    if half is None:
        return False
    return half if want == "withinhalfrange" else not half


def _c_stationary(_d, env):
    """Whether the ATTACKER remained stationary. The defender side has no
    flag behind it and no ability asking for it, so the condition only
    offers the attacker; adding the other side later means restoring the
    choice in condition_specs, a flag in setup_panel.FLAGS and one line
    in analyzer_core.build_views."""
    return bool(env.context.attacker_stationary)


def _c_charged(_d, env):
    return bool(env.context.attacker_charged)


def _c_in_cover(_d, env):
    return bool(env.context.defender_in_cover)


def _c_below_half(d, env):
    who = _key(d.get("who"))
    return bool(env.context.attacker_below_half if who == "attacker"
                else env.context.defender_below_half)


def _c_below_full(d, env):
    who = _key(d.get("who"))
    return bool(env.context.attacker_below_full if who == "attacker"
                else env.context.defender_below_full)


def _c_battle_round(d, env):
    rnd = env.context.battle_round
    if rnd is None:
        return False
    try:
        val = int(d.get("roundValue") or 0)
    except ValueError:
        return False
    return {"greaterthan": rnd > val, "lessthan": rnd < val,
            "equalto": rnd == val, "greaterthanorequal": rnd >= val,
            "lessthanorequal": rnd <= val}.get(_key(d.get("comparison")), False)


def _c_psychic_attack(d, env):
    # True when the weapon in scope carries the PSYCHIC keyword. With no
    # weapon in scope the condition refers to the INCOMING attack (the
    # defender role, and the weapon-free passes of the attacker role):
    # defer it, exactly like attackType. The attack maths decides it -
    # there the attacking weapon is known - so a defensive "only against
    # Psychic attacks" ability now works instead of silently never
    # firing.
    if env.weapon is None:
        return DYNAMIC
    return "PSYCHIC" in {k.upper() for k in (env.weapon.keywords or [])}


def _c_context_flag(attr_attacker, attr_defender):
    def ev(d, env):
        who = _key(d.get("who"))
        attr = attr_attacker if who == "attacker" else attr_defender
        return bool(getattr(env.context, attr))
    return ev


CONDITION_EVALUATORS = {
    "profileRole": _c_profile_role,
    "attackType": _c_attack_type,
    "keywordsOnly": _c_keywords_only,
    "keywordsExcludes": _c_keywords_excludes,
    "range": _c_range,
    "remainedStationary": _c_stationary,
    "attackerCharged": _c_charged,
    "targetInCover": _c_in_cover,
    "belowHalfStrength": _c_below_half,
    "belowFullStrength": _c_below_full,
    "battleRound": _c_battle_round,
    "objectiveRange": _c_context_flag("attacker_on_objective",
                                      "defender_on_objective"),
    "leaderAttached": _c_context_flag("attacker_has_leader",
                                      "defender_has_leader"),
    "engagementRange": _c_context_flag("attacker_in_engagement",
                                       "defender_in_engagement"),
    "psychicAttack": _c_psychic_attack,
    # Roll-time conditions: compiled into the effect string
    "crit": DYNAMIC, "attackStepRoll": DYNAMIC,
    "woundType": DYNAMIC, "attackCharacteristic": DYNAMIC,
}


def _dynamic_prefix(cond) -> str:
    """Compact textual form of a dynamic condition for the IF prefix."""
    t, d = cond.get("type"), cond.get("data", {})
    if t == "attackType":
        return f"{_key(d.get('attackType')).upper()}_ATTACK"
    if t == "psychicAttack":
        # Decided by parse_effect_strings, where the weapon is known.
        return "PSYCHIC_ATTACK"
    if t == "crit":
        return "CRIT_HIT" if _key(d.get("crit")) == "hitroll" else "CRIT_WOUND"
    if t == "attackStepRoll":
        step = {"hitroll": "HIT", "woundroll": "WOUND",
                "saveroll": "SAVE"}.get(_key(d.get("attackStep")), "HIT")
        tgt = {"orgreater": "+", "orless": "-",
               "exactly": "="}.get(_key(d.get("rollTarget")), "+")
        state = ("UNMOD" if _key(d.get("rollState")) == "unmodified"
                 else "MOD")
        return f"ROLL {step} {d.get('rollValue', '')}{tgt} {state}"
    if t == "woundType":
        return ("MW_ONLY" if _key(d.get("woundType")) == "mortalwounds"
                else "NORMAL_ONLY")
    if t == "attackCharacteristic":
        char = {"strength": "S", "attacks": "A", "ap": "AP",
                "damage": "D"}.get(_key(d.get("attackChar")), "S")
        cmp_ = {"greaterthan": "GT", "lessthan": "LT", "equalto": "EQ",
                "greaterthanorequal": "GE",
                "lessthanorequal": "LE"}.get(_key(d.get("comparison")), "GT")
        state = ("UNMOD" if _key(d.get("attackCharState")) == "unmodified"
                 else "MOD")
        return f"CHAR {char} {cmp_} {d.get('attackCharValue', '')} {state}"
    return t.upper()


# ---------- effect appliers ----------

# modifyRelative applications that are weapon characteristics; the rest
# (hitRoll / woundRoll / saveRoll) are roll-level -> effect strings.
_CHAR_ATTRS = {"bs": "_skill", "ws": "_skill", "ap": "AP",
               "damage": "D", "attacks": "A", "strength": "S"}
# Sign of "improve by 1": skills improve downwards (4+ -> 3+); AP follows
# the datasheet convention (negative), so improving makes it more negative.
_IMPROVE_SIGN = {"_skill": -1, "AP": -1, "D": +1, "A": +1, "S": +1}


# Model characteristics reachable by modify effects. Improving LD
# lowers the target (6+ is better than 7+), like skills; M and OC
# improve upwards.
_MODEL_ATTRS = {"m": "M", "ld": "LD", "oc": "OC",
                "t": "T", "sv": "Sv", "w": "W"}
# Toughness and Wounds improve upwards, saves downwards (4+ -> 3+).
_MODEL_IMPROVE_SIGN = {"M": +1, "LD": -1, "OC": +1,
                       "T": +1, "Sv": -1, "W": +1}


def _e_modify_relative(d, env):
    app = _key(d.get("application"))
    try:
        n = int(d.get("relativeValue") or 0)
    except ValueError:
        return []
    op = _key(d.get("operator"))
    if app in _CHAR_ATTRS:
        attr = _CHAR_ATTRS[app]
        sign = {"add": +1, "subtract": -1,
                "improve": _IMPROVE_SIGN[attr],
                "degrade": -_IMPROVE_SIGN[attr]}.get(op, +1)
        return [("wdelta", attr, sign * n)]
    if app in _MODEL_ATTRS:
        attr = _MODEL_ATTRS[app]
        sign = {"add": +1, "subtract": -1,
                "improve": _MODEL_IMPROVE_SIGN[attr],
                "degrade": -_MODEL_IMPROVE_SIGN[attr]}.get(op, +1)
        return [("mcdelta", attr, sign * n)]
    sign = +1 if op in ("add", "improve") else -1
    return [("weffect", f"{app.replace('roll', '_roll').upper()} {sign*n:+d}")]


def _e_modify_absolute(d, env):
    """Absolute set of a weapon or model characteristic; values may use
    dice notation. Roll applications make no sense for absolute sets
    and surface as an unsupported-effect warning downstream."""
    app = _key(d.get("application"))
    value = str(d.get("absoluteValue", "")).strip()
    if not value:
        return []
    if app in _CHAR_ATTRS:
        return [("wcset", _CHAR_ATTRS[app], value)]
    if app in _MODEL_ATTRS:
        return [("mcset", _MODEL_ATTRS[app], value)]
    return [("weffect", f"SET {app.upper()} {value}")]


def _e_reroll(d, env):
    what = _key(d.get("resultToReRoll"))
    app = _key(d.get("application")).replace("roll", "_roll").upper()
    if what == "single":
        return [("weffect", f"REROLL {app} {d.get('valueSingle', '1')}")]
    if what == "range":
        return [("weffect", f"REROLL {app} RANGE {d.get('valueRange', '')}")]
    return [("weffect", f"REROLL {app} FAILS")]


def _e_generate_extras(d, env):
    opt = {"extrahits": "EXTRA_HITS", "extraattacks": "EXTRA_ATTACKS",
           "extrawounds": "EXTRA_WOUNDS"}.get(_key(d.get("option")),
                                              "EXTRA_HITS")
    return [("weffect", f"{opt} {d.get('extrasValue', '1')}")]


def _e_special(d, env):
    return [("weffect", _key(d.get("option")).upper())]


def _e_mortal_wounds(d, env):
    tokens = [f"MORTAL_WOUNDS {d.get('mortalWoundsValue', '1')}"]
    if d.get("matchWeaponDamage"):
        tokens.append("MATCH_DAMAGE")
    if d.get("attackSequenceEnds"):
        tokens.append("END_SEQUENCE")
    if d.get("noSpillOver"):
        tokens.append("NO_SPILL")
    if d.get("cap"):
        tokens.append(f"CAP {d['cap']}")
    return [("weffect", " ".join(tokens))]


def _e_override_reqs(d, env):
    tokens = ["OVERRIDE", _key(d.get("outcome")).upper(),
              _key(d.get("type")).upper()]
    if d.get("crit"):
        tokens.append("CRIT")
    if d.get("irrespective"):
        tokens.append("IRRESPECTIVE")
    return [("weffect", " ".join(tokens))]


def _e_feel_no_pain(d, env):
    """Grant / override / modify a Feel No Pain roll.
    'grant' keeps the historical behaviour: it sets the model attribute,
    so the best value wins and FNP never stacks. 'override' and 'modify'
    are attack-scoped, so they are always exported as effect strings -
    which also gives them the IF-prefixes for free, i.e. a conditional
    FNP (e.g. only against mortal wounds)."""
    try:
        n = int(d.get("value"))
    except (TypeError, ValueError):
        return []
    op = _key(d.get("operator")) or "grant"
    if op == "override":
        return [("ueffect", f"FNPOVERRIDE {n}")]
    if op == "modify":
        return [("ueffect", f"FNP_ROLL {n:+d}")]
    return [("mset", "fnp", n)]


def _e_invuln(d, env):
    try:
        return [("mset", "invuln", int(d.get("invulnValue")))]
    except (TypeError, ValueError):
        return []


def _e_increase_attacks(d, env):
    try:
        return [("wdelta", "A", int(d.get("increaseWeaponAttacksValue") or 0))]
    except ValueError:
        return []


def _e_disable_mechanic(d, env):
    return [("ueffect", f"DISABLE {_key(d.get('mechanic')).upper()}")]


def _e_damage_reduction(d, env):
    """Defender effect: modify the Damage of each incoming attack. The
    attack maths applies all such modifiers in a fixed order (set, then
    multiply, then add, then floor at 1). 'operator' selects the step:
      'set'  -> fix the Damage to N (Step 1)
      'mult' -> multiply the Damage by N, rounding up (Step 2; 0.5 = halve)
      'add'  -> add N to the Damage; a reduction of k is 'add' with -k
                (Step 3)
    Missing operator defaults to 'add' (a plain damage reduction). The
    value is a float for 'mult' and an int otherwise."""
    try:
        mode = _key(d.get("operator")) or "add"
        raw = d.get("value") or 0
        value = float(raw) if mode == "mult" else int(raw)
        return [("dmgredux", mode, value)]
    except (TypeError, ValueError):
        return []


def _e_damage_set_zero(d, env):
    """Defender effect: force each incoming attack's Damage to 0,
    bypassing the usual 'at least 1 damage' floor (Step 4 special case).
    Takes no parameters."""
    return [("dmgsetzero",)]


def _e_ignore_malus(d, env):
    """Ignore NEGATIVE modifiers to one roll of the attack sequence
    (positive modifiers still apply). 'roll' selects which roll."""
    roll = _key(d.get("roll"))
    return [("weffect", f"IGNOREMALUS {roll.upper()}")] if roll else []


# Option keys are camelCase, weapon keywords are spelled out: map the
# ones whose spelling differs, so a setKeyword ability really lands on
# the keyword the attack maths looks for.
_KEYWORD_SPELLING = {
    "LETHALHITS": "LETHAL HITS", "DEVASTATINGWOUNDS": "DEVASTATING WOUNDS",
    "SUSTAINEDHITS": "SUSTAINED HITS", "RAPIDFIRE": "RAPID FIRE",
    "IGNORECOVER": "IGNORES COVER", "IGNORESCOVER": "IGNORES COVER",
    "TWINLINKED": "TWIN-LINKED", "INDIRECTFIRE": "INDIRECT FIRE",
    "ONESHOT": "ONE SHOT", "EXTRAATTACKS": "EXTRA ATTACKS",
    "CLOSEQUARTERS": "CLOSE-QUARTERS", "PISTOL": "CLOSE-QUARTERS",
}


def _e_hunter_target(d, env):
    """HUNTER X: restrict what the weapon may be fired at. Exported as an
    effect string so it inherits the IF-prefixes, and so that a weapon
    keyword and an ability end up on the same field."""
    kw = str(d.get("keyword", "")).strip().upper()
    return [("weffect", f"HUNTER {kw}")] if kw else []


def _e_single_reroll(d, env):
    """ONE re-roll of the chosen roll per activation (not per attack).
    The 'allowance' field is not part of the maths: it only drives the
    warning that counts how many of these are switched on across the
    unit's weapons (see analyzer_core.single_reroll_notes)."""
    roll = _key(d.get("roll")) or "hit"
    return [("weffect", f"REROLL ONE {roll.upper()}_ROLL")]


def _e_disable_weapon(d, env):
    """The weapon in scope cannot be selected for the attack. Emitted as
    a weapon effect string; analyzer_core.select_weapons_split reads it
    and reports the weapon as skipped instead of resolving it."""
    return [("weffect", "WEAPON_DISABLED")]


def _e_set_keyword(d, env):
    kw = str(d.get("keyword", "")).upper()
    return [("kw", _key(d.get("target")), _key(d.get("operation")),
             _KEYWORD_SPELLING.get(kw, kw))]


def _e_critical_threshold(d, env):
    """Attacker effect: lower the critical HIT or WOUND threshold to N+
    (unmodified). Emits a CRITON token resolved per-weapon by the maths."""
    app = _key(d.get("application")) or "hit"
    try:
        n = int(d.get("value") or 6)
    except (TypeError, ValueError):
        return []
    return [("weffect", f"CRITON {app.upper()} {n}")]


EFFECT_APPLIERS = {
    "modifyRelative": _e_modify_relative,
    "reRoll": _e_reroll,
    "generateExtras": _e_generate_extras,
    "special": _e_special,
    "mortalWounds": _e_mortal_wounds,
    "overrideReqs": _e_override_reqs,
    "feelNoPain": _e_feel_no_pain,
    "invulnSave": _e_invuln,
    "increaseWeaponAttacks": _e_increase_attacks,
    "hunterTarget": _e_hunter_target,
    "disableMechanic": _e_disable_mechanic,
    "setKeyword": _e_set_keyword,
    "disableWeapon": _e_disable_weapon,
    "singleReRoll": _e_single_reroll,
    "modifyAbsolute": _e_modify_absolute,
    "damageReduction": _e_damage_reduction,
    "damageSetZero": _e_damage_set_zero,
    "ignoreMalus": _e_ignore_malus,
    "criticalThreshold": _e_critical_threshold,
}

# Effects that make sense without a weapon in scope (model/unit level)
_WEAPON_FREE_EFFECTS = {"feelNoPain", "invulnSave", "disableMechanic",
                        "setKeyword", "damageReduction", "damageSetZero"}


# ---------- view construction ----------

def _eval_conditions(ability, env):
    """Return (active, prefixes): active=False if any static condition
    fails; dynamic conditions become IF-prefixes."""
    prefixes = []
    for cond in ability.get("conditions", []):
        ev = CONDITION_EVALUATORS.get(cond.get("type"))
        if ev is None:
            return False, []            # unknown condition: be conservative
        negate = bool(cond.get("data", {}).get("negate"))
        if ev is DYNAMIC:
            if negate:
                return False, []    # see below: not expressible
            prefixes.append(_dynamic_prefix(cond))
            continue
        result = ev(cond.get("data", {}), env)
        if result is DYNAMIC:
            # A roll-time condition becomes an IF-prefix in the effect
            # string, and the effect grammar has no negation - so a
            # negated dynamic condition cannot be expressed. Be
            # conservative and switch the ability off rather than apply
            # it with the wrong sense.
            if negate:
                return False, []
            prefixes.append(_dynamic_prefix(cond))
            continue
        if bool(result) == negate:
            return False, []
    return True, prefixes


_ATTR_NAMES = {"_skill": "SKILL", "AP": "AP", "D": "D", "A": "A", "S": "S"}


def _floor_char(attr, ch):
    """Apply the 11th-edition ABSOLUTE characteristic limits to a
    modified Characteristic (see rules_config.CHARACTERISTIC_LIMITS):
    BS/WS stay between 2+ and 6+, Sv never better than 2+, AP never
    above 0 (datasheet convention: negative is stronger), M and OC never
    below 0, everything else never below 1. There is NO cap on the
    modifier itself - only these limits on the result. Dice-based values
    are left untouched (the limits are about flat characteristics; dice
    results are resolved at roll time)."""
    if ch.is_none() or ch.is_dice():
        return ch
    v = ch.value_avg()
    limited = rules_config.clamp_characteristic(attr, v)
    return ch if limited == v else Characteristic(limited)


def _apply_ops(ops, prefixes, weapon_view, model_view, unit_view, deltas):
    pre = "".join(f"IF {p}: " for p in prefixes)
    models = (model_view if isinstance(model_view, list)
              else [model_view] if model_view is not None else [])
    for op in ops:
        kind = op[0]
        if kind == "wdelta" and weapon_view is None:
            # Defender role: "the weapon" is the incoming attack, unknown
            # until the attack is resolved. Export the delta as a string
            # so the attack maths can apply it to the attacking weapon
            # (only AP is modelled there; anything else warns).
            unit_view.effects.append(
                f"{pre}CHARMOD {_ATTR_NAMES.get(op[1], op[1])} "
                f"{op[2]:+d}")
        elif kind == "wdelta" and weapon_view is not None:
            if prefixes:
                # A conditional characteristic delta cannot be applied to
                # the view (the condition is roll-time): export it as a
                # string for the attack maths instead.
                weapon_view.effects.append(
                    f"{pre}CHARMOD {_ATTR_NAMES.get(op[1], op[1])} "
                    f"{op[2]:+d}")
            else:
                deltas[(id(weapon_view), op[1])] = \
                    deltas.get((id(weapon_view), op[1]), 0) + op[2]
        elif kind == "weffect":
            target = weapon_view if weapon_view is not None else unit_view
            target.effects.append(pre + op[1])
        elif kind == "mset":
            if prefixes:
                # Conditional FNP/invuln (e.g. 'FNP 4+ vs mortal wounds
                # only'): exported as a string, resolved at roll time.
                unit_view.effects.append(
                    f"{pre}SET{op[1].upper()} {op[2]}")
                continue
            for mv in models:
                cur = getattr(mv, op[1])
                # best (lowest N+) wins between existing and new value
                setattr(mv, op[1], op[2] if cur is None else min(cur, op[2]))
        elif kind == "dmgredux":
            # Defender Damage modifier: op = ("dmgredux", mode, value),
            # mode in {set, mult, add}. Always exported as an effect
            # string (with any roll-time IF-prefix); the attack maths
            # resolves it per-attack in the fixed set/mult/add/floor
            # order (see attack_math.apply_damage_modifiers). Emitted
            # once at unit level - it must NOT stack per weapon.
            if weapon_view is not None:
                continue
            mode, value = op[1], op[2]
            val = value if mode == "mult" else int(value)
            unit_view.effects.append(f"{pre}DMGREDUX {mode} {val}")
        elif kind == "dmgsetzero":
            # Defender effect: force incoming Damage to 0 (Step 4 special
            # case). Same unit-level, once-only handling as dmgredux.
            if weapon_view is not None:
                continue
            unit_view.effects.append(f"{pre}DMGSETZERO")
        elif kind == "mcdelta":
            # Model characteristic delta (M/LD/OC), capped like weapon
            # characteristic mods; with roll-time prefixes it can only
            # be exported as a string (harmless to the combat maths).
            # Applied ONLY in the weapon-free passes: per-weapon
            # re-evaluation of unit/model abilities must not stack the
            # same delta once per weapon (unlike mset, it is not
            # idempotent).
            if weapon_view is not None:
                continue
            if prefixes:
                unit_view.effects.append(
                    f"{pre}MODELMOD {op[1]} {op[2]:+d}")
                continue
            for mv in models:
                cur = getattr(mv, op[1], None)
                if cur is not None:
                    setattr(mv, op[1],
                            _floor_char(op[1], cur.with_delta(op[2])))
        elif kind == "mcset":
            if weapon_view is not None:
                continue
            if prefixes:
                unit_view.effects.append(
                    f"{pre}MODELSET {op[1]} {op[2]}")
                continue
            for mv in models:
                setattr(mv, op[1],
                        _floor_char(op[1], Characteristic(op[2])))
        elif kind == "wcset":
            if weapon_view is None:
                continue
            if prefixes:
                weapon_view.effects.append(
                    f"{pre}CHARSET {_ATTR_NAMES.get(op[1], op[1])} "
                    f"{op[2]}")
                continue
            setattr(weapon_view, op[1],
                    _floor_char(op[1], Characteristic(op[2])))
        elif kind == "ueffect":
            unit_view.effects.append(pre + op[1])
        elif kind == "kw":
            _t, op_, kw_ = op[1], op[2], op[3]
            if prefixes:
                # A roll-time condition cannot gate a keyword: the
                # keyword is read once, when the mechanics are built.
                # Export it as a string so the attack maths reports it
                # instead of applying it silently and unconditionally.
                (weapon_view if weapon_view is not None
                 else unit_view).effects.append(
                    f"{pre}KEYWORD {op_.upper()} {kw_}")
                continue
            # Scope: "this weapon" is only meaningful in the per-weapon
            # pass; every other target is resolved once, in the
            # weapon-free pass, so it is not applied again per weapon.
            if (_t == "weapon") != (weapon_view is not None):
                continue
            # Resolve targets: weapon / allWeapons / model / allModels / unit
            if _t == "weapon":
                targets = [weapon_view]
            elif _t == "allweapons":
                targets = [w for mv in models for w in mv.weapons]
            elif _t == "model":
                targets = models
            elif _t == "allmodels":
                targets = models
            else:
                targets = [unit_view]
            for tgt in targets:
                # Case-insensitive membership: a keyword already there as
                # 'Vehicle' must not be added again as 'VEHICLE', and a
                # removal must find it whatever its casing.
                present = [k for k in tgt.keywords
                           if str(k).strip().upper() == kw_]
                if op_ == "add" and not present:
                    tgt.keywords.append(kw_)
                elif op_ == "remove":
                    for k in present:
                        tgt.keywords.remove(k)


def build_view(unit: Unit, defender, context, role: str = "attacker"):
    """Return an immutable-by-convention deep copy of 'unit' with active
    ability effects applied (characteristic deltas capped per
    rules_config) and effect strings attached at the right scope."""
    view = copy.deepcopy(unit)
    deltas = {}          # (id(weapon_view), attr) -> accumulated delta

    # An ability with enabled=False is skipped entirely (absent default
    # means enabled). Filtering here, before abilities are sorted into
    # the unit/model/weapon passes, is the single choke point: the three
    # loops below never see a disabled ability.
    def _on(ab):
        return ab.get("enabled", True)

    unit_abilities = [ab for ab in view.abilities if _on(ab)]
    if (view.apply_leader_effects_to_self
            or view.attached_leaders or view.attached_supports):
        unit_abilities += [ab for ab in view.leader_effects if _on(ab)]

    all_models = view.models()

    # Model abilities flagged share_with_unit are promoted to unit
    # scope (they cover every model and weapon of the unit, leader's
    # included when one is attached); the others stay local to their
    # model. Weapon-level abilities are never promoted.
    local_abilities = {}
    for model in all_models:
        local, shared = [], []
        for ab in model.abilities:
            if not _on(ab):
                continue
            (shared if ab.get("share_with_unit") else local).append(ab)
        local_abilities[id(model)] = local
        unit_abilities += shared

    # Pass 1: unit-level abilities, weapon-free scope, evaluated ONCE.
    # In attacker role only weapon-independent effects apply here (the
    # rest is handled per weapon in pass 3); in defender role ALL effect
    # types apply here, because "the weapon" is the incoming attack,
    # unknown until roll time (weapon-dependent conditions like
    # attackType become IF prefixes). mset ops reach every model.
    env_u = Env(view, defender, context, role)
    for ab in unit_abilities:
        active, prefixes = _eval_conditions(ab, env_u)
        eff = ab.get("effect") or {}
        applier = EFFECT_APPLIERS.get(eff.get("type"))
        if not active or applier is None:
            continue
        if role == "defender" or eff.get("type") in _WEAPON_FREE_EFFECTS:
            _apply_ops(applier(eff.get("data", {}), env_u), prefixes,
                       None, all_models, view, deltas)
        elif eff.get("type") in ("modifyRelative", "modifyAbsolute"):
            # Hybrid types: their model-characteristic ops (M/LD/OC)
            # are weapon-free and must apply exactly once; the weapon
            # ops of the same ability stay with pass 3.
            ops = [op for op in applier(eff.get("data", {}), env_u)
                   if op[0] in ("mcdelta", "mcset")]
            _apply_ops(ops, prefixes, None, all_models, view, deltas)

    for model in all_models:
        # Pass 2: model-level abilities, weapon-free scope, per model
        # (shared ones were promoted to unit_abilities above)
        for ab in local_abilities[id(model)]:
            env = Env(view, defender, context, role, model=model)
            active, prefixes = _eval_conditions(ab, env)
            eff = ab.get("effect") or {}
            applier = EFFECT_APPLIERS.get(eff.get("type"))
            if not active or applier is None:
                continue
            if role == "defender" or eff.get("type") in _WEAPON_FREE_EFFECTS:
                _apply_ops(applier(eff.get("data", {}), env), prefixes,
                           None, model, view, deltas)
            elif eff.get("type") in ("modifyRelative", "modifyAbsolute"):
                ops = [op for op in applier(eff.get("data", {}), env)
                       if op[0] in ("mcdelta", "mcset")]
                _apply_ops(ops, prefixes, None, model, view, deltas)
        # Pass 3: weapon scope. Own-weapon abilities always; unit and
        # model abilities only in attacker role (they modify our attacks)
        for weapon in model.weapons:
            scoped = [ab for ab in weapon.abilities if _on(ab)]
            if role == "attacker":
                scoped = unit_abilities + local_abilities[id(model)] \
                    + scoped
            for ab in scoped:
                eff = ab.get("effect") or {}
                etype = eff.get("type")
                # setKeyword is weapon-free for its model/unit targets,
                # but its "this weapon" target needs the per-weapon pass
                # (where attackType and the like are static, decided
                # against the real weapon) - so it runs in both.
                if (etype in _WEAPON_FREE_EFFECTS and etype != "setKeyword") \
                        or etype not in EFFECT_APPLIERS:
                    continue
                env = Env(view, defender, context, role,
                          model=model, weapon=weapon)
                active, prefixes = _eval_conditions(ab, env)
                if active:
                    _apply_ops(EFFECT_APPLIERS[etype](eff.get("data", {}),
                                                      env),
                               prefixes, weapon, model, view, deltas)

    # Manual context characteristic modifiers (ctx.char_mods =
    # {'weapon': {attr: +/-N}, 'attacker_model': {...},
    # 'defender_model': {...}}) enter the SAME accumulator as ability
    # deltas, so the characteristic cap applies to the joint net
    # modifier. Weapon mods affect the attacker view; model mods affect
    # the view matching their role.
    env_ctx = context if context is not None else Context()
    cmods = getattr(env_ctx, "char_mods", None) or {}
    if role == "attacker":
        for attr, n in (cmods.get("weapon") or {}).items():
            for model in all_models:
                for weapon in model.weapons:
                    real = attr
                    if attr in ("BS", "WS"):
                        if (attr == "BS") != (weapon.type == "Ranged"):
                            continue
                        real = "_skill"
                    deltas[(id(weapon), real)] = \
                        deltas.get((id(weapon), real), 0) + n
    model_mods = cmods.get(f"{role}_model") or {}
    for attr, n in model_mods.items():
        for model in all_models:
            ch = getattr(model, attr, None)
            if isinstance(ch, Characteristic):
                setattr(model, attr,
                        _floor_char(attr, ch.with_delta(n)))

    # Apply the accumulated characteristic deltas. Characteristic
    # modifiers are NOT capped in 11th ed. - only the hit and wound ROLL
    # modifiers are (see rules_config) - so the net delta applies in
    # full and only the absolute limits bound the result.
    for model in view.models():
        for weapon in model.weapons:
            for attr in set(a for (wid, a) in deltas if wid == id(weapon)):
                floor_key = "BS" if attr == "_skill" else attr
                setattr(weapon, attr,
                        _floor_char(floor_key,
                                    getattr(weapon, attr).with_delta(
                                        deltas[(id(weapon), attr)])))
    return view
