"""Every button that is not self-explaining carries a tooltip.

A tooltip is a claim about the interface that nothing else can check: a
Tooltip binds a callback and keeps nothing readable, so a window full of
unexplained buttons looks exactly like a window full of explained ones.
ui_utils.tip therefore records the text on the widget, and this walks the
real windows and asks.

The exempt labels are the ones whose caption IS the explanation - OK,
Cancel, Close - plus the two the surrounding text already covers. Adding
a button without help is not forbidden; adding it without deciding is.
"""
import sys

import testpaths                                          # noqa: F401
import tkstub

tkstub.install()

sys.path.insert(0, testpaths.REPO_ROOT)     # the three programs live there

import tkinter as tk                                      # noqa: E402
from tkinter import ttk                                   # noqa: E402
import ui_utils as ui                                     # noqa: E402
import native_format as nf                                # noqa: E402

# Captions that need no tooltip: the word on the button is the whole
# explanation, and a tip repeating it would only be noise.
EXEMPT = {"OK", "Cancel", "Close", "Apply form", "Apply JSON"}


def buttons(widget, found=None):
    """Every ttk.Button at or under 'widget'."""
    found = [] if found is None else found
    if isinstance(widget, ttk.Button):
        found.append(widget)
    for child in widget.winfo_children():
        buttons(child, found)
    return found


def check(window, what):
    bare = []
    for btn in buttons(window):
        label = str(btn.cget("text") or "")
        if label in EXEMPT:
            continue
        text = getattr(btn, "_tip_text", None)
        if not text:
            bare.append(label)
            continue
        assert text != label, f"{what}: the tip of {label!r} only repeats it"
        assert len(text) > 20, f"{what}: the tip of {label!r} says nothing"
    assert not bare, f"{what}: buttons with no explanation: {bare}"
    return len(buttons(window))


root = tk.Tk()
total = 0

# --- the three main windows -------------------------------------------

import profile_editor                                     # noqa: E402
import attack_analyzer                                    # noqa: E402
import game_assistant                                     # noqa: E402

total += check(profile_editor.EditorApp(), "profile editor")
total += check(attack_analyzer.AnalyzerApp(), "attack analyzer")
total += check(game_assistant.GameAssistantApp(), "game assistant")
print("the three toolbars explain themselves")

# --- the dialogs ------------------------------------------------------


def army(name):
    return {"format": nf.FORMAT_TAG,
            "armies": [{"name": name, "units": []}]}


import army_load_dialog                                   # noqa: E402
import roster_picker                                      # noqa: E402
import list_dialog                                        # noqa: E402
import editor_widgets                                     # noqa: E402
import log_view                                           # noqa: E402
import attack_log                                         # noqa: E402

total += check(army_load_dialog.ArmyLoadDialog(
    root, [army("A"), army("B")], allow_save=True), "army load dialog")
total += check(roster_picker.RosterPicker(root, initialdir="."),
               "roster picker")
total += check(list_dialog.StringListDialog(root, "Keywords", [], []),
               "string list dialog")
total += check(editor_widgets.PickerDialog(root, "Pick", []),
               "picker dialog")
total += check(log_view.AttackLogWindow(root, attack_log.AttackLog(),
                                        lambda: None),
               "attack log window")

import setup_panel                                        # noqa: E402

total += check(setup_panel.SetupPanel(root), "setup panel")
print("the dialogs and the context panel explain themselves")

# --- the helper itself ------------------------------------------------

b = ui.tip(ttk.Button(root, text="Probe"), "what this button does")
assert b.cget("text") == "Probe", "tip() must return the widget it was given"
assert b._tip_text == "what this button does"
assert "<Motion>" in b.bind(), b.bind()
print(f"tip() returns the widget and binds the pointer; "
      f"{total} buttons checked")
print("ALL TOOLTIP TESTS PASS")
