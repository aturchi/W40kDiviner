"""Exact analytic attack mathematics.

Computes the EXACT probability distribution (PMF) of the outcome of a
shooting/fight sequence, by composing the per-attack outcome tree and
convolving over the number of attacks. No Monte Carlo is involved;
medians and any percentile are read off the exact CDF. The dice engine
(attack_resolve) is used by the game assistant to roll real attacks, and
in the test suite as a cross-validation oracle: tests/test_mc_parity.py
sweeps every mechanic and compares this PMF with the sampled one, mean
and whole distribution, within a tolerance derived from the exact
variance (tests/mc_support.py). That proves the two engines AGREE; the
rules-level checks, against values worked out in closed form, live in
test_critical_triggers, test_modifier_caps, test_fnp_and_mortals,
test_indirect_fire and test_close_quarters.

Scope (agreed simplifications): no model removal tracking, a single
defender reference model (T, Sv, W, invuln, fnp), gross damage as the
primary metric plus net damage (each unsaved wound capped at W).

Policies (documented, they affect results): re-rolls are applied to
failed dice only (no fishing for crits); crits happen on unmodified 6.

PMFs are lists of floats indexed by the integer outcome value.
"""

import re

import rules_config
from characteristics import Characteristic

# ---------------- PMF utilities ----------------


def delta(v: int) -> list:
    """A probability mass function (list indexed by value) that is 1.0 at v and 0 elsewhere - the identity element for convolve."""
    out = [0.0] * (v + 1)
    out[v] = 1.0
    return out


def convolve(a: list, b: list) -> list:
    """Convolve two probability mass functions into the pmf of the sum of the two independent variables."""
    out = [0.0] * (len(a) + len(b) - 1)
    for i, pa in enumerate(a):
        if pa:
            for j, pb in enumerate(b):
                if pb:
                    out[i + j] += pa * pb
    return out


def mix(pairs) -> list:
    """Weighted mixture of PMFs: pairs = [(weight, pmf), ...]."""
    n = max(len(p) for _w, p in pairs)
    out = [0.0] * n
    for w, p in pairs:
        for i, v in enumerate(p):
            out[i] += w * v
    return out


def pmf_stats(pmf: list) -> dict:
    """Summary stats (mean, median) of a probability mass function given as a list indexed by value."""
    mean = sum(i * p for i, p in enumerate(pmf))
    cdf, median = 0.0, 0
    for i, p in enumerate(pmf):
        cdf += p
        if cdf >= 0.5 - 1e-12:
            median = i
            break
    return {"mean": mean, "median": median}


def char_pmf(c: Characteristic) -> list:
    """PMF of a characteristic value (dice convolved, flat shifted)."""
    if c.is_none():
        return delta(0)
    out = delta(max(c.flat, 0))           # negative flats clipped at 0
    die = [0.0] + [1.0 / c.sides] * c.sides if c.count else None
    for _ in range(c.count):
        out = convolve(out, die)
    return out


def transform(pmf: list, fn) -> list:
    """PMF of fn(X) for integer-valued fn."""
    vals = {}
    for i, p in enumerate(pmf):
        if p:
            vals[fn(i)] = vals.get(fn(i), 0.0) + p
    out = [0.0] * (max(vals) + 1)
    for v, p in vals.items():
        out[v] = p
    return out


def binomial_thin(pmf: list, p_keep: float) -> list:
    """PMF of Binomial(X, p_keep) when X ~ pmf (per-point FNP)."""
    if p_keep >= 1.0:
        return list(pmf)
    from math import comb
    out = [0.0] * len(pmf)
    for n, pn in enumerate(pmf):
        if pn:
            for k in range(n + 1):
                out[k] += pn * comb(n, k) * p_keep ** k \
                    * (1 - p_keep) ** (n - k)
    return out


# ---------------- joint allocation PMFs ----------------
# Working out how many MODELS an attack kills needs more than the total
# damage, because damage is allocated one EVENT at a time and capped by
# the wounds left on the model it lands on: three hits of 2 damage are
# not one hit of 6. So an attack is described by three numbers.
#
#   AX_NORM  how many ordinary damage events it produced;
#   AX_DEV   how many events came from DEVASTATING WOUNDS. These ARE
#            mortal wounds - every ability keyed on mortal wounds bites
#            on them - but they are allocated like ordinary damage and
#            do NOT spill, so they are counted apart only because the
#            mortal-wound abilities can give them a different damage
#            law from the ordinary events;
#   AX_POOL  mortal wounds that DO spill, in damage points. They are
#            pooled and spent at the end of the whole activation.
#
# The three are correlated inside a single attack (one critical wound
# can yield mortal wounds AND ordinary extra hits), so they travel
# together as a joint distribution {(norm, dev, pool): p}. Most weapons
# need none of this: when the devastating events follow the same law as
# the ordinary ones and nothing spills, the plain event count is
# enough, and the 'wounds' chain already computes it.
AX_NORM, AX_DEV, AX_POOL = 0, 1, 2
_AXES = 3


def jdelta(norm: int = 0, dev: int = 0, pool: int = 0) -> dict:
    """Joint PMF with all its mass on one (norm, dev, pool) triple."""
    return {(norm, dev, pool): 1.0}


def jleaf(pmf: list, axis: int) -> dict:
    """A one-dimensional PMF seen as a joint one, all of it on one
    axis (AX_NORM, AX_DEV or AX_POOL)."""
    out = {}
    for v, p in enumerate(pmf):
        if p:
            key = [0] * _AXES
            key[axis] = v
            out[tuple(key)] = out.get(tuple(key), 0.0) + p
    return out


def jmix(pairs) -> dict:
    """Weighted mixture of joint PMFs: pairs = [(weight, jpmf), ...]."""
    out = {}
    for w, j in pairs:
        if not w:
            continue
        for k, p in j.items():
            out[k] = out.get(k, 0.0) + w * p
    return out


def jconvolve(a: dict, b: dict, eps: float = 1e-15) -> dict:
    """Joint PMF of the componentwise sum of two independent joint
    variables. Masses below eps are dropped: the support of a joint PMF
    grows as the product of the two supports, and the tails that matter
    to a kill count are never that thin."""
    out = {}
    for ka, pa in a.items():
        if pa < eps:
            continue
        for kb, pb in b.items():
            v = pa * pb
            if v >= eps:
                k = tuple(x + y for x, y in zip(ka, kb))
                out[k] = out.get(k, 0.0) + v
    return out


_JZERO = (0,) * _AXES


def jno_fail(j: dict, pf: float) -> dict:
    """'j' conditioned on this attack's die NOT failing: the failed
    branch contributes nothing, so it is the mass pf sitting on the
    all-zero key. Remove it, renormalise."""
    out = dict(j)
    out[_JZERO] = max(0.0, out.get(_JZERO, 0.0) - pf)
    scale = 1.0 - pf
    return {k: v / scale for k, v in out.items() if v}


# ---------------- d6 roll probabilities ----------------


def combine_reroll(a, b):
    """Strongest re-roll among two sources: 'fails' > '1' > None.
    Re-rolls don't stack on the same die (CAP_REROLLS limits repeats)."""
    if "fails" in (a, b):
        return "fails"
    if "1" in (a, b):
        return "1"
    return None


def roll_probs(target, mod: int, reroll: str = None, times: int = None,
               crit_on: int = 6, unmod_min: int = 1):
    """(p_success, p_crit) of one d6 roll needing 'target'+, with a net
    modifier (already capped by the caller), under 11th-ed rules:
    unmodified 1 always fails, unmodified 6 always succeeds, criticals
    on an unmodified crit_on+ (ANTI-style abilities lower it from 6)
    and a critical is automatically successful.
    reroll: None | '1' | 'fails'; times = max re-rolls per die
    (default rules_config.CAP_REROLLS). Policy: failed dice only.
    unmod_min: an UNMODIFIED result below this always fails, whatever
    the modifiers say (Indirect Fire: 6 with no spotter, 4 with one).
    It is a floor on the die, not a replacement for the roll: the
    modified result must still beat the target."""
    faces = [r for r in range(1, 7)
             if r >= unmod_min
             and (r == 6 or r >= crit_on
                  or (r > 1 and r + mod >= target))]
    p = len(faces) / 6.0
    pc = (7 - max(2, crit_on, unmod_min)) / 6.0
    if times is None:
        times = rules_config.CAP_REROLLS
    if reroll is None or times <= 0:
        return p, pc
    P = PC = 0.0
    cont = 1.0
    for _ in range(times + 1):
        P += cont * p
        PC += cont * pc
        cont *= (1.0 - p) if reroll == "fails" else 1.0 / 6.0
    return min(P, 1.0), min(PC, 1.0)


def hit_threshold_mw_probs(target, mod, reroll, thr):
    """Hit roll with a 'on unmodified thr+: mortal wounds, sequence
    ends' branch sharing the same die: returns (p_mw, p_hit). Faces
    thr..6 trigger the MW branch (including the natural 6, so no
    critical hits remain); lower faces hit normally. Re-rolls apply to
    failed dice only and may land in the MW region."""
    times = rules_config.CAP_REROLLS
    p_mw0 = (7 - max(2, thr)) / 6.0
    p_hit0 = sum(1 for r in range(2, thr)
                 if r + mod >= target) / 6.0
    p_fail0 = 1.0 - p_mw0 - p_hit0
    if reroll is None or times <= 0:
        return p_mw0, p_hit0
    P_mw = P_hit = 0.0
    cont = 1.0
    for _ in range(times + 1):
        P_mw += cont * p_mw0
        P_hit += cont * p_hit0
        cont *= p_fail0 if reroll == "fails" else 1.0 / 6.0
    return P_mw, P_hit


def wound_target(s: int, t: int) -> int:
    """The wound-roll target (2..6) for Strength s against Toughness t, per the 11th-edition wound chart."""
    if s >= 2 * t:
        return 2
    if s > t:
        return 3
    if s == t:
        return 4
    if 2 * s > t:
        return 5
    return 6


def _p_save_roll(target, mod, reroll, times):
    """P(successful save roll): no auto-success on 6 (an impossible save
    stays impossible), unmodified 1 always fails; optional re-roll."""
    if target is None:
        return 0.0
    p = sum(1 for r in range(2, 7) if r + mod >= target) / 6.0
    if reroll is None or times <= 0 or p == 0.0:
        return p
    P, cont = 0.0, 1.0
    for _ in range(times + 1):
        P += cont * p
        cont *= (1.0 - p) if reroll == "fails" else 1.0 / 6.0
    return min(P, 1.0)


def save_fail_prob(sv, ap, invuln,
                   save_mod: int = 0, invuln_mod: int = 0,
                   save_reroll: str = None, invuln_reroll: str = None) \
        -> float:
    """P(failed save). AP follows the datasheet convention (negative or
    zero, e.g. -4); the penalty is taken as abs(ap), so a mistakenly
    positive value behaves identically. Armour and invulnerable saves
    are evaluated separately (the invuln ignores AP and armour-save
    modifiers/re-rolls) and the best success probability wins; an
    unmodified 1 always fails.

    11th-ed. limits: the Sv and invulnerable CHARACTERISTICS can never be
    better than 2+, so both are clamped BEFORE AP is applied - a 1+ save
    hit by AP-1 saves on 2+, not on 1+. Save-roll modifiers are NOT
    capped (only hit and wound are), and the Benefit of Cover no longer
    improves the save: it is a -1 BS penalty applied at the hit stage."""
    times = rules_config.CAP_REROLLS
    p_arm = 0.0
    if sv is not None:
        target = rules_config.clamp_characteristic("Sv", sv) + abs(ap)
        p_arm = _p_save_roll(target, save_mod, save_reroll, times)
    if invuln is not None:
        invuln = rules_config.clamp_characteristic("invuln", invuln)
    p_inv = _p_save_roll(invuln, invuln_mod, invuln_reroll, times)
    return 1.0 - max(p_arm, p_inv)


# Characteristics of an INCOMING attack a defender ability may modify,
# mapped to the WeaponMechanics field holding the modifier. "SKILL" is
# what modifier_engine calls the BS/WS pair; a modifier to the Damage
# characteristic reuses dmg_add, which already models the fixed
# set/multiply/add order of the damage chain.
_INCOMING_CHAR_MODS = {"AP": "ap_mod", "S": "str_mod", "A": "attacks_mod",
                       "SKILL": "skill_mod", "D": "dmg_add"}


def _effective_ap(base_ap: int, mech) -> int:
    """AP of a normal attack: the weapon's value plus any defender-side
    modifier, clamped by the absolute limit (never worse than 0)."""
    return rules_config.clamp_characteristic("AP", base_ap + mech.ap_mod)


def _crit_ap(base_ap: int, mech) -> int:
    """AP on the critical-wound branch: an absolute set (crit_ap_set)
    wins over the improving delta (crit_ap_delta); the defender-side
    modifier applies on top of either, as modifiers always do."""
    ap = (mech.crit_ap_set if mech.crit_ap_set is not None
          else base_ap - abs(mech.crit_ap_delta))
    return rules_config.clamp_characteristic("AP", ap + mech.ap_mod)


def effective_fnp(defender_ref: dict, mech, mw: bool):
    """(fnp_target, roll_modifier) actually in force for one damage
    stream. Sources, in order:
      * the defender's own FNP;
      * an ability GRANTING one (mech.fnp_grant, or mech.fnp_mw for
        mortal wounds only): the BEST value wins, FNP never stacks;
      * an ability OVERRIDING it (mech.fnp_set / fnp_set_mw): forced,
        even when it is worse - 7 means "no FNP at all";
      * roll modifiers (mech.fnp_mod, plus fnp_mod_mw on mortal wounds).
    Returns (None, 0) when no FNP applies."""
    fnp = defender_ref.get("fnp")
    if mech.fnp_grant is not None:
        fnp = mech.fnp_grant if fnp is None else min(fnp, mech.fnp_grant)
    if mw and mech.fnp_mw is not None:
        fnp = mech.fnp_mw if fnp is None else min(fnp, mech.fnp_mw)
    if mech.fnp_set is not None:
        fnp = mech.fnp_set
    if mw and mech.fnp_set_mw is not None:
        fnp = mech.fnp_set_mw
    if not fnp:
        return None, 0
    mod = mech.fnp_mod + (mech.fnp_mod_mw if mw else 0)
    if "fnp" in mech.ignore_malus:
        mod = max(0, mod)
    return fnp, mod


def effective_invuln(defender_ref: dict, mech):
    """The invulnerable save in force for this attack: the defender's own,
    or one granted by an ability (mech.invuln_grant). Like Feel No Pain,
    an invulnerable save never stacks - the BEST (lowest) value wins.
    Shared by both engines so they cannot drift apart."""
    inv = defender_ref.get("invuln")
    if mech.invuln_grant is not None:
        inv = mech.invuln_grant if inv is None \
            else min(inv, mech.invuln_grant)
    return inv


def damage_reroll_range(char):
    """Which die results a free "re-roll the Damage roll" should re-roll.

    The datasheet gives no range: the player re-rolls a result only when
    the re-roll is expected to beat it, i.e. anything strictly below the
    die's mean (N+1)/2. That is 1..N//2 - for a D6, results 1-3 (a 3 is
    below the 3.5 mean, a 4 is not); for a D3, only a 1. Returns None for
    a flat Damage characteristic, where there is no roll to re-roll.
    """
    sides = getattr(char, "sides", None)
    if not getattr(char, "count", 0) or not sides:
        return None
    return (1, sides // 2)


def reroll_low_damage(pmf: list, lo: int, hi: int) -> list:
    """Damage re-roll policy: results in [lo, hi] are re-rolled once
    (CAP_REROLLS permitting). Exact PMF transform."""
    if rules_config.CAP_REROLLS <= 0:
        return list(pmf)
    mass = sum(p for v, p in enumerate(pmf) if lo <= v <= hi)
    if mass == 0.0:
        return list(pmf)
    out = [(0.0 if lo <= v <= hi else p) for v, p in enumerate(pmf)]
    return mix([(1.0, out), (mass, pmf)])


# ---------------- weapon mechanics ----------------


class WeaponMechanics:
    """Flags/values extracted from weapon keywords + ability effects."""

    def copy(self):
        """Shallow copy with the mutable containers duplicated, so a
        what-if variant cannot write back into the original."""
        other = WeaponMechanics()
        other.__dict__.update(self.__dict__)
        other.ignore_malus = set(self.ignore_malus)
        other.anti = list(self.anti)
        other.warnings = list(self.warnings)
        return other

    def __init__(self):
        self.sustained = 0          # extra hits per critical hit
        self.extra_hits = 0         # extra hits per SUCCESSFUL hit (any
        #                             hit, not just a critical one); the
        #                             bonus hits are never critical and
        #                             never generate further extras
        self.extra_wounds = 0       # extra (normal) wounds per wound
        self.extra_wounds_crit = 0  # ...and per CRITICAL wound only
        self.extra_attacks = 0      # extra attacks with this weapon
        self.lethal = False         # crit hit auto-wounds
        self.lethal_crit = False    # crit hit scores a CRITICAL wound
        self.devastating = False    # crit wound -> MW = damage (replaces)
        self.torrent = False        # auto-hit, no crits
        self.auto_hit = False       # OVERRIDE HIT ALWAYS (same as torrent)
        self.hit_unmod_only = None  # X: hits only on unmodified X+
        self.crit_wound_on = 6      # ANTI-style critical wound threshold
        self.crit_hit_on = 6        # critical HIT threshold (unmodified
        #                             N+; lowered by a criticalThreshold
        #                             ability, e.g. Conversion 4+)
        self.crit_mw = None         # {'value','match','end'} on crit wound
        self.hitroll_mw = None      # {'thr','value','match'} same-die MW
        self.crit_ap_delta = 0      # AP delta on the crit-wound branch
        self.crit_ap_set = None     # absolute AP on the crit-wound branch
        #                             (datasheet "that attack has an AP of
        #                             -N"); the strongest value wins and it
        #                             takes precedence over crit_ap_delta
        self.ap_mod = 0             # DEFENDER-side modifiers to the
        self.str_mod = 0            # characteristics of the INCOMING
        self.attacks_mod = 0        # attack ("subtract 1 from the
        self.skill_mod = 0          # Strength characteristic of that
        #                             attack", "worsen its AP by 1", ...).
        #                             They are CHARACTERISTIC modifiers, so
        #                             they are not capped, only clamped by
        #                             the absolute limits; skill_mod is a
        #                             BS/WS modifier (positive = worsened,
        #                             like the Benefit of Cover) and joins
        #                             cover/plunging fire. A modifier to
        #                             the Damage characteristic is folded
        #                             into dmg_add, which already models
        #                             the fixed set/mult/add order.
        self.cover = False          # the defender has the Benefit of Cover
        #                             from an ability (11th-ed. Stealth),
        #                             on top of any terrain cover from the
        #                             attack setup: it is the same -1 BS
        #                             and does NOT stack with it.
        self.fnp_grant = None       # FNP GRANTED by an ability (best wins)
        self.fnp_mw = None          # ...granted vs mortal wounds only
        self.fnp_set = None         # FNP OVERRIDDEN for this attack
        self.fnp_set_mw = None      # ...vs mortal wounds only
        self.fnp_mod_mw = 0         # FNP roll modifier vs mortal wounds only
        self.invuln_mw = None       # invulnerable save vs mortal wounds only
        self.invuln_grant = None    # invulnerable save granted for this
        #                             attack (best value wins, like FNP)
        self.dmg_reroll = None      # (lo, hi) damage re-roll range
        self.dmg_reroll_any = False # "you can re-roll the Damage roll"
        #                             with no range given: the range is
        #                             then the die's own losing half
        #                             (see damage_reroll_range).
        self.anti = []              # [(KEYWORD, X)] from ANTI-... X+
        self.twin_linked = False    # re-roll wound (fails)
        self.auto_wound = False      # OVERRIDE WOUND ALWAYS: every hit
        #                              auto-wounds (normal wound, no roll)
        self.rapid_fire = 0         # +N attacks at half range
        self.melta = 0              # +N damage at half range
        self.blast = 0              # BLAST X: +X attacks per 5 defender
        #                             models (0 = no Blast; plain BLAST -> 1)
        self.cleave = 0             # CLEAVE X: melee Blast, same scaling
        self.heavy = False          # +1 to hit if attacker stationary
        self.lance = False          # +1 to wound if attacker charged
        self.ignores_cover = False
        self.indirect = False       # INDIRECT FIRE: usable in indirect
        #                             shooting mode, with its penalties
        self.conversion = False     # CONVERSION: critical hits on 4+ when
        #                             the target is at least half the
        #                             weapon's range away
        self.hunter = []            # HUNTER X: may only be fired at units
        #                             with keyword X (targeting rule, not
        #                             maths - see analyzer_core)
        self.single_reroll = None   # "hit"|"wound": ONE die of that roll
        #                             may be re-rolled per activation
        #                             (Targeting Array and the like). Not
        #                             a per-attack re-roll: it adds one
        #                             fresh die when at least one such
        #                             roll failed - see analyze_weapon.
        self.ignore_cq_penalty = False  # the model ignores the -1 for
        #                             shooting into Engagement Range
        #                             (Siege Shield and the like)
        self.close_quarters = False  # CLOSE-QUARTERS (ex PISTOL): can be
        #                              fired at a unit the attacker is
        #                              engaged with, and is exempt from
        #                              the close-quarters -1 to hit
        # Per-attack Damage-characteristic modifiers from DMGREDUX /
        # DMGSETZERO effect strings (defender abilities, evaluated against
        # the attacking weapon). They are applied to the Damage D of each
        # attack in this FIXED order, regardless of declaration order
        # (see apply_damage_modifiers):
        #   Step 1  dmg_set      set D to a fixed value (None = no set)
        #   Step 2  dmg_mult     multiply D cumulatively (GW: round UP)
        #   Step 3  dmg_add      add to D (a reduction is a negative add)
        #   Step 4  floor at 1, UNLESS dmg_set_zero forces D to 0
        self.dmg_set = None         # Step 1: fixed override (int or None)
        self.dmg_mult = 1.0         # Step 2: cumulative factor (0.5 = halve)
        self.dmg_add = 0            # Step 3: net additive modifier
        self.dmg_set_zero = False   # Step 4: force D to 0 (bypass the floor)
        self.hazardous = False      # dual-profile reporting
        self.hit_mod = 0            # net roll modifiers (capped later)
        self.wound_mod = 0
        self.save_mod = 0           # modifier to the DEFENDER's save roll
        self.invuln_mod = 0         # modifier to the invuln save roll
        self.fnp_mod = 0            # modifier to the Feel No Pain roll
        # ignore-malus: when set, NEGATIVE modifiers to that roll are
        # ignored (clamped to 0); positive modifiers still apply.
        self.ignore_malus = set()   # subset of {hit, skill, wound, save,
        #                             invuln, fnp}. 11th ed. keeps the hit
        #                             ROLL modifiers and the BS/WS
        #                             CHARACTERISTIC modifiers (Cover,
        #                             Stealth, abilities) in two separate
        #                             groups, so they are ignored
        #                             separately: 'hit' clears the roll
        #                             penalties, 'skill' the characteristic
        #                             ones.
        self.reroll_hit = None      # None | '1' | 'fails'
        self.reroll_wound = None
        self.reroll_save = None     # defender-side re-rolls
        self.reroll_invuln = None
        self.reroll_fnp = None
        self.warnings = []          # unsupported tokens, reported to user


# BLAST is numeric in 11th ed. ("BLAST X"): plain "BLAST" parses to 1.
# CLEAVE X is the melee equivalent of Blast (same +X per 5 target models).
_KW_NUMERIC = {"SUSTAINED HITS": "sustained", "RAPID FIRE": "rapid_fire",
               "MELTA": "melta", "BLAST": "blast", "CLEAVE": "cleave"}
_KW_FLAGS = {"LETHAL HITS": "lethal", "DEVASTATING WOUNDS": "devastating",
             "TORRENT": "torrent", "TWIN-LINKED": "twin_linked",
             "HEAVY": "heavy", "LANCE": "lance",
             "IGNORES COVER": "ignores_cover", "HAZARDOUS": "hazardous",
             "INDIRECT FIRE": "indirect",
             "CLOSE-QUARTERS": "close_quarters",
             "CLOSE QUARTERS": "close_quarters",
             # PISTOL is the 10th-ed. name of the same keyword: rosters
             # fetched before the rename must behave identically.
             "PISTOL": "close_quarters",
             "CONVERSION": "conversion"}
# Weapon abilities the attacker (or a defender ability) can switch off,
# and the value that means "off". Keyed by the datasheet name, so the
# same vocabulary drives the attack-setup dialogs and the 'DISABLE X'
# effect string emitted by disableMechanic.
OPTIONAL_ABILITIES = {
    "LETHAL HITS": ("lethal", False),
    "DEVASTATING WOUNDS": ("devastating", False),
    "SUSTAINED HITS": ("sustained", 0),
    "TWIN-LINKED": ("twin_linked", False),
    "HEAVY": ("heavy", False),
    "LANCE": ("lance", False),
    "IGNORES COVER": ("ignores_cover", False),
    "MELTA": ("melta", 0),
    "RAPID FIRE": ("rapid_fire", 0),
    "BLAST": ("blast", 0),
    "CLEAVE": ("cleave", 0),
    "TORRENT": ("torrent", False),
    "HAZARDOUS": ("hazardous", False),
    "INDIRECT FIRE": ("indirect", False),
    "ANTI": ("anti", []),
    "CONVERSION": ("conversion", False),
    "HUNTER": ("hunter", []),
}

# Abilities offered as "add to every attack" in the attack setup: the
# token is what parse_weapon_keywords() will read, so numeric ones carry
# their default X.
ADDABLE_ABILITIES = ["LETHAL HITS", "DEVASTATING WOUNDS", "SUSTAINED HITS 1",
                     "TWIN-LINKED", "HEAVY", "LANCE", "IGNORES COVER",
                     "TORRENT", "MELTA 2", "RAPID FIRE 1", "BLAST 1",
                     "PSYCHIC", "CONVERSION"]


def add_hunter(mech, keyword: str):
    """Record a HUNTER X restriction (case- and spacing-insensitive, no
    duplicates). The restriction is about TARGETING, not about the
    maths: analyzer_core decides whether the weapon may fire at all."""
    kw = str(keyword).strip().upper()
    if kw and kw not in mech.hunter:
        mech.hunter.append(kw)


def disable_abilities(mech, names, warn=None):
    """Switch the named weapon abilities off on 'mech'. Names are matched
    on the datasheet spelling and may carry their X ("SUSTAINED HITS 2",
    "ANTI-VEHICLE 4+"): only the ability part is used."""
    for raw in names or ():
        key = str(raw).upper().strip()
        for label, (attr, off) in OPTIONAL_ABILITIES.items():
            if key == label or key.startswith(label):
                setattr(mech, attr, list(off) if isinstance(off, list)
                        else off)
                break
        else:
            if warn:
                warn(f"cannot switch off unknown ability '{raw}'")


def add_abilities(mech, tokens):
    """Give every attack the listed weapon abilities (attack setup),
    exactly as if the datasheet carried the keyword."""
    if tokens:
        parse_weapon_keywords(list(tokens), mech)


# PSYCHIC is handled explicitly (ignore-malus on the hit roll), not here.
_KW_IGNORED = {"EXTRA ATTACKS", "ASSAULT", "ONE SHOT", "PRECISION"}
_ANTI_RE = re.compile(r"^ANTI[- ]([A-Z' ]+?)\s+(\d)\+?$")
# HUNTER X names a keyword instead of a number: "HUNTER-VEHICLE".
_HUNTER_RE = re.compile(r"^HUNTER[- ]([A-Z' ]+)$")

# CONVERSION: the critical HIT threshold it grants beyond half range.
CONVERSION_CRIT_HIT = 4

# Overwatch: the unmodified roll needed to hit, and its legal range.
OVERWATCH_DEFAULT = 6
OVERWATCH_RANGE = (2, 6)


def overwatch_target(ctx: dict):
    """The unmodified roll Overwatch needs, or None when the attack is
    not an Overwatch one. Overwatch hits ONLY on that unmodified result:
    no hit modifiers (BS/WS ones included) and no re-rolls apply. The
    wound roll onwards is unaffected."""
    if not ctx.get("overwatch"):
        return None
    lo, hi = OVERWATCH_RANGE
    try:
        value = int(ctx.get("overwatch_value") or OVERWATCH_DEFAULT)
    except (TypeError, ValueError):
        value = OVERWATCH_DEFAULT
    return max(lo, min(hi, value))


def parse_x_value(text, warn=None):
    """The X after a keyword: a flat number ("2") or a dice expression
    ("D3", "2D6+1"), which 11th ed. allows for Rapid Fire and friends.
    Returns an int for a flat value and a Characteristic for dice, so
    the flat case stays exactly as cheap as it was. None on nonsense."""
    text = str(text or "").strip()
    if not text:
        return 1
    try:
        return int(text)
    except ValueError:
        pass
    try:
        c = Characteristic(text)
    except Exception:
        c = None
    if c is None or c.is_none() or (c.count == 0 and c.flat == 0):
        if warn:
            warn(f"bad value '{text}'")
        return None
    return c.flat if c.count == 0 else c


def x_active(value) -> bool:
    """True when an X value can contribute anything at all."""
    if value is None:
        return False
    if isinstance(value, Characteristic):
        return not value.is_none() and (value.count > 0 or value.flat > 0)
    return value > 0


def x_pmf(value) -> list:
    """PMF of an X value (flat or dice)."""
    if not x_active(value):
        return delta(0)
    return char_pmf(value) if isinstance(value, Characteristic) \
        else delta(int(value))


def _x_sum(a, b):
    """a + b where either may be dice: two dice values are kept as a
    Characteristic sum when possible, otherwise the flats add."""
    if isinstance(a, Characteristic) or isinstance(b, Characteristic):
        ca = a if isinstance(a, Characteristic) else Characteristic(int(a))
        cb = b if isinstance(b, Characteristic) else Characteristic(int(b))
        if ca.sides == cb.sides or ca.count == 0 or cb.count == 0:
            out = Characteristic(0)
            out.count = ca.count + cb.count
            out.sides = ca.sides or cb.sides
            out.flat = ca.flat + cb.flat
            return out
        return ca                      # mixed dice: keep the first
    return int(a) + int(b)


def x_text(value) -> str:
    """How the value is spelled back to the user."""
    if isinstance(value, Characteristic):
        if not value.count:
            return str(value.flat)
        base = f"{value.count}D{value.sides}"
        return base if not value.flat else f"{base}{value.flat:+d}"
    return str(value)


def x_value(value, rng=None) -> int:
    """Resolve an X value to an int, rolling the dice if it is one."""
    if not x_active(value):
        return 0
    if isinstance(value, Characteristic):
        return value.value(rng) or 0
    return int(value)


def parse_weapon_keywords(keywords, mech: WeaponMechanics):
    """Parse weapon keywords (e.g. Sustained Hits, Lethal Hits, Devastating Wounds, Torrent, Blast) into the WeaponMechanics flags that drive the damage maths."""
    for kw in keywords or []:
        kw = str(kw).strip().upper()      # rosters vary in casing
        m = _ANTI_RE.match(kw)
        if m:
            mech.anti.append((m.group(1).strip(), int(m.group(2))))
            continue
        m = _HUNTER_RE.match(kw)
        if m:
            add_hunter(mech, m.group(1))
            continue
        matched = False
        for name, attr in _KW_NUMERIC.items():
            if kw.startswith(name):
                tail = kw[len(name):].strip()
                value = parse_x_value(
                    tail, lambda msg: mech.warnings.append(
                        f"{msg} in keyword '{kw}'"))
                if value is not None:
                    setattr(mech, attr, value)
                matched = True
        if matched:
            continue
        if kw in _KW_FLAGS:
            setattr(mech, _KW_FLAGS[kw], True)
        elif kw == "PSYCHIC":
            # 11th ed.: "ignore any or all modifiers to that attack's BS
            # or WS characteristic and any or all modifiers to the hit
            # roll" - both groups, via the shared ignore-malus set.
            mech.ignore_malus.update(("hit", "skill"))
        elif kw in _KW_IGNORED or not kw:
            pass
        else:
            mech.warnings.append(f"unsupported keyword '{kw}' (ignored)")


# ---------------- effect-string parsing ----------------

_ROLL_RE = re.compile(r"^ROLL (HIT|WOUND|SAVE) (\d)([+\-=]) (UNMOD|MOD)$")
_CHAR_RE = re.compile(r"^CHAR (S|A|AP|D) (GT|LT|EQ|GE|LE) (-?\d+) "
                      r"(MOD|UNMOD)$")
_RANGE_RE = re.compile(r"^REROLL DAMAGE RANGE \[(\d+),\s*(\d+)\]$")
# "Re-roll a Damage roll of N": the single-value form of the same thing,
# which the ability editor offers for the Damage application too.
_DMG_ONE_RE = re.compile(r"^REROLL DAMAGE (\d+)$")


def _eval_char_cond(m, weapon) -> bool:
    """Evaluate a CHAR condition against the (already modified) weapon;
    None weapon -> False (cannot decide)."""
    if weapon is None:
        return False
    val = {"S": weapon.S, "A": weapon.A, "AP": weapon.AP,
           "D": weapon.D}[m.group(1)].value_avg()
    if val is None:
        return False
    if m.group(1) == "AP":
        val = abs(val)              # compare AP magnitudes
    ref = abs(int(m.group(3))) if m.group(1) == "AP" else int(m.group(3))
    return {"GT": val > ref, "LT": val < ref, "EQ": val == ref,
            "GE": val >= ref, "LE": val <= ref}[m.group(2)]


def _split_conditions(s: str):
    """Split 'IF A: IF B: PAYLOAD' -> (['A', 'B'], 'PAYLOAD')."""
    conds = []
    while s.startswith("IF "):
        cond, sep, rest = s[3:].partition(": ")
        if not sep:
            break
        conds.append(cond.strip())
        s = rest
    return conds, s.strip()


def _parse_mw_payload(tokens):
    """MORTAL_WOUNDS <n|None> [MATCH_DAMAGE] [END_SEQUENCE] [NO_SPILL]
    [CAP x] -> dict or None on CAP (not modelled)."""
    out = {"value": None, "match": "MATCH_DAMAGE" in tokens,
           "end": "END_SEQUENCE" in tokens,
           # Mortal wounds normally spill from a destroyed model to the
           # next; a few abilities say they do not. Only the kill chain
           # cares - the damage totals are the same either way.
           "spill": "NO_SPILL" not in tokens}
    if "CAP" in tokens:
        return None
    try:
        out["value"] = int(tokens[1])
    except (ValueError, IndexError):
        out["value"] = None
    return out


def parse_effect_strings(strings, attack_type: str, mech: WeaponMechanics,
                         weapon=None):
    """Fold the view effect strings into the mechanics. CHAR and
    RANGED/MELEE_ATTACK conditions are decided here (the weapon is
    known); roll-time conditions select the mechanic branch. Unknown
    combinations are collected as warnings."""
    for raw in strings or []:
        conds, s = _split_conditions(raw.strip())
        applies, dyn = True, []
        for c in conds:
            if c in ("RANGED_ATTACK", "MELEE_ATTACK"):
                applies &= (c.split("_")[0].title() == attack_type)
            elif c == "PSYCHIC_ATTACK":
                # "only against Psychic attacks": a property of the
                # ATTACKING weapon, which the defender view cannot see -
                # so modifier_engine defers it to here.
                kws = {str(k).strip().upper()
                       for k in (getattr(weapon, "keywords", None) or ())}
                applies &= "PSYCHIC" in kws
            elif _CHAR_RE.match(c):
                applies &= _eval_char_cond(_CHAR_RE.match(c), weapon)
            else:
                dyn.append(c)
        if not applies:
            continue
        tok = s.split()
        try:
            self_handled = _dispatch(dyn, s, tok, mech)
        except (IndexError, ValueError):
            self_handled = False
        if not self_handled:
            mech.warnings.append(f"unsupported effect '{raw}'")


def _dispatch(dyn, s, tok, mech) -> bool:
    """Apply one payload under its dynamic conditions; True if handled."""
    roll_m = _ROLL_RE.match(dyn[0]) if len(dyn) == 1 else None
    # ---- unconditional payloads ----
    if not dyn:
        if tok[0] == "HIT_ROLL":
            mech.hit_mod += int(tok[1])
        elif tok[0] == "WOUND_ROLL":
            mech.wound_mod += int(tok[1])
        elif tok[0] == "SAVE_ROLL":
            mech.save_mod += int(tok[1])
        elif tok[0] == "REROLL" and tok[1] == "ONE" \
                and tok[2] in ("HIT_ROLL", "WOUND_ROLL"):
            # ONE re-roll for the whole activation, not one per attack.
            mech.single_reroll = tok[2].split("_")[0].lower()
        elif tok[0] == "REROLL" and tok[1] in ("HIT_ROLL", "WOUND_ROLL"):
            kind = "reroll_hit" if tok[1] == "HIT_ROLL" else "reroll_wound"
            what = {"FAILS": "fails", "1": "1"}.get(tok[2])
            if what is None:
                return False
            setattr(mech, kind, combine_reroll(getattr(mech, kind), what))
        elif _RANGE_RE.match(s):
            m = _RANGE_RE.match(s)
            mech.dmg_reroll = (int(m.group(1)), int(m.group(2)))
        elif _DMG_ONE_RE.match(s):
            n = int(_DMG_ONE_RE.match(s).group(1))
            mech.dmg_reroll = (n, n)
        elif tok[0] == "REROLL" and tok[1] == "DAMAGE" and tok[2] == "FAILS":
            # "You can re-roll the Damage roll": no range is given, so
            # the sensible policy is re-rolling the results a player
            # would - see damage_reroll_range.
            mech.dmg_reroll_any = True
        elif s == "OVERRIDE HIT ALWAYS":
            mech.auto_hit = True
        elif s == "OVERRIDE WOUND ALWAYS":
            # Every hit automatically wounds (a normal, non-critical wound),
            # analogous to TORRENT on the hit stage.
            mech.auto_wound = True
        elif tok[0] == "LETHALHITS":
            mech.lethal = True
        elif tok[0] == "DEVASTATINGWOUNDS":
            mech.devastating = True
        elif tok[0] == "TORRENT":
            mech.torrent = True
        elif tok[0] == "TWINLINKED":
            mech.twin_linked = True
        elif tok[0] == "BLAST":
            mech.blast = mech.blast or 1
        elif tok[0] == "CLEAVE":
            mech.cleave = mech.cleave or 1
        elif tok[0] == "PSYCHIC":
            mech.ignore_malus.update(("hit", "skill"))
        elif tok[0] == "IGNORECOVER":
            mech.ignores_cover = True
        elif tok[0] == "IGNOREMALUS" and len(tok) >= 2:
            roll = tok[1].lower()
            if roll in ("hit", "skill", "wound", "save", "invuln", "fnp"):
                mech.ignore_malus.add(roll)
            else:
                return False
        elif tok[0] == "CRITON" and len(tok) >= 3:
            # CRITON HIT|WOUND N -> lower the critical threshold (best wins)
            step, n = tok[1], int(tok[2])
            if step == "HIT":
                mech.crit_hit_on = min(mech.crit_hit_on, n)
            elif step == "WOUND":
                mech.crit_wound_on = min(mech.crit_wound_on, n)
            else:
                return False
        elif tok[0] == "CHARMOD" and len(tok) >= 3 \
                and tok[1] in _INCOMING_CHAR_MODS:
            # Defender ability: "worsen/improve the <characteristic> of
            # that attack by N". Sign convention follows the datasheet:
            # +1 on AP or on the BS/WS modifier makes the attack worse,
            # +1 on S / A / D makes it better.
            attr = _INCOMING_CHAR_MODS[tok[1]]
            setattr(mech, attr, getattr(mech, attr) + int(tok[2]))
        elif tok[0] == "BENEFITOFCOVER":
            # An ability granting the Benefit of Cover (11th-ed. Stealth).
            # Boolean, so it can never stack with terrain cover.
            mech.cover = True
        elif tok[0] == "DMGREDUX" and len(tok) >= 3:
            # DMGREDUX set|mult|add N -> a modifier on the incoming attack's
            # Damage, resolved against the attacking weapon (static conds
            # already applied). Folded into the four-step model on 'mech';
            # the ordered application happens in apply_damage_modifiers.
            #   set N    -> Step 1: fix Damage to N (best/lowest wins)
            #   mult f   -> Step 2: multiply cumulatively (0.5 = halve)
            #   add N    -> Step 3: additive (a reduction of k is 'add -k')
            mode = tok[1]
            if mode == "mult":
                mech.dmg_mult *= float(tok[2])
            elif mode == "set":
                n = int(tok[2])
                mech.dmg_set = n if mech.dmg_set is None \
                    else min(mech.dmg_set, n)
            else:                       # 'add' (default / back-compatible)
                mech.dmg_add += int(tok[2])
        elif tok[0] == "DMGSETZERO":
            # Step 4 special case: force the final Damage to 0, bypassing
            # the "always at least 1" floor (e.g. an ability that negates
            # the attack's damage entirely).
            mech.dmg_set_zero = True
        elif tok[0] in ("EXTRAATTACKS", "WEAPON_DISABLED"):
            pass                    # selection-level tokens, no maths
        elif tok[0] == "EXTRA_HITS":
            # generateExtras "extra hits" with no roll-time condition:
            # every successful hit yields X more. Under a critical-hit
            # condition the same token becomes SUSTAINED HITS instead
            # (see the CRIT_HIT branch below).
            add = parse_x_value(tok[1], mech.warnings.append)
            if x_active(add):
                mech.extra_hits = (add if not x_active(mech.extra_hits)
                                   else _x_sum(mech.extra_hits, add))
        elif tok[0] == "EXTRA_WOUNDS":
            # Every successful wound yields X more. Like the bonus hits
            # of SUSTAINED HITS, the bonus wounds are NORMAL wounds: they
            # are not rolled, so they can never be critical.
            add = parse_x_value(tok[1], mech.warnings.append)
            if x_active(add):
                mech.extra_wounds = (add if not x_active(mech.extra_wounds)
                                     else _x_sum(mech.extra_wounds, add))
        elif tok[0] == "EXTRA_ATTACKS":
            # X further attacks with this weapon. It is a count, not a
            # roll-time event, so it joins the Rapid Fire / Blast extras.
            add = parse_x_value(tok[1], mech.warnings.append)
            if x_active(add):
                mech.extra_attacks = (add if not x_active(mech.extra_attacks)
                                      else _x_sum(mech.extra_attacks, add))
        elif tok[0] == "SETINVULN":
            # An ability granting an invulnerable save for this attack
            # (a conditional one, e.g. "only against Ranged attacks",
            # arrives here once parse_effect_strings has decided the
            # condition). The best value wins; it never stacks.
            v = int(tok[1])
            mech.invuln_grant = v if mech.invuln_grant is None \
                else min(mech.invuln_grant, v)
        elif tok[0] == "CONVERSION":
            mech.conversion = True
        elif tok[0] == "HUNTER" and len(tok) >= 2:
            add_hunter(mech, " ".join(tok[1:]))
        elif tok[0] == "FNP_ROLL":
            mech.fnp_mod += int(tok[1])
        elif tok[0] == "FNPOVERRIDE":
            # Forced FNP for this attack, better OR worse than the
            # defender's own (7 = no Feel No Pain at all).
            mech.fnp_set = int(tok[1])
        elif tok[0] == "SETFNP":
            # Granted FNP: never stacks, the best value wins - here and
            # against the defender's own value (see effective_fnp).
            v = int(tok[1])
            mech.fnp_grant = v if mech.fnp_grant is None \
                else min(mech.fnp_grant, v)
        elif tok[0] == "DISABLE":
            if tok[1:] == ["CLOSEQUARTERSPENALTY"]:
                # Not a weapon ability: the -1 a MONSTER/VEHICLE takes
                # for shooting the unit it is engaged with.
                mech.ignore_cq_penalty = True
            else:
                # disableMechanic: switch a weapon ability off for this
                # attack
                disable_abilities(mech, [" ".join(tok[1:])],
                                  lambda m: mech.warnings.append(m))
        else:
            return False
        return True
    # ---- single roll-time condition ----
    if dyn == ["CRIT_HIT"]:
        if tok[0] == "EXTRA_HITS":
            add = parse_x_value(tok[1], mech.warnings.append)
            if x_active(add):
                mech.sustained = (add if not x_active(mech.sustained)
                                  else _x_sum(mech.sustained, add))
        elif s == "OVERRIDE WOUND ALWAYS":
            mech.lethal = True
        elif s == "OVERRIDE WOUND ALWAYS CRIT":
            mech.lethal_crit = True
        else:
            return False
        return True
    if dyn == ["CRIT_WOUND"]:
        if tok[0] == "EXTRA_WOUNDS":
            # Bonus wounds on a CRITICAL wound only - the wound-stage
            # counterpart of SUSTAINED HITS. Like every bonus wound they
            # are normal wounds: not rolled, so never critical, and they
            # generate no extras of their own.
            add = parse_x_value(tok[1], mech.warnings.append)
            if x_active(add):
                mech.extra_wounds_crit = (
                    add if not x_active(mech.extra_wounds_crit)
                    else _x_sum(mech.extra_wounds_crit, add))
        elif tok[0] == "MORTAL_WOUNDS":
            mw = _parse_mw_payload(tok)
            if mw is None:
                return False        # CAP not modelled
            mech.crit_mw = mw
        elif tok[0] == "CHARMOD" and tok[1] == "AP":
            mech.crit_ap_delta += int(tok[2])
        elif tok[0] == "CHARSET" and tok[1] == "AP":
            # "on a Critical Wound, that attack has an AP of -N": an
            # absolute value, not a delta. The strongest (most negative)
            # wins if several abilities set it.
            n = int(tok[2])
            mech.crit_ap_set = n if mech.crit_ap_set is None \
                else min(mech.crit_ap_set, n)
        else:
            return False
        return True
    if dyn == ["MW_ONLY"]:
        # Abilities that only bite on mortal wounds (Devastating Wounds
        # and the like): a granted FNP (best wins), an overridden one, a
        # modifier to that roll, or an invulnerable save - the one thing
        # that can stop a mortal wound, since they ignore armour.
        if tok[0] == "SETFNP":
            v = int(tok[1])
            mech.fnp_mw = v if mech.fnp_mw is None else min(mech.fnp_mw, v)
            return True
        if tok[0] == "FNPOVERRIDE":
            mech.fnp_set_mw = int(tok[1])
            return True
        if tok[0] == "FNP_ROLL":
            mech.fnp_mod_mw += int(tok[1])
            return True
        if tok[0] == "SETINVULN":
            v = int(tok[1])
            mech.invuln_mw = v if mech.invuln_mw is None \
                else min(mech.invuln_mw, v)
            return True
    if roll_m and roll_m.group(4) == "UNMOD" and roll_m.group(3) == "+":
        step, thr = roll_m.group(1), int(roll_m.group(2))
        if step == "WOUND" and s == "OVERRIDE WOUND ALWAYS CRIT":
            mech.crit_wound_on = min(mech.crit_wound_on, thr)
            return True
        if step == "HIT" and s == "OVERRIDE HIT ONLY IRRESPECTIVE":
            mech.hit_unmod_only = thr
            return True
        if step == "HIT" and tok[0] == "MORTAL_WOUNDS":
            mw = _parse_mw_payload(tok)
            if mw is None or not mw["end"]:
                return False        # only sequence-ending form modelled
            mw["thr"] = thr
            mech.hitroll_mw = mw
            return True
    return False


def _cap(mod: int) -> int:
    """Clamp a net HIT or WOUND roll modifier (11th ed.: +/-1). Saving
    throws, invulnerable saves and Feel No Pain are NOT capped."""
    return rules_config.cap_roll(mod)


def has_damage_modifiers(mech) -> bool:
    """True if any defender Damage modifier is active on 'mech' (lets the
    callers skip the transform entirely in the common no-modifier case)."""
    return (mech.dmg_set is not None or mech.dmg_mult != 1.0
            or mech.dmg_add != 0 or mech.dmg_set_zero)


def apply_damage_modifiers(d: int, mech) -> int:
    """Apply the defender's per-attack Damage modifiers to a single
    Damage value 'd', in the FIXED 11th-ed. order (independent of the
    order the abilities were declared):

      Step 1  set    : replace D by a fixed value (mech.dmg_set)
      Step 2  mult   : multiply cumulatively, rounding UP (mech.dmg_mult)
      Step 3  add    : additive modifier, e.g. -1 (mech.dmg_add)
      Step 4  floor  : D is at least 1, UNLESS mech.dmg_set_zero forces 0

    A 0-Damage input (no attack) stays 0. Used by the exact maths (via
    transform over the Damage PMF) and mirrored by the dice resolver."""
    from math import ceil
    if d <= 0:
        return 0
    if mech.dmg_set is not None:                       # Step 1
        d = mech.dmg_set
    if mech.dmg_mult != 1.0:                           # Step 2 (round up)
        d = ceil(d * mech.dmg_mult)
    d += mech.dmg_add                                  # Step 3
    if mech.dmg_set_zero:                              # Step 4 (special)
        return 0
    return max(1, d)                                   # Step 4 (floor)


# ---------------- per-weapon analysis ----------------


def _pmf_equal(a: list, b: list, eps: float = 1e-12) -> bool:
    """Two PMFs that are the same law to within rounding."""
    n = max(len(a), len(b))
    return all(abs((a[i] if i < len(a) else 0.0)
                   - (b[i] if i < len(b) else 0.0)) < eps for i in range(n))


def _event_damage(thinned: list, w_ref: int) -> list:
    """Damage of ONE allocation event, i.e. the post-FNP damage law
    conditioned on being greater than zero: an attack whose damage is
    fully absorbed allocates nothing and is not an event at all.

    Pre-capped at W because the allocation caps it at the wounds LEFT
    on the model, which can only be smaller - nothing is lost and the
    support stays short.
    """
    p0 = thinned[0] if thinned else 1.0
    if p0 >= 1.0 - 1e-15:
        return [1.0]                      # nothing ever gets through
    out = [0.0] * (min(len(thinned) - 1, w_ref) + 1)
    for v, p in enumerate(thinned):
        if v:
            out[min(v, w_ref)] += p / (1.0 - p0)
    return out


# Mechanics worth naming in an audit, as (attribute, label). A value of
# 0/False/None means the ability is not in play and is left out.
_MECH_LABELS = (
    ("sustained", "SUSTAINED HITS %s"), ("extra_hits", "+%s hit per hit"),
    ("extra_wounds", "+%s wound per wound"),
    ("extra_wounds_crit", "+%s wound per critical wound"),
    ("extra_attacks", "+%s attack"),
    ("lethal", "LETHAL HITS"), ("lethal_crit", "critical hit -> critical "
                                "wound"),
    ("devastating", "DEVASTATING WOUNDS"), ("torrent", "TORRENT"),
    ("auto_hit", "auto-hit"), ("auto_wound", "auto-wound"),
    ("twin_linked", "TWIN-LINKED"), ("heavy", "HEAVY"),
    ("lance", "LANCE"), ("conversion", "CONVERSION"),
    ("indirect", "INDIRECT FIRE"), ("ignores_cover", "ignores cover"),
    ("hazardous", "HAZARDOUS"), ("close_quarters", "CLOSE-QUARTERS"),
    ("blast", "BLAST %s"), ("cleave", "CLEAVE %s"),
    ("rapid_fire", "RAPID FIRE %s"), ("melta", "MELTA %s"),
    ("hit_unmod_only", "hits only on unmodified %s+"),
)


def active_mechanics(mech, ctx: dict = None) -> list:
    """The abilities that actually took part in this attack, named.

    An audit is only worth reading if it says what fired, not what could
    have fired: the flags left on from three analyses ago are exactly
    what the reader is looking for.
    """
    ctx = ctx or {}
    out = []
    for attr, label in _MECH_LABELS:
        val = getattr(mech, attr, None)
        if not val:
            continue
        out.append(label % val if "%s" in label else label)
    for kw, x in mech.anti:
        out.append(f"ANTI-{kw} {x}+")
    if mech.crit_hit_on != 6:
        out.append(f"critical hit on {mech.crit_hit_on}+")
    if mech.crit_wound_on != 6:
        out.append(f"critical wound on {mech.crit_wound_on}+")
    if mech.crit_mw:
        out.append("critical wound -> mortal wounds")
    if mech.hitroll_mw:
        out.append(f"hit roll {mech.hitroll_mw['thr']}+ -> mortal wounds")
    for roll in ("hit", "wound", "save", "invuln", "fnp"):
        rr = getattr(mech, "reroll_" + roll, None)
        if rr:
            out.append(f"re-roll {roll}: {rr}")
    if mech.single_reroll:
        out.append(f"one {mech.single_reroll} re-roll per activation")
    if mech.ignore_malus:
        out.append("ignores penalties to: "
                   + ", ".join(sorted(mech.ignore_malus)))
    for attr, label in (("dmg_set", "damage set to %s"),
                        ("dmg_add", "damage %+d"),
                        ("invuln_grant", "invulnerable %s+ granted"),
                        ("fnp_grant", "FNP %s+ granted"),
                        ("fnp_set", "FNP set to %s+")):
        val = getattr(mech, attr, None)
        if val:
            out.append(label % val)
    if mech.dmg_mult != 1.0:
        out.append(f"damage x{mech.dmg_mult:g}")
    if mech.dmg_set_zero:
        out.append("damage set to 0")
    return out


def analyze_weapon(weapon, defender_ref: dict, ctx: dict,
                   mech: WeaponMechanics, alloc: bool = False) -> dict:
    """Exact analysis of one weapon (view object) against a reference
    defender {'T','Sv','W','invuln','fnp','models','keywords'} with
    context flags {'half_range','stationary','charged','cover'}.

    Returns attacks/wounds/damage PMFs and their stats. With alloc=True
    it also returns ['alloc'], the ingredients the kill-count chain
    needs: the per-attack JOINT (mortal, normal) PMF and the number of
    attacks. It costs one extra pass over the branch structure, so it is
    off unless a caller asks."""
    half = bool(ctx.get("half_range"))
    warn = mech.warnings.append

    # ---- number of attacks: A per copy (+rapid fire/blast), x count ----
    # X may be a dice expression (11th ed.), so the extras are a PMF and
    # not a number. For BLAST/CLEAVE the bonus is "X attacks for every 5
    # models", which with a dice X is read as one roll PER GROUP of five
    # rather than a single roll multiplied - for a flat X the two are the
    # same thing.
    extra_pmf = delta(0)
    if half and x_active(mech.rapid_fire):
        extra_pmf = convolve(extra_pmf, x_pmf(mech.rapid_fire))
    groups = max(0, defender_ref.get("models", 1) // 5)
    # BLAST (ranged) and CLEAVE (melee) both add X attacks per 5 target
    # models; a weapon carries at most one of them.
    for src in (mech.blast, mech.cleave):
        if groups and x_active(src):
            for _ in range(groups):
                extra_pmf = convolve(extra_pmf, x_pmf(src))
    # generateExtras "extra attacks": X further attacks with the weapon,
    # unconditional (a roll-time condition cannot change a count decided
    # before the dice are rolled).
    if x_active(mech.extra_attacks):
        extra_pmf = convolve(extra_pmf, x_pmf(mech.extra_attacks))
    per_copy = char_pmf(weapon.A)
    if mech.attacks_mod:
        # Defender ability on the attack's Attacks characteristic: it
        # modifies the characteristic, so it lands BEFORE the extra
        # attacks granted by Rapid Fire / Blast / Cleave.
        per_copy = transform(
            per_copy,
            lambda v: rules_config.clamp_characteristic(
                "A", v + mech.attacks_mod))
    if len(extra_pmf) > 1 or extra_pmf[0] != 1.0:
        per_copy = convolve(per_copy, extra_pmf)
    attacks_pmf = delta(0)
    for _ in range(max(1, weapon.count)):
        attacks_pmf = convolve(attacks_pmf, per_copy)

    # ---- hit stage ----
    # 11th ed. splits the two groups of modifiers, each capped on its own
    # (see rules_config): HIT ROLL modifiers...
    #   - Heavy: +1 when the attacker moved less than 3" ('stationary').
    #   - Damaged bracket: -1 on ALL of this model's attacks.
    # ...and BS/WS CHARACTERISTIC modifiers:
    #   - Benefit of Cover: -1 BS on RANGED attacks (unless the weapon
    #     Ignores Cover). Replaces the 10th-ed. +1-to-save rule.
    #   - Plunging Fire: +1 BS on RANGED attacks.
    hit_mod = mech.hit_mod + (1 if (mech.heavy and ctx.get("stationary"))
                              else 0)
    if ctx.get("damaged"):
        hit_mod -= 1
    # Close-quarters shooting: a MONSTER/VEHICLE model firing at the unit
    # it is engaged with takes -1 to hit with everything EXCEPT its
    # CLOSE-QUARTERS weapons. The caller sets the flag only for such an
    # attacker (non-MONSTER/VEHICLE models may only fire CLOSE-QUARTERS
    # weapons in the first place, and take no penalty).
    if ctx.get("close_quarters_penalty") and not mech.close_quarters \
            and not mech.ignore_cq_penalty:
        hit_mod -= 1
    # INDIRECT FIRE (11th ed. indirect shooting mode): the target always
    # counts as being in Cover, the hit roll cannot be re-rolled, and an
    # unmodified result below 6 always fails - 4 instead of 6 when the
    # unit Remained Stationary and a friendly unit can see the target
    # ('spotter'). Applies only to weapons that HAVE the keyword; the
    # caller decides which weapons are fired at all.
    indirect = bool(ctx.get("indirect")) and mech.indirect
    unmod_min = 1
    reroll_hit = mech.reroll_hit
    if indirect:
        unmod_min = 4 if ctx.get("spotter") else 6
        reroll_hit = None
    skill_mod = 0
    if weapon.type == "Ranged":
        if (ctx.get("cover") or mech.cover or indirect) \
                and not mech.ignores_cover:
            skill_mod -= 1
        if ctx.get("plunging"):
            skill_mod += 1
    # A defender ability may also modify the attack's BS/WS. It uses the
    # characteristic convention (+1 = worse), so it enters with the
    # opposite sign of the roll-style skill_mod above.
    skill_mod -= mech.skill_mod
    # "any or all": the best use of the choice is to drop the negatives
    # and keep the positives. The two groups are independent - an ability
    # that ignores modifiers to the HIT ROLL does not ignore the Benefit
    # of Cover, which in 11th ed. is a BS penalty. PSYCHIC sets both.
    if "hit" in mech.ignore_malus:
        hit_mod = max(0, hit_mod)
    if "skill" in mech.ignore_malus:
        skill_mod = max(0, skill_mod)   # roll-style sign: penalty < 0
    hit_mod = _cap(hit_mod)             # the ROLL modifier is capped...
    skill = weapon.WS if weapon.type == "Melee" else weapon.BS
    # ...the CHARACTERISTIC modifier is not: it is uncapped and only
    # bounded by the absolute limits (BS/WS never better than 2+, never
    # worse than 6+). A BS/WS modifier shifts the target number the other
    # way (+1 BS = easier). Clamping here and not after adding hit_mod is
    # deliberate: the rules limit the characteristic, then the roll
    # modifier applies on top of the clamped value.
    skill_target = rules_config.clamp_characteristic(
        "BS", (skill.value() or 0) - skill_mod)
    # CONVERSION: at least half the weapon's range away, critical hits
    # come on 4+. The 'half_range' flag says the attack IS within half
    # range, so an unticked flag means the bonus applies - the analyzer
    # cannot know the real distance, and 'beyond' is the common case.
    crit_hit_on = mech.crit_hit_on
    if mech.conversion and not ctx.get("half_range"):
        crit_hit_on = min(crit_hit_on, CONVERSION_CRIT_HIT)
    # OVERWATCH: hits only on an unmodified N+ (6 by default). Every hit
    # modifier and every re-roll is discarded - TORRENT still hits
    # automatically, since it makes no hit roll at all - while the wound
    # roll and everything after it are resolved normally.
    ow = overwatch_target(ctx)
    if ow is not None:
        hit_mod, skill_target, reroll_hit = 0, ow, None
        unmod_min = max(unmod_min, ow)
    p_mw_hit = 0.0
    if mech.torrent or mech.auto_hit or skill.is_none():
        p_hit, p_crit_hit = 1.0, 0.0      # auto-hit: no roll, no crits
        if mech.hitroll_mw or mech.hit_unmod_only:
            warn("hit-roll mechanic combined with auto-hit: ignored")
    elif mech.hitroll_mw:
        p_mw_hit, p_hit = hit_threshold_mw_probs(
            skill_target, hit_mod, reroll_hit, mech.hitroll_mw["thr"])
        p_crit_hit = 0.0                   # the natural 6 feeds the MW branch
        if indirect:
            warn("indirect fire combined with a hit-roll mortal-wound "
                 "mechanic: the unmodified-roll floor is not applied")
    elif mech.hit_unmod_only:
        # hits only on an unmodified X+, irrespective of modifiers
        p_hit, p_crit_hit = roll_probs(max(mech.hit_unmod_only, unmod_min),
                                       0, reroll_hit, crit_on=crit_hit_on)
    else:
        p_hit, p_crit_hit = roll_probs(skill_target, hit_mod, reroll_hit,
                                       crit_on=crit_hit_on,
                                       unmod_min=unmod_min)
    p_norm_hit = p_hit - p_crit_hit

    # ---- wound stage ----
    s = rules_config.clamp_characteristic(
        "S", (weapon.S.value() or 0) + mech.str_mod)
    t = defender_ref["T"]
    wt = wound_target(s, t)
    wound_mod = mech.wound_mod + (1 if (mech.lance and ctx.get("charged"))
                                  else 0)
    if "wound" in mech.ignore_malus:
        wound_mod = max(0, wound_mod)
    wound_mod = _cap(wound_mod)
    crit_wound_on = mech.crit_wound_on
    # ANTI-X: the defender keywords may arrive in any casing.
    dkw = {str(k).strip().upper()
           for k in (defender_ref.get("keywords") or ())}
    for kw, x in mech.anti:
        if str(kw).strip().upper() in dkw:
            crit_wound_on = min(crit_wound_on, x)
    reroll_wound = combine_reroll("fails" if mech.twin_linked else None,
                                  mech.reroll_wound)
    q_w, q_cw = roll_probs(wt, wound_mod, reroll_wound,
                           crit_on=crit_wound_on)
    if mech.auto_wound:
        q_w, q_cw = 1.0, 0.0        # auto-wound: always a normal wound
    q_nw = q_w - q_cw

    # ---- saves (normal and crit-wound branch) ----
    # AP of the attack: the weapon's own value, then any defender-side
    # modifier (ap_mod), clamped by the absolute limit (never worse
    # than 0).
    ap = _effective_ap(weapon.AP.value() or 0, mech)
    # Saving-throw modifiers are NOT capped (only hit and wound are).
    save_mod = (max(0, mech.save_mod) if "save" in mech.ignore_malus
                else mech.save_mod)
    invuln_mod = (max(0, mech.invuln_mod)
                  if "invuln" in mech.ignore_malus else mech.invuln_mod)
    common = (defender_ref["Sv"], save_mod, invuln_mod,
              mech.reroll_save, mech.reroll_invuln)

    def p_uns(ap_val):
        sv, smod, imod, srr, irr = common
        return save_fail_prob(sv, ap_val, effective_invuln(defender_ref, mech),
                              smod, imod, srr, irr)

    p_unsaved = p_uns(ap)
    ap_crit = _crit_ap(weapon.AP.value() or 0, mech)
    p_unsaved_crit = p_uns(ap_crit) if ap_crit != ap else p_unsaved

    # ---- damage PMFs (normal and mortal-wound streams) ----
    # The damage re-roll range refers to the DIE result, so it is
    # applied per-die, before the flat bonus and before MELTA.
    dmg_rr = mech.dmg_reroll or (damage_reroll_range(weapon.D)
                                 if mech.dmg_reroll_any else None)
    if dmg_rr and weapon.D.count:
        die = [0.0] + [1.0 / weapon.D.sides] * weapon.D.sides
        die = reroll_low_damage(die, *dmg_rr)
        dmg_raw = delta(max(weapon.D.flat, 0))
        for _ in range(weapon.D.count):
            dmg_raw = convolve(dmg_raw, die)
    else:
        dmg_raw = char_pmf(weapon.D)
        if dmg_rr:
            dmg_raw = reroll_low_damage(dmg_raw, *dmg_rr)
    if half and x_active(mech.melta):
        dmg_raw = convolve(dmg_raw, x_pmf(mech.melta))
    # Defender Damage modifiers (set / multiply / add / floor, in that
    # fixed order - see apply_damage_modifiers): applied to the final
    # Damage of each attack. This acts on the per-attack Damage
    # characteristic, so it also feeds the DEVASTATING mortal-wound
    # stream (mortals = Damage) built below.
    if has_damage_modifiers(mech):
        dmg_raw = transform(dmg_raw, lambda v: apply_damage_modifiers(v, mech))
    # DEVASTATING WOUNDS inflicts MORTAL WOUNDS, so every ability keyed
    # on mortal wounds bites on it: an invulnerable save or a Feel No
    # Pain "against mortal wounds" thins this stream exactly like any
    # other mortal wound, and that is what mw_save_thin / fnp_thin(mw=
    # True) below do. The ONE thing that sets these mortal wounds apart
    # is how they are allocated - they do not spill from a destroyed
    # model to the next - which changes no damage total and is picked up
    # only by the kill chain, through mw_spills.
    crit_mw = mech.crit_mw
    mw_spills = crit_mw is not None and crit_mw.get("spill", True)
    if mech.devastating and crit_mw is None:
        crit_mw = {"value": None, "match": True, "end": True}
    mw_raw = (dmg_raw if (crit_mw or {}).get("match", True)
              else delta((crit_mw or {}).get("value") or 1))
    hitmw_raw = None
    if mech.hitroll_mw:
        hitmw_raw = (dmg_raw if mech.hitroll_mw["match"]
                     else delta(mech.hitroll_mw["value"] or 1))

    def fnp_thin(pmf, mw: bool):
        fnp, fnp_mod = effective_fnp(defender_ref, mech, mw)
        if not fnp:
            return pmf
        eff = fnp - fnp_mod               # FNP: no cap (like saves, 11th)
        p_ig = min(5.0 / 6.0, max(0.0, (7 - eff) / 6.0))
        times = rules_config.CAP_REROLLS
        if mech.reroll_fnp and times > 0 and p_ig > 0:
            P, cont = 0.0, 1.0
            for _ in range(times + 1):
                P += cont * p_ig
                cont *= ((1.0 - p_ig) if mech.reroll_fnp == "fails"
                         else 1.0 / 6.0)
            p_ig = min(P, 5.0 / 6.0)
        return binomial_thin(pmf, 1.0 - p_ig)

    def mw_save_thin(pmf):
        """An invulnerable save that applies to mortal wounds (they
        ignore armour, so nothing else can stop them bar Feel No Pain).
        Rolled per mortal wound, the way they are allocated, and before
        FNP."""
        if mech.invuln_mw is None:
            return pmf
        p_ok = _p_save_roll(
            rules_config.clamp_characteristic("invuln", mech.invuln_mw),
            invuln_mod, mech.reroll_invuln, rules_config.CAP_REROLLS)
        return binomial_thin(pmf, 1.0 - p_ok)

    w_ref = defender_ref.get("W") or 1
    streams = {}
    hmw_spills = bool(mech.hitroll_mw) and mech.hitroll_mw.get("spill", True)
    for name, raw, is_mw, spills in (("n", dmg_raw, False, False),
                                     ("mw", mw_raw, True, mw_spills),
                                     ("hmw", hitmw_raw, True, hmw_spills)):
        if raw is None:
            continue
        thinned = fnp_thin(mw_save_thin(raw) if is_mw else raw, is_mw)
        streams[name] = {
            "damage": thinned,
            "damage_net": transform(thinned, lambda v: min(v, w_ref)),
            "wounds": transform(thinned, lambda v: 1 if v > 0 else 0)}
        # Allocation view. A stream that SPILLS contributes its damage
        # to a pool spent at the end of the activation, one point at a
        # time; a stream that does not contributes one allocation EVENT,
        # whose size is drawn later from that stream's event law and
        # capped by the wounds left on the model it lands on.
        axis = (AX_POOL if spills else
                AX_DEV if is_mw else AX_NORM)
        streams[name]["alloc"] = jleaf(
            thinned if spills else streams[name]["wounds"], axis)

    def _no_fail(pmf, pf):
        """'pmf' conditioned on this attack's die NOT failing. The failed
        branch contributes exactly 0, so it is the mass pf sitting at
        index 0; remove it and renormalise."""
        out = list(pmf)
        out[0] = max(0.0, out[0] - pf)
        scale = 1.0 - pf
        return [v / scale for v in out]

    def _combine(power, power_ok, w0, extra):
        """Base over n attacks, plus the extra die exactly when at least
        one of those n dice failed. Splitting on that event is what keeps
        the two CORRELATED: the extra never lands on a sequence where
        nothing failed, and those sequences are also the ones with the
        most damage."""
        size = max(len(power), len(power_ok))
        rest = []
        for i in range(size):
            a = power[i] if i < len(power) else 0.0
            b = power_ok[i] if i < len(power_ok) else 0.0
            rest.append(max(0.0, a - w0 * b))
        tail = convolve(rest, extra)
        out = [0.0] * max(len(tail), len(power_ok))
        for i, v in enumerate(power_ok):
            out[i] += w0 * v
        for i, v in enumerate(tail):
            out[i] += v
        return out

    # ONE re-roll for the whole activation (mech.single_reroll): the
    # player re-rolls a FAILED die, which is always the best use of it.
    # Exactly: with probability q_n = 1 - (1 - p_fail)^n over n attacks
    # at least one such die failed, and re-rolling it adds one fresh
    # outcome - a whole attack for a hit re-roll, a wound roll onwards
    # for a wound one. Everything else in the sequence is untouched, so
    # the total is the base chain convolved with that single extra.
    # (Bonus dice from SUSTAINED HITS are not counted among the dice
    # that may have failed: they are hits, not hit rolls.)
    single_extra = {}

    def _with_extras(base, count, unit, ops=(mix, convolve)):
        """*base* plus *count* further copies of *unit*, where count may
        itself be a die: mix over its PMF, the same way the total mixes
        over the number of attacks. 'ops' is the (mix, convolve) pair of
        the value algebra in use - the scalar one by default, the joint
        (mortal, normal) one for the allocation chain."""
        _mix, _conv = ops
        if not x_active(count):
            return base
        n_pmf, cur, parts = x_pmf(count), base, []
        for k, pk in enumerate(n_pmf):
            if pk:
                parts.append((pk, cur))
            if k < len(n_pmf) - 1:
                cur = _conv(cur, unit)
        return _mix(parts)

    per_attack_cache = {}

    def build_chain(key):
        """Per-attack outcome PMF for one metric ('damage',
        'damage_net', 'wounds' or 'alloc'). The first three are scalar
        PMFs; 'alloc' runs the very same branch structure over joint
        (mortal, normal) pairs, which is what the kill count needs."""
        joint = key == "alloc"
        _mix, _conv = (jmix, jconvolve) if joint else (mix, convolve)
        ops = (_mix, _conv)
        zero = jdelta() if joint else delta(0)
        leaf_n = streams["n"][key]
        leaf_mw = streams["mw"][key]
        after_save = _mix([(p_unsaved, leaf_n), (1 - p_unsaved, zero)])
        after_save_crit = _mix([(p_unsaved_crit, leaf_n),
                                (1 - p_unsaved_crit, zero)])
        if crit_mw:
            cw_leaf = (leaf_mw if crit_mw["end"]
                       else _conv(leaf_mw, after_save_crit))
        else:
            cw_leaf = after_save_crit
        # EXTRA WOUNDS: a scored wound yields X more (extra_wounds on
        # any wound, extra_wounds_crit on a critical one). They are not
        # rolled, so they are always NORMAL wounds - even the ones a
        # critical wound generated, and even when the critical branch
        # ends the sequence for itself.
        nw_branch = _with_extras(after_save, mech.extra_wounds, after_save,
                                 ops)
        # A critical wound collects both kinds of bonus. Stacking them as
        # two successive draws, rather than summing the two X values, is
        # what the rules describe when they come from two abilities: each
        # rolls its own die.
        cw_branch = _with_extras(
            _with_extras(cw_leaf, mech.extra_wounds, after_save, ops),
            mech.extra_wounds_crit, after_save, ops)
        per_hit = _mix([(q_nw, nw_branch), (q_cw, cw_branch),
                        (1 - q_w, zero)])
        if mech.lethal_crit:
            crit_hit_base = cw_branch
        elif mech.lethal:
            crit_hit_base = nw_branch
        else:
            crit_hit_base = per_hit
        # SUSTAINED HITS: bonus hits on a CRITICAL hit only.
        crit_branch = _with_extras(crit_hit_base, mech.sustained, per_hit,
                                   ops)
        # EXTRA HITS: bonus hits on ANY successful hit. Both kinds of
        # bonus hit are hits, not hit rolls, so they are never critical
        # and never generate extras of their own - which is why the unit
        # convolved in is per_hit and not the branch itself.
        norm_branch = _with_extras(per_hit, mech.extra_hits, per_hit, ops)
        crit_branch = _with_extras(crit_branch, mech.extra_hits, per_hit,
                                   ops)
        pairs = [(p_norm_hit, norm_branch), (p_crit_hit, crit_branch),
                 (1 - p_hit - p_mw_hit, zero)]
        if p_mw_hit:
            pairs.append((p_mw_hit, streams["hmw"][key]))
        per_attack = _mix(pairs)
        if mech.single_reroll == "hit":
            # a failed hit roll, re-rolled into a whole fresh attack
            single_extra[key] = (per_attack,
                                 max(0.0, 1 - p_hit - p_mw_hit))
        elif mech.single_reroll == "wound":
            # a failed wound roll: only the hits that actually rolled to
            # wound can fail (LETHAL HITS turns criticals into automatic
            # wounds, so those never roll).
            rolled = p_norm_hit if (mech.lethal or mech.lethal_crit) \
                else p_hit
            single_extra[key] = (per_hit, rolled * max(0.0, 1 - q_w))
        per_attack_cache[key] = per_attack
        return per_attack

    # ---- totals: mixture over the number of attacks ----
    out = {"attacks_pmf": attacks_pmf,
           "attacks": pmf_stats(attacks_pmf)}
    # Audit trail: the numbers the chain ACTUALLY used, recorded here
    # rather than recomputed by a reader, so what the interface shows
    # cannot drift from what was calculated. Formatting lives in the
    # audit module; this is raw material.
    _fnp_v, _fnp_m = effective_fnp(defender_ref, mech, False)
    out["audit"] = {
        "weapon": weapon.name, "count": weapon.count,
        "type": weapon.type,
        "attacks": {"expr": str(weapon.A), "mean": pmf_stats(attacks_pmf)["mean"],
                    "mod": mech.attacks_mod,
                    "rapid_fire": mech.rapid_fire if half else 0,
                    "blast": mech.blast or mech.cleave},
        "hit": {"auto": bool(mech.torrent or mech.auto_hit
                             or skill.is_none()),
                "skill": skill.value(), "target": skill_target,
                "mod": hit_mod, "unmod_min": unmod_min,
                "crit_on": crit_hit_on, "reroll": reroll_hit,
                "overwatch": ow, "cover": bool(
                    (ctx.get("cover") or mech.cover or indirect)
                    and not mech.ignores_cover and weapon.type != "Melee"),
                "p": p_hit, "p_crit": p_crit_hit, "p_mw": p_mw_hit},
        "wound": {"S": s, "T": t, "target": wt, "mod": wound_mod,
                  "crit_on": crit_wound_on, "reroll": reroll_wound,
                  "auto": bool(mech.auto_wound),
                  "p": q_w, "p_crit": q_cw},
        "save": {"Sv": defender_ref["Sv"], "ap": ap, "ap_crit": ap_crit,
                 "invuln": effective_invuln(defender_ref, mech),
                 "mod": save_mod, "invuln_mod": invuln_mod,
                 "reroll": mech.reroll_save,
                 "p_unsaved": p_unsaved, "p_unsaved_crit": p_unsaved_crit},
        "fnp": {"value": _fnp_v, "mod": _fnp_m,
                "mw_only": mech.fnp_mw or mech.fnp_set_mw,
                "invuln_mw": mech.invuln_mw},
        "damage": {"expr": str(weapon.D), "mean": pmf_stats(dmg_raw)["mean"],
                   "melta": mech.melta if half else 0},
        "mechanics": active_mechanics(mech, ctx),
        "warnings": list(mech.warnings)}
    for key in ("damage", "damage_net", "wounds"):
        pa = build_chain(key)
        extra_pmf, p_fail = single_extra.get(key, (None, 0.0))
        single = extra_pmf is not None and 0.0 < p_fail < 1.0
        pa_ok = _no_fail(pa, p_fail) if single else None
        power, power_ok, acc = delta(0), delta(0), []
        for n, pn in enumerate(attacks_pmf):
            if pn:
                if single and n:
                    acc.append((pn, _combine(power, power_ok,
                                             (1.0 - p_fail) ** n,
                                             extra_pmf)))
                else:
                    acc.append((pn, power))
            if n < len(attacks_pmf) - 1:
                power = convolve(power, pa)
                if single:
                    power_ok = convolve(power_ok, pa_ok)
        total = mix(acc)
        out[key + "_pmf"] = total
        out[key] = pmf_stats(total)
    if alloc:
        # Not folded into a total here: how the attacks land on MODELS
        # depends on the state of the target unit, which only the caller
        # knows (it may already have been shot at by another weapon), so
        # the per-attack law is handed over as it is.
        #
        # Two paths. The cheap one: when nothing spills AND the
        # devastating events follow the same damage law as the ordinary
        # ones, every event of this weapon is interchangeable, so the
        # attack is fully described by HOW MANY events it produced -
        # which is the 'wounds' chain, already built above. No joint
        # PMF, no extra cost, and that covers almost every weapon in a
        # real roster. Otherwise the three axes must stay correlated
        # and the joint chain is built instead.
        ev_norm = _event_damage(streams["n"]["damage"], w_ref)
        ev_dev = (_event_damage(streams["mw"]["damage"], w_ref)
                  if crit_mw and not mw_spills else None)
        spills = bool(mw_spills or hmw_spills)
        joint = spills or (ev_dev is not None
                           and not _pmf_equal(ev_dev, ev_norm))
        key = "alloc" if joint else "wounds"
        pa = per_attack_cache.get(key) or build_chain(key)
        extra, p_fail = single_extra.get(key, (None, 0.0))
        single = None
        if extra is not None and 0.0 < p_fail < 1.0:
            single = {"extra": extra, "p_fail": p_fail,
                      "per_attack_ok": (jno_fail(pa, p_fail) if joint
                                        else _no_fail(pa, p_fail))}
        out["alloc"] = {"per_attack": pa, "joint": joint,
                        "event_damage": ev_norm,
                        "event_damage_dev": ev_dev or ev_norm,
                        "attacks_pmf": attacks_pmf, "single": single}
    out["warnings"] = list(mech.warnings)
    return out


def analyze_weapon_best(weapon, defender_ref: dict, ctx: dict, mech,
                        alloc: bool = False):
    """analyze_weapon(), but taking the better side of the ONE choice the
    11th-ed. rules leave the attacker mid-sequence: LETHAL HITS is
    optional ("you can"), and using it turns a critical hit into an
    ordinary automatic wound - which LOSES damage when the weapon also
    has ANTI-X or DEVASTATING WOUNDS, because an automatic wound is not
    a critical wound.

    Returns (result, note): 'note' is None when nothing was declined,
    otherwise a short string naming the ability that was passed up and
    what it was worth. Callers that must follow the user's selection
    literally should keep calling analyze_weapon()."""
    res = analyze_weapon(weapon, defender_ref, ctx, mech, alloc)
    if not mech.lethal:
        return res, None
    alt_mech = mech.copy()
    alt_mech.lethal = False
    alt = analyze_weapon(weapon, defender_ref, ctx, alt_mech, alloc)
    gain = alt["damage"]["mean"] - res["damage"]["mean"]
    if gain > 1e-9:
        return alt, f"LETHAL HITS declined (+{gain:.2f} damage without it)"
    return res, None


def hazardous_damage_per_fail(keywords) -> int:
    """11th ed.: a failed Hazardous test (a d6 roll of 1-2) deals 3
    damage to a MONSTER or VEHICLE, 1 damage otherwise. 'keywords' are
    the FIRING unit's keywords."""
    kw = {str(k).upper() for k in (keywords or [])}
    return 3 if (kw & {"MONSTER", "VEHICLE"}) else 1


def hazardous_self_damage_mean(count: int, dmg_per_fail: int = 1) -> float:
    """Mean self-damage (11th ed.): per weapon copy, a d6 roll of 1-2
    fails the Hazardous test and deals dmg_per_fail damage. The median
    is 0 and is intentionally not reported."""
    return max(1, count) * (2.0 / 6.0) * dmg_per_fail
