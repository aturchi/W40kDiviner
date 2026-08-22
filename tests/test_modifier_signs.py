"""Sign conventions of the manual modifiers.

The value field of the manual-modifier panel means two different things
depending on the target, and they read in OPPOSITE directions:

  * a ROLL modifier is die-side ('r + mod >= target'), so +1 always
    makes the roll easier - for whoever rolls it, which for save,
    invuln and FNP is the DEFENDER;
  * a CHARACTERISTIC modifier is a raw delta on the stored value, so it
    improves BS/WS/Sv/LD (target numbers) and AP (stored negative) only
    when it is NEGATIVE, and everything else when it is positive.

modifier_engine.improving_sign owns that direction and is checked here
against the two tables the ability effects already use, so a panel
default or hint can never disagree with what an ability does. The
end-to-end half - that a negative BS delta really improves the attack -
is measured on the analyzer, without touching the GUI.

setup_panel needs tkinter; where it imports, its helpers are checked too.
"""
import testpaths                      # sets up sys.path to the engine src/
import analyzer_core as ac
import modifier_engine as me
import unit_model as um


# ---------------- 1. the direction table ----------------

# Target numbers and AP improve DOWNWARDS...
for attr in ("BS", "WS", "Sv", "LD", "invuln", "AP", "_skill"):
    assert me.improving_sign(attr) == -1, attr
# ...every other characteristic upwards.
for attr in ("A", "S", "D", "RNG", "M", "T", "W", "OC"):
    assert me.improving_sign(attr) == +1, attr
# An unknown attribute must not raise: it defaults to the common case.
assert me.improving_sign("nonsense") == +1

# The lookup must agree with the tables the ability effects use, or an
# ability's "improve by 1" and a manual modifier would disagree.
for attr, sign in me._IMPROVE_SIGN.items():
    assert me.improving_sign(attr) == sign, attr
for attr, sign in me._MODEL_IMPROVE_SIGN.items():
    assert me.improving_sign(attr) == sign, attr
# BS and WS are the datasheet names of the same '_skill' characteristic.
assert me.improving_sign("BS") == me.improving_sign("_skill")


# ---------------- 2. the direction is the real one ----------------

def roster(sv=3):
    return {"format": "w40k-sim/6", "armies": [{"name": "T", "units": [{
        "name": "U", "profile_name": "U", "points": 10,
        "keywords": ["Infantry"], "abilities": [], "core_abilities": [],
        "faction_abilities": [], "leadership": [], "support": [],
        "leader_effects": [], "apply_leader_effects_to_self": False,
        "damageable": False, "unit_composition": "", "wargear_options": "",
        "notes": "",
        "models": [{"name": "M", "model_count": 1, "M": 6, "T": 4, "Sv": sv,
                    "W": 2, "LD": 6, "OC": 1, "invuln": None, "fnp": None,
                    "keywords": [], "abilities": [], "weapons": [
                        {"name": "gun", "type": "Ranged", "RNG": 24, "A": 6,
                         "BS": 3, "S": 5, "AP": -1, "D": 1, "count": 1,
                         "keywords": [], "abilities": []}]}]}]}]}


ATT = um.units_from_native(roster())[0]
DEF = um.units_from_native(roster())[0]


def damage(mods):
    """Mean damage of the whole unit under those manual modifiers, taking
    the defensive profile from the (modified) defender view, the way the
    analyzer does."""
    aview, dview = ac.build_views(ATT, DEF, {}, mods)
    ref = ac.reference_options(dview)[0][1]
    return ac.run_analysis(aview, dview, ref, {}, "ranged",
                           manual=mods)["totals"]["damage"]["mean"]


BASE = damage({})
assert BASE > 0

# Roll modifiers: +1 helps whoever rolls the die.
assert damage({"rolls": {"hit": +1}}) > BASE
assert damage({"rolls": {"hit": -1}}) < BASE
assert damage({"rolls": {"save": +1}}) < BASE      # the defender rolls it
assert damage({"rolls": {"save": -1}}) > BASE

# Weapon characteristics: BS and AP improve with a NEGATIVE delta.
assert damage({"weapon": {"BS": -1}}) > BASE
assert damage({"weapon": {"BS": +1}}) < BASE
assert damage({"weapon": {"AP": -1}}) > BASE
assert damage({"weapon": {"AP": +1}}) < BASE
# ...the rest with a positive one.
assert damage({"weapon": {"A": +1}}) > BASE
assert damage({"weapon": {"D": +1}}) > BASE

# Defender characteristics: a better Sv (-1) or a higher T shields it.
assert damage({"defender_model": {"Sv": -1}}) < BASE
assert damage({"defender_model": {"Sv": +1}}) > BASE
assert damage({"defender_model": {"T": +1}}) < BASE

# The sign that improves the ATTACK is the improving sign of the
# characteristic on the weapon, and its opposite on the defender.
for attr in ("BS", "AP", "A", "D"):
    better = {"weapon": {attr: me.improving_sign(attr)}}
    assert damage(better) >= BASE, attr
for attr in ("Sv", "T"):
    worse_for_attacker = {"defender_model": {attr: me.improving_sign(attr)}}
    assert damage(worse_for_attacker) <= BASE, attr


# ---------------- 3. the panel helpers, when Tk is available ----------

try:
    import setup_panel as sp
except ImportError as exc:            # headless box: tkinter not installed
    print("setup_panel skipped (%s)" % exc)
else:
    for label, kind, key in sp.MOD_TARGETS:
        default = sp.mod_default_value(kind, key)
        hint = sp.mod_hint(kind, key)
        assert hint, label
        if kind == "rerolls":
            continue
        # The default must be the improving sign, and the hint must
        # announce the same sign it fills in - a hint that says '-1' over
        # a field holding '+1' is worse than no hint at all.
        assert default in ("+1", "-1"), (label, default)
        assert int(default) == sp.mod_improving_sign(kind, key), label
        assert hint.startswith(default), (label, default, hint)
        if kind == "rolls":
            assert default == "+1", label
    # The two kinds really do disagree, which is the whole reason for
    # the per-target default.
    assert sp.mod_default_value("rolls", "hit") == "+1"
    assert sp.mod_default_value("weapon", "BS") == "-1"
    assert sp.mod_default_value("weapon", "AP") == "-1"
    assert sp.mod_default_value("weapon", "A") == "+1"
    assert sp.mod_default_value("defender_model", "Sv") == "-1"
    assert "defender" in sp.mod_hint("rolls", "save")
    assert "attacker" in sp.mod_hint("rolls", "hit")

print("ALL MODIFIER SIGN TESTS PASS")
