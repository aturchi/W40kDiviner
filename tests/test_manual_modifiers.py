"""Manual modifiers of the attack setup, end to end.

The setup panel turns its modifier list into
  {'rolls': {hit|wound|save|invuln|fnp: +/-N},
   'rerolls': {hit|wound|save|invuln|fnp: '1'|'fails'},
   'weapon'|'attacker_model'|'defender_model': {CHAR: +/-N}}
and both GUIs hand that dict to build_views and to run_analysis. What
must hold:

  * every roll modifier and every RE-ROLL reaches the weapon mechanics
    and moves the result in the right direction;
  * a manual re-roll never weakens an ability's own re-roll (the
    strongest of the two wins, they do not stack);
  * characteristic modifiers are baked into the views by build_views;
  * the exact maths and the dice resolver agree on all of it.

Headless: setup_panel itself needs tkinter, so this exercises the
contract it produces, not the widget.
"""
import json

import testpaths                      # sets up sys.path to the engine src/
import analyzer_core as ac
import attack_math as am
import leader_core as lc
import mc_support as mcs
import unit_model as um

data = json.load(open(testpaths.roster("space-marines.json")))
units = um.units_from_native(data)
by_name = {u.name: u for u in units}
leaders, rest = lc.split_leaders(units)
supports, others = lc.split_supports(rest)
# The attacker must have a ranged weapon whose damage really goes through
# the defender's save, or the save-modifier assertion below is testing
# nothing: DEVASTATING WOUNDS turns critical wounds into mortal wounds,
# which ignore saves entirely, and a weapon that also carries ANTI-X can
# end up with every wound critical (a real case in the Space Marine
# roster: the Lieutenant's Combi-weapon, ANTI-INFANTRY 4+ + DEVASTATING
# WOUNDS, does no save-able damage at all to INFANTRY). PISTOL /
# CLOSE-QUARTERS weapons are excluded too: they do not fire in the ranged
# attack setup used here.
_EXCLUDED_KW = set(ac.CLOSE_QUARTERS_KW) | {"DEVASTATING WOUNDS"}


def _rolls_saves(unit) -> bool:
    for model in unit.models():
        for w in model.weapons:
            kws = {str(k).strip().upper() for k in (w.keywords or [])}
            if w.type == "Ranged" and not (kws & _EXCLUDED_KW):
                return True
    return False


att = next(u for u in others if _rolls_saves(u))
dfn = next(u for u in others
           if u.name != att.name
           and any(m.Sv is not None for m in u.models()))


def total(mods, mode="ranged"):
    aview, dview = ac.build_views(att, dfn, {}, mods)
    ref = ac.reference_options(dview)[0][1]
    res = ac.run_analysis(aview, dview, ref, {}, mode, None, mods)
    assert not res["warnings"], res["warnings"]
    return res["totals"]["damage"]["mean"]


def first_mech(mods):
    aview, dview = ac.build_views(att, dfn, {}, mods)
    w = next(w for m in aview.models() for w in m.weapons
             if w.type == "Ranged")
    return w, dview, ac.mechanics_for_attack(w, dview, "Ranged", mods, {})


base = total({})

# --- 1. roll modifiers -------------------------------------------------
assert total({"rolls": {"hit": 1}}) > base, "+1 to hit must help"
assert total({"rolls": {"hit": -1}}) < base, "-1 to hit must hurt"
assert total({"rolls": {"wound": 1}}) > base
assert total({"rolls": {"save": 1}}) < base, "a better save must hurt"
print("manual roll modifiers reach the maths with the right sign")

# --- 2. re-rolls -------------------------------------------------------
rr_1 = total({"rerolls": {"hit": "1"}})
rr_f = total({"rerolls": {"hit": "fails"}})
assert base < rr_1 < rr_f, (base, rr_1, rr_f)
assert base < total({"rerolls": {"wound": "1"}}) \
    < total({"rerolls": {"wound": "fails"}})
assert total({"rerolls": {"save": "fails"}}) < base, \
    "the defender re-rolling failed saves must reduce the damage"
for roll in ("hit", "wound", "save", "invuln", "fnp"):
    _w, _d, mech = first_mech({"rerolls": {roll: "fails"}})
    got = getattr(mech, f"reroll_{roll}")
    assert got == "fails", f"{roll}: manual re-roll lost ({got!r})"
print("manual re-rolls of every roll reach the weapon mechanics")

# --- 3. a manual re-roll never weakens an ability's own ----------------
# LETHAL-style abilities aside, the strongest re-roll wins and they never
# stack: an ability re-rolling failures plus a manual "1s" stays "fails".
_w, _d, mech = first_mech({})
mech.reroll_hit = "fails"
assert am.combine_reroll(mech.reroll_hit, "1") == "fails"
assert am.combine_reroll(None, "1") == "1"
assert am.combine_reroll("1", "fails") == "fails"
assert am.combine_reroll(None, None) is None
print("the strongest re-roll wins and they never stack")

# --- 4. characteristic modifiers are baked into the views --------------
aview, _dv = ac.build_views(att, dfn, {}, {"weapon": {"BS": -1}})
plain, _d2 = ac.build_views(att, dfn, {}, {})
for m1, m0 in zip(aview.models(), plain.models()):
    for w1, w0 in zip(m1.weapons, m0.weapons):
        if w1.type == "Ranged":
            assert w1._skill.value() == w0._skill.value() - 1, w1.name
assert total({"weapon": {"BS": -1}}) > base, "a better BS must help"
assert total({"defender_model": {"T": 2}}) < base, "tougher must hurt"
print("characteristic modifiers are applied when the views are built")

# --- 5. the dice resolver agrees --------------------------------------
for label, mods in [("hit re-roll", {"rerolls": {"hit": "fails"}}),
                    ("wound re-roll", {"rerolls": {"wound": "1"}}),
                    ("save re-roll", {"rerolls": {"save": "fails"}}),
                    ("roll modifiers", {"rolls": {"hit": 1, "wound": -1}})]:
    w, dview, mech = first_mech(mods)
    ref = ac.reference_options(dview)[0][1]
    ok, msg = mcs.check_weapon(label, w, ref, {}, mech)
    assert ok, f"{label}: {msg}"
print("exact maths and dice resolver agree on the manual modifiers")

print("ALL MANUAL-MODIFIER TESTS PASS")

# --- 6. characteristics are printed, not rolled -----------------------
# Characteristic.value() ROLLS a dice notation, so it must never be used
# to display a profile or to compare two scenarios: the inspect panel
# would show a different number at every refresh. notation() is what
# display code uses, value_avg() what comparisons use.
from characteristics import Characteristic              # noqa: E402
import leader_core as _lc                               # noqa: E402

for spec, shown, avg in (("D3", "D3", 2.0), ("D6", "D6", 3.5),
                         ("2D6+1", "2D6+1", 8.0), (3, "3", 3.0),
                         ("-", "-", None)):
    c = Characteristic(spec)
    assert c.notation() == shown, (spec, c.notation())
    assert str(c) == shown
    assert c.value_avg() == avg, (spec, c.value_avg())

# The inspect text must be stable across calls even with dice profiles.
# The synthetic roster has none, so give one weapon a dice Damage.
dice_unit = next(u for u in units
                 for m in u.models() for w in m.weapons
                 if w.type == "Ranged")
target_w = next(w for m in dice_unit.models() for w in m.weapons
                if w.type == "Ranged")
target_w.D = Characteristic("D6")
texts = {_lc.unit_inspect_text(dice_unit) for _ in range(8)}
assert len(texts) == 1, "the inspect text must not roll the dice"
assert "D D6" in texts.pop(), "the dice notation must appear as written"
print("dice characteristics are displayed as written, not rolled")
