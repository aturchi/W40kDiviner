"""Test ui_utils.ScrollableFrame and its wheel decoding, and the fact that
the setup panel really builds into the scrolling body.

Everything here runs on tkstub when the real toolkit is missing, which is
the point: the bug this guards against is structural (a widget built into
the LabelFrame instead of into the scrolling body would simply never
scroll), and structure is visible without a display.
"""
import testpaths                      # noqa: F401  (sets sys.path to src/)
import tkstub

tkstub.install_if_missing()

import tkinter as tk                  # noqa: E402  (must follow the stub)
from tkinter import ttk               # noqa: E402
import ui_utils as ui                 # noqa: E402


class WheelEvent:
    """Stand-in for a Tk event: only 'num' and 'delta' are read."""

    def __init__(self, num=0, delta=0):
        self.num, self.delta = num, delta


# ---------------- 1. wheel decoding, all three conventions -----------

# X11 sends button 4 (up) and 5 (down) and carries no delta at all.
assert ui.wheel_units(WheelEvent(num=4)) == -1
assert ui.wheel_units(WheelEvent(num=5)) == +1
# Windows: multiples of 120, one notch each.
assert ui.wheel_units(WheelEvent(delta=120)) == -1
assert ui.wheel_units(WheelEvent(delta=-120)) == +1
assert ui.wheel_units(WheelEvent(delta=240)) == -2
# macOS: a small delta, still one notch.
assert ui.wheel_units(WheelEvent(delta=1)) == -1
assert ui.wheel_units(WheelEvent(delta=-3)) == +1
# No movement is not a direction.
assert ui.wheel_units(WheelEvent()) == 0
# A wheel UP must scroll the view towards the TOP, which is a NEGATIVE
# yview_scroll: getting this backwards is the classic inverted-scroll bug.
up, down = ui.wheel_units(WheelEvent(num=4)), ui.wheel_units(WheelEvent(num=5))
assert up < 0 < down


# ---------------- 2. the container ------------------------------------

root = tk.Tk()
sf = ui.ScrollableFrame(root)

# The body is a child of the canvas, not of the frame: a child packed
# into the ScrollableFrame itself would sit next to the scrolling area
# and never move with it.
assert sf.body.master is sf.canvas
assert sf.canvas.master is sf

# The wheel is bound on the widgets, not on the container, because Tk
# does not pass a wheel event up to a parent.
label = ttk.Label(sf.body, text="x")
listbox = tk.Listbox(sf.body)
sf.bind_wheel()
for seq in ui.ScrollableFrame._WHEEL_EVENTS:
    assert seq in label._binds, seq
    # ...except on a widget that scrolls itself: the wheel over a list is
    # the list's.
    assert seq not in listbox._binds, seq

# Handling the wheel must stop there, so a ttk Spinbox under the pointer
# does not ALSO increment its value.
assert sf._on_wheel(WheelEvent(num=5)) == "break"


# ---------------- 3. the setup panel builds into the body -------------

try:
    import setup_panel as sp
except ImportError as exc:            # no tkinter and no stub: skip
    print("setup_panel skipped (%s)" % exc)
else:
    panel = sp.SetupPanel(root)
    assert panel.body is panel._scroll.body
    # Every control must be inside the scrolling body. The panel itself
    # holds exactly one child, the ScrollableFrame.
    assert panel.winfo_children() == [panel._scroll], panel.winfo_children()
    # Spot-check the widgets that are furthest down the column - those are
    # the ones a short screen used to cut off.
    for widget in (panel.melee_combo, panel.mod_list, panel.preset_box,
                   panel.ability_label):
        node = widget.master
        while node is not None and node is not panel.body:
            node = getattr(node, "master", None)
        assert node is panel.body, widget

    # The options dialog carries the font scale in both shapes, and only
    # the caps shape is the two programs that compute attacks.
    assert callable(sp.show_options_dialog)
    assert not hasattr(sp, "show_font_dialog"), \
        "the font dialog was merged into show_options_dialog"
    assert "100" in sp.FONT_SCALE_CHOICES
    assert sp.FONT_SCALE_MIN < 100 < sp.FONT_SCALE_MAX

print("ALL SCROLLABLE FRAME TESTS PASS")
