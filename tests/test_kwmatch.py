"""Test the keyword matcher for leader/support attachment: whole-entry
(Space Marines) and word-by-word (T'au) conventions, plus singular/plural."""
import testpaths                      # sets up sys.path to the engine src/
import unit_model as um

m = um._entry_matches_keywords
# T'au word-by-word: split keywords, plural entry
tau_kw = ["Battlesuit", "Crisis", "Fireknife", "Fly", "Vehicle"]
assert m("Crisis Fireknife Battlesuits", tau_kw), "T'au word-by-word failed"
assert not m("Crisis Sunforge Battlesuits", tau_kw), "should not match other variant"
# SM whole-entry: full name is a single keyword
sm_kw = ["Assault Intercessor Squad", "Battleline", "Infantry", "Tacticus"]
assert m("Assault Intercessor Squad", sm_kw), "SM whole-entry failed"
assert m("Assault Intercessor Squads", sm_kw), "SM plural whole-entry failed"
assert not m("Intercessor Squad", sm_kw), "partial name must not match"
# singular/plural helper
assert um._kw_key("Battlesuits") == um._kw_key("Battlesuit")
assert um._kw_key("Allies") == um._kw_key("Ally")
assert um._kw_key("Wolves") == um._kw_key("Wolf")
# spurious entry doesn't match
assert not m("Any unit with", tau_kw)
assert not m("", tau_kw)
# A keyword may itself be several words: 'Wolf Guard Headtakers' is
# covered by the pair 'WOLF GUARD' + 'HEADTAKERS' (the datasheet splits
# them because the unit mixes INFANTRY and BEASTS models).
MIXED = ["INFANTRY", "BEASTS", "IMPERIUM", "WOLF GUARD", "HEADTAKERS",
         "HUNTING WOLVES", "ADEPTUS ASTARTES", "SPACE WOLVES"]
assert um._entry_matches_keywords("Wolf Guard Headtakers", MIXED)
assert um._entry_matches_keywords("Hunting Wolves", MIXED)
assert um._entry_matches_keywords("Wolf Guard", MIXED)
# ...but a word the unit does not carry still fails
assert not um._entry_matches_keywords("Wolf Guard Terminators", MIXED)
assert not um._entry_matches_keywords("Blood Claws", MIXED)
# and a single stray word of a multi-word keyword is not a match
assert not um._entry_matches_keywords("Guard", MIXED)
print("a multi-word keyword covers several words of an entry")

print("ALL KW-MATCH TESTS PASS")
