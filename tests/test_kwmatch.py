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
print("ALL KW-MATCH TESTS PASS")
