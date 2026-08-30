"""The profile editor's import and join/save wiring.

Import no longer merges same-named armies behind the user's back
(load_many did); it lists what is on disk (split_armies) and hands the
decision to the load dialog. Two consequences are asserted here:

- what "Revert" and a silent "Save" may target. They may only target the
  source file when the document in memory IS that file - one path,
  nothing joined or renamed, every army kept - because anything else
  would write a truncated or reshaped roster over the original.
- the dialog is handed COPIES of the in-memory armies, so a rename
  inside it does not reach the loaded document unless it is confirmed.
"""
import json
import os
import shutil
import sys
import tempfile

import testpaths                                          # noqa: F401
import tkstub

tkstub.install()

sys.path.insert(0, testpaths.REPO_ROOT)     # profile_editor.py lives there

import native_format as nf                                # noqa: E402
import profile_editor as pe                               # noqa: E402

TMP = tempfile.mkdtemp(prefix="w40k_editor_")


def unit(name):
    return {"name": name, "points": 0, "models": [], "keywords": [],
            "leadership": [], "support": [], "abilities": []}


def write(fname, armies):
    path = os.path.join(TMP, fname)
    data = {"format": nf.FORMAT_TAG,
            "armies": [{"name": n, "units": [unit(u) for u in us]}
                       for n, us in armies]}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    return path


ONE = write("one.json", [("Space Marines", ["Intercessor"])])
TWO = write("two.json", [("Space Marines", ["Intercessor", "Captain"]),
                         ("Space Wolves", ["Blood Claw"])])

app = pe.EditorApp()


class FakeDialog:
    """Stands in for ArmyLoadDialog: 'picked' is what the user ticked,
    'modified' whether they joined or renamed anything."""

    made = []

    def __init__(self, parent, singles, allow_save=False, title="",
                 open_label=""):
        self.singles = singles
        self.allow_save = allow_save
        self.state = type("S", (), {"modified": False})()
        self.result = None
        FakeDialog.made.append(self)

    def arrange(self, picked, modified=False):
        self.state.modified = modified
        armies = []
        for i in picked:
            armies.extend(self.singles[i]["armies"])
        self.result = {"format": nf.FORMAT_TAG, "armies": armies}


def run_import(paths, arrange=None):
    """Drive cmd_import with the file picker and the dialog replaced."""
    FakeDialog.made.clear()
    pe.ask_roster_files = lambda *a, **k: tuple(paths)

    def factory(*a, **k):
        dlg = FakeDialog(*a, **k)
        if arrange is not None:
            arrange(dlg)
        return dlg

    pe.ArmyLoadDialog = factory
    app.wait_window = lambda *a, **k: None
    app.cmd_import()
    return FakeDialog.made[0] if FakeDialog.made else None


# --- one file, one army: no dialog, the path is kept ------------------

assert run_import([ONE]) is None, "one army needs no dialog"
assert app.current_path == ONE, app.current_path
assert [a["name"] for a in app.data["armies"]] == ["Space Marines"]
print("single army: imported straight, source path kept ->",
      os.path.basename(app.current_path))

# --- one file, two armies, everything kept and untouched --------------

run_import([TWO], lambda d: d.arrange([0, 1]))
assert [a["name"] for a in app.data["armies"]] == ["Space Marines",
                                                   "Space Wolves"]
assert app.current_path == TWO, app.current_path
print("whole file taken unchanged: the source path is still usable")

# --- a subset of that file: the document is no longer the file --------

run_import([TWO], lambda d: d.arrange([1]))
assert [a["name"] for a in app.data["armies"]] == ["Space Wolves"]
assert app.current_path is None, \
    "saving a subset over the source file would truncate it"
print("subset imported: source path dropped")

# --- everything kept but joined or renamed ----------------------------

run_import([TWO], lambda d: d.arrange([0, 1], modified=True))
assert app.current_path is None, \
    "a joined or renamed document is not the file it came from"
print("modified in the dialog: source path dropped")

# --- two files: same-named armies stay TWO armies ---------------------

dlg = run_import([ONE, TWO], lambda d: d.arrange([0, 1, 2]))
assert [d["armies"][0]["name"] for d in dlg.singles] == [
    "Space Marines", "Space Marines", "Space Wolves"], \
    "split_armies must not merge two armies that share a name"
assert len(app.data["armies"]) == 3, app.data["armies"]
assert app.current_path is None, "a union of two files is neither of them"
print("two files, three armies (the collision is shown, not merged)")

# The editor's dialog offers Save; the import goes through it.
assert dlg.allow_save is True

# --- Join / save on what is already loaded ----------------------------

FakeDialog.made.clear()
pe.ArmyLoadDialog = FakeDialog
app.wait_window = lambda *a, **k: None
before = [a["name"] for a in app.data["armies"]]
app.cmd_join_armies()                       # dialog left unconfirmed
assert FakeDialog.made and FakeDialog.made[0].result is None
assert [a["name"] for a in app.data["armies"]] == before, \
    "cancelling the dialog must leave the document alone"

# The dialog gets COPIES: renaming inside it cannot reach the loaded
# document until Apply. The units list is shared on purpose - copying it
# would mean duplicating the whole roster to change a string.
handed = FakeDialog.made[0].singles
handed[0]["armies"][0]["name"] = "Renamed in the dialog"
assert app.data["armies"][0]["name"] == before[0], app.data["armies"][0]
assert handed[0]["armies"][0]["units"] is app.data["armies"][0]["units"], \
    "the units list is shared, only the army dict is copied"
print("Join/save works on copies: a cancelled rename does not stick")

shutil.rmtree(TMP, ignore_errors=True)
print("ALL EDITOR IMPORT TESTS PASS")
