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

# Join Alpha(0) + Beta(1) -> new army; originals removed, joined appended
st.join([0, 1], "AB")
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
