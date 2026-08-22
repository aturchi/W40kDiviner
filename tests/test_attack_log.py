"""The game assistant's attack log: what is recorded, and what is derived.

No tkinter here (attack_log holds none), and no external data: the one
end-to-end check builds a weapon by hand and resolves it with the real
dice engine, so the recorded entry is compared against a resolution the
test did not fabricate.

The property that matters most is that the log agrees with the results
popup: the popup counts every event (mortal wounds included) and sums
every amount, and entry_totals must reach the same two numbers by its
own route.
"""
import csv as csv_module
import json
import random

import testpaths                      # sets up sys.path to the engine src/
import attack_log as al
import attack_math as am
import attack_resolve as ar
from unit_model import Weapon

REF = {"T": 4, "Sv": 3, "W": 2, "invuln": None, "fnp": 5, "models": 5,
       "keywords": set()}


def mech_for(keywords):
    m = am.WeaponMechanics()
    am.parse_weapon_keywords(keywords, m)
    return m


# --- 1. a real resolution, recorded ----------------------------------
# DEVASTATING WOUNDS so the entry carries both kinds of event, and a
# Feel No Pain on the defender so some of them are thinned away.
weapon = Weapon(name="pulse rifle, long", wtype="Ranged", A="6", skill=3,
                S=6, AP=-1, D="2", count=4)
mech = mech_for(["DEVASTATING WOUNDS", "SUSTAINED HITS 1"])
rng = random.Random(20260821)
res = ar.resolve_weapon(weapon, REF, {"half_range": True}, mech, rng)

log = al.AttackLog()
entry = log.record("Fire Warrior Team", "Intercessor Squad", REF,
                   [(weapon, mech.hazardous, res)],
                   skipped=[(Weapon(name="markerlight", wtype="Ranged",
                                    A="1", skill=4, S=1, AP=0, D="1",
                                    count=1), "indirect fire only")],
                   mode="ranged", context=["Within half range"],
                   stamp="21:07:12")

# the popup's own arithmetic, computed here independently
popup_events = len(res["events"])
popup_damage = sum(e["amount"] for e in res["events"])
tot = al.entry_totals(entry)
assert tot["events"] == popup_events, (tot, popup_events)
assert tot["damage"] == popup_damage, (tot, popup_damage)
assert tot["attacks"] == res["attacks"]
assert tot["normal"] + tot["mortal"] == tot["damage"]
assert popup_events > 0 and tot["mortal"] > 0, \
    "the seeded resolution must produce both kinds of event"

# individual amounts survive: three events of 2 are not one of 6
rec = entry["weapons"][0]
assert rec["damage"] == [e["amount"] for e in res["events"]
                         if e["kind"] == "damage"]
assert rec["mortal"] == [e["amount"] for e in res["events"]
                         if e["kind"] == "mortal"]
assert rec["count"] == 4 and rec["name"] == "pulse rifle, long"
assert entry["skipped"][0]["reason"] == "indirect fire only"
assert entry["seq"] == 1 and entry["turn"] == 1
print("recorded entry agrees with the resolution and with the popup")

# --- 2. context in words ----------------------------------------------
labels = {"half_range": "Within half range", "cover": "Benefit of Cover"}
lines = al.context_lines(
    {"half_range": True, "cover": False, "charged": True,
     "overwatch": True, "overwatch_value": 5,
     "disabled_abilities": ["a1"], "extra_abilities": []},
    mods=[("Hit roll", "rolls", "hit", -1),
          ("Hit reroll 1s", "rerolls", ("hit", "1"), None)],
    labels=labels)
assert "Within half range" in lines
assert "Benefit of Cover" not in lines          # unticked: not context
assert "charged" in lines                       # no label: key spelled out
assert "Overwatch (hits on 5+)" in lines
assert "1 ability switched off" in lines
assert "Hit roll: -1" in lines and "Hit reroll 1s" in lines
assert "overwatch_value" not in " ".join(lines)
print("context lines list only what was actually in play")

# --- 3. numbering, turns, deletion ------------------------------------
log.new_turn()
e2 = log.record("Crisis Team", "Intercessor Squad", REF,
                [(weapon, False, {"attacks": 3, "events": [
                    {"kind": "damage", "amount": 2}],
                    "self_damage": 0, "warnings": []})],
                mode="ranged", stamp="21:12:00")
e3 = log.record("Crisis Team", "Captain", REF, [], mode="melee",
                melee="fists", stamp="21:15:00")
assert (e2["seq"], e2["turn"]) == (2, 2)
assert len(log) == 3
assert al.entry_totals(e3) == {"attacks": 0, "events": 0, "damage": 0,
                               "normal": 0, "mortal": 0, "self_damage": 0}
assert log.remove([3]) == 1 and len(log) == 2
assert log._next_seq() == 3, "numbering must not be reused after a delete"
dropped = log.undo_last()
assert dropped["seq"] == 2 and len(log) == 1
log.add(dropped)                               # put it back, renumbered
assert log.entries[-1]["seq"] == 2
print("numbering, turns and deletion behave")

# --- 4. running totals by defender -------------------------------------
by_def = dict(al.damage_by_defender(log.entries))
assert set(by_def) == {"Intercessor Squad"}
assert by_def["Intercessor Squad"]["attacks"] == 2
assert by_def["Intercessor Squad"]["damage"] == popup_damage + 2
assert by_def["Intercessor Squad"]["mortal"] == tot["mortal"]
print("running totals by defending unit add up")

# --- 5. session round trip (plain JSON types only) ---------------------
blob = json.loads(json.dumps(log.to_json()))
back = al.AttackLog(blob)
assert len(back) == len(log) and back.turn == log.turn
assert back.to_text() == log.to_text()
assert al.AttackLog(None).entries == [] and al.AttackLog(None).turn == 1
assert al.AttackLog("rubbish").entries == []          # never raises
partial = al.AttackLog({"entries": [{"attacker": "x", "defender": "y",
                                     "turn": 4}]})
assert partial.entries[0]["seq"] == 1 and partial.turn == 4, \
    "a hand-edited log must be repaired, not rejected"
print("session round trip keeps the log intact")

# --- 6. text and CSV ---------------------------------------------------
text = log.to_text()
assert "===== TURN 1 =====" in text and "===== TURN 2 =====" in text
assert "pulse rifle, long x4" in text
assert "not fired: indirect fire only" in text
assert f"{tot['damage']} damage to allocate" in text
assert "Damage rolled so far" in text

csv = log.to_csv()
rows = csv.strip().split("\n")
# header + (1 weapon + 1 skipped) for entry 1 + 1 weapon for entry 2
assert len(rows) == 4, rows
assert rows[0] == ",".join(al.CSV_COLUMNS)
assert '"pulse rifle, long"' in rows[1], "a comma in a name must be quoted"
assert rows[2].endswith("not fired: indirect fire only")
# parsed back with the standard reader: the quoting must be real CSV,
# and every row must have exactly as many fields as there are columns
parsed = list(csv_module.reader(csv.splitlines()))
assert all(len(r) == len(al.CSV_COLUMNS) for r in parsed), parsed
assert parsed[1][al.CSV_COLUMNS.index("weapon")] == "pulse rifle, long"
print("text and CSV exports are well formed")

print("OK: attack log")
