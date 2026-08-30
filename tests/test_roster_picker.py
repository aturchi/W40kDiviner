"""Roster file picker: folder listing, the cross-folder basket, and the
dialog that drives them.

The point of the whole feature is that a file list can be built with the
mouse alone and SURVIVES walking into another folder - neither of which
the platform's own file dialog does. Both claims are asserted here
against a real temporary tree, and then again through the widget.
"""
import os
import shutil
import tempfile

import testpaths                                        # noqa: F401
import roster_picker_core as core

TMP = tempfile.mkdtemp(prefix="w40k_picker_")


def write(path, text="{}"):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


A = os.path.join(TMP, "a")
B = os.path.join(TMP, "b")
SUB = os.path.join(A, "sub")
os.makedirs(SUB)
os.makedirs(B)
A_ONE = write(os.path.join(A, "one.json"), '{"x": 1}')
A_TWO = write(os.path.join(A, "Two.json"))
write(os.path.join(A, "notes.txt"), "not a roster")
write(os.path.join(A, ".hidden.json"))
B_ONE = write(os.path.join(B, "one.json"))
B_THREE = write(os.path.join(B, "three.json"))

# ---------------------------------------------------------------- rows

st = core.RosterPickerState(A)
rows = st.rows()
kinds = [k for k, _n, _l in rows]
names = [n for _k, n, _l in rows]
assert kinds == ["dir", "dir", "file", "file"], rows
assert names == [core.PARENT, "sub", "one.json", "Two.json"], names
print("rows: folders first, files sorted case-insensitively:", names)

# .txt is not a roster and a dotfile is not shown at all.
assert "notes.txt" not in names and ".hidden.json" not in names, names

# The label of a file carries its size, the label of a folder is bracketed.
labels = {n: lab for _k, n, lab in rows}
assert labels["sub"] == "[sub]" and labels[core.PARENT] == "[..]", labels
assert labels["one.json"].startswith("one.json   (") \
    and labels["one.json"].endswith("B)"), labels["one.json"]
assert core.size_label(0) == "0 B" and core.size_label(1023) == "1023 B"
assert core.size_label(1024) == "1.0 KB", core.size_label(1024)
assert core.size_label(5 * 1024 ** 2) == "5.0 MB", core.size_label(5 * 1024 ** 2)
print("labels:", labels["one.json"], "|", labels["sub"])

# ------------------------------------------------------------- filter

st.filter = "TW"                       # case-insensitive substring
names = [n for _k, n, _l in st.rows()]
assert names == [core.PARENT, "sub", "Two.json"], names
st.filter = "zzz"                      # matches no FILE
names = [n for _k, n, _l in st.rows()]
assert names == [core.PARENT, "sub"], names
print("filter hides files but never folders:", names)
st.filter = ""

# --------------------------------------------------------- navigation

assert st.parent() == TMP
assert st.enter("sub") is True and st.folder == SUB
assert st.enter(core.PARENT) is True and st.folder == A
print("navigation: into sub and back out ->", st.folder)

root = os.path.abspath(os.sep)
at_root = core.RosterPickerState(root)
assert at_root.parent() is None, at_root.parent()
assert [k for k, _n, _l in at_root.rows() if _n == core.PARENT] == []
print("at the filesystem root there is no [..] row")

# A folder that cannot be listed leaves the state exactly as it was: the
# probe in set_folder runs BEFORE the assignment, so a bad path does not
# strand the window on a folder it cannot show.
before = st.folder
try:
    st.set_folder(os.path.join(TMP, "does-not-exist"))
    raise AssertionError("a missing folder must raise")
except OSError:
    pass
assert st.folder == before, st.folder
print("a missing folder raises and leaves the current one untouched")

# ------------------------------------------------- basket across folders

st.set_folder_selection(["one.json", "Two.json"])
assert st.basket() == (A_ONE, A_TWO), st.basket()
assert st.in_folder() == ["one.json", "Two.json"], st.in_folder()

st.set_folder(B)                       # walk away
assert st.basket() == (A_ONE, A_TWO), "the basket must survive navigation"
assert st.in_folder() == [], st.in_folder()
st.set_folder_selection(["three.json"])
assert st.basket() == (A_ONE, A_TWO, B_THREE), st.basket()
print("basket spans folders:", [os.path.basename(p) for p in st.basket()])

# Unticking in THIS folder must not touch the other folder's entries.
st.set_folder_selection([])
assert st.basket() == (A_ONE, A_TWO), st.basket()

# Re-ticking one of two entries drops only the other, and the survivor
# keeps its position (an assignment would have reordered them).
st.set_folder(A)
st.set_folder_selection(["Two.json"])
assert st.basket() == (A_TWO,), st.basket()
st.set_folder_selection(["one.json", "Two.json"])
assert st.basket() == (A_TWO, A_ONE), st.basket()
print("re-ticking keeps the surviving entry in place:",
      [os.path.basename(p) for p in st.basket()])

# ------------------------------------------------------------- labels

st.clear()
st.add([A_ONE, B_THREE])
assert st.labels() == ["one.json", "three.json"], st.labels()
st.add([B_ONE])                        # now two files called one.json
assert st.labels() == [f"one.json   ({A})", "three.json",
                       f"one.json   ({B})"], st.labels()
print("same-named files from two folders are told apart:", st.labels()[0])

# ------------------------------------------------------- add / remove

assert st.add([A_ONE]) == 0, "a path already in the basket is not added twice"
assert st.add([A_TWO]) == 1
assert st.remove([B_ONE, os.path.join(TMP, "nope.json")]) == 1
assert B_ONE not in st.basket(), st.basket()
assert st.summary() == "3 files selected", st.summary()
st.remove([A_ONE, A_TWO])
assert st.summary() == "1 file selected", st.summary()
assert st.clear() == 1 and st.summary() == "no file selected"
print("add/remove/clear report what they did; summary follows")

# ------------------------------------------------- remembered folder

core.forget()
assert core.last_folder() is None
core.remember(B)
assert core.default_folder() == B, core.default_folder()
core.remember(os.path.join(TMP, "gone"))
assert core.default_folder() != os.path.join(TMP, "gone"), \
    "a remembered folder that no longer exists must not be offered"
core.forget()
print("the last folder is remembered, unless it has disappeared")

print("ALL ROSTER PICKER CORE TESTS PASS")


# --------------------------------------------------------- the dialog

import tkstub                                            # noqa: E402

tkstub.install()

import tkinter as tk                                     # noqa: E402
import ui_utils as ui                                    # noqa: E402
import roster_picker as rp                               # noqa: E402

_root = tk.Tk()
dlg = rp.RosterPicker(_root, initialdir=A)

# Tk's 'multiple' mode is the whole point: a plain click toggles ONE row
# and leaves the rest alone. EXTENDED would need Ctrl+click, which is
# what this window exists to avoid.
assert dlg.files_lb.cget("selectmode") == tk.MULTIPLE, \
    dlg.files_lb.cget("selectmode")
assert dlg.basket_lb.cget("selectmode") == tk.MULTIPLE
# Two Listboxes in one window: with the X selection left on, picking in
# one of them silently clears the other.
assert dlg.files_lb.cget("exportselection") is False
assert dlg.basket_lb.cget("exportselection") is False

_texts = []


def _walk(w):
    _texts.append(str(w.cget("text")) if "text" in getattr(w, "_opts", {})
                  else "")
    for c in w.winfo_children():
        _walk(c)


_walk(dlg)
hints = [t for t in _texts if "click" in t.lower()]
assert any(ui.TOGGLE_SELECT_HINT in t for t in hints), hints
assert not any("Ctrl+click" in t or "Cmd+click" in t for t in hints), hints
print("the file list toggles on click, and the hint says so")


def rows_named(dialog):
    return [n for _k, n, _l in dialog._rows]


def click(dialog, name):
    """Tick a row the way Tk does: set the selection, then let the widget
    hear about it. Real Tk's class binding does exactly this pair."""
    i = rows_named(dialog).index(name)
    dialog.files_lb.selection_set(i)
    dialog.files_lb.event_generate("<<ListboxSelect>>")


def unclick(dialog, name):
    i = rows_named(dialog).index(name)
    dialog.files_lb.selection_clear(i)
    dialog.files_lb.event_generate("<<ListboxSelect>>")


click(dlg, "one.json")
click(dlg, "Two.json")
assert dlg.state.basket() == (A_ONE, A_TWO), dlg.state.basket()
assert list(dlg.basket_lb.get(0, tk.END)) == ["one.json", "Two.json"]
assert dlg.count_lbl.cget("text") == "2 files selected"
print("two clicks, two files, no modifier key:",
      list(dlg.basket_lb.get(0, tk.END)))

unclick(dlg, "one.json")
assert dlg.state.basket() == (A_TWO,), dlg.state.basket()
assert dlg.count_lbl.cget("text") == "1 file selected"
print("clicking again deselects")

# A folder row cannot be put in the basket, however it is clicked.
click(dlg, "sub")
assert dlg.state.basket() == (A_TWO,), dlg.state.basket()
assert not dlg.files_lb.selection_includes(rows_named(dlg).index("sub"))
print("a folder row is not a file: never enters the basket")

# Walking into another folder keeps the basket and re-ticks on the way
# back - this is the behaviour the native dialog cannot offer at all.
dlg._enter("sub")
assert dlg.state.folder == SUB and dlg.state.basket() == (A_TWO,)
assert dlg.folder_var.get() == SUB, dlg.folder_var.get()
dlg.cmd_up()
assert dlg.state.folder == A
assert dlg.files_lb.selection_includes(rows_named(dlg).index("Two.json"))
assert not dlg.files_lb.selection_includes(rows_named(dlg).index("one.json"))
print("the basket survives navigation and the rows come back ticked")

# Remove works on the basket side and un-ticks the file row.
dlg.basket_lb.selection_set(0)
dlg.cmd_remove()
assert dlg.state.basket() == (), dlg.state.basket()
assert not dlg.files_lb.selection_includes(rows_named(dlg).index("Two.json"))
print("Remove clears the basket entry and its row")

# Nothing chosen: Open must not accept. "result is still empty" does not
# say that on its own - an Open that went through on an empty basket
# would leave it empty too - so the giveaway is the side effect: a real
# Open records the folder for the next load, and a refused one does not.
core.forget()
dlg.cmd_open()
assert dlg.result == (), dlg.result
assert core.last_folder() is None, "Open must refuse an empty basket"

click(dlg, "one.json")
dlg.cmd_open()
assert dlg.result == (A_ONE,), dlg.result
assert core.last_folder() == A, core.last_folder()
print("Open returns the basket and remembers the folder:", dlg.result)

core.forget()
shutil.rmtree(TMP, ignore_errors=True)
print("ALL ROSTER PICKER TESTS PASS")
