"""Exact analytic attack mathematics.

Computes the EXACT probability distribution (PMF) of the outcome of a
shooting/fight sequence, by composing the per-attack outcome tree and
convolving over the number of attacks. No Monte Carlo is involved;
medians and any percentile are read off the exact CDF. Monte Carlo is
used only in the test suite as a cross-validation oracle.

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
        self.fnp_mw = None          # FNP applying to mortal wounds only
        self.dmg_reroll = None      # (lo, hi) damage re-roll range
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
        self.ignore_malus = set()   # subset of {hit, wound, save,
        #                             invuln, fnp}
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
             "INDIRECT FIRE": "indirect"}
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
}

# Abilities offered as "add to every attack" in the attack setup: the
# token is what parse_weapon_keywords() will read, so numeric ones carry
# their default X.
ADDABLE_ABILITIES = ["LETHAL HITS", "DEVASTATING WOUNDS", "SUSTAINED HITS 1",
                     "TWIN-LINKED", "HEAVY", "LANCE", "IGNORES COVER",
                     "TORRENT", "MELTA 2", "RAPID FIRE 1", "BLAST 1",
                     "PSYCHIC"]


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
_KW_IGNORED = {"PISTOL", "EXTRA ATTACKS", "ASSAULT", "ONE SHOT",
               "PRECISION"}
_ANTI_RE = re.compile(r"^ANTI[- ]([A-Z' ]+?)\s+(\d)\+?$")


def parse_weapon_keywords(keywords, mech: WeaponMechanics):
    """Parse weapon keywords (e.g. Sustained Hits, Lethal Hits, Devastating Wounds, Torrent, Blast) into the WeaponMechanics flags that drive the damage maths."""
    for kw in keywords or []:
        kw = kw.strip().upper()
        m = _ANTI_RE.match(kw)
        if m:
            mech.anti.append((m.group(1).strip(), int(m.group(2))))
            continue
        matched = False
        for name, attr in _KW_NUMERIC.items():
            if kw.startswith(name):
                tail = kw[len(name):].strip()
                try:
                    setattr(mech, attr, int(tail) if tail else 1)
                except ValueError:
                    mech.warnings.append(f"bad value in keyword '{kw}'")
                matched = True
        if matched:
            continue
        if kw in _KW_FLAGS:
            setattr(mech, _KW_FLAGS[kw], True)
        elif kw == "PSYCHIC":
            # 11th ed.: psychic attacks ignore negative modifiers to the
            # hit roll (BS/WS). Modelled via the shared ignore-malus set.
            mech.ignore_malus.add("hit")
        elif kw in _KW_IGNORED or not kw:
            pass
        else:
            mech.warnings.append(f"unsupported keyword '{kw}' (ignored)")


# ---------------- effect-string parsing ----------------

_ROLL_RE = re.compile(r"^ROLL (HIT|WOUND|SAVE) (\d)([+\-=]) (UNMOD|MOD)$")
_CHAR_RE = re.compile(r"^CHAR (S|A|AP|D) (GT|LT|EQ|GE|LE) (-?\d+) "
                      r"(MOD|UNMOD)$")
_RANGE_RE = re.compile(r"^REROLL DAMAGE RANGE \[(\d+),\s*(\d+)\]$")


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
           "end": "END_SEQUENCE" in tokens}
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
        elif tok[0] == "REROLL" and tok[1] in ("HIT_ROLL", "WOUND_ROLL"):
            kind = "reroll_hit" if tok[1] == "HIT_ROLL" else "reroll_wound"
            what = {"FAILS": "fails", "1": "1"}.get(tok[2])
            if what is None:
                return False
            setattr(mech, kind, combine_reroll(getattr(mech, kind), what))
        elif _RANGE_RE.match(s):
            m = _RANGE_RE.match(s)
            mech.dmg_reroll = (int(m.group(1)), int(m.group(2)))
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
            mech.ignore_malus.add("hit")
        elif tok[0] == "IGNORECOVER":
            mech.ignores_cover = True
        elif tok[0] == "IGNOREMALUS" and len(tok) >= 2:
            roll = tok[1].lower()
            if roll in ("hit", "wound", "save", "invuln", "fnp"):
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
        elif tok[0] == "EXTRAATTACKS":
            pass                    # selection-level keyword, no maths
        elif tok[0] == "DISABLE":
            # disableMechanic: switch a weapon ability off for this attack
            disable_abilities(mech, [" ".join(tok[1:])],
                              lambda m: mech.warnings.append(m))
        else:
            return False
        return True
    # ---- single roll-time condition ----
    if dyn == ["CRIT_HIT"]:
        if tok[0] == "EXTRA_HITS":
            mech.sustained += int(tok[1])
        elif s == "OVERRIDE WOUND ALWAYS":
            mech.lethal = True
        elif s == "OVERRIDE WOUND ALWAYS CRIT":
            mech.lethal_crit = True
        else:
            return False
        return True
    if dyn == ["CRIT_WOUND"]:
        if tok[0] == "MORTAL_WOUNDS":
            mw = _parse_mw_payload(tok)
            if mw is None:
                return False        # CAP not modelled
            mech.crit_mw = mw
        elif tok[0] == "CHARMOD" and tok[1] == "AP":
            mech.crit_ap_delta += int(tok[2])
        else:
            return False
        return True
    if dyn == ["MW_ONLY"] and tok[0] == "SETFNP":
        v = int(tok[1])
        mech.fnp_mw = v if mech.fnp_mw is None else min(mech.fnp_mw, v)
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


def analyze_weapon(weapon, defender_ref: dict, ctx: dict,
                   mech: WeaponMechanics) -> dict:
    """Exact analysis of one weapon (view object) against a reference
    defender {'T','Sv','W','invuln','fnp','models','keywords'} with
    context flags {'half_range','stationary','charged','cover'}.

    Returns attacks/wounds/damage PMFs and their stats."""
    half = bool(ctx.get("half_range"))
    warn = mech.warnings.append

    # ---- number of attacks: A per copy (+rapid fire/blast), x count ----
    extra_a = (mech.rapid_fire if half else 0)
    # BLAST (ranged) and CLEAVE (melee) both add X attacks per 5 target
    # models; a weapon carries at most one of them.
    if mech.blast or mech.cleave:
        extra_a += (mech.blast + mech.cleave) \
            * max(0, defender_ref.get("models", 1) // 5)
    per_copy = char_pmf(weapon.A)
    if extra_a:
        per_copy = convolve(per_copy, delta(extra_a))
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
        if (ctx.get("cover") or indirect) and not mech.ignores_cover:
            skill_mod -= 1
        if ctx.get("plunging"):
            skill_mod += 1
    if "hit" in mech.ignore_malus:
        # PSYCHIC: "ignore any or all modifiers to that attack's BS or WS
        # characteristic and any or all modifiers to the hit roll" - the
        # best use of "any or all" is to drop the negatives and keep the
        # positives, in BOTH groups.
        hit_mod = max(0, hit_mod)
        skill_mod = max(0, skill_mod)
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
                                       0, reroll_hit,
                                       crit_on=mech.crit_hit_on)
    else:
        p_hit, p_crit_hit = roll_probs(skill_target, hit_mod, reroll_hit,
                                       crit_on=mech.crit_hit_on,
                                       unmod_min=unmod_min)
    p_norm_hit = p_hit - p_crit_hit

    # ---- wound stage ----
    s = weapon.S.value() or 0
    t = defender_ref["T"]
    wt = wound_target(s, t)
    wound_mod = mech.wound_mod + (1 if (mech.lance and ctx.get("charged"))
                                  else 0)
    if "wound" in mech.ignore_malus:
        wound_mod = max(0, wound_mod)
    wound_mod = _cap(wound_mod)
    crit_wound_on = mech.crit_wound_on
    for kw, x in mech.anti:
        if kw in (defender_ref.get("keywords") or set()):
            crit_wound_on = min(crit_wound_on, x)
    reroll_wound = combine_reroll("fails" if mech.twin_linked else None,
                                  mech.reroll_wound)
    q_w, q_cw = roll_probs(wt, wound_mod, reroll_wound,
                           crit_on=crit_wound_on)
    if mech.auto_wound:
        q_w, q_cw = 1.0, 0.0        # auto-wound: always a normal wound
    q_nw = q_w - q_cw

    # ---- saves (normal and crit-wound branch) ----
    ap = weapon.AP.value() or 0
    # Saving-throw modifiers are NOT capped (only hit and wound are).
    save_mod = (max(0, mech.save_mod) if "save" in mech.ignore_malus
                else mech.save_mod)
    invuln_mod = (max(0, mech.invuln_mod)
                  if "invuln" in mech.ignore_malus else mech.invuln_mod)
    common = (defender_ref["Sv"], save_mod, invuln_mod,
              mech.reroll_save, mech.reroll_invuln)

    def p_uns(ap_val):
        sv, smod, imod, srr, irr = common
        return save_fail_prob(sv, ap_val, defender_ref.get("invuln"),
                              smod, imod, srr, irr)

    p_unsaved = p_uns(ap)
    ap_crit = ap - abs(mech.crit_ap_delta)   # AP improves (more negative)
    p_unsaved_crit = p_uns(ap_crit) if mech.crit_ap_delta else p_unsaved

    # ---- damage PMFs (normal and mortal-wound streams) ----
    # The damage re-roll range refers to the DIE result, so it is
    # applied per-die, before the flat bonus and before MELTA.
    if mech.dmg_reroll and weapon.D.count:
        die = [0.0] + [1.0 / weapon.D.sides] * weapon.D.sides
        die = reroll_low_damage(die, *mech.dmg_reroll)
        dmg_raw = delta(max(weapon.D.flat, 0))
        for _ in range(weapon.D.count):
            dmg_raw = convolve(dmg_raw, die)
    else:
        dmg_raw = char_pmf(weapon.D)
        if mech.dmg_reroll:
            dmg_raw = reroll_low_damage(dmg_raw, *mech.dmg_reroll)
    if mech.melta and half:
        dmg_raw = convolve(dmg_raw, delta(mech.melta))
    # Defender Damage modifiers (set / multiply / add / floor, in that
    # fixed order - see apply_damage_modifiers): applied to the final
    # Damage of each attack. This acts on the per-attack Damage
    # characteristic, so it also feeds the DEVASTATING mortal-wound
    # stream (mortals = Damage) built below.
    if has_damage_modifiers(mech):
        dmg_raw = transform(dmg_raw, lambda v: apply_damage_modifiers(v, mech))
    crit_mw = mech.crit_mw
    if mech.devastating and crit_mw is None:
        crit_mw = {"value": None, "match": True, "end": True}
    mw_raw = (dmg_raw if (crit_mw or {}).get("match", True)
              else delta((crit_mw or {}).get("value") or 1))
    hitmw_raw = None
    if mech.hitroll_mw:
        hitmw_raw = (dmg_raw if mech.hitroll_mw["match"]
                     else delta(mech.hitroll_mw["value"] or 1))

    def fnp_thin(pmf, mw: bool):
        fnp = defender_ref.get("fnp")
        if mw and mech.fnp_mw is not None:
            fnp = mech.fnp_mw if fnp is None else min(fnp, mech.fnp_mw)
        if not fnp:
            return pmf
        fnp_mod = (max(0, mech.fnp_mod) if "fnp" in mech.ignore_malus
                   else mech.fnp_mod)
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

    w_ref = defender_ref.get("W") or 1
    streams = {}
    for name, raw, is_mw in (("n", dmg_raw, False), ("mw", mw_raw, True),
                             ("hmw", hitmw_raw, True)):
        if raw is None:
            continue
        thinned = fnp_thin(raw, is_mw)
        streams[name] = {
            "damage": thinned,
            "damage_net": transform(thinned, lambda v: min(v, w_ref)),
            "wounds": transform(thinned, lambda v: 1 if v > 0 else 0)}

    def build_chain(key):
        """Per-attack outcome PMF for one metric ('damage',
        'damage_net' or 'wounds')."""
        zero = delta(0)
        leaf_n = streams["n"][key]
        leaf_mw = streams["mw"][key]
        after_save = mix([(p_unsaved, leaf_n), (1 - p_unsaved, zero)])
        after_save_crit = mix([(p_unsaved_crit, leaf_n),
                               (1 - p_unsaved_crit, zero)])
        if crit_mw:
            cw_leaf = (leaf_mw if crit_mw["end"]
                       else convolve(leaf_mw, after_save_crit))
        else:
            cw_leaf = after_save_crit
        per_hit = mix([(q_nw, after_save), (q_cw, cw_leaf),
                       (1 - q_w, zero)])
        if mech.lethal_crit:
            crit_hit_base = cw_leaf
        elif mech.lethal:
            crit_hit_base = after_save
        else:
            crit_hit_base = per_hit
        crit_branch = crit_hit_base
        for _ in range(mech.sustained):
            crit_branch = convolve(crit_branch, per_hit)
        pairs = [(p_norm_hit, per_hit), (p_crit_hit, crit_branch),
                 (1 - p_hit - p_mw_hit, zero)]
        if p_mw_hit:
            pairs.append((p_mw_hit, streams["hmw"][key]))
        return mix(pairs)

    # ---- totals: mixture over the number of attacks ----
    out = {"attacks_pmf": attacks_pmf,
           "attacks": pmf_stats(attacks_pmf)}
    for key in ("damage", "damage_net", "wounds"):
        pa = build_chain(key)
        power, acc = delta(0), []
        for n, pn in enumerate(attacks_pmf):
            if pn:
                acc.append((pn, power))
            if n < len(attacks_pmf) - 1:
                power = convolve(power, pa)
        total = mix(acc)
        out[key + "_pmf"] = total
        out[key] = pmf_stats(total)
    out["warnings"] = list(mech.warnings)
    return out


def analyze_weapon_best(weapon, defender_ref: dict, ctx: dict, mech):
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
    res = analyze_weapon(weapon, defender_ref, ctx, mech)
    if not mech.lethal:
        return res, None
    alt_mech = mech.copy()
    alt_mech.lethal = False
    alt = analyze_weapon(weapon, defender_ref, ctx, alt_mech)
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
