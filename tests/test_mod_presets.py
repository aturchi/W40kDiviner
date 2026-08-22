"""Named modifier presets (src/mod_presets.py).

The store is what survives a save/load cycle, so the checks are about
round-tripping and about the two mistakes a preset could quietly cause:
applying it twice (doubling a modifier with nothing in the list to show
for it) and losing the tuple shape of a re-roll key through JSON.
"""
import json

import testpaths                      # sets up sys.path to the engine src/
import mod_presets as mp

HIT = ("Hit roll", "rolls", "hit", 1)
WOUND = ("Wound roll", "rolls", "wound", -1)
RR = ("Hit reroll 1s", "rerolls", ("hit", "1"), None)
AP = ("Weapon AP", "weapon", "AP", -1)

# ---- how an entry reads ------------------------------------------------
assert mp.describe(HIT) == "Hit roll: +1"
assert mp.describe(WOUND) == "Wound roll: -1"
assert mp.describe(RR) == "Hit reroll 1s"          # no value for a re-roll
assert mp.summary([HIT, WOUND]) == "Hit roll: +1, Wound roll: -1"
assert mp.summary([]) == "empty"
assert mp.summary([HIT, WOUND, AP, RR], limit=2).endswith("(+2 more)")

# ---- the store ---------------------------------------------------------
store = mp.PresetStore()
assert len(store) == 0 and store.names() == []
assert store.save("Marker Light", [HIT, RR]) is True
assert store.save("Aura", [WOUND]) is True
assert store.names() == ["Marker Light", "Aura"]    # insertion order
assert "Marker Light" in store and "nope" not in store
assert store.get("Marker Light") == [HIT, RR]
# A preset with no name, or with nothing in it, would be a menu entry
# that does nothing.
assert store.save("", [HIT]) is False
assert store.save("Empty", []) is False
assert len(store) == 2

# ---- rename keeps its place in the menu --------------------------------
assert store.rename("Marker Light", "Markerlight") is True
assert store.names() == ["Markerlight", "Aura"], store.names()
assert store.rename("Markerlight", "Aura") is False   # name taken
assert store.rename("missing", "x") is False
assert store.delete("Aura") is True and store.delete("Aura") is False

# ---- JSON round trip: a re-roll key must stay a pair -------------------
store = mp.PresetStore()
store.save("Marker Light", [HIT, RR, AP])
blob = json.loads(json.dumps(store.to_json()))     # what a session file
back = mp.PresetStore(blob)                        # would hand back
assert back.get("Marker Light") == store.get("Marker Light")
assert isinstance(back.get("Marker Light")[1][2], tuple), \
    "the re-roll key came back as a list and would never compare equal"

# ---- applying: adds, never doubles -------------------------------------
mods, added, skipped = mp.apply_to([], [HIT, RR])
assert (added, skipped) == (2, 0) and mods == [HIT, RR]
mods2, added, skipped = mp.apply_to(mods, [HIT, RR])
assert (added, skipped) == (0, 2), (added, skipped)
assert mods2 == mods, "applying the same preset twice changed the list"
# Two different presets combine, which is the normal case at the table.
mods3, added, skipped = mp.apply_to(mods, [WOUND])
assert (added, skipped) == (1, 0) and mods3[-1] == WOUND
# A partial overlap adds only what is missing.
mods4, added, skipped = mp.apply_to(mods, [HIT, AP])
assert (added, skipped) == (1, 1) and AP in mods4

# The same entry arriving from JSON (lists, not tuples) is still
# recognised as already present.
as_lists = [list(HIT), ["Hit reroll 1s", "rerolls", ["hit", "1"], None]]
_m, added, skipped = mp.apply_to(mods, as_lists)
assert (added, skipped) == (0, 2), (added, skipped)

# ---- the value keeps its sign, which is the whole point ---------------
minus = ("Hit roll", "rolls", "hit", -1)
assert not mp.same(HIT, minus)
_m, added, _s = mp.apply_to([HIT], [minus])
assert added == 1, "a +1 and a -1 on the same roll are different entries"

print("mod presets: OK")
