"""The printable cheat sheet of a unit.

Both renderers come from one intermediate structure, so what is checked
here is mostly that structure - plus the two things a printed sheet can
get silently and embarrassingly wrong:

  * a DICE characteristic must be printed as the datasheet writes it
    (A "D6"), never rolled: value() would put one random number on the
    paper and a different one on the next print;
  * a DISABLED ability must still appear, marked as off. An ability
    missing from the sheet is invisible; an ability printed as "[OFF]"
    is a fact the opponent can check.

The CSV export of the analyzer table is checked here too - the file has
to be the table, not a second opinion about it.

No tkinter, no external data.
"""
import csv as csv_module
import io

import testpaths                      # sets up sys.path to the engine src/
import analyzer_core as ac
import cheat_sheet as cs
import result_rows
from unit_model import units_from_native


def ability(name, desc="", enabled=True):
    return {"name": name, "description": desc, "enabled": enabled,
            "share_with_unit": False, "conditions": [],
            "effect": {"type": "special", "data": {}}}


def weapon(name, wtype="Ranged", A="2", D="1", count=1, keywords=()):
    return {"name": name, "type": wtype, "RNG": 24 if wtype == "Ranged"
            else None, "A": A, "BS": 3, "WS": 3, "S": 4, "AP": -1, "D": D,
            "count": count, "keywords": list(keywords), "abilities": []}


def unit_dict(name, weapons, abilities=(), leadership=(), count=1,
              **extra):
    out = {"name": name, "profile_name": name, "points": 95,
           "keywords": ["Infantry", "Grenades"], "abilities": list(abilities),
           "core_abilities": [], "faction_abilities": [],
           "leader_effects": [], "leadership": list(leadership),
           "support": [], "apply_leader_effects_to_self": False,
           "damageable": False, "unit_composition": "1 Sergeant, 4 troopers",
           "wargear_options": "", "notes": "",
           "models": [{"name": f"{name} model", "model_count": count,
                       "M": 6, "T": 4, "Sv": 3, "W": 2, "LD": 6, "OC": 2,
                       "invuln": 4, "fnp": None, "keywords": [],
                       "abilities": [], "weapons": weapons}]}
    out.update(extra)
    return out


DATA = {"format": "w40k-sim/6", "armies": [{"name": "Test", "units": [
    unit_dict("Squad",
              [weapon("bolt rifle", count=5, keywords=["Rapid fire 1"]),
               weapon("chainsword", wtype="Melee", A="D6", count=5),
               weapon("plasma", A="1", D="D3", count=1)],
              abilities=[ability("Oath", "Re-roll hits."),
                         ability("Old rule", "Not in play.", enabled=False)],
              count=5),
    unit_dict("Chief", [weapon("power fist", wtype="Melee", A="4")],
              abilities=[ability("Rites", "Fights first.")],
              leadership=["Infantry"])]}]}

units = units_from_native(DATA)
squad = next(u for u in units if u.name == "Squad")
chief = next(u for u in units if u.name == "Chief")

# --- 1. the structure --------------------------------------------------

s = cs.sections(squad)
assert s["name"] == "Squad" and s["points"] == 95
assert s["keywords"] == ["Infantry", "Grenades"]
assert len(s["models"]) == 1
m = s["models"][0]
assert m["count"] == 5
assert dict(m["stats"])["Sv"] == "3+" and dict(m["stats"])["Inv"] == "4+"
assert "FNP" not in dict(m["stats"]), "an absent FNP must not be printed"
assert [r[0] for r in m["ranged"]] == ["bolt rifle", "plasma"]
assert [r[0] for r in m["melee"]] == ["chainsword"]
text_head = cs.as_text(squad)
assert "Ranged" in text_head and "Melee" in text_head, \
    "the two weapon tables must be told apart on paper"
assert ("Unit composition", "1 Sergeant, 4 troopers") in s["notes"]
print("sections span the models, split ranged from melee, keep the notes")

# --- 2. dice characteristics are printed, never rolled ----------------

chain = next(r for r in m["melee"] if r[0] == "chainsword")
assert chain[cs.MELEE_COLUMNS.index("A")] == "D6", chain
plasma = next(r for r in m["ranged"] if r[0] == "plasma")
assert plasma[cs.RANGED_COLUMNS.index("D")] == "D3", plasma
# ...and it is the same on every render, which value() would not be
assert cs.as_text(squad) == cs.as_text(squad)
print("dice characteristics keep their notation across renders")

# --- 3. a disabled ability is printed as off, not dropped -------------

names = {a["name"]: a for a in s["abilities"]}
assert names["Oath"]["enabled"] and not names["Old rule"]["enabled"]
text = cs.as_text(squad)
assert "Old rule" in text and "[OFF]" in text
assert "Re-roll hits." in text
html = cs.as_html(squad)
assert "Old rule" in html and "[OFF]" in html and "class='off'" in html
print("a disabled ability is printed as off, not dropped")

# --- 4. the leader's models and abilities travel with the unit --------

joined = squad.attach_leader(chief)
js = cs.sections(joined)
assert [mm["name"] for mm in js["models"]] == ["Squad model", "Chief model"]
assert "Rites" in {a["name"] for a in js["abilities"]}
assert js["points"] == 190
assert "power fist" in cs.as_text(joined)
print("a joined unit prints the leader's models and abilities too")

# --- 5. HTML is escaped and self-contained ----------------------------

nasty = units_from_native({"format": "w40k-sim/6", "armies": [{
    "name": "x", "units": [unit_dict(
        "A<b>&</b>", [weapon("gun & <shield>")],
        abilities=[ability("<script>", "1 < 2 & 3 > 2")])]}]})[0]
out = cs.as_html(nasty)
assert "<script>" not in out and "&lt;script&gt;" in out
assert "A&lt;b&gt;&amp;" in out and "gun &amp; &lt;shield&gt;" in out
assert out.startswith("<!DOCTYPE html>") and out.rstrip().endswith("</html>")
assert "<style>" in out, "the sheet must print without any other file"
print("HTML is escaped and stands on its own")

# --- 6. the extension chooses the renderer ----------------------------

assert cs.render(squad, "/tmp/x.txt") == cs.as_text(squad)
assert cs.render(squad, "/tmp/X.HTML") == cs.as_html(squad)
assert cs.render(squad, "/tmp/no_extension") == cs.as_html(squad)
name = cs.default_filename(nasty)
assert name == "A_b____b_cheatsheet" and name.replace("_", "").isalnum(), name
print("the file name chooses the format and survives any file system")

# --- 7. the exported CSV is the table ---------------------------------

aview, dview = ac.build_views(squad, chief, {}, {})
ref = ac.reference_options(dview)[0][1]
results = ac.run_analysis(aview, dview, ref, {}, "ranged", None, {})
rows = list(csv_module.reader(io.StringIO(result_rows.to_csv(results))))
table = result_rows.table(results)
# The heading carries the STATISTIC on show, so a file exported while a
# column was reading a percentile cannot be read as a table of means.
assert rows[0] == ["Weapon"] + [result_rows.heading(k)
                                for k, _t, _w in
                                result_rows.columns(results)]
import dist_stats as _ds                                    # noqa: E402
hi_label = _ds.SPREAD_LABELS[1]
upper = result_rows.to_csv(results, {"dmg": "hi"}).splitlines()[0]
assert f"Damage {hi_label}" in upper and "Damage \u03bc" not in upper, upper
assert len(rows) == len(table) + 1, (len(rows), len(table))
for csv_row, (name, values) in zip(rows[1:], table):
    assert csv_row == [name] + [str(v) for v in values], (csv_row, name)
assert rows[-1][0].startswith("TOTAL"), rows[-1]
print("the exported CSV is row for row the table on screen")

print("OK: cheat sheet and CSV export")
