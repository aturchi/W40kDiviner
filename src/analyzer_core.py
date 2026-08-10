"""Analyzer core: glue between the object model / modifier engine and
the exact attack mathematics. GUI-free and fully testable headless.

Flow:
  aview, dview = build_views(attacker, defender, flags)
  opts = reference_options(dview)        # >1 -> ask the user to pick
  results = run_analysis(aview, dview, ref, flags, mode, melee, manual)
"""

import copy

from modifier_engine import Context
import attack_math as am


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
                  attacker_stationary=flags.get("stationary"),
                  attacker_charged=flags.get("charged"),
                  defender_in_cover=flags.get("cover"),
                  attacker_below_half=flags.get("attacker_below_half"),
                  defender_below_half=flags.get("defender_below_half"),
                  defender_below_full=flags.get("defender_below_full"),
                  attacker_below_full=flags.get("attacker_below_full"),
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


def reference_options(dview):
    """Distinct defensive profiles in the defender unit:
    [(label, ref_dict)]. One entry -> no popup needed."""
    seen, out = set(), []
    n_models = sum(m.model_count for m in dview.models())
    # Defender keywords for ANTI-X N+: the model's EFFECTIVE keywords
    # (inherited unit keywords + the model's own, minus '-TOKEN'
    # suppressions), using the CURRENT unit-view keywords as the base so
    # combat-time modifications (setKeyword) are reflected. Each distinct
    # defensive profile (stats + keywords) yields one reference.
    for m in dview.models():
        kws = {k.upper() for k in m.effective_keywords(dview.keywords)}
        ref = {"T": m.T.value(), "Sv": m.Sv.value(), "W": m.W.value(),
               "invuln": m.invuln, "fnp": m.fnp, "models": n_models,
               "keywords": kws}
        key = (ref["T"], ref["Sv"], ref["W"], ref["invuln"], ref["fnp"],
               frozenset(kws))
        if key in seen:
            continue
        seen.add(key)
        inv = f" inv{ref['invuln']}+" if ref["invuln"] else ""
        fnp = f" fnp{ref['fnp']}+" if ref["fnp"] else ""
        out.append((f"{m.name}  (T{ref['T']} Sv{ref['Sv']}+ "
                    f"W{ref['W']}{inv}{fnp})", ref))
    return out


def select_weapons(aview, mode: str, melee_name: str = None):
    """Weapons taking part in the attack.
    mode 'ranged': all Ranged weapons except PISTOL;
    mode 'pistol': only PISTOL weapons;
    mode 'melee' : the chosen weapon plus EXTRA ATTACKS melee weapons."""
    out = []
    for model in aview.models():
        for w in model.weapons:
            kw = {k.upper() for k in w.keywords}
            if mode == "ranged" and w.type == "Ranged" \
                    and "PISTOL" not in kw:
                out.append(w)
            elif mode == "pistol" and w.type == "Ranged" \
                    and "PISTOL" in kw:
                out.append(w)
            elif mode == "melee" and w.type == "Melee" \
                    and (w.name == melee_name or "EXTRA ATTACKS" in kw):
                out.append(w)
    return out


def melee_choices(aview):
    """Names of melee weapons selectable as the main fight weapon."""
    return sorted({w.name for m in aview.models() for w in m.weapons
                   if w.type == "Melee"
                   and "EXTRA ATTACKS" not in {k.upper()
                                               for k in w.keywords}})


def _hazardous_variant(weapon):
    """Copy of the weapon with +1 S, +1 AP, +1 D (supercharged use)."""
    v = copy.copy(weapon)
    v.S = weapon.S.with_delta(1)
    v.AP = weapon.AP.with_delta(-1)   # AP improves (datasheet negative)
    v.D = weapon.D.with_delta(1)
    return v


def _mechanics_for(weapon, dview, attack_type, manual):
    mech = am.WeaponMechanics()
    am.parse_weapon_keywords(weapon.keywords, mech)
    am.parse_effect_strings(weapon.effects, attack_type, mech, weapon)
    am.parse_effect_strings(dview.effects, attack_type, mech, weapon)
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
    HAZARDOUS weapons get a second entry with the +1S/-1AP/+1D profile
    and the mean self-damage (its median is 0 and is not reported)."""
    manual = manual or {}
    attack_type = "Melee" if mode == "melee" else "Ranged"
    haz_damage = am.hazardous_damage_per_fail(aview.keywords)
    ctx = {"half_range": flags.get("half_range"),
           "stationary": flags.get("stationary"),
           "charged": flags.get("charged"),
           "cover": flags.get("cover"),
           "plunging": flags.get("plunging"),
           "damaged": flags.get("damaged")}
    rows, warnings = [], []
    gross, net = am.delta(0), am.delta(0)
    for w in select_weapons(aview, mode, melee_name):
        mech = _mechanics_for(w, dview, attack_type, manual)
        variants = [(w.name, w, None)]
        if mech.hazardous:
            variants.append((f"{w.name} [HAZARDOUS]",
                             _hazardous_variant(w),
                             am.hazardous_self_damage_mean(w.count,
                                                           haz_damage)))
        for i, (label, wv, selfdmg) in enumerate(variants):
            res = am.analyze_weapon(wv, ref, ctx, mech)
            rows.append({"name": label, "count": wv.count,
                         "attacks": res["attacks"],
                         "wounds": res["wounds"],
                         "damage": res["damage"],
                         "damage_net": res["damage_net"],
                         "self_damage_mean": selfdmg})
            warnings += [f"{label}: {x}" for x in res["warnings"]]
            if i == 0:      # totals use the NORMAL profile only
                gross = am.convolve(gross, res["damage_pmf"])
                net = am.convolve(net, res["damage_net_pmf"])
    return {"weapons": rows,
            "totals": {"damage": am.pmf_stats(gross),
                       "damage_net": am.pmf_stats(net),
                       "damage_pmf": gross, "damage_net_pmf": net},
            "warnings": sorted(set(warnings))}
