"""Test ArmyLoadState: join a subset, discard-on-unselect, build union."""
import testpaths                      # sets up sys.path to the engine src/
import native_format as nf
from army_load_core import ArmyLoadState

def army(name, unit_names):
    return {"format": nf.FORMAT_TAG, "armies": [{"name": name, "units": [
        {"name": n, "models": [], "keywords": [], "leadership": [],
         "support": []} for n in unit_names]}]}

st = ArmyLoadState([army("Alpha", ["x", "shared"]),
                    army("Beta", ["y", "shared"]),
                    army("Gamma", ["z"])])
assert st.names() == ["Alpha", "Beta", "Gamma"]

# Join Alpha(0) + Beta(1) -> new army; originals removed, joined appended.
# A join is a change to the document: what comes out is no longer any of
# the files it came from, so the caller must not save it back over one.
assert st.modified is False
st.join([0, 1], "AB")
assert st.modified is True
assert st.names() == ["Gamma", "AB"], st.names()
ab = st.armies[1]["armies"][0]
names = [u["name"] for u in ab["units"]]
assert names == ["x", "shared_Alpha", "y", "shared_Beta"], names
print("join: colliding units suffixed, originals removed:", names)

# Build with only the joined army selected (Gamma discarded)
data = st.build([1])
assert len(data["armies"]) == 1 and data["armies"][0]["name"] == "AB"
print("build joined-only: Gamma discarded, imported =",
      [a["name"] for a in data["armies"]])

# Build with both -> union of two armies
data2 = st.build([0, 1])
assert [a["name"] for a in data2["armies"]] == ["Gamma", "AB"]
print("build both:", [a["name"] for a in data2["armies"]])

# Errors
try:
    st.join([0], "x"); assert False
except ValueError: pass
try:
    st.join([0, 1], "  "); assert False
except ValueError: pass
assert st.build([]) is None
print("ALL ARMYLOAD TESTS PASS")


# --- the dialog itself: picking armies with the mouse only ------------

# The list used Tk's EXTENDED mode, where a plain click REPLACES the
# selection and picking a subset needs Ctrl+click. MULTIPLE toggles one
# entry per click and leaves the rest alone, which is what a short list
# of armies wants; the hint has to match, or it tells the player to hold
# a key that does nothing.
import tkstub                                          # noqa: E402

tkstub.install()

import tkinter as tk                                   # noqa: E402
import ui_utils as ui                                  # noqa: E402
import army_load_dialog as ald                         # noqa: E402

_root = tk.Tk()
_dlg = ald.ArmyLoadDialog(_root, [
    {"format": "w40k-sim/6", "armies": [{"name": "Alpha", "units": []}]},
    {"format": "w40k-sim/6", "armies": [{"name": "Beta", "units": []}]},
    {"format": "w40k-sim/6", "armies": [{"name": "Gamma", "units": []}]}])
assert _dlg.listbox.cget("selectmode") == tk.MULTIPLE, \
    _dlg.listbox.cget("selectmode")
assert list(_dlg.listbox.get(0, tk.END)) == ["Alpha", "Beta", "Gamma"]

# The hint must not name a modifier key the mode does not use.
_texts = []


def _walk(w):
    _texts.append(str(w.cget("text")) if "text" in getattr(w, "_opts", {})
                  else "")
    for c in w.winfo_children():
        _walk(c)


_walk(_dlg)
_hint = [t for t in _texts if "click" in t.lower()]
assert _hint, _texts
assert any(ui.TOGGLE_SELECT_HINT in t for t in _hint), _hint
assert not any("Ctrl+click" in t or "Cmd+click" in t for t in _hint), _hint
print("the army list toggles on click, and says so")


# --- rename, conflicts, save ------------------------------------------

import json                                              # noqa: E402
import os                                                # noqa: E402
import tempfile                                          # noqa: E402
import ability_ids                                       # noqa: E402
from army_load_core import ArmyLoadState as _State        # noqa: E402


def fresh():
    return _State([army("Space Marines", ["a", "b"]),
                   army("Space Marines", ["c"]),
                   army("T\u2019au Empire", ["d"])])


# A working set fresh off the disk claims nothing has been done to it:
# the caller uses that to decide whether Save may write back to the file
# it came from without asking.
st2 = fresh()
assert st2.modified is False
st2.rename(1, "Space Marines (Legends)")
assert st2.modified is True
assert st2.names() == ["Space Marines", "Space Marines (Legends)",
                       "T\u2019au Empire"], st2.names()
print("rename:", st2.names()[1])

# The name has to be free and non-empty: both joins reject duplicates, so
# a rename that created one would only move the failure further away.
for bad, why in ((0, "Space Marines (Legends)"), (0, "   ")):
    try:
        st2.rename(bad, why)
        raise AssertionError(f"rename to {why!r} must be refused")
    except ValueError:
        pass
assert st2.names()[0] == "Space Marines", st2.names()
st2.rename(0, "Space Marines")          # renaming an army to its own name
print("rename refuses an empty or already-taken name")

# conflicts() answers for the SELECTION, not for the whole list: two
# armies may share a name while the pair the user picked does not.
st3 = fresh()
assert st3.conflicts() == ["Space Marines"], st3.conflicts()
assert st3.conflicts([0, 2]) == [], st3.conflicts([0, 2])
assert st3.conflicts([0, 1]) == ["Space Marines"]
assert st3.conflicts([1]) == []
print("conflicts follow the selection:", st3.conflicts([0, 1]))

# build() is lenient by default (the user may still want to look at a
# colliding pair) and strict for save.
assert len(st3.build([0, 1])["armies"]) == 2
try:
    st3.build([0, 1], strict=True)
    raise AssertionError("a strict build must reject duplicate names")
except ValueError as exc:
    assert "Space Marines" in str(exc), exc
print("strict build rejects what a lenient one accepts")

# save(): one army -> single-army file, several -> multi-army file, each
# army keeping its own identity.
tmpdir = tempfile.mkdtemp(prefix="w40k_join_")
one = os.path.join(tmpdir, "one.json")
multi = os.path.join(tmpdir, "multi.json")

st4 = fresh()
st4.rename(1, "Space Marines (Legends)")
armies, units, _stamped = st4.save([0], one)
assert (armies, units) == (1, 2), (armies, units)
back = nf.load(one)
assert [a["name"] for a in back["armies"]] == ["Space Marines"], back

armies, units, _stamped = st4.save([0, 1, 2], multi)
assert (armies, units) == (3, 4), (armies, units)
back = nf.load(multi)
assert [a["name"] for a in back["armies"]] == [
    "Space Marines", "Space Marines (Legends)", "T\u2019au Empire"], back
print("save: one army ->", armies, "in the multi file, units =", units)

try:
    st4.save([], os.path.join(tmpdir, "never.json"))
    raise AssertionError("saving nothing must be refused")
except ValueError:
    pass
assert not os.path.exists(os.path.join(tmpdir, "never.json"))

# A colliding pair must never reach the disk: the file could not be
# joined or split again afterwards.
st5 = fresh()
never = os.path.join(tmpdir, "clash.json")
try:
    st5.save([0, 1], never)
    raise AssertionError("saving two same-named armies must be refused")
except ValueError:
    pass
assert not os.path.exists(never), "the refused save must not have written"
print("save refuses - and does not write - a file with colliding names")

# Ability ids are re-stamped before writing: they are unique per SOURCE
# file, so a merge without re-stamping produces a file whose toggles
# address two abilities at once.
dup_ability = {"name": "Shared", "description": "", "enabled": True,
               "share_with_unit": False, "conditions": [],
               "effect": {"type": "special", "data": {}}, "id": "SAME"}
st6 = _State([army("One", ["u1"]), army("Two", ["u2"])])
st6.armies[0]["armies"][0]["units"][0]["abilities"] = [dict(dup_ability)]
st6.armies[1]["armies"][0]["units"][0]["abilities"] = [dict(dup_ability)]
stamped_path = os.path.join(tmpdir, "ids.json")
_a, _u, stamped = st6.save([0, 1], stamped_path)
assert stamped >= 1, stamped
with open(stamped_path, encoding="utf-8") as fh:
    written = json.load(fh)
ids = [ab["id"] for a in written["armies"] for u in a["units"]
       for ab in u.get("abilities", [])]
assert len(ids) == len(set(ids)) == 2, ids
assert ability_ids.ensure_ids(written) == 0, "the written file is already unique"
print("save re-stamps colliding ability ids:", stamped, "->", ids)

import shutil                                            # noqa: E402
shutil.rmtree(tmpdir, ignore_errors=True)


# --- the dialog: rename and save wired to the buttons -----------------

def make_dialog(state_armies, allow_save=True):
    dlg = ald.ArmyLoadDialog(_root, state_armies, allow_save=allow_save)
    return dlg


clash = [army("Space Marines", ["a"]), army("Space Marines", ["b"]),
         army("T\u2019au Empire", ["c"])]
d = make_dialog(clash)
assert d.save_btn is not None, "the editor's dialog must offer Save"
assert make_dialog(clash, allow_save=False).save_btn is None, \
    "the analyzer's dialog must not"

# The warning is not a refusal after the fact: it appears as soon as a
# colliding pair is ticked.
assert d.warn.cget("text") == "", d.warn.cget("text")
d.listbox.selection_set(0)
d.listbox.selection_set(2)
d.listbox.event_generate("<<ListboxSelect>>")
assert d.warn.cget("text") == "", d.warn.cget("text")
d.listbox.selection_set(1)
d.listbox.event_generate("<<ListboxSelect>>")
assert "share a name" in d.warn.cget("text"), d.warn.cget("text")
print("the dialog warns while ticking:", d.warn.cget("text")[:48], "...")

# Rename through the button clears it, and the renamed row stays picked.
d._ask_name = lambda *a, **k: "Space Marines (Legends)"
d.listbox.selection_clear(0, tk.END)
d.listbox.selection_set(1)
d.cmd_rename()
assert d.state.names()[1] == "Space Marines (Legends)", d.state.names()
assert d.listbox.selection_includes(1), "the renamed army stays selected"
d.listbox.selection_set(0)
d.listbox.selection_set(2)
d.listbox.event_generate("<<ListboxSelect>>")
assert d.warn.cget("text") == "", d.warn.cget("text")
print("renaming through the button clears the warning")

# A file name is suggested from what is being written.
assert ald.ArmyLoadDialog._suggest_filename(["T\u2019au Empire"]) \
    == "t-au-empire.json"
assert ald.ArmyLoadDialog._suggest_filename(["A", "B"]) == "joined.json"

# Rename acts on ONE army: with two ticked there is no way to tell which
# name the answer belongs to.
d._ask_name = lambda *a, **k: "Should not happen"
d.listbox.selection_clear(0, tk.END)
d.listbox.selection_set(0)
d.listbox.selection_set(2)
_before = list(d.state.names())
d.cmd_rename()
assert d.state.names() == _before, d.state.names()
print("Rename refuses a selection of two")

tmpdir = tempfile.mkdtemp(prefix="w40k_join_")
out = os.path.join(tmpdir, "written.json")
d.listbox.selection_set(1)              # all three ticked, no collision
d._ask_path = lambda initialfile: out
d.cmd_save()
assert [a["name"] for a in nf.load(out)["armies"]] == [
    "Space Marines", "Space Marines (Legends)", "T\u2019au Empire"]
assert d.result is None, "Save must not answer the caller"
assert d in _root.winfo_children(), \
    "Save must leave the window open - several files, one session"
print("Save writes the ticked armies and leaves the window open")

# Cancelling the file dialog writes nothing.
d._ask_path = lambda initialfile: ""
os.remove(out)
d.cmd_save()
assert not os.path.exists(out), "a cancelled save must not write"

# A colliding selection is refused BEFORE the file dialog: the user is
# not asked where to put a file that will not be written.
clash2 = make_dialog([army("Space Marines", ["a"]),
                      army("Space Marines", ["b"])])
_asked = []
clash2._ask_path = lambda initialfile: _asked.append(initialfile) or out
clash2.listbox.selection_set(0)
clash2.listbox.selection_set(1)
clash2.cmd_save()
assert _asked == [], "a colliding save must not even ask for a path"
assert not os.path.exists(out), "a colliding save must not write"
print("a colliding save is refused before the file dialog opens")

shutil.rmtree(tmpdir, ignore_errors=True)
print("ALL ARMY JOIN/SAVE TESTS PASS")
