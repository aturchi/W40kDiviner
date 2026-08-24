"""Smoke test of the histogram drawing code without a display.

src/dist_view.py cannot be exercised by the rest of the suite (no Tk in
a headless environment, and no window to look at in CI), yet its drawing
routine is plain arithmetic that is easy to break. Here a minimal stub
of the handful of Tk names it touches is installed in sys.modules BEFORE
importing it, so _draw() actually runs and every shape it emits can be
checked: bars inside the frame, one bar per histogram bin, the threshold
colour applied to the right ones.

This deliberately does NOT test Tk itself - it tests the geometry.
"""
import sys
import types

import testpaths                      # sets up sys.path to the engine src/


# ---- minimal tkinter stub ---------------------------------------------

class _Widget:
    def __init__(self, *_a, **kw):
        self.shapes = []
        self.kw = dict(kw)
        self.calls = []

    def configure(self, **kw):
        """Recorded rather than swallowed: whether a widget was handed a
        NAMED font or a literal (family, size, style) tuple is exactly
        what one of the tests below has to be able to see."""
        self.calls.append(("configure", (), kw))
        self.kw.update(kw)

    config = configure

    def __getattr__(self, _name):     # bind/pack/delete/...
        return lambda *_a, **_kw: None


class _Canvas(_Widget):
    _w, _h = 700, 300             # class defaults: __getattr__ must not
                                  # turn a missing size into a lambda

    def cget(self, option):
        """Real behaviour, not a lambda: the drawing code subtracts the
        border from the widget size to get the drawable area, and a stub
        that answered None there would hide the very arithmetic under
        test."""
        return self.kw.get(option, 0)

    def delete(self, *_a):
        self.shapes = []

    def _add(self, kind, coords, kw):
        self.shapes.append((kind, coords, kw))

    def create_rectangle(self, *c, **kw):
        self._add("rect", c, kw)

    def create_line(self, *c, **kw):
        self._add("line", c, kw)

    def create_text(self, *c, **kw):
        self._add("text", c, kw)

    def winfo_width(self):
        return self._w

    def winfo_height(self):
        return self._h


tk = types.ModuleType("tkinter")
for _n in ("E", "W", "N", "S", "NW", "NE", "SW", "SE", "BOTH", "X", "Y",
           "LEFT", "RIGHT", "TOP", "BOTTOM", "END", "VERTICAL"):
    setattr(tk, _n, _n.lower())
class _Var(_Widget):
    """Tk variable: the only stub that needs real behaviour, since the
    distribution frame stores the user's threshold in one."""

    def __init__(self, value=None, **_kw):
        super().__init__()
        self._v = value

    def get(self):
        return self._v

    def set(self, v):
        self._v = v


tk.Canvas = _Canvas
tk.Frame = tk.Toplevel = _Widget
tk.StringVar = tk.BooleanVar = _Var
ttk = types.ModuleType("tkinter.ttk")
ttk.Frame = ttk.Label = ttk.Button = ttk.Entry = _Widget
ttk.Radiobutton = ttk.Checkbutton = ttk.Spinbox = _Widget
_FONT_NAMES = {"TkDefaultFont", "TkSmallCaptionFont"}
_FONTS_CREATED = []


class _Font:
    """Only what the drawing code asks a font for, plus enough of Tk's
    named-font bookkeeping to catch a mistake the old stub could not
    see: tkinter.font.Font sets delete_font on a font it CREATES, and
    its __del__ destroys the Tk font when the wrapper is collected. A
    caller that does not hold the wrapper loses the font - silently,
    because Tk then reads the name as a FAMILY and falls back.

    LINE is a class attribute so a test can sweep the font scale: the
    margins are measured off this font, so the geometry has to be
    checked at more than one size. measure() is deliberately
    proportional to LINE, so scaling the font scales the labels too -
    which is the whole failure mode being guarded against.
    """

    LINE = 13
    ASPECT = 0.55                 # rough width of a character, in lines

    def __init__(self, name=None, exists=False, **opts):
        self.name = name or "TkDefaultFont"
        self.opts = dict(opts)
        self.delete_font = not exists
        if name and not exists:
            _FONT_NAMES.add(name)
            _FONTS_CREATED.append(self)

    def metrics(self, _what):
        return self.LINE

    def measure(self, text):
        return int(round(len(text) * self.LINE * self.ASPECT))

    def cget(self, option):
        return self.opts.get(option,
                             {"family": "Stub", "size": 9}.get(option))

    def configure(self, **kw):
        self.opts.update(kw)


def _nametofont(name):
    if name not in _FONT_NAMES:
        raise tk.TclError("named font %s does not already exist" % name)
    return _Font(name=name, exists=True)


font = types.ModuleType("tkinter.font")
font.nametofont = _nametofont
font.Font = _Font
# dist_view reaches ui_utils for the shared hint colour, and ui_utils
# imports these two at module level. They are never called here: the
# stub exists so that importing the drawing code does not need a
# display, not so that dialogs can be opened without one.
filedialog = types.ModuleType("tkinter.filedialog")
messagebox = types.ModuleType("tkinter.messagebox")
for _n in ("askopenfilename", "asksaveasfilename", "askdirectory"):
    setattr(filedialog, _n, lambda *_a, **_kw: "")
for _n in ("showerror", "showinfo", "showwarning", "askyesno"):
    setattr(messagebox, _n, lambda *_a, **_kw: None)
ttk.Separator = ttk.Scrollbar = ttk.Treeview = ttk.Combobox = _Widget
ttk.Style = _Widget
tk.Listbox = tk.Text = tk.Label = tk.IntVar = _Widget
tk.SOLID = "solid"
tk.TclError = Exception
tk.ttk, tk.font = ttk, font
sys.modules["tkinter"] = tk
sys.modules["tkinter.ttk"] = ttk
sys.modules["tkinter.font"] = font
sys.modules["tkinter.filedialog"] = filedialog
sys.modules["tkinter.messagebox"] = messagebox

import dist_stats as ds               # noqa: E402
import dist_view as dv                # noqa: E402


def canvas(pmf, threshold=None, cumulative=True, w=700, h=300, xmax=None,
           xmin=None):
    c = dv.HistogramCanvas(None, pmf, threshold, cumulative, xmax, xmin)
    c._w, c._h = w, h
    c._draw()
    return c


def frame_of(shapes):
    """(x0, y0, x1, y1) of the plotting frame, read off its own grid.

    The margins are measured from the font, so a test that recomputed
    them from constants would be asserting its own arithmetic rather
    than the drawing's. Everything here is checked against what was
    actually put on the canvas.
    """
    grid = [c for k, c, kw in shapes
            if k == "line" and len(c) == 4 and c[1] == c[3]
            and kw.get("fill") in (dv.GRID, dv.AXIS)]
    xs = [c[0] for c in grid] + [c[2] for c in grid]
    ys = [c[1] for c in grid]
    return min(xs), min(ys), max(xs), max(ys)


d6 = [0.0] + [1 / 6] * 6

# One bar per bin, all inside the plotting frame, none taller than it.
c = canvas(d6)
fx0, fy0, fx1, fy1 = frame_of(c.shapes)
bars = [s for s in c.shapes if s[0] == "rect"]
bins = ds.histogram(d6, max_bars=max(4, (fx1 - fx0) // dv._MIN_BAR_PX))["bins"]
assert len(bars) == len(bins), (len(bars), len(bins))
for _k, (bx0, by0, bx1, by1), _kw in bars:
    assert fx0 <= bx0 < bx1 <= fx1, (bx0, bx1)
    assert fy0 - 1e-9 <= by0 <= by1 <= fy1 + 1e-9, (by0, by1)

# Nothing the chart draws may fall off the canvas, at ANY font scale.
# The margins used to be fixed while the scale labels grew with the
# font, so the leftmost label was drawn at a negative x - which Tk
# clips silently, one character at a time.
for _line in (13, 17, 20, 26, 30, 40):
    _Font.LINE = _line
    for _w, _h in ((700, 300), (1000, 400), (400, 200), (1400, 800)):
        for _kw_args in ({}, {"cumulative": False}, {"xmax": 3},
                         {"xmin": 3}, {"threshold": 5}):
            cc = canvas(d6, w=_w, h=_h, **_kw_args)
            inner_w, inner_h = dv._inner(cc)
            assert inner_w == _w - 2 and inner_h == _h - 2, \
                "the 1 px highlight ring must be taken off both sides"
            for _k, _c, _kwx in cc.shapes:
                if _k != "text":
                    continue
                width = _Font().measure(str(_kwx.get("text", "")))
                anchor = str(_kwx.get("anchor", ""))
                x = _c[0]
                left = (x - width if anchor.endswith("e")
                        else x if anchor.endswith("w") else x - width / 2)
                assert left >= 0, (_line, _w, _h, _kwx.get("text"),
                                   "label clipped on the left")
                # The two 'not plotted' captions are free text: their
                # width comes from the numbers in them and no margin can
                # be reserved for it. They are only guaranteed to START
                # inside the canvas (see HistogramCanvas._note); the
                # scales, whose vocabulary is fixed, must fit whole -
                # inside the DRAWABLE area, which is not the widget.
                if str(_kwx.get("text", "")).startswith(("tail above",
                                                         "below ")):
                    continue
                assert left + width <= inner_w, (_line, _w, _h,
                                                 _kwx.get("text"),
                                                 "label clipped on the right")
                top = _c[1] - (_line if anchor.startswith("s")
                               else 0 if anchor.startswith("n")
                               else _line / 2)
                assert top >= 0 and top + _line <= inner_h, \
                    (_line, _w, _h, _kwx.get("text"), anchor,
                     "label clipped vertically")
_Font.LINE = 13

# Threshold: every bar reaching it is drawn in the "over" colour, and no
# bar below it is.
c = canvas(d6, threshold=5)
overs = [(s[1][0], s[2]["fill"]) for s in c.shapes if s[0] == "rect"]
assert [f for _x, f in overs].count(dv.BAR_OVER) == 2, overs   # 5 and 6
assert overs[0][1] == dv.BAR_FILL
assert overs[-1][1] == dv.BAR_OVER

# A degenerate PMF (all the mass on 0) must still draw without dividing
# by zero.
c = canvas([1.0])
assert [s for s in c.shapes if s[0] == "rect"], "no bar for delta(0)"

# Too small to plot: give up cleanly rather than draw outside the frame.
c = canvas(d6, w=40, h=20)
assert not c.shapes, c.shapes

# Cumulative overlay: one polyline, monotonically non-increasing in
# probability, i.e. non-decreasing in canvas y.
c = canvas(d6, cumulative=True)
poly = [s for s in c.shapes if s[0] == "line"
        and s[2].get("fill") == dv.CUM_LINE]
assert len(poly) == 1, len(poly)
ys = list(poly[0][1][1::2])
assert all(b >= a - 1e-9 for a, b in zip(ys, ys[1:])), ys
assert not [s for s in canvas(d6, cumulative=False).shapes
            if s[0] == "line" and s[2].get("fill") == dv.CUM_LINE]

# The multi-series frame: switching series must swap both the plotted
# PMF and the threshold, and keep each series' own threshold.
series = dv.result_series(net_pmf=d6, gross_pmf=[0.0] * 3 + [1.0],
                          kills_pmf=[0.5, 0.5], unit_wounds=4, models=1)
assert [s["key"] for s in series] == ["net", "kills", "gross"], series

frame = dv.DistributionFrame(None, series)
assert frame._which.get() == "net"
assert frame._entry.get() == "4"                  # unit wounds
assert frame.canvas.shapes, "frame drew nothing"
frame._entry.set("2")
frame._refresh()
assert frame._thr["net"] == "2", frame._thr
frame._which.set("kills")
frame._switch()
assert frame._entry.get() == "1", frame._entry.get()   # models
frame._which.set("net")
frame._switch()
assert frame._entry.get() == "2", "the typed threshold was lost"

# The X-axis length follows the OPPOSITE rule, and on purpose: a
# threshold is a question worth carrying between series, an axis length
# is a view of one distribution and means nothing on another.
assert frame._xmax.get() == str(ds.default_xmax(d6))
frame._xmax.set("3")
frame._refresh()
assert max(hi for _lo, hi, _p in
           ds.histogram(d6, cut=frame._xmax_value(d6))["bins"]) == 3
frame._which.set("kills")
frame._switch()
assert frame._xmax.get() == str(ds.default_xmax([0.5, 0.5]))
frame._which.set("net")
frame._switch()
assert frame._xmax.get() == str(ds.default_xmax(d6)), \
    "the axis length must NOT be remembered across a switch"
# Halfway through typing is not an error, and neither is a value the
# series cannot reach: both fall back on something drawable.
frame._xmax.set("")
assert frame._xmax_value(d6) is None
frame._xmax.set("999")
assert frame._xmax_value(d6) == 6
frame._refresh()

# The FLOOR follows the same rules as the ceiling, and is reset by a
# switch just as the ceiling is: an axis window is a view of one
# distribution and means nothing on another.
assert frame._xmin.get() == "0"
frame._xmin.set("3")
assert frame._xmin_value(d6) == 3
frame._which.set("kills")
frame._switch()
assert frame._xmin.get() == "0", "the floor must not survive a switch"
frame._which.set("net")
frame._switch()
assert frame._xmin.get() == "0"
frame._xmin.set("")
assert frame._xmin_value(d6) is None       # halfway through typing
frame._xmin.set("0")
assert frame._xmin_value(d6) is None       # zero IS the automatic floor
frame._xmin.set("999")
assert frame._xmin_value(d6) == 6
frame._refresh()

# A non-numeric threshold must not raise, it just switches the readout
# off (the user is halfway through typing).
frame._entry.set("")
frame._refresh()
assert frame._threshold() is None

# ---- comparison overlay ------------------------------------------------
# Survival curves of several distributions on one chart: one polyline
# per series, each non-increasing in probability, plus a legend entry.
series = [{"name": "A", "pmf": d6},
          {"name": "B", "pmf": [0.0, 0.5, 0.5]}]
ov = dv.OverlayCanvas(None, series, threshold=3)
ov._w, ov._h = 700, 260
ov._draw()
lines = [sh for sh in ov.shapes if sh[0] == "line"
         and sh[2].get("fill") in dv.OVERLAY_COLOURS]
assert len(lines) == 2, len(lines)
for _k, coords, _kw in lines:
    ys = list(coords[1::2])
    assert all(b >= a - 1e-9 for a, b in zip(ys, ys[1:])), ys
legend = [sh for sh in ov.shapes if sh[0] == "text"
          and sh[2].get("text") in ("A", "B")]
assert len(legend) == 2, legend
# The shorter distribution must still span the whole axis, so the two
# curves are read on the same scale.
xs = [list(sh[1][0::2]) for sh in lines]
assert abs(max(xs[0]) - max(xs[1])) < 1e-9, xs

# The axis runs to the top of the SUPPORT, not to the end of the longest
# vector: kill_chain sizes its laws on the target unit, so a pin that can
# only take 3 wounds off a 15-wound unit used to be drawn on an axis of
# 15 and squashed into the left quarter of the chart.
padded = [{"name": "A", "pmf": [0.5, 0.5] + [0.0] * 13},
          {"name": "B", "pmf": [0.2, 0.3, 0.5] + [0.0] * 12}]
ov3 = dv.OverlayCanvas(None, padded)
ov3._w, ov3._h = 700, 260
ov3._draw()
axis = [int(sh[2]["text"]) for sh in ov3.shapes if sh[0] == "text"
        and str(sh[2]["text"]).isdigit()]
assert max(axis) == 2, axis          # not 15
# The curves must span the chart on that axis, not a fraction of it.
curves = [sh for sh in ov3.shapes if sh[0] == "line"
          and sh[2].get("fill") in dv.OVERLAY_COLOURS]
for _k, coords, _kw in curves:
    assert abs(max(coords[0::2]) - frame_of(ov3.shapes)[2]) < 1e-9, \
        coords[0::2]

# A threshold no pin can reach is REPORTED, not silently dropped: before
# the axis was clamped it always landed exactly on the right edge, so a
# marker that disappears is a new way to be misread.
ov4 = dv.OverlayCanvas(None, padded, threshold=15)
ov4._w, ov4._h = 700, 260
ov4._draw()
assert not [sh for sh in ov4.shapes if sh[0] == "line"
            and sh[2].get("dash")], "no marker can be drawn off the axis"
assert any(str(sh[2].get("text", "")).startswith(">= 15: out of reach")
           for sh in ov4.shapes if sh[0] == "text"), \
    "an unreachable threshold must say so"
# One inside the range is still drawn as a line, as before.
ov5 = dv.OverlayCanvas(None, padded, threshold=1)
ov5._w, ov5._h = 700, 260
ov5._draw()
assert [sh for sh in ov5.shapes if sh[0] == "line" and sh[2].get("dash")]

# Nothing to draw, or too small to draw: give up cleanly.
empty = dv.OverlayCanvas(None, [])
empty._w, empty._h = 700, 260
empty._draw()
assert not empty.shapes
ov2 = dv.OverlayCanvas(None, series)
ov2._w, ov2._h = 50, 20
ov2._draw()
assert not ov2.shapes

# ---- nothing is drawn off the top of the canvas -----------------------

# The annotations above the plotting frame ("tail above N", "P(>= v)")
# hang from its top edge by a BOTTOM anchor, so the band above it must
# be at least one line of the caption font tall. It was 12 px against a
# 13 px line and the captions were clipped; at 150% font they would have
# been clipped by three times as much, so the band follows the font.
LINE = 13                             # what the stub font reports
for _kind, _coords, _kw in canvas(d6, xmax=3).shapes:
    if _kind != "text":
        continue
    top = _coords[1] - (LINE if str(_kw.get("anchor", "")).startswith("s")
                        else LINE / 2)
    assert top >= 0, (_kw.get("text"), _coords, _kw.get("anchor"))


# ---- a forced X axis --------------------------------------------------

# Shortening the axis drops BARS and says so; it must never change the
# distribution, which the percentiles beside the chart still describe.
short = canvas(d6, xmax=3)
labels = [s[2]["text"] for s in short.shapes if s[0] == "text"]
assert not any(lab in ("4", "5", "6") for lab in labels), labels
assert any(str(lab).startswith("tail above 3") for lab in labels), labels
# The bars that remain are redrawn wider, not left in place: the axis is
# rescaled, so the last one still ends at the right edge of the frame.
bars = [s for s in short.shapes if s[0] == "rect"]
assert abs(bars[-1][1][2] - frame_of(short.shapes)[2]) < 2, bars[-1][1]
# Asking for more than the support is clamped, not honoured, and draws
# exactly what the automatic axis would have.
assert len([s for s in canvas(d6, xmax=999).shapes if s[0] == "rect"]) == \
    len([s for s in canvas(d6).shapes if s[0] == "rect"])

# ---- a forced FLOOR ---------------------------------------------------

# Raising the bottom of the axis drops the bars below it and says how
# much probability went with them, at the end it fell off: a narrowed
# window must never read as a smaller distribution.
floored = canvas(d6, xmin=3)
labels = [s[2]["text"] for s in floored.shapes if s[0] == "text"]
assert not any(lab in ("1", "2") for lab in labels), labels
assert any(str(lab).startswith("below 3") for lab in labels), labels
# The note sits on the LEFT, opposite the upper-tail one, so the two can
# be shown together without overlapping. Checked by POSITION rather than
# by anchor: _note() clamps both into the canvas and therefore places
# them itself, with a west anchor either way.
def note_x(shapes):
    """{'below N': x, 'tail above M': x} of the two captions."""
    return {str(s[2]["text"]).split(":")[0]: s[1][0]
            for s in shapes if s[0] == "text"
            and str(s[2]["text"]).startswith(("below ", "tail above "))}


assert "below 3" in note_x(floored.shapes)
both = canvas(d6, xmin=2, xmax=4)
sides = note_x(both.shapes)
assert set(sides) == {"below 2", "tail above 4"}, sides
assert sides["below 2"] < sides["tail above 4"], sides
assert sides["below 2"] >= 0 and sides["tail above 4"] >= 0, sides
# Neither is allowed to start off the canvas even when the chart is
# narrow enough that they cannot both fit whole.
narrow = note_x(canvas(d6, xmin=2, xmax=4, w=300, h=200).shapes)
assert all(x >= 0 for x in narrow.values()), narrow
# A floor above the ceiling collapses to it rather than drawing nothing.
assert [s for s in canvas(d6, xmin=9, xmax=4).shapes if s[0] == "rect"]

# ---- the plotting frame is never inverted -----------------------------

# The guard on the canvas size used to be a pair of constants (w < 60,
# h < 50) while the margins are set by the font: both ends could pass
# the guard and still come out reversed. At 200% font and h = 60 the
# frame had y1 < y0, so every bar had negative height and the
# probability scale was drawn upside down; at w = 61 the same happened
# sideways. The guard now reads the FRAME, so either it is big enough
# to draw or nothing is drawn.

for _line in (13, 20, 26, 30, 40):
    _Font.LINE = _line
    for _w in (40, 61, 90, 141, 142, 300, 700, 1400):
        for _h in (20, 50, 55, 60, 72, 90, 300, 800):
            c = canvas(d6, w=_w, h=_h)
            if not c.shapes:              # too small to read: nothing drawn
                continue
            fx0, fy0, fx1, fy1 = frame_of(c.shapes)
            assert fx1 > fx0, (_line, _w, _h, "frame inverted sideways")
            assert fy1 > fy0, (_line, _w, _h, "frame inverted vertically")
            for _k, _c, _kw in c.shapes:
                if _k != "rect":
                    continue
                bx0, by0, bx1, by1 = _c
                assert bx1 >= bx0 and by1 >= by0, (_line, _w, _h,
                                                   "bar drawn inside out")
                assert by1 <= fy1 + 1e-9 and by0 >= fy0 - 1e-9, \
                    (_line, _w, _h, "bar outside the frame")
# A canvas that WAS drawn upside down must now decline to draw at all.
_Font.LINE = 30
assert not canvas(d6, w=700, h=60).shapes, "h=60 at 200% font must not draw"
_Font.LINE = 13
assert not canvas(d6, w=61, h=300).shapes, "w=61 is narrower than the margins"

# ---- fonts follow the font scale --------------------------------------

# ("TkDefaultFont", 10, "bold") is not the default font in bold: Tk reads
# it as family / size / style, so the size is a literal and
# apply_font_scale - which reconfigures NAMED fonts - cannot reach it.
# Every font this module asks for must therefore be a name.
import ast                            # noqa: E402
import os                             # noqa: E402

_src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(
    __file__))), "src", "dist_view.py")
with open(_src, encoding="utf-8") as _fh:
    _tree = ast.parse(_fh.read())
for _node in ast.walk(_tree):
    if not isinstance(_node, ast.Call):
        continue
    for _kw in _node.keywords:
        if _kw.arg != "font":
            continue
        assert not isinstance(_kw.value, (ast.Tuple, ast.List)), \
            ("font=(family, size, style) pins the size and stops "
             "following the font scale; use a named font "
             f"(line {_kw.value.lineno})")

# The bold twin is a name, and the same one every time it is asked for.
import ui_utils as _ui                # noqa: E402
_FONT_NAMES.discard(_ui.BOLD_FONT)    # start again from "never created"
_before = len(_FONTS_CREATED)
assert _ui.bold_font() == _ui.BOLD_FONT
assert isinstance(_ui.bold_font(), str)
assert _ui.BOLD_FONT in _FONT_NAMES, "the named font was never created"
# Asking again must not create it again.
_ui.bold_font()
_new = _FONTS_CREATED[_before:]
assert len(_new) == 1, [f.name for f in _new]
# ...and it must OUTLIVE the wrapper that created it. tkinter deletes a
# font it created when its Python wrapper is collected, and nothing
# holds this one; Tk then reads the name as a family, fails to find it
# and falls back to the default, so the bug shows up as text that is
# simply not bold rather than as an error.
assert _new[0].delete_font is False, \
    "a created font that is not held is destroyed again by __del__"
assert _new[0].opts.get("weight") == "bold", _new[0].opts
# The twin follows TkDefaultFont rather than the scale, so it is right
# however the two are created and rescaled in relation to each other.
_nametofont("TkDefaultFont").configure(size=17)
_ui.sync_bold_font()
assert _nametofont(_ui.BOLD_FONT).cget("size") == \
    _nametofont("TkDefaultFont").cget("size")

# Selecting a series must re-font every cell of the table with a NAME,
# both the row it bolds and the rows it puts back to normal.
frame._which.set("gross")
frame._switch()
for _key, _cells in frame._stat_rows.items():
    for _cell in _cells:
        _fonts = [kw["font"] for k, _a, kw in _cell.calls
                  if k == "configure" and "font" in kw]
        assert _fonts, "a cell was never given a font"
        assert all(isinstance(f, str) for f in _fonts), _fonts
    assert _fonts[-1] == (_ui.BOLD_FONT if _key == "gross"
                          else "TkDefaultFont"), (_key, _fonts[-1])
frame._which.set("net")
frame._switch()

print("histogram canvas: OK (%d shapes)" % len(canvas(d6).shapes))
