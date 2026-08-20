"""Analyzer core: glue between the object model / modifier engine and
the exact attack mathematics. GUI-free and fully testable headless.

Flow:
  aview, dview = build_views(attacker, defender, flags)
  opts = reference_options(dview)        # one entry per distinct
                                         # defensive profile; the
                                         # analyzer reports them
                                         # all, the game assistant
                                         # asks which one to use
  sugg = suggested_references(dview, opts)  # advisory: the profile the
                                         # rules fix for the wound roll
  results = run_analysis(aview, dview, ref, flags, mode, melee, manual)
"""

import re

from modifier_engine import Context
import attack_math as am


def _is_led(unit) -> bool:
    """True when a CHARACTER is attached to this unit, which is what the
    leaderAttached condition asks about. Both slots count: a Support
    character (an Ancient, an Apothecary, a Pack Leader) is a CHARACTER
    joining the unit exactly like a Leader, and build_view already
    applies its leader effects the same way."""
    return bool(getattr(unit, "attached_leaders", None)
                or getattr(unit, "attached_supports", None))


def build_views(attacker, defender, flags: dict, mods: dict = None):
    """Build attacker/defender combat views from context flags and
    manual modifiers. mods = {'rolls': {hit|wound|save|invuln|fnp: +/-N},
    'weapon': {attr: +/-N}, 'attacker_model': {attr: +/-N},
    'defender_model': {attr: +/-N}} ('model' accepted as legacy alias of
    'defender_model'). Every entry is also stored on the Context object
    (roll_mods / char_mods), so the unit and attack libraries enforce
    the global caps independently."""
    mods = mods or {}
    ctx = Context(range_half=flags.get("half_range"),
                  attacker_stationary=flags.get("attacker_stationary"),
                  attacker_charged=flags.get("charged"),
                  defender_in_cover=flags.get("cover"),
                  attacker_below_half=flags.get("attacker_below_half"),
                  defender_below_half=flags.get("defender_below_half"),
                  defender_below_full=flags.get("defender_below_full"),
                  attacker_below_full=flags.get("attacker_below_full"),
                  attacker_on_objective=flags.get("attacker_on_objective"),
                  defender_on_objective=flags.get("defender_on_objective"),
                  attacker_in_engagement=flags.get("attacker_in_engagement"),
                  defender_in_engagement=flags.get("defender_in_engagement"),
                  # Not a user flag: whether a unit is being led is known
                  # from the unit itself (a combined unit carries its
                  # leader), so the leaderAttached condition is decided
                  # automatically.
                  attacker_has_leader=_is_led(attacker),
                  defender_has_leader=_is_led(defender),
                  roll_mods=dict(mods.get("rolls") or {}),
                  reroll_mods=dict(mods.get("rerolls") or {}),
                  char_mods={
                      "weapon": dict(mods.get("weapon") or {}),
                      "attacker_model": dict(mods.get("attacker_model")
                                             or {}),
                      "defender_model": dict(mods.get("defender_model")
                                             or mods.get("model") or {})})
    aview = attacker.against(defender, ctx, role="attacker")
    dview = defender.against(attacker, ctx, role="defender")
    return aview, dview


def _ref_key(ref):
    """Dedup/comparison key of a reference profile: the characteristics
    and keywords that change the attack maths."""
    return (ref["T"], ref["Sv"], ref["W"], ref["invuln"], ref["fnp"],
            frozenset(ref["keywords"]))


def _model_ref(model, dview, n_models):
    """(label, ref) for one model group of the defender view.
    Defender keywords for ANTI-X N+: the model's EFFECTIVE keywords
    (inherited unit keywords + the model's own, minus '-TOKEN'
    suppressions), using the CURRENT unit-view keywords as the base so
    combat-time modifications (setKeyword) are reflected."""
    kws = {str(k).strip().upper()
           for k in model.effective_keywords(dview.keywords)}
    ref = {"T": model.T.value(), "Sv": model.Sv.value(),
           "W": model.W.value(), "invuln": model.invuln,
           "fnp": model.fnp, "models": n_models, "keywords": kws}
    inv = f" inv{ref['invuln']}+" if ref["invuln"] else ""
    fnp = f" fnp{ref['fnp']}+" if ref["fnp"] else ""
    return (f"{model.name}  (T{ref['T']} Sv{ref['Sv']}+ "
            f"W{ref['W']}{inv}{fnp})", ref)


def reference_options(dview):
    """Distinct defensive profiles in the defender unit:
    [(label, ref_dict)]. One entry -> no popup needed. Each distinct
    defensive profile (stats + keywords) yields one reference."""
    seen, out = set(), []
    n_models = sum(m.model_count for m in dview.models())
    for m in dview.models():
        label, ref = _model_ref(m, dview, n_models)
        key = _ref_key(ref)
        if key in seen:
            continue
        seen.add(key)
        out.append((label, ref))
    return out


def suggested_references(dview, opts=None):
    """Indices in 'opts' of the profile(s) the rules prescribe for the
    WOUND roll: the highest Toughness among the unit's BODYGUARD models
    (its own models, ignoring an attached leader or support), or among
    all models when nothing is attached. More than one index comes back
    when several bodyguard profiles share that Toughness - they differ
    in save/wounds only, which the rules settle when the attack is
    allocated, not when the target is selected. Empty set if unknown.

    Advisory only: the caller still lets the user pick any profile.
    """
    opts = reference_options(dview) if opts is None else opts
    n_models = sum(m.model_count for m in dview.models())
    getter = getattr(dview, "bodyguard_models", None)
    pool = list(getter()) if getter is not None else list(dview.models())
    pool = pool or list(dview.models())
    tough = {}
    for m in pool:
        _label, ref = _model_ref(m, dview, n_models)
        t = ref["T"] if isinstance(ref["T"], (int, float)) else None
        if t is None:
            continue
        key = _ref_key(ref)
        tough[key] = max(t, tough.get(key, t))
    if not tough:
        return set()
    best = max(tough.values())
    wanted = {k for k, t in tough.items() if t == best}
    return {i for i, (_label, ref) in enumerate(opts)
            if _ref_key(ref) in wanted}


INDIRECT_SKIP = "inapplicable due to indirect fire"
CQ_BLAST_SKIP = "BLAST cannot target an engaged unit"
CQ_NOT_CQ_SKIP = "not a CLOSE-QUARTERS weapon"
CQ_ONLY_SKIP = "CLOSE-QUARTERS: fires only in close quarters"
DISABLED_SKIP = "unusable in this attack setup"
ZERO_COUNT_SKIP = "count set to 0"
_DISABLED = "WEAPON_DISABLED"


def hunter_skip_reason(mech, dview):
    """Why a HUNTER X weapon may not fire at this target, or None.
    HUNTER X weapons may only be shot at units with keyword X. The check
    lives here rather than in select_weapons_split because the
    restriction can also be GRANTED by an ability (a 'HUNTER X' effect
    string), which is only known once the mechanics are built."""
    if not mech.hunter:
        return None
    target = {str(k).strip().upper() for k in (dview.keywords or ())}
    if target & set(mech.hunter):
        return None
    return ("HUNTER-" + "/".join(mech.hunter)
            + ": the target does not have that keyword")
CQ_KEYWORDS = {"MONSTER", "VEHICLE"}
# PISTOL is the 10th-ed. spelling of CLOSE-QUARTERS: rosters fetched
# before the rename still carry it, so both are accepted everywhere.
CLOSE_QUARTERS_KW = {"CLOSE-QUARTERS", "CLOSE QUARTERS", "PISTOL"}


def close_quarters_attacker(aview) -> bool:
    """True when the attacking unit is a MONSTER or a VEHICLE, which is
    what decides the close-quarters shooting rule: those models may fire
    everything (at -1 to hit unless the weapon is CLOSE-QUARTERS, and
    never with BLAST), everyone else may fire CLOSE-QUARTERS weapons
    only."""
    return bool({str(k).strip().upper()
                 for k in (aview.keywords or ())} & CQ_KEYWORDS)


def ability_selection(flags: dict) -> dict:
    """The attack-setup ability selection carried in the flags dict:
    {'extra': [...], 'disabled': [...], 'optimise': bool}. 'optimise'
    defaults to True - where the rules leave a real choice (Lethal Hits
    is optional in 11th ed.) the better side is taken and reported;
    switch it off to follow the selection literally."""
    flags = flags or {}
    return {"extra": list(flags.get("extra_abilities") or []),
            "disabled": list(flags.get("disabled_abilities") or []),
            "optimise": flags.get("optimise_abilities", True)}


def select_weapons(aview, mode: str, melee_name: str = None,
                   indirect: bool = False):
    """Weapons taking part in the attack.
    mode 'ranged'        : every Ranged weapon, minus the CLOSE-QUARTERS
                           ones unless the unit is a MONSTER/VEHICLE;
    mode 'close_quarters': shooting at a unit the attacker is engaged
                           with (11th ed.) - see select_weapons_split;
    mode 'melee'         : the chosen weapon plus EXTRA ATTACKS melee
                           weapons.

    With indirect=True the unit is using the 11th-ed. indirect shooting
    mode: ONLY weapons with the INDIRECT FIRE keyword are fired. The
    others are not silently dropped - see select_weapons_split."""
    kept, _skipped = select_weapons_split(aview, mode, melee_name, indirect)
    return kept


def select_weapons_split(aview, mode: str, melee_name: str = None,
                         indirect: bool = False):
    """(kept, skipped) where 'skipped' is [(weapon, reason)] - weapons
    that would normally take part but are excluded by the attack setup,
    so the caller can show them greyed out instead of hiding them.

    In 'close_quarters' mode the unit is shooting the enemy unit it is
    engaged with. A MONSTER or VEHICLE attacker fires everything except
    BLAST weapons (which may never target an engaged unit); any other
    attacker may only fire CLOSE-QUARTERS weapons - PISTOL counts as the
    same keyword (see CLOSE_QUARTERS_KW). Whether the unit is really
    engaged is the user's call - the program cannot see the table.

    The restriction runs the other way too: a model that is not a
    MONSTER/VEHICLE must choose between its CLOSE-QUARTERS weapons and
    its other ranged weapons, so in the plain 'ranged' mode its
    CLOSE-QUARTERS weapons stay silent. MONSTER/VEHICLE models are
    exempt and fire everything.

    Keyword matching is case-insensitive throughout: rosters spell the
    same keyword as 'Pistol', 'PISTOL' or 'pistol' depending on where
    they were fetched from."""
    kept, skipped = [], []
    cq = mode == "close_quarters"
    # A weapon switched off by an ability (disableWeapon) is reported,
    # not silently dropped - same treatment as indirect fire and close
    # quarters. Only the UNCONDITIONAL form counts: a roll-time
    # condition cannot decide whether a weapon is fired.
    big = close_quarters_attacker(aview)
    for model in aview.models():
        for w in model.weapons:
            kw = {str(k).strip().upper() for k in w.keywords}
            is_cq = bool(kw & CLOSE_QUARTERS_KW)
            if mode == "ranged" and w.type == "Ranged":
                if is_cq and not big:
                    skipped.append((w, CQ_ONLY_SKIP))
                    continue
            elif cq and w.type == "Ranged":
                if big and "BLAST" in kw:
                    skipped.append((w, CQ_BLAST_SKIP))
                    continue
                if not big and not is_cq:
                    skipped.append((w, CQ_NOT_CQ_SKIP))
                    continue
            elif mode == "melee" and w.type == "Melee" \
                    and (w.name == melee_name or "EXTRA ATTACKS" in kw):
                pass
            else:
                continue
            if (w.count or 0) <= 0:
                # Count 0 = weapon switched off by the user (inspect
                # window): reported like any other exclusion, not hidden.
                skipped.append((w, ZERO_COUNT_SKIP))
            elif _DISABLED in (w.effects or ()):
                skipped.append((w, DISABLED_SKIP))
            elif indirect and w.type == "Ranged" \
                    and "INDIRECT FIRE" not in kw:
                skipped.append((w, INDIRECT_SKIP))
            else:
                kept.append(w)
    return kept, skipped


def mechanics_for_attack(weapon, dview, attack_type, manual, flags=None,
                         aview=None):
    """Public wrapper of _mechanics_for that also applies the attack-setup
    ability selection carried in 'flags' (used by the game assistant,
    which resolves weapons one by one with the dice engine). Pass 'aview'
    so the attacker's own unit-level effect strings are seen too."""
    return _mechanics_for(weapon, dview, attack_type, manual,
                          ability_selection(flags), aview)


def melee_choices(aview):
    """Names of melee weapons selectable as the main fight weapon."""
    return sorted({w.name for m in aview.models() for w in m.weapons
                   if w.type == "Melee" and (w.count or 0) > 0
                   and "EXTRA ATTACKS" not in {str(k).strip().upper()
                                               for k in w.keywords}})


# Tokens an ATTACKER's unit-level effect string may carry. Most unit
# abilities reach the weapons directly (they are applied per weapon, so
# they land in weapon.effects); what stays on the attacker's unit view is
# the weapon-free vocabulary, and of that only DISABLE means anything for
# our own attacks. The rest of that vocabulary (FNP, invulnerable saves,
# Damage reduction) is defender-side and is read from dview.effects, so
# it must NOT be picked up here - it would hand the DEFENDER an ability
# the attacker declared.
_ATTACKER_UNIT_TOKENS = ("DISABLE",)


def _attacker_unit_effects(effects):
    """The attacker's unit-level effect strings that apply to its own
    attacks (see _ATTACKER_UNIT_TOKENS)."""
    out = []
    for raw in effects or ():
        body = str(raw).split(":")[-1].strip()
        if body.split(" ")[0] in _ATTACKER_UNIT_TOKENS:
            out.append(raw)
    return out


_RE_SUFFIX = re.compile(r"\s*\[[^\]]*\]\s*$")


def _key_of(value, default=""):
    """The 'key' of a CHOICE field, which is stored as {title, key}."""
    if isinstance(value, dict):
        value = value.get("key")
    return str(value or default).strip().lower()


def _iter_view_abilities(aview):
    """(scope label, ability dict) for every ability of an attacker view,
    whatever its scope - the checks below are unit-wide."""
    for ab in getattr(aview, "abilities", None) or ():
        yield ("unit", ab)
    for model in aview.models():
        for ab in getattr(model, "abilities", None) or ():
            yield (f"model {model.name}", ab)
        for weapon in model.weapons:
            for ab in getattr(weapon, "abilities", None) or ():
                yield (f"weapon {weapon.name}", ab)


def exclusive_group_notes(aview) -> list:
    """Check the "select one of the following" ability groups.

    A datasheet that says "select one weapon" or "select one of the
    following" is modelled as several switched-off copies of the
    ability, one per choice, all carrying the same 'exclusive_group'
    label. Nothing stops the player ticking two, so this counts what is
    on and warns - the engine cannot pick for them.
    """
    counts = {}
    for scope, ab in _iter_view_abilities(aview):
        group = str(ab.get("exclusive_group") or "").strip()
        if not group or not ab.get("enabled", True):
            continue
        # Copies of one choice often share a name and differ only by the
        # weapon they sit on (Nova Charge), so the scope is what tells
        # them apart in the message.
        name = ab.get("name") or group
        counts.setdefault(group, []).append(
            name if name != group and scope == "unit"
            else f"{name} ({scope})")
    notes = []
    for group, picked in sorted(counts.items()):
        if len(picked) > 1:
            notes.append(
                f"{group}: {len(picked)} choices are enabled "
                f"({', '.join(sorted(picked))}), but only ONE of them "
                f"applies - switch off the others.")
    return notes


def single_reroll_notes(aview) -> list:
    """Check how the unit spends its 'one re-roll per activation'
    abilities (singleReRoll).

    The rule allows ONE re-roll for the whole activation, but the
    ability sits on the weapons - one disabled copy per candidate - so
    nothing stops the player ticking two. This counts what is switched
    on, per datasheet ability, and says what is wrong:

      * allowance 'exclusive' (hit OR wound): more than one on at all;
      * allowance 'eachKind'  (hit AND wound): more than one of a kind
        on, or a kind left unused when it was available.

    Returns a list of strings for the analysis warnings.
    """
    found = {}                      # ability name -> {kind: [enabled...]}
    allowance = {}
    for model in aview.models():
        for weapon in model.weapons:
            for ab in getattr(weapon, "abilities", None) or ():
                eff = ab.get("effect") or {}
                if eff.get("type") != "singleReRoll":
                    continue
                data = eff.get("data", {})
                # Copies of one datasheet ability are named "<name>
                # [hit roll]" / "[wound roll]" per weapon: the budget
                # belongs to the datasheet ability, so group on the
                # base name.
                name = _RE_SUFFIX.sub(
                    "", ab.get("name") or "Single re-roll").strip()
                kind = _key_of(data.get("roll"), "hit")
                allowance[name] = _key_of(data.get("allowance"),
                                          "exclusive")
                found.setdefault(name, {}).setdefault(kind, []).append(
                    bool(ab.get("enabled", True)))

    notes = []
    for name, kinds in sorted(found.items()):
        on = {k: sum(1 for e in v if e) for k, v in kinds.items()}
        total = sum(on.values())
        if allowance.get(name) == "eachkind":
            # Nothing enabled at all: the player simply is not using the
            # ability, which is not a mistake worth a warning.
            for kind, n in (sorted(on.items()) if total else ()):
                if n > 1:
                    notes.append(
                        f"{name}: {n} {kind}-roll re-rolls are enabled "
                        f"across this unit's weapons; the rule allows "
                        f"one - switch off all but the weapon you want.")
                elif n == 0:
                    notes.append(
                        f"{name}: no {kind}-roll re-roll is enabled, but "
                        f"this ability grants one of EACH kind - you can "
                        f"also enable one {kind}-roll re-roll on a "
                        f"weapon.")
        elif total > 1:
            picked = ", ".join(f"{n}x {k}" for k, n in sorted(on.items())
                               if n)
            notes.append(
                f"{name}: {total} re-rolls are enabled across this "
                f"unit's weapons ({picked}), but the rule allows only "
                f"ONE, of either kind - switch off all but one.")
    return notes


def _mechanics_for(weapon, dview, attack_type, manual, abilities=None,
                   aview=None):
    """Weapon mechanics for one attack. 'abilities' is the attack-setup
    ability selection: {'extra': [tokens added to EVERY attack],
    'disabled': [abilities switched off]}. Extras are added first and
    can then be switched off like any datasheet ability."""
    mech = am.WeaponMechanics()
    am.parse_weapon_keywords(weapon.keywords, mech)
    am.parse_effect_strings(weapon.effects, attack_type, mech, weapon)
    am.parse_effect_strings(dview.effects, attack_type, mech, weapon)
    if aview is not None:
        am.parse_effect_strings(_attacker_unit_effects(aview.effects),
                                attack_type, mech, weapon)
    abilities = abilities or {}
    am.add_abilities(mech, abilities.get("extra"))
    am.disable_abilities(mech, abilities.get("disabled"),
                         lambda m: mech.warnings.append(m))
    rolls = (manual or {}).get("rolls") or {}
    mech.hit_mod += rolls.get("hit", 0)
    mech.wound_mod += rolls.get("wound", 0)
    mech.save_mod += rolls.get("save", 0)
    mech.invuln_mod += rolls.get("invuln", 0)
    mech.fnp_mod += rolls.get("fnp", 0)
    rr = (manual or {}).get("rerolls") or {}
    mech.reroll_hit = am.combine_reroll(mech.reroll_hit, rr.get("hit"))
    mech.reroll_wound = am.combine_reroll(mech.reroll_wound,
                                          rr.get("wound"))
    mech.reroll_save = am.combine_reroll(mech.reroll_save, rr.get("save"))
    mech.reroll_invuln = am.combine_reroll(mech.reroll_invuln,
                                           rr.get("invuln"))
    mech.reroll_fnp = am.combine_reroll(mech.reroll_fnp, rr.get("fnp"))
    return mech


def run_analysis(aview, dview, ref: dict, flags: dict, mode: str,
                 melee_name: str = None, manual: dict = None) -> dict:
    """Analyze every selected weapon; returns
    {'weapons': [per-weapon dicts], 'totals': {...}, 'warnings': [...]}.
    manual = {'rolls': {...}} roll modifiers (characteristic modifiers
    are already baked into the views by build_views via the Context).
    A HAZARDOUS weapon is analysed once, exactly as the roster lists it,
    with the mean self-damage attached (its median is 0 and is not
    reported): datasheets already carry the two profiles as two separate
    weapons ("standard" and "supercharge"/"overcharge"), and the boosted
    one IS the one flagged HAZARDOUS - so recomputing the boost here
    would apply it twice. Which profile to fire stays the player's
    choice: both are listed.
    'skipped' lists the weapons excluded by the attack setup (indirect
    fire), so the caller can show them greyed out with the reason."""
    manual = manual or {}
    attack_type = "Melee" if mode == "melee" else "Ranged"
    haz_damage = am.hazardous_damage_per_fail(aview.keywords)
    # ctx keys are attacker-side by nature, so they carry no side
    # prefix; the FLAG behind this one does (attacker_stationary), to
    # pair with defender_stationary.
    ctx = {"half_range": flags.get("half_range"),
           "stationary": flags.get("attacker_stationary"),
           "charged": flags.get("charged"),
           "cover": flags.get("cover"),
           "plunging": flags.get("plunging"),
           "damaged": flags.get("damaged"),
           "indirect": flags.get("indirect"),
           "spotter": flags.get("spotter"),
           "overwatch": flags.get("overwatch"),
           "overwatch_value": flags.get("overwatch_value"),
           "close_quarters_penalty": (mode == "close_quarters"
                                      and close_quarters_attacker(aview))}
    # How the unit spends its "one re-roll per activation" abilities:
    # they live on the weapons, so the count is a unit-wide check.
    rows, warnings = [], (list(single_reroll_notes(aview))
                          + list(exclusive_group_notes(aview)))
    gross, net = am.delta(0), am.delta(0)
    kept, skipped = select_weapons_split(aview, mode, melee_name,
                                         bool(flags.get("indirect")))
    abilities = ability_selection(flags)
    optimise = abilities.get("optimise", True)
    for w in kept:
        mech = _mechanics_for(w, dview, attack_type, manual, abilities,
                              aview)
        why = hunter_skip_reason(mech, dview)
        if why:
            skipped.append((w, why))
            continue
        label = w.name
        selfdmg = (am.hazardous_self_damage_mean(w.count, haz_damage)
                   if mech.hazardous else None)
        if optimise:
            res, note = am.analyze_weapon_best(w, ref, ctx, mech)
        else:
            res, note = am.analyze_weapon(w, ref, ctx, mech), None
        if note:
            label = f"{label}  [{note}]"
        rows.append({"name": label, "count": w.count,
                     "attacks": res["attacks"],
                     "wounds": res["wounds"],
                     "damage": res["damage"],
                     "damage_net": res["damage_net"],
                     "self_damage_mean": selfdmg})
        warnings += [f"{label}: {x}" for x in res["warnings"]]
        gross = am.convolve(gross, res["damage_pmf"])
        net = am.convolve(net, res["damage_net_pmf"])
    return {"weapons": rows,
            "skipped": [{"name": w.name, "count": w.count, "reason": why}
                        for w, why in skipped],
            "totals": {"damage": am.pmf_stats(gross),
                       "damage_net": am.pmf_stats(net),
                       "damage_pmf": gross, "damage_net_pmf": net},
            "warnings": sorted(set(warnings))}
