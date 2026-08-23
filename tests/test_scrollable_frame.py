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
import ui_prefs                       # noqa: E402


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

# A Canvas is judged, not assumed: a nested scrolling area keeps its own
# wheel, but a CHART drawn on a canvas scrolls nothing, and skipping it
# would leave a dead patch in the middle of a scrolling page - which is
# most of the analyzer's result page.
chart = tk.Canvas(sf.body)
nested = tk.Canvas(sf.body, yscrollcommand=lambda *a: None)
assert not ui.ScrollableFrame._scrolls_itself(chart)
assert ui.ScrollableFrame._scrolls_itself(nested)
assert ui.ScrollableFrame._scrolls_itself(listbox)

# The body is stretched to the viewport when the content is shorter, which
# is what lets a page scroll AND keep an expand=True child growing.
sf._on_canvas()
assert sf._size[1] >= sf.body.winfo_reqheight()


# ---------------- 2b. tooltips ----------------------------------------

class MotionEvent:
    """Stand-in for a Tk pointer event."""

    def __init__(self, x=0, y=0):
        self.x, self.y = x, y
        self.x_root, self.y_root = x + 100, y + 100


# The text is chosen from the POSITION, because a Treeview heading is
# not a widget of its own and cannot be bound to directly.
target = ttk.Label(root, text="table")
asked = []


def help_for(event):
    asked.append((event.x, event.y))
    return "the heading means this" if event.x < 50 else None


tip = ui.Tooltip(target, help_for)
# tkstub runs after() immediately, so scheduling and showing collapse
# into one step here; on the real toolkit they are DELAY_MS apart.
tip._on_motion(MotionEvent(x=10))
assert tip._win is not None, "no tip over a heading with help"
# Moving WITHIN the same heading must not rebuild it: a Motion event
# arrives per pixel and rescheduling on each would mean the tip never
# becomes due.
window, calls = tip._win, len(asked)
tip._on_motion(MotionEvent(x=11))
assert tip._win is window and len(asked) == calls + 1
# Moving onto something with no help takes it away.
tip._on_motion(MotionEvent(x=200))
assert tip._win is None
# ...and so does leaving the widget, from any state.
tip._on_motion(MotionEvent(x=10))
tip._hide()
assert tip._win is None and tip._text is None


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


# ---------------- 4. the analyzer's result page, structurally ---------

# The result page is a renderer, so it has no pure module to test. What
# CAN be checked without a display is that the three pieces are wired at
# all: the page scrolls, the combined chart is built into it rather than
# behind a gesture, and the wheel is bound after the children exist.
import ast                            # noqa: E402
import os                             # noqa: E402


def call_names(node):
    """Dotted names of every call inside 'node'. Written by hand rather
    than with ast.unparse, which is 3.9+ and the project is 3.8+."""
    out = set()
    for call in (n for n in ast.walk(node) if isinstance(n, ast.Call)):
        parts, func = [], call.func
        while isinstance(func, ast.Attribute):
            parts.append(func.attr)
            func = func.value
        if isinstance(func, ast.Name):
            parts.append(func.id)
        out.add(".".join(reversed(parts)))
    return out


_analyzer = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "attack_analyzer.py")
with open(_analyzer, encoding="utf-8") as fh:
    _tree = ast.parse(fh.read())
_page = next(n for n in ast.walk(_tree)
             if isinstance(n, ast.FunctionDef) and n.name == "_result_page")
_calls = call_names(_page)
assert "ui.ScrollableFrame" in _calls, "the result page must scroll"
assert "scroll.bind_wheel" in _calls, "the wheel needs binding, see #2"
assert "self._embed_distribution" in _calls, \
    "the inline chart must still be reachable when the option is on"
# The inline chart is an OPTION, so the page must read the preference
# rather than always building it - and the totals block must not open a
# popup of its own, which would be the same numbers in three places.
_names = {n.attr for n in ast.walk(_page) if isinstance(n, ast.Attribute)}
assert "EMBED_DISTRIBUTION" in _names, \
    "the inline chart must be conditional on the preference"
_block = next(n for n in ast.walk(_tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_totals_block")
assert "dist_view.open_distribution" not in call_names(_block)

# The default is the double-click, and it must reach the TOTAL row as
# well as the weapons - that is the whole point of the gesture being the
# same one.
_open = next(n for n in ast.walk(_tree)
             if isinstance(n, ast.FunctionDef) and n.name == "_open_row_dist")
assert "dist_view.open_distribution" in call_names(_open)
assert not ui_prefs.EMBED_DISTRIBUTION, "the inline chart is opt-in"


# ---------------- 5. the X-axis length is per-view, not remembered ----

# A threshold is a QUESTION and is carried across series; an axis length
# is a VIEW of one distribution and is not. dist_stats owns the default.
import dist_stats as ds               # noqa: E402

_kills = [0.0] * 6 + [1.0]            # support 0..6
_damage = [0.0] * 60 + [1.0]          # support 0..60
assert ds.default_xmax(_kills) != ds.default_xmax(_damage), \
    "an axis that fits one series is meaningless on the other"
assert ds.default_xmax([1.0]) == 0    # degenerate: one value, no axis

# Forcing the axis hides BARS, never probability: the mass left out is
# reported, and the percentiles keep describing the whole distribution.
_d6 = [0.0] + [1 / 6] * 6
_h = ds.histogram(_d6, max_bars=40, cut=3)
assert max(hi for _lo, hi, _p in _h["bins"]) == 3
assert abs(_h["cut_mass"] - 0.5) < 1e-12, _h["cut_mass"]
assert abs(sum(p for _lo, _hi, p in _h["bins"]) + _h["cut_mass"] - 1.0) < 1e-12
# Out-of-range requests are clamped, not honoured.
assert max(hi for _lo, hi, _p in ds.histogram(_d6, cut=999)["bins"]) == 6

print("ALL SCROLLABLE FRAME TESTS PASS")
