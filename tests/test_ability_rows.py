"""Ability rows of the game assistant table.

The table shows one row per ability of a roster entry, and masking that
row switches the ability off. Three things must hold for that to work:

  * the row id grammar (tree_ids) round-trips, and the decoration rows
    never parse as items - an 'abilities' separator that parsed as
    ability 0 would silently toggle the first ability;
  * the key stored in the row id maps to the SAME ability the row was
    built from, across every scope (unit, core, faction, leader effect,
    model, weapon) and across the entry's parts (unit + helpers) - and
    keeps doing so when the entry changes shape, which is the whole
    point of keying on the ability's own id rather than its position;
  * writing the flag reaches the engine: a unit rebuilt from the roster
    must lose the effect of an ability whose row was masked.

The GUI toggle itself is two lines (parse the id, write the flag), so it
is reproduced here on the pure functions it calls - no tkinter needed,
exactly like test_dialog_logic.py.
"""
import testpaths                      # sets up sys.path to the engine src/
import leader_core as lc
import modifier_engine as me
import tree_ids
import unit_model as um


# ---------------- fixtures ----------------


def ability(name, kw=None, aid=None):
    """An ability with no effect, or one that grants a weapon keyword
    (observable in the combat view). 'aid' is the persistent id the row
    key is built from; None leaves the ability without one."""
    eff = {"type": "special", "data": {}} if kw is None else {
        "type": "setKeyword", "data": {
            "target": {"title": "All weapons", "key": "allWeapons"},
            "operation": {"title": "Add", "key": "add"},
            "keyword": kw}}
    ab = {"name": name, "description": "", "enabled": True,
          "share_with_unit": False, "conditions": [], "effect": eff}
    if aid is not None:
        ab["id"] = aid
    return ab


def unit_dict(name, abilities=None, core=None, faction=None,
              leader_effects=None, model_ab=None, weapon_ab=None):
    return {"name": name, "profile_name": name, "points": 10,
            "keywords": ["Infantry"],
            "abilities": abilities or [], "core_abilities": core or [],
            "faction_abilities": faction or [],
            "leader_effects": leader_effects or [],
            "leadership": [], "support": [],
            "apply_leader_effects_to_self": False, "damageable": False,
            "unit_composition": "", "wargear_options": "", "notes": "",
            "models": [{"name": f"{name} model", "model_count": 1, "M": 6,
                        "T": 4, "Sv": 3, "W": 2, "LD": 6, "OC": 1,
                        "invuln": None, "fnp": None, "keywords": [],
                        "abilities": model_ab or [],
                        "weapons": [{"name": "gun", "type": "Ranged",
                                     "RNG": 24, "A": 2, "BS": 3, "S": 4,
                                     "AP": 0, "D": 1, "count": 1,
                                     "keywords": [],
                                     "abilities": weapon_ab or []}]}]}


def sample_entry():
    """A joined entry covering every ability scope on both parts."""
    base = unit_dict("Base",
                     abilities=[ability("Grant", kw="LETHAL HITS",
                                        aid="a-grant")],
                     core=[ability("Core one", aid="a-core")],
                     faction=[ability("Faction one", aid="a-faction")],
                     model_ab=[ability("Model one", aid="a-model")],
                     weapon_ab=[ability("Weapon one", aid="a-weapon")])
    lead = unit_dict("Chief", abilities=[ability("Chief own", aid="a-own")],
                     leader_effects=[ability("Chief aura", aid="a-aura")],
                     model_ab=[ability("Chief model one", aid="a-lmodel")])
    lead["leadership"] = ["Infantry"]
    return lc.make_entry(base, lead)


def view_of(entry):
    """Attacker combat view of the entry, rebuilt from the roster dicts
    the way the game assistant does at every resolution."""
    unit = lc.build_entry_unit(entry, {}, set(), {}, "w40k-sim/6")
    return me.build_view(unit, None, me.Context(), role="attacker")


def weapon_keywords(v):
    return {str(k).upper() for m in v.models() for w in m.weapons
            for k in w.keywords}


def toggle_row(entry, iid, masked):
    """What cmd_mask does to an ability row, on the pure functions."""
    ui, key = tree_ids.parse_ability(iid)
    assert ui is not None, f"{iid} is not an ability row"
    return lc.set_entry_ability_enabled(entry, key, not masked)


def row_iid(entry, name, ui=0):
    """The row id the table would build for the ability called 'name'."""
    key = next(k for k, _s, a in lc.entry_ability_keys(entry)
               if a["name"] == name)
    return tree_ids.ability_iid(ui, key)


# ---------------- 1. row id grammar ----------------

assert tree_ids.parse(tree_ids.weapon_iid(3, 1, 2)) == (3, 1, 2, None)
assert tree_ids.parse(tree_ids.copy_iid(3, 1, 0)) == (3, 1, None, 0)
assert tree_ids.parse(tree_ids.model_iid(12, 4)) == (12, 4, None, None)
assert tree_ids.parse(tree_ids.unit_iid(7)) == (7, None, None, None)
assert tree_ids.parse_ability(tree_ids.ability_iid(3, "1f2e")) == (3, "1f2e")
assert tree_ids.parse_ability(tree_ids.ability_iid(3, "#7")) == (3, "#7")

# Decoration and cross-kind rows must not be mistaken for items: this is
# what keeps an 'abilities' separator from toggling ability 0.
assert tree_ids.parse_ability(tree_ids.abilities_sep_iid(3)) == (None, None)
assert tree_ids.parse(tree_ids.abilities_sep_iid(3)) == (None,) * 4
assert tree_ids.parse(tree_ids.models_sep_iid(3, 1)) == (None,) * 4
assert tree_ids.parse(tree_ids.ability_iid(3, "1f2e")) == (None,) * 4
assert tree_ids.parse_ability(tree_ids.model_iid(3, 5)) == (None, None)
assert tree_ids.is_separator(tree_ids.abilities_sep_iid(3))
assert not tree_ids.is_separator(tree_ids.ability_iid(3, "1f2e"))
assert tree_ids.parse("") == (None,) * 4 and tree_ids.parse("junk")[0] is None

# Every structural row resolves to its unit, ability rows included: the
# table uses this to know which unit is selected.
for iid in (tree_ids.unit_iid(4), tree_ids.model_iid(4, 0),
            tree_ids.weapon_iid(4, 0, 1), tree_ids.copy_iid(4, 0, 0),
            tree_ids.ability_iid(4, "1f2e")):
    assert tree_ids.entry_index(iid) == 4, iid
assert tree_ids.entry_index(tree_ids.abilities_sep_iid(4)) is None

# --- 2. the row index maps back to the row's own ability -------------

entry = sample_entry()
rows = list(lc.entry_ability_dicts(entry))
scopes = [s for s, _ab in rows]
assert scopes == ["unit", "core", "faction",
                  "model: Base model", "weapon: gun",
                  "leader:0: unit", "leader:0: leader effect",
                  "leader:0: model: Chief model"], scopes
keyed = lc.entry_ability_keys(entry)
assert [(s, a) for _k, s, a in keyed] == rows, "key list drifted from the enum"
assert [k for k, _s, _a in keyed] == [
    "a-grant", "a-core", "a-faction", "a-model", "a-weapon",
    "a-own", "a-aura", "a-lmodel"], keyed
for key, scope, ab in keyed:
    got_scope, got_ab = lc.entry_ability_by_key(entry, key)
    assert got_scope == scope and got_ab is ab, key  # identity, not equality
assert lc.entry_ability_by_key(entry, "no-such-key") == (None, None)

# The label names the ability: a description-only label would render the
# rows with no description (core/faction) as indistinguishable blanks.
labels = [lc.entry_ability_label(s, a) for s, a in rows]
assert labels[1] == "[core] Core one", labels[1]
assert labels[6] == "[leader:0: leader effect] Chief aura", labels[6]
assert lc.entry_ability_label("unit", {"name": "", "description":
                                       "no name"}) == "[unit] <unnamed ability>"

# --- 3. writing the flag ---------------------------------------------

assert lc.set_entry_ability_enabled(entry, "a-core", False) is True
assert entry["unit"]["core_abilities"][0]["enabled"] is False
assert lc.set_entry_ability_enabled(entry, "a-aura", False) is True
assert lc.helpers(entry, "leader")[0]["leader_effects"][0]["enabled"] is False
# the neighbours are untouched
assert entry["unit"]["abilities"][0]["enabled"] is True
assert entry["unit"]["faction_abilities"][0]["enabled"] is True
# unknown key (a stale row id): reported, never raised
assert lc.set_entry_ability_enabled(entry, "gone", False) is False

# --- 4. end to end: masking the row disables the ability -------------

entry = sample_entry()
iid = row_iid(entry, "Grant")

assert "LETHAL HITS" in weapon_keywords(view_of(entry)), \
    "the granting ability is not active to begin with"
toggle_row(entry, iid, masked=True)
assert "LETHAL HITS" not in weapon_keywords(view_of(entry)), \
    "a masked ability still reached the combat view"
toggle_row(entry, iid, masked=False)
assert "LETHAL HITS" in weapon_keywords(view_of(entry)), \
    "unmasking did not switch the ability back on"

# --- 5. the row tag is rebuilt from the flag -------------------------
# _fill_tree greys a row when the flag is off, so a session reload shows
# the abilities exactly as they were left.
toggle_row(entry, iid, masked=True)
assert lc.entry_ability_by_key(entry, tree_ids.parse_ability(iid)[1])[1] \
    .get("enabled", True) is False
# ...and the flag survives the rebuild of the Unit object.
unit = lc.build_entry_unit(entry, {}, set(), {}, "w40k-sim/6")
assert not next(ab for ab in unit.abilities
                if ab.get("name") == "Grant").get("enabled", True)

# --- 6. the key survives a change of shape of the entry ---------------
# This is what keying on the ability id buys: a leader joined in FIRST
# position shifts every later ability, so a positional row id would end
# up switching a DIFFERENT ability off.

entry = sample_entry()
aura_iid = row_iid(entry, "Chief aura")
keys_before = [k for k, _s, _a in lc.entry_ability_keys(entry)]
toggle_row(entry, aura_iid, masked=True)

extra = unit_dict("Second", abilities=[ability("Second own", aid="a-second")])
extra["leadership"] = ["Infantry"]
entry = lc.set_helpers(entry, "leader", [extra] + lc.helpers(entry, "leader"))
keys_after = [k for k, _s, _a in lc.entry_ability_keys(entry)]
assert keys_after.index("a-aura") != keys_before.index("a-aura"), \
    "the fixture no longer shifts positions - the test proves nothing"
assert tree_ids.parse_ability(aura_iid)[1] == "a-aura"
scope, ab = lc.entry_ability_by_key(entry, "a-aura")
assert ab is not None and ab["name"] == "Chief aura", scope
assert ab.get("enabled", True) is False, "the row now points elsewhere"
assert lc.entry_ability_by_key(entry, "a-second")[1]["enabled"] is True

# --- 7. rosters without usable ids fall back to the position ---------
# Files that never went through ability_ids.normalize, or two parts
# repeating one id, must still give every row a distinct key.

plain = lc.make_entry(unit_dict("Plain", abilities=[ability("One"),
                                                    ability("Two")]))
keys = [k for k, _s, _a in lc.entry_ability_keys(plain)]
assert keys == ["#0", "#1"], keys
assert lc.entry_ability_by_key(plain, "#1")[1]["name"] == "Two"
assert lc.set_entry_ability_enabled(plain, "#0", False) is True
assert plain["unit"]["abilities"][0]["enabled"] is False

clash = lc.make_entry(unit_dict("Clash", abilities=[ability("One", aid="x"),
                                                    ability("Two", aid="x")],
                                core=[ability("Three", aid="y")]))
keys = [k for k, _s, _a in lc.entry_ability_keys(clash)]
assert keys == ["#0", "#1", "y"], keys          # only the clashing pair falls back
assert len(set(keys)) == len(keys), "duplicate row keys"

# Sanity: um is the loader behind build_entry_unit (import kept honest).
assert um.units_from_native({"format": "w40k-sim/6", "armies": [
    {"name": "x", "units": [unit_dict("Solo")]}]})[0].name == "Solo"

print("ALL ABILITY ROW TESTS PASS")
