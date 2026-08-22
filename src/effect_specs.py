"""Effect type registry.

Declarative schema of every supported ability-effect type, mirroring the
source export format where applicable. Same conventions as
condition_specs; extra field kind BOOL (stored as a real boolean).

Types marked extension=True are project additions (not in the source export format):
  disableMechanic, setKeyword.
Option keys not observed in the dataset are sensible completions; the
attack engine is the authority on their semantics.
"""

from spec_kinds import CHOICE, ENUM, TEXT, BOOL, COMBO  # noqa: F401
import keywords_config

_APPLICATIONS = [("Hit roll", "hitRoll"), ("Wound roll", "woundRoll"),
                 ("Save roll", "saveRoll"), ("Feel No Pain roll", "fnpRoll"),
                 ("BS", "bs"), ("WS", "ws"),
                 ("AP", "ap"), ("Damage", "damage"), ("Attacks", "attacks"),
                 ("Strength", "strength"), ("Movement (M)", "m"),
                 ("Leadership (LD)", "ld"),
                 ("Objective Control (OC)", "oc"),
                 # Model profile characteristics: what an ability
                 # granting extra Wounds or Toughness, or a better
                 # armour save, acts on.
                 ("Toughness (T)", "t"), ("Save (Sv)", "sv"),
                 ("Wounds (W)", "w")]

EFFECT_SPECS = {
    "modifyRelative": {
        "text": "Modify (relative)",
        "description": "Modify an attribute or roll by +/-N.",
        "fields": [
            ("application", CHOICE, "Apply to", _APPLICATIONS),
            ("operator", CHOICE, "Operator",
             [("Add", "add"), ("Subtract", "subtract"),
              ("Improve by", "improve"), ("Degrade by", "degrade")]),
            ("relativeValue", TEXT, "Value (N)", None),
        ],
    },
    "modifyAbsolute": {
        "text": "Modify (absolute)",
        "description": "Set a new value for an attribute or result.",
        "fields": [
            ("application", CHOICE, "Apply to", _APPLICATIONS),
            ("absoluteValue", TEXT, "New value", None),
        ],
    },
    "reRoll": {
        "text": "Re-roll",
        "description": "Re-roll specific results (1s, all failures, ...).",
        "fields": [
            ("application", CHOICE, "Apply to",
             [("Hit roll", "hitRoll"), ("Wound roll", "woundRoll"),
              ("Save roll", "saveRoll"), ("Damage", "damage")]),
            ("resultToReRoll", CHOICE, "Result to re-roll",
             [("Single result", "single"), ("Result range", "range"),
              ("All possible failures", "allPossibleFailures")]),
            ("valueSingle", TEXT, "Single value (e.g. 1)", None),
            ("valueRange", TEXT, "Range (e.g. 1-2)", None),
            ("limit", CHOICE, "Limit",
             [("No limit", "none"), ("Once per phase", "once")]),
        ],
    },
    "overrideReqs": {
        "text": "Override requirements",
        "description": "Set new requirements for a successful outcome.",
        "fields": [
            ("outcome", CHOICE, "Outcome",
             [("Hit", "hit"), ("Wound", "wound"), ("Save", "save")]),
            ("type", CHOICE, "Type",
             [("Always", "always"), ("Only", "only")]),
            ("crit", BOOL, "On critical only", None),
            ("irrespective", BOOL, "Irrespective of modifiers", None),
        ],
    },
    "generateExtras": {
        "text": "Generate extras",
        "description": "Generate extra attacks/hits/wounds per attack.",
        "fields": [
            ("option", CHOICE, "Generate",
             [("Extra hits", "extraHits"), ("Extra attacks", "extraAttacks"),
              ("Extra wounds", "extraWounds")]),
            ("extrasValue", TEXT, "Amount per attack", None),
        ],
    },
    "increaseWeaponAttacks": {
        "text": "Increase weapon attacks",
        "description": "Change the weapon Attacks characteristic by +/-N.",
        "fields": [
            ("increaseWeaponAttacksValue", TEXT, "Value (+/-N)", None),
            ("applyToExtraAttacks", BOOL, "Apply to extra attacks", None),
        ],
    },
    "mortalWounds": {
        "text": "Mortal wounds",
        "description": "Generate mortal wounds.",
        "fields": [
            ("mortalWoundsValue", TEXT, "Amount (N or D notation)", None),
            ("matchWeaponDamage", BOOL, "Match weapon damage", None),
            ("attackSequenceEnds", BOOL, "Attack sequence ends", None),
            ("noSpillOver", BOOL, "No spill-over", None),
            ("cap", TEXT, "Cap (optional)", None),
        ],
    },
    "feelNoPain": {
        "text": "Feel no pain",
        "description": "Grant, override or modify a Feel No Pain roll. "
                       "'Grant' never stacks (the best value wins); "
                       "'override' forces the value even if it is worse "
                       "(7 = no FNP at all); 'modify' shifts the roll by "
                       "+/-N. Add an 'only vs mortal wounds' condition to "
                       "restrict any of them to that damage.",
        "fields": [
            ("operator", CHOICE, "Operator",
             [("Grant (best wins)", "grant"), ("Override", "override"),
              ("Modify roll (+/-N)", "modify")]),
            ("value", TEXT, "FNP value (N+), or modifier for 'modify'",
             None),
        ],
    },
    "invulnSave": {
        "text": "Invulnerable save",
        "description": "Provide an invulnerable save of N+.",
        "fields": [("invulnValue", TEXT, "Invuln value (N+)", None)],
    },
    "damageReduction": {
        "text": "Damage modifier (defender)",
        "description": "Modify the Damage of each incoming attack (applies "
                       "when this unit is the defender). All damage "
                       "modifiers are resolved in a FIXED order: (1) 'Set' "
                       "fixes the Damage to N; (2) 'Multiply' scales it by "
                       "the factor N, rounding UP (0.5 = halve); (3) 'Add' "
                       "adds N, so a classic 'reduce damage by 1' is Add "
                       "with N = -1. After all steps the Damage is floored "
                       "at 1 (use the 'Damage set to 0' effect to bypass "
                       "that floor). The value is a whole number for Set/"
                       "Add and a decimal factor for Multiply.",
        "fields": [
            ("operator", CHOICE, "Operation",
             [("Add (e.g. -1)", "add"), ("Multiply (e.g. 0.5)", "mult"),
              ("Set (fix to N)", "set")]),
            ("value", TEXT, "Value (N or factor)", None),
        ],
    },
    "damageSetZero": {
        "text": "Damage set to 0 (defender)",
        "description": "Force each incoming attack's Damage to 0, bypassing "
                       "the usual 'at least 1 damage' floor. Applies when "
                       "this unit is the defender and takes effect after "
                       "every other damage modifier. Takes no parameters.",
        "fields": [],
    },
    "ignoreMalus": {
        "text": "Ignore negative modifiers to a roll",
        "description": "Ignore NEGATIVE modifiers to the chosen roll "
                       "(positive modifiers still apply). Hit/Wound act "
                       "on this unit's attacks; Save/Invuln/FNP act when "
                       "this unit defends. 'Hit' covers the hit ROLL "
                       "modifiers only: in 11th ed. the BS/WS "
                       "CHARACTERISTIC modifiers (Benefit of Cover, "
                       "Stealth, abilities) are a separate group, chosen "
                       "with 'Skill'. A PSYCHIC weapon ignores both.",
        "fields": [("roll", ENUM, "Roll",
                    ["Hit", "Skill", "Wound", "Save", "Invuln", "FNP"])],
    },
    "criticalThreshold": {
        "text": "Critical hit/wound on N+",
        "description": "Score a Critical hit (or wound) on an unmodified "
                       "roll of N+ instead of 6 (e.g. Conversion: crit hit "
                       "on 4+). The best (lowest) threshold wins.",
        "fields": [
            ("application", CHOICE, "Critical on",
             [("Critical hit", "hit"), ("Critical wound", "wound")]),
            ("value", TEXT, "Threshold (N+)", None),
        ],
    },
    "special": {
        "text": "Special (core weapon ability)",
        "description": "Core rule mechanic handled natively by the engine.",
        "fields": [
            ("option", CHOICE, "Mechanic",
             [("Blast", "blast"), ("Cleave", "cleave"),
              ("Extra attacks", "extraAttacks"),
              ("Ignore cover", "ignoreCover"), ("Lethal hits", "lethalHits"),
              ("Devastating wounds", "devastatingWounds"),
              ("Torrent", "torrent"), ("Twin-linked", "twinLinked"),
              # Defender side: the unit counts as having the Benefit of
              # Cover (11th-ed. Stealth). Boolean, so it never stacks
              # with the terrain cover of the attack setup.
              ("Benefit of cover (defender)", "benefitOfCover"),
              ("Hazardous", "hazardous"), ("Precision", "precision"),
              ("Lance", "lance"), ("Indirect fire", "indirectFire"),
              ("One shot", "oneShot"),
              # 11th ed. renamed Pistol to Close-quarters; the old key is
              # kept so abilities saved before the rename still resolve.
              ("Close-quarters", "closeQuarters"), ("Pistol", "pistol"),
              ("Assault", "assault"), ("Heavy", "heavy")]),
        ],
    },
    "hunterTarget": {
        "text": "Hunter X (target restriction)",
        "description": "The weapon may only be fired at units with the "
                       "given keyword (11th-ed. HUNTER X). Several of "
                       "them stack as alternatives: the target needs any "
                       "one of the listed keywords.",
        "fields": [("keyword", COMBO, "Keyword (X)",
                    keywords_config.all_keywords())],
    },
    # ---------- Project extensions ----------
    "disableWeapon": {
        "text": "Weapon unusable",
        "extension": True,
        "description": "The weapon cannot be selected for the attack "
                       "while this ability's conditions hold; the "
                       "analyzer and the game assistant list it greyed "
                       "out with a reason instead of resolving it. Put "
                       "it on the WEAPON, and use a negated condition "
                       "for the usual 'only usable while ...' form "
                       "(e.g. negated 'Attacker remained stationary' "
                       "for a weapon that needs the unit to stand "
                       "still). Takes no parameters.",
        "fields": [],
    },
    "singleReRoll": {
        "text": "Re-roll ONE die per activation",
        "extension": True,
        "description": "One single die of the chosen roll may be "
                       "re-rolled each time the unit is selected to "
                       "attack - NOT one per attack. Put it on the "
                       "WEAPON that should get the re-roll: the rule is "
                       "one re-roll for the whole activation, so a copy "
                       "goes on every candidate weapon, all switched "
                       "off, and the player ticks one in the inspect "
                       "window. 'Allowance' says how the datasheet "
                       "spends it: 'One roll of any kind' warns when "
                       "more than one is on at all; 'One roll of each "
                       "kind' warns when a kind is left unused. "
                       "The Damage re-roll needs a Damage ROLL to work "
                       "on: on a flat Damage characteristic, or on a "
                       "weapon that already re-rolls low Damage dice, "
                       "it is reported as doing nothing.",
        "fields": [
            ("roll", CHOICE, "Roll",
             [("Hit roll", "hit"), ("Wound roll", "wound"),
              ("Damage roll", "damage")]),
            # Worded without naming the kinds: there are three of them
            # now, and which ones a given datasheet offers is its own
            # business. Rosters saved with the older wording still read
            # correctly - a CHOICE is resolved by KEY first, see
            # spec_forms.choice_title.
            ("allowance", CHOICE, "Allowance",
             [("One roll of any kind (one in total)", "exclusive"),
              ("One roll of each kind (one per kind)", "eachKind")]),
        ],
    },
    "attachmentSlots": {
        "text": "Leader / support slots",
        "extension": True,
        "description": "Change how many Leader or Support units may be "
                       "attached to this unit (both default to 1). "
                       "Structural: it is read when the units are "
                       "joined, BEFORE any attack context exists, so "
                       "the ability's conditions are ignored - use the "
                       "enable/disable toggle to switch it on when the "
                       "datasheet requirement is met.",
        "fields": [
            ("slot", CHOICE, "Slot",
             [("Leader", "leader"), ("Support", "support")]),
            ("operator", CHOICE, "Operation",
             [("Add", "add"), ("Set", "set")]),
            ("value", TEXT, "Value (N)", None),
        ],
    },
    "disableMechanic": {
        "text": "Disable mechanic",
        "extension": True,
        "description": "Disable a mechanic or ability (engine-interpreted).",
        "fields": [("mechanic", CHOICE, "Mechanic to disable",
                    [("Invulnerable save", "invulnSave"),
                     ("Re-roll hits", "reRollHits"),
                     ("Re-roll wounds", "reRollWounds"),
                     ("Re-roll damage", "reRollDamage"),
                     ("Save (incl. invulnerable)", "save"),
             # Not a weapon ability: the -1 to hit a MONSTER/VEHICLE
             # takes for shooting the unit it is engaged with.
             ("Close-quarters hit penalty", "closeQuartersPenalty")])],
    },
    "setKeyword": {
        "text": "Set keyword",
        "extension": True,
        "description": "Add or remove a keyword on the chosen target.",
        "fields": [
            ("target", CHOICE, "Target",
             [("This weapon", "weapon"), ("All weapons", "allWeapons"),
              ("This model", "model"), ("All models", "allModels"),
              ("Unit", "unit")]),
            ("operation", CHOICE, "Operation",
             [("Add", "add"), ("Remove", "remove")]),
            ("keyword", COMBO, "Keyword (value after name if parametric)",
             keywords_config.all_keywords()),
        ],
    },
}


def list_types():
    """Effect type ids sorted, native types first."""
    native = [t for t, s in EFFECT_SPECS.items() if not s.get("extension")]
    ext = [t for t, s in EFFECT_SPECS.items() if s.get("extension")]
    return sorted(native) + sorted(ext)


def new_effect(etype: str) -> dict:
    """Build a new effect dict of the given type with default values."""
    spec = EFFECT_SPECS[etype]
    data = {}
    for key, kind, _label, options in spec["fields"]:
        if kind == CHOICE:
            data[key] = {"title": options[0][0], "key": options[0][1]}
        elif kind == BOOL:
            data[key] = False
        else:
            data[key] = ""
    eff = {"text": spec["text"], "type": etype, "data": data}
    if spec.get("extension"):
        eff["extension"] = True
    return eff
