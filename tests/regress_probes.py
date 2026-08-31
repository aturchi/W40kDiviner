"""Shared fixtures and helpers for the regression digest (test_regress.py).

Everything here is DATA-SOURCE AGNOSTIC: the probe units, the context
flag sets and the ability-isolation machinery are defined in code, so
the real and the synthetic digests exercise the engine through exactly
the same lens and only the roster under test differs.

Why probes at all: an ability only shows up in the numbers when the
attack it modifies is one it applies to. A single defender cannot
trigger a keyword-gated ability (ANTI-VEHICLE-style conditions), a
damage reduction (needs a multi-damage attack) or an invulnerable save
(needs AP), so the abilities were silently untested. The probe matrix
below spans those cases:

  defenders -- light infantry, armoured elite with invuln + FNP, high
    Toughness vehicle, monster, and a FLY flyer (keyword conditions);
  attackers -- massed light fire, a single high-AP high-Damage shot
    (damage reduction / invuln bite here), and a PSYCHIC weapon.

Ability isolation: for a target ability the unit is analysed twice --
once with EVERY ability disabled, once with only the target enabled --
so the reported delta belongs to that ability alone and never to the
sum of whatever else the datasheet carries.
"""
import copy

import testpaths                        # puts src/ on sys.path
import analyzer_core as ac
import unit_model as um


# Ability lists a unit dict may carry. core/faction abilities are folded
# into unit.abilities at Unit construction, so they count here too.
ABILITY_LISTS = ("abilities", "core_abilities", "faction_abilities",
                 "leader_effects")


# --- Probe units ---------------------------------------------------------

def _weapon(name, wtype, A, skill, S, AP, D, count=1, rng=None, kws=None,
            abilities=None):
    w = {"name": name, "type": wtype, "RNG": rng, "A": A, "S": S, "AP": AP,
         "D": D, "count": count, "keywords": list(kws or []),
         "abilities": list(abilities or [])}
    w["BS" if wtype == "Ranged" else "WS"] = skill
    return w


# A critical wound inflicting a SPILLING mortal wound. DEVASTATING
# WOUNDS inflicts mortal wounds too, and the mortal-wound-only abilities
# bite on both, so that is not what sets them apart: a devastating
# mortal wound is allocated like ordinary damage and does NOT spill from
# a destroyed model to the next, while this one does. The pool it builds
# is the path Probe Lance cannot reach.
CRIT_MORTAL = {
    "name": "Probe mortal spike",
    "description": "Each time an attack made with this weapon scores a "
                   "Critical Wound, the target suffers 1 mortal wound "
                   "and the attack sequence ends.",
    "enabled": True,
    "conditions": [{"text": "Critical hit/wound", "type": "crit",
                    "data": {"crit": {"title": "Critical wound",
                                      "key": "woundRoll"}}}],
    "effect": {"text": "Mortal wounds", "type": "mortalWounds",
               "data": {"mortalWoundsValue": "1",
                        "attackSequenceEnds": True}},
    "id": "probecritmortal0000000000000001"}


def _model(name, count, T, Sv, W, weapons, invuln=None, fnp=None, kws=None):
    return {"name": name, "model_count": count, "M": 6, "T": T, "Sv": Sv,
            "W": W, "LD": 6, "OC": 1, "invuln": invuln, "fnp": fnp,
            "keywords": list(kws or []), "abilities": [], "weapons": weapons}


def _unit(name, points, models, keywords=None, abilities=None):
    return {"name": name, "profile_name": name, "points": points,
            "keywords": list(keywords or []) + [name],
            "abilities": list(abilities or []),
            "leader_effects": [], "models": models}


# Defenders: one per defensive archetype the roster abilities key off.
PROBE_DEFENDERS = [
    _unit("Probe Infantry", 100,
          [_model("Probe Trooper", 10, 4, 3, 2,
                  [_weapon("Probe rifle", "Ranged", 2, 3, 4, -1, 1,
                           count=10, rng=24),
                   _weapon("Probe blade", "Melee", 2, 3, 4, 0, 1,
                           count=10)])],
          keywords=["INFANTRY"]),
    _unit("Probe Elite", 150,
          [_model("Probe Veteran", 5, 5, 2, 3,
                  [_weapon("Probe bolter", "Ranged", 2, 3, 5, -2, 2,
                           count=5, rng=24),
                   _weapon("Probe hammer", "Melee", 3, 3, 8, -2, 2,
                           count=5)],
                  invuln=4, fnp=5)],
          keywords=["INFANTRY", "CHARACTER"]),
    _unit("Probe Vehicle", 200,
          [_model("Probe Hull", 1, 10, 2, 14,
                  [_weapon("Probe cannon", "Ranged", 3, 3, 10, -3, 3,
                           count=1, rng=48),
                   _weapon("Probe ram", "Melee", 3, 4, 8, -1, 2, count=1)],
                  invuln=5)],
          keywords=["VEHICLE"]),
    _unit("Probe Monster", 190,
          [_model("Probe Beast", 1, 9, 3, 12,
                  [_weapon("Probe spines", "Ranged", 4, 4, 6, -1, 2,
                           count=1, rng=24),
                   _weapon("Probe claws", "Melee", 5, 3, 9, -2, 3,
                           count=1)],
                  invuln=4)],
          keywords=["MONSTER"]),
    # Real datasheets gate abilities on TITANIC, TOWERING and
    # FORTIFICATION (Stormsurge's Titan-killer, Typhon's Sunderer of
    # Fortresses). Without a probe carrying them those abilities look
    # dead when they are merely untargeted, so one deliberately
    # over-keyworded colossus stands in for all three.
    _unit("Probe Colossus", 400,
          [_model("Probe Bastion", 1, 12, 2, 22,
                  [_weapon("Probe battery", "Ranged", 6, 4, 12, -3, 3,
                           count=1, rng=48),
                   _weapon("Probe stomp", "Melee", 4, 4, 12, -2, 4,
                           count=1)],
                  invuln=5)],
          keywords=["VEHICLE", "TITANIC", "TOWERING", "FORTIFICATION"]),
    _unit("Probe Flyer", 180,
          [_model("Probe Airframe", 1, 9, 3, 12,
                  [_weapon("Probe autocannon", "Ranged", 4, 3, 9, -2, 3,
                           count=1, rng=48),
                   _weapon("Probe talons", "Melee", 3, 4, 6, -1, 2,
                           count=1)],
                  invuln=5)],
          keywords=["VEHICLE", "FLY", "AIRCRAFT"]),
]

# Attackers: one per offensive archetype. 'Probe Lance' is the one that
# makes damage reduction and invulnerable saves observable; 'Probe
# Psyker' carries a PSYCHIC weapon so psychicAttack conditions fire.
PROBE_ATTACKERS = [
    _unit("Probe Shooter", 120,
          [_model("Probe Gunner", 10, 4, 3, 2,
                  [_weapon("Probe volley gun", "Ranged", 3, 3, 5, -1, 1,
                           count=10, rng=24),
                   _weapon("Probe combat blade", "Melee", 3, 3, 5, -1, 1,
                           count=10)])],
          keywords=["INFANTRY"]),
    # DEVASTATING WOUNDS: mortal wounds that no saving throw can stop
    # and that do not spill. The mortal-wound-only abilities bite on
    # them; the SPILLING kind is probed on Probe Psyker instead (see
    # CRIT_MORTAL), since the two are allocated differently.
    _unit("Probe Lance", 170,
          [_model("Probe Gun Platform", 1, 9, 2, 10,
                  [_weapon("Probe lance", "Ranged", 2, 3, 14, -4, 6,
                           count=1, rng=48,
                           kws=["Devastating Wounds"]),
                   _weapon("Probe siege fist", "Melee", 3, 3, 12, -3, 4,
                           count=1, kws=["Devastating Wounds"])],
                  invuln=5)],
          keywords=["VEHICLE"]),
    _unit("Probe Psyker", 110,
          [_model("Probe Adept", 1, 4, 3, 4,
                  [_weapon("Probe mindburn", "Ranged", 4, 3, 8, -2, 2,
                           count=1, rng=18, kws=["PSYCHIC"],
                           abilities=[CRIT_MORTAL]),
                   _weapon("Probe force stave", "Melee", 4, 3, 8, -2, 2,
                           count=1, kws=["PSYCHIC"],
                           abilities=[CRIT_MORTAL])],
                  invuln=4)],
          keywords=["INFANTRY", "PSYKER", "CHARACTER"]),
]


# --- Corner probes: the paths the ROSTER fixture does not reach ----------

# The digest is only a safety net over the paths its fixture walks, and
# three of them the curated rosters never do. Measured on this fixture:
# 894 allocations built, 26 of them joint, 3 with any mass on the
# devastating axis - and all 3 against a single-model target, where the
# allocation order cannot move a figure by construction; and 908 weapons
# analysed, 901 carrying no damage modifier at all, the other 7 all the
# same isolated 'add -1', with no halving and no melta bonus anywhere
# near them. So a digest that did not change proved nothing about those
# paths, and said so three times in a row without anyone able to tell.
#
# The units below exist to make those paths reachable. They are probes,
# not plausible datasheets: each one carries the least that makes one
# path observable, and nothing else.

def _cond_defender():
    return {"text": "Profile role", "type": "profileRole",
            "data": {"profileRole": "Defender", "negate": False},
            "preselected": False}


# Feel No Pain that answers MORTAL WOUNDS only - the shape the real
# rosters use (Recitation of Faith, Advanced Armour). Against a weapon
# with DEVASTATING WOUNDS this is what gives the devastating events a
# damage law of their own, which is what makes the allocation ORDER
# observable: without it the two kinds of event are interchangeable and
# the order cannot matter.
MW_ONLY_FNP = {
    "name": "Probe mortal ward",
    "description": "Feel No Pain 4+, against mortal wounds only.",
    "enabled": True, "share_with_unit": False,
    "conditions": [_cond_defender(),
                   {"text": "Wound type", "type": "woundType",
                    "data": {"woundType": {"title": "Mortal wounds",
                                           "key": "mortalWounds"},
                             "negate": False}, "preselected": False}],
    "effect": {"text": "Feel no pain", "type": "feelNoPain",
               "data": {"operator": {"title": "Grant (best wins)",
                                     "key": "grant"}, "value": "4"}},
    "id": "probemortalward0000000000000001"}


def _damage_mod(name, op_key, op_title, value, ident):
    return {"name": name, "enabled": True, "share_with_unit": False,
            "description": f"Damage modifier: {op_title} {value}.",
            "conditions": [_cond_defender()],
            "effect": {"text": "Damage modifier (defender)",
                       "type": "damageReduction",
                       "data": {"operator": {"title": op_title,
                                             "key": op_key},
                                "value": str(value)}},
            "id": ident}


# Halving and blunting, as two separate abilities so the digest can show
# each alone and both together. Every damageReduction in the curated
# rosters is the second one; the first, and the pair, are unreached.
DMG_HALVE = _damage_mod("Probe halving", "mult", "Multiply", 0.5,
                        "probedamagehalve000000000000001")
DMG_BLUNT = _damage_mod("Probe blunting", "add", "Add (e.g. -1)", -1,
                        "probedamageblunt000000000000001")
# The two spellings that TELL THE FIVE-STEP ORDER APART. Halving with a
# subtraction, and a melta bonus with a halving, give the same answer
# under any ordering - ceil(x) + a == ceil(x + a) for integer a - so the
# probes above walk the code without measuring it. These two do measure
# it: a SET deletes a bonus applied before it but not one applied at
# step 3, and a POSITIVE modifier lands on the far side of a division
# depending on which step it belongs to.
DMG_SET_ONE = _damage_mod("Probe damping", "set", "Set", 1,
                          "probedamageset10000000000000001")
DMG_BOOST = _damage_mod("Probe overload", "add", "Add (e.g. -1)", 1,
                        "probedamageboost00000000000001")


CORNER_DEFENDERS = [
    # MULTI-MODEL, and with wounds to spare per model: the allocation
    # order can only show up when a devastating event can be wasted on a
    # model an ordinary one already hurt, which needs W > 1 and n > 1.
    _unit("Probe Warden", 140,
          [_model("Probe Sentinel", 5, 5, 3, 3,
                  [_weapon("Probe carbine", "Ranged", 3, 3, 5, -1, 1,
                           count=5, rng=24),
                   _weapon("Probe glaive", "Melee", 3, 3, 6, -1, 2,
                           count=5)])],
          keywords=["INFANTRY"], abilities=[MW_ONLY_FNP]),
    # Deep enough to survive several rounds of a melta, so the damage
    # figures are not all clipped by the model's own wounds.
    _unit("Probe Bulwark", 210,
          [_model("Probe Redoubt", 1, 10, 2, 16,
                  [_weapon("Probe mortar", "Ranged", 3, 4, 8, -1, 2,
                           count=1, rng=48),
                   _weapon("Probe fist", "Melee", 3, 4, 10, -2, 3,
                           count=1)],
                  invuln=5)],
          keywords=["VEHICLE"], abilities=[DMG_HALVE, DMG_BLUNT]),
    # Sets the incoming Damage to 1. Against a melta this is the case
    # that separates "the bonus is convolved in before the chain" (the
    # set deletes it, answer 1) from "the bonus is step 3" (it survives,
    # answer 3).
    _unit("Probe Nullifier", 190,
          [_model("Probe Nullstone", 1, 10, 2, 16,
                  [_weapon("Probe nullbeam", "Ranged", 3, 4, 8, -1, 2,
                           count=1, rng=48),
                   _weapon("Probe nullfist", "Melee", 3, 4, 10, -2, 3,
                           count=1)],
                  invuln=5)],
          keywords=["VEHICLE"], abilities=[DMG_SET_ONE]),
    # A POSITIVE Damage modifier and a halving on the same attack: the
    # addition belongs to step 3 and the halving to step 4, so the
    # addition happens FIRST. Doing it the other way round - halve, then
    # add - is the only other reading, and the two disagree.
    _unit("Probe Overloader", 200,
          [_model("Probe Resonator", 1, 10, 2, 16,
                  [_weapon("Probe resonance", "Ranged", 3, 4, 8, -1, 2,
                           count=1, rng=48),
                   _weapon("Probe resonant fist", "Melee", 3, 4, 10, -2, 3,
                           count=1)],
                  invuln=5)],
          keywords=["VEHICLE"], abilities=[DMG_BOOST, DMG_HALVE]),
]

CORNER_ATTACKERS = [
    # MELTA: the bonus lands on the Damage at half range, which is the
    # one place the attacker's own damage arithmetic meets the
    # defender's modifiers. The base Damage is deliberately ODD: with an
    # even one the four-step and the five-step orders agree by accident
    # on every case here, and the probe would watch the difference
    # without ever seeing it.
    _unit("Probe Melter", 160,
          [_model("Probe Burner", 1, 8, 3, 8,
                  [_weapon("Probe melta", "Ranged", 2, 3, 12, -4, 5,
                           count=1, rng=12, kws=["MELTA 2"]),
                   _weapon("Probe cutter", "Melee", 2, 3, 10, -3, 4,
                           count=1)],
                  invuln=5)],
          keywords=["INFANTRY"]),
    # Many small devastating events into a unit whose models take more
    # than one to kill: that is where allocating them attack by attack
    # instead of as a phase wastes a different amount, so this is the
    # probe that actually MEASURES the order rather than merely touching
    # the code path.
    _unit("Probe Stormlance", 180,
          [_model("Probe Gunhand", 10, 4, 3, 2,
                  [_weapon("Probe stormgun", "Ranged", 3, 3, 6, -2, 2,
                           count=10, rng=24, kws=["Devastating Wounds"]),
                   _weapon("Probe stormblade", "Melee", 3, 3, 6, -1, 2,
                           count=10, kws=["Devastating Wounds"])],
                  )],
          keywords=["INFANTRY"]),
]

# Half range on its own: the melta bonus without the dozen other
# positional conditions FLAGS_ON would switch on at the same time.
FLAGS_HALF = {"half_range": True}


def _by_name(pool, name):
    for unit in pool:
        if unit["name"] == name:
            return unit
    raise KeyError(name)


def corner_cases():
    """[(label, attacker_native, defender_native, mode, flags)] for the
    '## corners' digest section.

    Each path is printed WITH the ability and without it, using the same
    variant() machinery the ability probe uses, so the digest carries
    the delta and not just a number: a line that moves is attributable
    to the mechanic named in its label.
    """
    lance = _by_name(PROBE_ATTACKERS, "Probe Lance")
    melter = _by_name(CORNER_ATTACKERS, "Probe Melter")
    storm = _by_name(CORNER_ATTACKERS, "Probe Stormlance")
    warden = _by_name(CORNER_DEFENDERS, "Probe Warden")
    bulwark = _by_name(CORNER_DEFENDERS, "Probe Bulwark")
    nuller = _by_name(CORNER_DEFENDERS, "Probe Nullifier")
    overload = _by_name(CORNER_DEFENDERS, "Probe Overloader")
    halve, blunt = ("abilities", 0), ("abilities", 1)
    return [
        # 1. DEVASTATING WOUNDS into a multi-model defender that
        #    mitigates mortal wounds only. 'bare' is the same fight with
        #    the ward switched off: the two lines differ only by the
        #    devastating events having a damage law of their own, which
        #    is the whole of the allocation-order question.
        ("dev.ward.ranged", lance, warden, "ranged", FLAGS_OFF),
        ("dev.bare.ranged", lance, variant(warden), "ranged", FLAGS_OFF),
        ("dev.ward.melee", lance, warden, "melee", FLAGS_OFF),
        ("dev.bare.melee", lance, variant(warden), "melee", FLAGS_OFF),
        ("storm.ward.ranged", storm, warden, "ranged", FLAGS_OFF),
        ("storm.bare.ranged", storm, variant(warden), "ranged", FLAGS_OFF),
        ("storm.ward.melee", storm, warden, "melee", FLAGS_OFF),
        # 2. MELTA at half range against a defender that modifies the
        #    incoming Damage. 'far' is the same weapon out of melta
        #    range, so the bonus itself is readable off the pair.
        ("melta.near.bare", melter, variant(bulwark), "ranged", FLAGS_HALF),
        ("melta.far.bare", melter, variant(bulwark), "ranged", FLAGS_OFF),
        ("melta.near.blunt", melter, variant(bulwark, blunt), "ranged",
         FLAGS_HALF),
        ("melta.near.halve", melter, variant(bulwark, halve), "ranged",
         FLAGS_HALF),
        # 3. Halving and blunting TOGETHER, which is where their order
        #    decides the answer: on a Damage of 8, halve-then-blunt
        #    gives 3 and blunt-then-halve gives 4.
        ("melta.near.both", melter, bulwark, "ranged", FLAGS_HALF),
        ("melta.far.both", melter, bulwark, "ranged", FLAGS_OFF),
        # 4. The order of the five steps itself: a set against a melta
        #    bonus, and a positive modifier against a halving. Unlike
        #    everything above, these two DISAGREE between the four-step
        #    and the five-step model.
        ("order.set.near", melter, nuller, "ranged", FLAGS_HALF),
        ("order.set.far", melter, nuller, "ranged", FLAGS_OFF),
        ("order.boost.near", melter, overload, "ranged", FLAGS_HALF),
        ("order.boost.far", melter, overload, "ranged", FLAGS_OFF),
    ]


# --- Context flag sets ---------------------------------------------------

# Two fixed contexts. 'off' is the neutral baseline; 'on' turns on every
# positional condition at once so the abilities gated on them fire. An
# ability is probed under 'off' first and only falls back to 'on' when
# 'off' produced no observable delta, which keeps the digest readable
# while still covering the context-gated abilities.
FLAGS_OFF = {}
FLAGS_ON = {
    # 'cover' is a -1 BS modifier and 'damaged' a -1 hit-roll modifier:
    # both are needed, because ignoreMalus distinguishes the two.
    "half_range": True, "attacker_stationary": True, "charged": True,
    "cover": True, "damaged": True, "attacker_on_objective": True,
    "defender_on_objective": True, "attacker_below_half": True,
    "defender_below_half": True, "attacker_below_full": True,
    "defender_below_full": True, "attacker_in_engagement": True,
    "defender_in_engagement": True,
}
FLAGSETS = (("off", FLAGS_OFF), ("on", FLAGS_ON))

# Attack modes the ability probe runs. close_quarters is here because
# some abilities (the close-quarters hit penalty, CLOSE-QUARTERS weapon
# selection) exist only in that mode.
PROBE_MODES = ("ranged", "melee", "close_quarters")

# Flags swept ONE AT A TIME by the '## flags' digest section, so a change
# in any single context path is attributable.
SINGLE_FLAGS = [
    "half_range", "attacker_stationary", "charged", "cover", "plunging",
    "damaged", "attacker_below_half", "defender_below_half",
    "attacker_below_full", "defender_below_full", "attacker_on_objective",
    "defender_on_objective", "overwatch",
]


# --- Roster pairings -----------------------------------------------------

# Attacker/defender pairs for the '## damage' section, given as
# (army_key, unit_name) with army_key in {'sm', 'tau'}. Only names that
# exist in BOTH the real and the synthetic roster are used, so the two
# digests cover the same matchups. The set spans: volume fire vs armour
# + FNP, melee vs armour, walker vs monster, vehicle AT vs infantry,
# infantry AP vs high Toughness, character vs invulnerable elite, big
# blast vs horde, and melta vs walker.
PAIRS = [
    (("sm", "Intercessor Squad"), ("sm", "Terminator Squad")),
    (("sm", "Assault Intercessor Squad"), ("sm", "Terminator Squad")),
    (("sm", "Redemptor Dreadnought"), ("tau", "Riptide Battlesuit")),
    (("sm", "Ballistus Dreadnought"), ("tau", "Crisis Sunforge")),
    (("sm", "Terminator Squad"), ("tau", "Hammerhead Gunship")),
    (("sm", "Captain"), ("sm", "Bladeguard Veteran Squad")),
    (("sm", "Bladeguard Veteran Squad"), ("sm", "Intercessor Squad")),
    (("tau", "Hammerhead Gunship"), ("sm", "Intercessor Squad")),
    (("tau", "Riptide Battlesuit"), ("sm", "Assault Intercessor Squad")),
    (("tau", "Crisis Sunforge"), ("sm", "Ballistus Dreadnought")),
]

# The pair used by the '## flags' sweep and by the weapon-selection
# section: an attacker with a varied weapon rack against light infantry.
FLAG_PAIR = (("sm", "Redemptor Dreadnought"), ("sm", "Intercessor Squad"))

# Units the digest needs beyond the pairs: leader/support attachment.
EXTRA_UNITS = [("sm", "Captain"), ("sm", "Bladeguard Ancient"),
               ("sm", "Ancient"), ("sm", "Intercessor Squad"),
               ("sm", "Assault Intercessor Squad"),
               ("sm", "Bladeguard Veteran Squad")]


# Weapon keywords whose presence changes which weapons an attack setup
# keeps. The '## selection' section picks ONE attacker per keyword (the
# first in name order that carries it), so the section stays short and
# still covers every branch of select_weapons_split.
SELECTION_KEYWORDS = ("INDIRECT FIRE", "BLAST", "PISTOL", "CLOSE-QUARTERS",
                      "TORRENT", "HAZARDOUS")


def selection_attackers(units):
    """{keyword: unit} -- one representative attacker per weapon keyword
    of SELECTION_KEYWORDS, searched across every army in name order so
    the choice is deterministic."""
    pool = [u for key in sorted(units) for u in
            sorted(units[key], key=lambda x: x.name)]
    out = {}
    for kw in SELECTION_KEYWORDS:
        for unit in pool:
            found = any(kw == str(k).strip().upper()
                        or str(k).strip().upper().startswith(kw + " ")
                        for model in unit.models()
                        for weapon in model.weapons
                        for k in weapon.keywords)
            if found:
                out[kw] = unit
                break
    return out


def required_names(army_key):
    """Unit names the digest looks up by name in the given army, so the
    extractor knows which units it must keep."""
    wanted = set()
    for pair in PAIRS + [FLAG_PAIR]:
        for key, name in pair:
            if key == army_key:
                wanted.add(name)
    for key, name in EXTRA_UNITS:
        if key == army_key:
            wanted.add(name)
    return wanted


# --- Ability bookkeeping -------------------------------------------------

# Effect types whose maths is the most delicate -- the damage chain, the
# defensive rolls, the roll-modifier caps and the extra-attack generators
# are the parts an engine change is most likely to disturb. The default
# (curated) digest probes only abilities using these; --complete probes
# every enabled ability in the roster.
CRITICAL_EFFECTS = frozenset({
    "damageReduction",        # damage chain: set -> mult -> add -> floor
    "damageSetZero",
    "feelNoPain",             # grant / override / modify, no stacking
    "invulnSave",
    "ignoreMalus",            # interacts with the roll-modifier cap
    "modifyRelative",         # roll caps and characteristic limits
    "modifyAbsolute",
    "generateExtras",         # extra hits / attacks / wounds
    "increaseWeaponAttacks",
    "reRoll",                 # single / range / fails, one per activation
    "mortalWounds",
    "overrideReqs",
    "criticalThreshold",
    "disableMechanic",
})


def _key(value, default=""):
    """The 'key' of a spec option, which may be a dict or a bare string."""
    if isinstance(value, dict):
        return str(value.get("key", default))
    return str(value or default)


def enabled_abilities(unit_native):
    """[(list_name, index, ability)] for every enabled ability of a unit
    dict, in a stable order."""
    out = []
    for lst in ABILITY_LISTS:
        for i, ab in enumerate(unit_native.get(lst) or []):
            if isinstance(ab, dict) and ab.get("enabled"):
                out.append((lst, i, ab))
    return out


def ability_signature(ability):
    """Coarse fingerprint of what an ability DOES, used to pick one
    representative per distinct mechanic for the curated digest:
    effect type + its main option/application + the condition types."""
    eff = ability.get("effect") or {}
    data = eff.get("data") or {}
    detail = ""
    for field in ("application", "option", "operator", "mechanic", "roll"):
        if field in data:
            detail = _key(data[field])
            break
    conds = ",".join(sorted(str(c.get("type")) for c in
                            (ability.get("conditions") or [])))
    return (str(eff.get("type")), detail, conds)


def effect_label(ability):
    """Short human label of the effect, e.g. 'reRoll/hitRoll'."""
    sig = ability_signature(ability)
    return f"{sig[0]}/{sig[1]}" if sig[1] else sig[0]


def ability_role(ability):
    """'attacker', 'defender' or None -- the side the ability applies to,
    read off its profileRole condition. Decides which probe direction is
    worth running; None means run both."""
    for cond in ability.get("conditions") or []:
        if cond.get("type") == "profileRole":
            role = str((cond.get("data") or {}).get("profileRole", "")).lower()
            if role in ("attacker", "defender"):
                return role
    return None


def variant(unit_native, keep=None):
    """Copy of a unit dict with every ability disabled except *keep*
    (a (list_name, index) pair). keep=None disables them all -- that is
    the reference side of every ability delta."""
    out = copy.deepcopy(unit_native)
    for lst in ABILITY_LISTS:
        for i, ab in enumerate(out.get(lst) or []):
            if isinstance(ab, dict):
                ab["enabled"] = bool(keep is not None and keep == (lst, i))
    return out


# --- Engine helpers ------------------------------------------------------

def as_unit(unit_native):
    """Build a single engine Unit from a bare unit dict."""
    return um.units_from_native(
        {"format": "w40k-sim/6",
         "armies": [{"name": "Probe", "units": [copy.deepcopy(unit_native)]}]})[0]


def analyse(attacker, defender, flags, mode, ref_index=0):
    """run_analysis on two engine Units; returns the result dict, or None
    when the pairing has nothing to fire in this mode (no melee weapon,
    no defensive profile). Melee needs an explicit weapon name: the
    alphabetically first melee weapon is used, for determinism."""
    aview, dview = ac.build_views(attacker, defender, flags, {})
    opts = ac.reference_options(dview)
    if not opts or ref_index >= len(opts):
        return None
    melee_name = None
    if mode == "melee":
        choices = sorted(ac.melee_choices(aview))
        if not choices:
            return None
        melee_name = choices[0]
    return ac.run_analysis(aview, dview, opts[ref_index][1], flags, mode,
                           melee_name=melee_name)


def total_damage(attacker, defender, flags, mode):
    """Mean of the total (gross) Damage, or None when nothing fires."""
    res = analyse(attacker, defender, flags, mode)
    if res is None:
        return None
    return res["totals"]["damage"]["mean"]


def needs_leader(ability):
    """True when the ability only works once a leader has JOINED the
    unit that owns it (a leaderAttached condition). Such an ability is
    inert on the bare datasheet and must be probed on a combined unit."""
    return any(c.get("type") == "leaderAttached"
               for c in (ability.get("conditions") or []))


def attachment_targets(units, natives):
    """Two maps, both computed once per digest, that let the ability
    probe build COMBINED units:

      'join' -- {leader_or_support_name: (kind, target_native)}: what
        each leader / support can join. A leader_effects (or shared)
        ability applies to the unit being LED, not to the leader
        carrying it, so probing the leader alone shows nothing.
      'led'  -- {unit_name: leader_native}: which leader can join each
        plain unit. This is the mirror case -- an ability gated on
        leaderAttached belongs to the LED unit and needs a leader
        supplied from outside.

    Candidates are scanned in name order, so the choice is stable."""
    by_name = {str(u.get("name", "")): u for u in natives}
    ordered = sorted(units, key=lambda u: u.name)
    plain = [u for u in ordered if not getattr(u, "leadership", None)
             and not getattr(u, "support", None)]
    leaders = [u for u in ordered if getattr(u, "leadership", None)]
    join, led = {}, {}
    for unit in ordered:
        is_leader = bool(getattr(unit, "leadership", None))
        is_support = bool(getattr(unit, "support", None))
        if not (is_leader or is_support):
            continue
        for target in plain:
            if target.name == unit.name or target.name not in by_name:
                continue
            joins = (target.can_attach(unit) if is_leader
                     else target.can_support(unit))
            if joins:
                join[unit.name] = ("leader" if is_leader else "support",
                                   by_name[target.name])
                break
    for unit in plain:
        for leader in leaders:
            if leader.name in by_name and unit.can_attach(leader):
                led[unit.name] = by_name[leader.name]
                break
    return {"join": join, "led": led}


def resolve_attach(unit_native, ability, list_name, maps):
    """(kind, other_native) for an ability that can only be measured on a
    COMBINED unit, or None when the bare datasheet is enough.

    Shared by the digest and by the synthetic roster's self-check so the
    two cannot disagree about what "this ability does nothing" means."""
    name = str(unit_native.get("name", ""))
    if list_name == "leader_effects" or ability.get("share_with_unit"):
        return (maps.get("join") or {}).get(name)
    if needs_leader(ability):
        leader = (maps.get("led") or {}).get(name)
        return ("led", leader) if leader is not None else None
    return None


def combined_unit(unit_native, keep, other_native, kind):
    """Engine unit for a leader/support and the unit it joined.

    kind 'leader'/'support': *unit* is the JOINER and *other* the unit
    it joins. kind 'led': the roles are reversed -- *unit* is the unit
    under test and *other* is a leader supplied to satisfy its
    leaderAttached condition. Either way every ability except the one
    under test is disabled on BOTH sides, so the measured delta belongs
    to that ability alone."""
    if kind == "led":
        target = as_unit(variant(unit_native, keep))
        return target.attach_leader(as_unit(variant(other_native, None)))
    joiner = as_unit(variant(unit_native, keep))
    target = as_unit(variant(other_native, None))
    return (target.attach_leader(joiner) if kind == "leader"
            else target.attach_support(joiner))


def find_unit(units, needle):
    """Look a unit up by name: exact match first (case-insensitive), then
    substring. Exact-first matters because roster names nest ('Captain'
    is a prefix of 'Captain In Gravis Armour')."""
    low = needle.lower()
    for u in units:
        if u.name.lower() == low:
            return u
    for u in units:
        if low in u.name.lower():
            return u
    return None
