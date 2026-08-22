"""Spec-driven forms: a CHOICE survives its own label being renamed.

A CHOICE is stored in a roster as {"title": ..., "key": ...}. The KEY is
the only part the engine reads; the title is what the combobox shows.
Before this was fixed the form seeded itself from the stored TITLE and
mapped it back with an unguarded lookup, so correcting the wording of a
spec label turned every roster already saved with the old wording into a
KeyError on the next save - a whole class of breakage sitting behind a
one-word documentation improvement.

What is checked:

  1. resolution is KEY-first in both directions, so an old title
     displays as the current label and saves back to the same key;
  2. nothing raises on a stored value the spec no longer knows, and the
     KEY is preserved when it is still valid - a renamed label must not
     silently change what an ability DOES;
  3. the real case this came from: the singleReRoll 'allowance' labels
     were reworded in the same commit as the fix, and a roster carrying
     the OLD wording must round-trip unharmed;
  4. the form round-trips through the actual widgets, driven headless.

Run:  python3 tests/test_spec_forms.py
"""
import testpaths                      # sets up sys.path to the engine src/
import tkstub

tkstub.install_if_missing()

import tkinter as tk                  # noqa: E402  (must follow the stub)
import spec_forms as sf               # noqa: E402
import effect_specs as es             # noqa: E402
import condition_specs as cs          # noqa: E402
import modifier_engine as me          # noqa: E402

OPTIONS = [("Brand new wording", "alpha"),
           ("Second option", "beta")]


# --- 1. key first, title second ---------------------------------------
# The stored title is stale; the key still names the option, so the form
# shows the CURRENT label.
assert sf.choice_title(OPTIONS, {"title": "Ancient wording",
                                 "key": "alpha"}) == "Brand new wording"
# No key at all (a hand-written roster): fall back on the title.
assert sf.choice_title(OPTIONS, {"title": "Second option"}) == "Second option"
# Keys are matched the way modifier_engine._key reads them.
assert sf.choice_title(OPTIONS, {"key": "ALPHA"}) == "Brand new wording"
# Nothing usable at all: the spec default, which is what a freshly
# created ability would get anyway.
assert sf.choice_title(OPTIONS, {"title": "?", "key": "?"}) == \
    "Brand new wording"
assert sf.choice_title(OPTIONS, None) == "Brand new wording"
assert sf.choice_title((), {"key": "alpha"}) == ""
print("a stored choice is resolved by key first, and never by luck")


# --- 2. writing back never raises, and never moves the key ------------
assert sf.choice_value(OPTIONS, "Second option") == {
    "title": "Second option", "key": "beta"}
# The title the widget holds is unknown to the spec, but the value being
# replaced still names a valid option: keep it.
kept = sf.choice_value(OPTIONS, "Ancient wording",
                       {"title": "Ancient wording", "key": "beta"})
assert kept == {"title": "Second option", "key": "beta"}, kept
# Nothing to go on: the spec default, rather than an exception.
assert sf.choice_value(OPTIONS, "???", {"key": "???"}) == {
    "title": "Brand new wording", "key": "alpha"}
assert sf.choice_value((), "anything") == {}
print("writing back keeps the key, and a renamed label raises nothing")


# --- 3. the real case: singleReRoll, saved before the rewording -------
FIELDS = es.EFFECT_SPECS["singleReRoll"]["fields"]
ALLOWANCE = next(o for k, _kind, _l, o in FIELDS if k == "allowance")
assert {k for _t, k in ALLOWANCE} == {"exclusive", "eachKind"}
# ...and the third kind the Damage re-roll added
ROLL = next(o for k, _kind, _l, o in FIELDS if k == "roll")
assert {k for _t, k in ROLL} == {"hit", "wound", "damage"}

old_roster = {"roll": {"title": "Hit roll", "key": "hit"},
              "allowance": {"title": "One roll of each kind (hit AND wound)",
                            "key": "eachKind"}}
assert sf.choice_title(ALLOWANCE, old_roster["allowance"]) \
    == "One roll of each kind (one per kind)"
# and what the engine reads is untouched by any of it
assert me._key(old_roster["allowance"]) == "eachkind"
print("a roster saved with the old allowance wording still reads right")


# --- 4. round trip through the real widgets ---------------------------
root = tk.Tk()
frame = tk.Frame(root)
data = dict(old_roster)
fvars = sf.build_form(frame, FIELDS, data)
shown = {key: var.get() for key, _kind, var, *_ in fvars}
assert shown["allowance"] == "One roll of each kind (one per kind)", shown
assert shown["roll"] == "Hit roll", shown

sf.apply_form(fvars, FIELDS, data)          # user pressed OK, touching nothing
assert data["allowance"]["key"] == "eachKind", data
assert data["allowance"]["title"] == "One roll of each kind (one per kind)"
assert data["roll"] == {"title": "Hit roll", "key": "hit"}, data

# now the user actually changes it, to the kind that did not exist before
for key, _kind, var, *_ in fvars:
    if key == "roll":
        var.set("Damage roll")
sf.apply_form(fvars, FIELDS, data)
assert data["roll"] == {"title": "Damage roll", "key": "damage"}, data
print("the form round-trips an old ability and edits it without loss")


# --- 5. every CHOICE in every spec has a usable default ---------------
# choice_title and choice_value fall back on options[0]; an empty option
# list would make that fallback silently produce nothing.
for name, spec in list(es.EFFECT_SPECS.items()) + list(
        cs.CONDITION_SPECS.items()):
    for key, kind, _label, options in spec.get("fields") or ():
        if kind != "choice":
            continue
        assert options, (name, key)
        assert len({k for _t, k in options}) == len(options), (name, key)
        assert len({t for t, _k in options}) == len(options), (name, key)
print("every CHOICE in every spec has distinct titles, keys and a default")

print("OK: spec forms")
