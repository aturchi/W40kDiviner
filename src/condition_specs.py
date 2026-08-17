"""Condition type registry.

Declarative schema of every supported ability-condition type. The GUI
generates editing forms from these specs, and the future attack engine
will use the same registry to evaluate conditions.

Field kinds:
  CHOICE   -> stored as {"title": ..., "key": ...} (export style)
  ENUM     -> stored as a plain string from a fixed list
  TEXT     -> stored as a free string (numbers kept as strings, as in
              the source export, e.g. rollValue: "3")
  KEYWORDS -> stored as a list of uppercase strings

Types marked extension=True are project additions inspired by the
WH40k 11th-edition core rules; they are not part of the source
export format (a re-import there would ignore them).
"""

from spec_kinds import CHOICE, ENUM, TEXT, BOOL, KEYWORDS  # noqa: F401

# Reusable option lists: list of (title, key)
_WHO = [("Attacker", "attacker"), ("Defender", "defender")]
_ROLL_STATE = [("Unmodified", "unmodified"), ("Modified", "modified")]
_COMPARISON = [("Greater than", "greaterThan"), ("Less than", "lessThan"),
               ("Equal to", "equalTo"),
               ("Greater than or equal", "greaterThanOrEqual"),
               ("Less than or equal", "lessThanOrEqual")]

# Each spec: text (UI title), description, fields = list of
# (data_key, kind, label, options). Options: (title, key) for CHOICE,
# plain strings for ENUM, ignored for TEXT/KEYWORDS.
CONDITION_SPECS = {
    # ---------- Standard types (source export format) ----------
    "profileRole": {
        "text": "Profile role",
        "description": "Require the current profile to be set as the attacker or defender.",
        "fields": [("profileRole", ENUM, "Role", ["Attacker", "Defender"])],
    },
    "attackType": {
        "text": "Attack type",
        "description": "Restrict to just melee attacks or ranged attacks.",
        "fields": [("attackType", ENUM, "Attack type", ["Melee", "Ranged"])],
    },
    "range": {
        "text": "Range",
        "description": "Check attack range.",
        "fields": [("range", CHOICE, "Range requirement",
                    [("Within half range", "withinHalfRange"),
                     ("Beyond half range", "beyondHalfRange")])],
    },
    "crit": {
        "text": "Critical hit/wound",
        "description": "Require a hit or wound to be \"critical\".",
        "fields": [("crit", CHOICE, "Critical on",
                    [("Critical hit", "hitRoll"),
                     ("Critical wound", "woundRoll")])],
    },
    "attackStepRoll": {
        "text": "Attack step roll",
        "description": "Require a specific roll value in the attack sequence.",
        "fields": [
            ("attackStep", CHOICE, "Attack step",
             [("Hit roll", "hitRoll"), ("Wound roll", "woundRoll"),
              ("Save roll", "saveRoll")]),
            ("rollReq", CHOICE, "Requirement",
             [("Specific roll", "specificRoll"),
              ("Successful roll", "successfulRoll"),
              ("Failed roll", "failedRoll")]),
            ("rollState", CHOICE, "Roll state", _ROLL_STATE),
            ("rollTarget", CHOICE, "Target",
             [("Or greater", "orGreater"), ("Or less", "orLess"),
              ("Exactly", "exactly")]),
            ("rollValue", TEXT, "Roll value", None),
        ],
    },
    "attackCharacteristic": {
        "text": "Attack characteristic",
        "description": "Evaluate an attack characteristic.",
        "fields": [
            ("attackChar", CHOICE, "Characteristic",
             [("Strength", "strength"), ("Attacks", "attacks"),
              ("AP", "ap"), ("Damage", "damage")]),
            ("comparison", CHOICE, "Comparison", _COMPARISON),
            ("attackCharValue", TEXT, "Value", None),
            ("attackCharState", CHOICE, "State", _ROLL_STATE),
        ],
    },
    "remainedStationary": {
        "text": "Remained stationary",
        "description": "Whether a profile remained stationary this turn.",
        "fields": [("remainedStationary", CHOICE, "Who",
                    [("Attacker remained stationary",
                      "attackerStationary")])],
    },
    "attackerCharged": {
        "text": "Attacker charged",
        "description": "Whether the attacker charged.",
        "fields": [("attackerCharged", CHOICE, "Requirement",
                    [("Attacker charged", "attackerCharged")])],
    },
    # 'who' lets a condition ask about the ATTACKING unit's own keywords
    # ("while this model is leading a BLOOD CLAWS unit"), not only the
    # target's. It defaults to the target, which is what every condition
    # written before this field meant.
    "keywordsOnly": {
        "text": "Keywords (only)",
        "description": "Require one or more keywords. 'Whose keywords' "
                       "picks the unit they are read from: the target of "
                       "the attack (the default, and what every older "
                       "condition means) or the unit the ability belongs "
                       "to - which is how \"while this model is leading a "
                       "BLOOD CLAWS unit\" is written.",
        "fields": [("keywords", KEYWORDS, "Keywords (comma-separated)",
                    None),
                   ("who", CHOICE, "Whose keywords",
                    [("Target unit", "target"), ("This unit", "self")])],
    },
    "keywordsExcludes": {
        "text": "Keywords (excludes)",
        "description": "Exclude one or more keywords. 'Whose keywords' "
                       "works as in Keywords (only).",
        "fields": [("keywords", KEYWORDS, "Keywords (comma-separated)",
                    None),
                   ("who", CHOICE, "Whose keywords",
                    [("Target unit", "target"), ("This unit", "self")])],
    },
    "woundType": {
        "text": "Wound type",
        "description": "Only apply to a given wound type.",
        "fields": [("woundType", CHOICE, "Wound type",
                    [("Mortal wounds", "mortalWounds"),
                     ("Normal wounds", "normalWounds")])],
    },
    "psychicAttack": {
        "text": "Psychic attack",
        "description": "Require the attacking weapon to be a Psychic "
                       "weapon (PSYCHIC keyword).",
        "fields": [],
    },
    # ---------- Project extensions (WH40k 11th ed. rules) ----------
    "targetInCover": {
        "text": "Target in cover",
        "extension": True,
        "description": "The defender has the Benefit of Cover.",
        "fields": [],
    },
    "belowHalfStrength": {
        "text": "Below half strength",
        "extension": True,
        "description": "A unit is Below Half-strength.",
        "fields": [("who", CHOICE, "Who", _WHO)],
    },
    "belowFullStrength": {
        "text": "Below full strength",
        "extension": True,
        "description": "A unit has lost at least one model (below its "
                       "Starting Strength).",
        "fields": [("who", CHOICE, "Who", _WHO)],
    },
    "battleRound": {
        "text": "Battle round",
        "extension": True,
        "description": "Check the current battle round number.",
        "fields": [("comparison", CHOICE, "Comparison", _COMPARISON),
                   ("roundValue", TEXT, "Round", None)],
    },
    "objectiveRange": {
        "text": "Within objective range",
        "extension": True,
        "description": "A unit is within range of an objective marker.",
        "fields": [("who", CHOICE, "Who", _WHO)],
    },
    "leaderAttached": {
        "text": "Leader attached",
        "extension": True,
        "description": "A unit is being led (a CHARACTER is attached).",
        "fields": [("who", CHOICE, "Who", _WHO)],
    },
    "engagementRange": {
        "text": "Within engagement range",
        "extension": True,
        "description": "A unit is within Engagement Range of an enemy unit.",
        "fields": [("who", CHOICE, "Who", _WHO)],
    },
}


# Every condition can be NEGATED. The flag is injected here as an extra
# BOOL field of every spec, so the spec-driven editor form renders its
# checkbox and writes it back with no GUI code of its own. It is honoured
# by modifier_engine._eval_conditions and only makes sense for conditions
# decided before the dice are rolled (see NEGATE_LABEL).
NEGATE_KEY = "negate"
NEGATE_LABEL = "Negate: the condition must NOT hold"
for _spec in CONDITION_SPECS.values():
    _spec["fields"] = list(_spec["fields"]) + [
        (NEGATE_KEY, BOOL, NEGATE_LABEL, None)]


def list_types():
    """Return condition type ids sorted, native types first."""
    native = [t for t, s in CONDITION_SPECS.items() if not s.get("extension")]
    ext = [t for t, s in CONDITION_SPECS.items() if s.get("extension")]
    return sorted(native) + sorted(ext)


def new_condition(ctype: str) -> dict:
    """Build a new condition dict of the given type with default values."""
    spec = CONDITION_SPECS[ctype]
    data = {}
    for key, kind, _label, options in spec["fields"]:
        if kind == CHOICE:
            data[key] = {"title": options[0][0], "key": options[0][1]}
        elif kind == ENUM:
            data[key] = options[0]
        elif kind == KEYWORDS:
            data[key] = []
        elif kind == BOOL:
            data[key] = False
        else:  # TEXT
            data[key] = ""
    cond = {"text": spec["text"], "type": ctype, "data": data,
            "description": spec["description"], "preselected": False}
    if spec.get("extension"):
        cond["extension"] = True
    return cond
