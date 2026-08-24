"""Geometry of the distribution drawing code, against the real toolkit
whenever there is one.

WHY THIS EXISTS. src/dist_view.py is arithmetic wearing a canvas: margins
derived from font metrics, bars fitted into a frame, an axis that can be
narrowed at either end. All of it is easy to break and none of it is
covered by looking at a screenshot.

HOW IT RUNS. The real tkinter is used when it imports AND a display
answers; otherwise tests/tkstub steps in and says so on stdout. The
difference is confined to the four helpers below - every assertion in
this file reads the drawing through find_all / type / coords / itemcget
/ bbox, which are Tk's own, so the same checks run on either. That is
deliberate: an earlier version of this test reached into stub attributes,
passed here, and failed on the developer's machine.

WHAT IS FAKED EVEN ON REAL TK. Two things, both stated rather than
hidden. A Canvas only reports a size once it is mapped, so winfo_width /
winfo_height are overridden per instance - the arithmetic under test then
runs on real fonts, real items and real bbox. And the caption font is
resized directly instead of through the Options dialog, which is what
apply_font_scale does anyway.
"""
import gc

import testpaths                      # noqa: F401  (sets sys.path)
import tkstub

# --- toolkit selection ---------------------------------------------------

REAL = not tkstub.install_if_missing()
MASTER = None
if REAL:
    import tkinter as _tk
    try:
        MASTER = _tk.Tk()
        MASTER.withdraw()
    except Exception as _exc:         # tkinter present, no display
        print("[test_hist_canvas] tkinter imports but no display answers "
              "(%s): falling back to the stub" % _exc)
        tkstub.install()
        REAL, MASTER = False, None

import tkinter as tk                  # noqa: E402
from tkinter import font as tkfont    # noqa: E402

import dist_stats as ds               # noqa: E402
import dist_view as dv                # noqa: E402
import ui_utils as ui                 # noqa: E402

CAPTION = "TkSmallCaptionFont"

# --- reading a drawing, through Tk's own API -----------------------------

#: itemcget raises on an option the item type does not have, so ask each
#: kind only for what it can answer.
_ITEM_OPTIONS = {"line": ("fill", "dash"),
                 "rectangle": ("fill", "outline"),
                 "text": ("fill", "anchor", "text")}


def shapes_of(c):
    """[(type, coords, options)] for everything on the canvas.

    Built only from find_all / type / coords / itemcget, which real
    tkinter.Canvas and tkstub.Canvas both provide.
    """
    out = []
    for item in c.find_all():
        kind = c.type(item)
        opts = {k: c.itemcget(item, k)
                for k in _ITEM_OPTIONS.get(kind, ())}
        out.append((kind, tuple(float(v) for v in c.coords(item)), opts))
    return out


def frame_of(c):
    """(x0, y0, x1, y1) of the plotting frame, read off its own grid.

    The margins come from font metrics, so a test that recomputed them
    from the module's constants would be asserting its own arithmetic
    instead of the drawing's.
    """
    grid = [co for kind, co, kw in shapes_of(c)
            if kind == "line" and len(co) == 4 and co[1] == co[3]
            and kw.get("fill") in (dv.GRID, dv.AXIS)]
    xs = [co[0] for co in grid] + [co[2] for co in grid]
    ys = [co[1] for co in grid]
    return min(xs), min(ys), max(xs), max(ys)


def caption():
    """The font the drawing code measures its margins with."""
    return tkfont.nametofont(CAPTION)


def set_caption(size):
    """Resize that font, which is what apply_font_scale does to it."""
    caption().configure(size=size)


def set_size(c, w, h):
    """What the canvas will report as its size.

    A real Canvas has none until it is mapped, and mapping one needs a
    window on screen; overriding the two accessors keeps everything else
    - fonts, items, bbox - real.
    """
    if hasattr(c, "set_size"):
        c.set_size(w, h)
    else:
        c.winfo_width = lambda: w
        c.winfo_height = lambda: h


def canvas(pmf, threshold=None, cumulative=True, w=700, h=300, xmax=None,
           xmin=None):
    c = dv.HistogramCanvas(MASTER, pmf, threshold, cumulative, xmax, xmin)
    set_size(c, w, h)
    c._draw()
    return c


def overlay(series, threshold=None, w=700, h=260):
    c = dv.OverlayCanvas(MASTER, series, threshold=threshold)
    set_size(c, w, h)
    c._draw()
    return c


def dist_frame(series, note="", w=700, h=300):
    """A DistributionFrame whose own canvas has a size.

    It builds that canvas itself, so set_size() has to reach inside and
    the frame then has to be asked to redraw. Under a stub the canvas
    had a default size and this was invisible; a real unmapped Canvas
    reports a width of 1 and _draw() rightly declines to draw at all.
    """
    f = dv.DistributionFrame(MASTER, series, note)
    set_size(f.canvas, w, h)
    f._refresh()
    return f


d6 = [0.0] + [1 / 6] * 6

# One bar per bin, all inside the plotting frame, none taller than it.
c = canvas(d6)
fx0, fy0, fx1, fy1 = frame_of(c)
bars = [s for s in shapes_of(c) if s[0] == "rectangle"]
bins = ds.histogram(d6, max_bars=max(4, int(fx1 - fx0) // dv._MIN_BAR_PX))["bins"]
assert len(bars) == len(bins), (len(bars), len(bins))
for _k, (bx0, by0, bx1, by1), _kw in bars:
    assert fx0 <= bx0 < bx1 <= fx1, (bx0, bx1)
    assert fy0 - 1e-9 <= by0 <= by1 <= fy1 + 1e-9, (by0, by1)

# Nothing the chart draws may fall off the canvas, at ANY font scale.
# The margins used to be fixed while the scale labels grew with the
# font, so the leftmost label was drawn at a negative x - which Tk
# clips silently, one character at a time. Read through bbox(), the
# toolkit's own answer to "where did this actually land".
for _size in (7, 9, 12, 16, 20, 24):
    set_caption(_size)
    for _w, _h in ((700, 300), (1000, 400), (400, 200), (1400, 800)):
        for _kw_args in ({}, {"cumulative": False}, {"xmax": 3},
                         {"xmin": 3}, {"threshold": 5}):
            cc = canvas(d6, w=_w, h=_h, **_kw_args)
            inner_w, inner_h = dv._inner(cc)
            assert inner_w == _w - 2 and inner_h == _h - 2, \
                "the 1 px highlight ring must be taken off both sides"
            for _item in cc.find_all():
                if cc.type(_item) != "text":
                    continue
                _txt = cc.itemcget(_item, "text")
                _x0, _y0, _x1, _y1 = cc.bbox(_item)
                _where = (_size, _w, _h, _txt)
                # bbox is one past the last pixel on real Tk, hence the
                # 1 px of slack at the far edges.
                assert _x0 >= 0, _where + ("clipped on the left",)
                assert _y0 >= 0 and _y1 <= inner_h + 1, \
                    _where + ("clipped vertically",)
                # The two 'not plotted' captions are free text: their
                # width comes from the numbers in them and no margin can
                # be reserved for it. They are only guaranteed to START
                # inside the canvas (see HistogramCanvas._note); the
                # scales, whose vocabulary is fixed, must fit whole -
                # inside the DRAWABLE area, which is not the widget.
                if _txt.startswith(("tail above", "below ")):
                    continue
                assert _x1 <= inner_w + 1, _where + ("clipped right",)
set_caption(9)

# Threshold: every bar reaching it is drawn in the "over" colour, and no
# bar below it is.
c = canvas(d6, threshold=5)
overs = [(s[1][0], s[2]["fill"]) for s in shapes_of(c) if s[0] == "rectangle"]
assert [f for _x, f in overs].count(dv.BAR_OVER) == 2, overs   # 5 and 6
assert overs[0][1] == dv.BAR_FILL
assert overs[-1][1] == dv.BAR_OVER

# A degenerate PMF (all the mass on 0) must still draw without dividing
# by zero.
c = canvas([1.0])
assert [s for s in shapes_of(c) if s[0] == "rectangle"], "no bar for delta(0)"

# Too small to plot: give up cleanly rather than draw outside the frame.
c = canvas(d6, w=40, h=20)
assert not shapes_of(c), shapes_of(c)

# Cumulative overlay: one polyline, monotonically non-increasing in
# probability, i.e. non-decreasing in canvas y.
c = canvas(d6, cumulative=True)
poly = [s for s in shapes_of(c) if s[0] == "line"
        and s[2].get("fill") == dv.CUM_LINE]
assert len(poly) == 1, len(poly)
ys = list(poly[0][1][1::2])
assert all(b >= a - 1e-9 for a, b in zip(ys, ys[1:])), ys
assert not [s for s in shapes_of(canvas(d6, cumulative=False))
            if s[0] == "line" and s[2].get("fill") == dv.CUM_LINE]

# The multi-series frame: switching series must swap both the plotted
# PMF and the threshold, and keep each series' own threshold.
series = dv.result_series(net_pmf=d6, gross_pmf=[0.0] * 3 + [1.0],
                          kills_pmf=[0.5, 0.5], unit_wounds=4, models=1)
assert [s["key"] for s in series] == ["net", "kills", "gross"], series

frame = dist_frame(series)
assert frame._which.get() == "net"
assert frame._entry.get() == "4"                  # unit wounds
assert shapes_of(frame.canvas), "frame drew nothing"
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
ov = dv.OverlayCanvas(MASTER, series, threshold=3)
set_size(ov, 700, 260)
ov._draw()
lines = [sh for sh in shapes_of(ov) if sh[0] == "line"
         and sh[2].get("fill") in dv.OVERLAY_COLOURS]
assert len(lines) == 2, len(lines)
for _k, coords, _kw in lines:
    ys = list(coords[1::2])
    assert all(b >= a - 1e-9 for a, b in zip(ys, ys[1:])), ys
legend = [sh for sh in shapes_of(ov) if sh[0] == "text"
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
ov3 = dv.OverlayCanvas(MASTER, padded)
set_size(ov3, 700, 260)
ov3._draw()
axis = [int(sh[2]["text"]) for sh in shapes_of(ov3) if sh[0] == "text"
        and str(sh[2]["text"]).isdigit()]
assert max(axis) == 2, axis          # not 15
# The curves must span the chart on that axis, not a fraction of it.
curves = [sh for sh in shapes_of(ov3) if sh[0] == "line"
          and sh[2].get("fill") in dv.OVERLAY_COLOURS]
for _k, coords, _kw in curves:
    assert abs(max(coords[0::2]) - frame_of(ov3)[2]) < 1e-9, \
        coords[0::2]

# A threshold no pin can reach is REPORTED, not silently dropped: before
# the axis was clamped it always landed exactly on the right edge, so a
# marker that disappears is a new way to be misread.
ov4 = dv.OverlayCanvas(MASTER, padded, threshold=15)
set_size(ov4, 700, 260)
ov4._draw()
assert not [sh for sh in shapes_of(ov4) if sh[0] == "line"
            and sh[2].get("dash")], "no marker can be drawn off the axis"
assert any(str(sh[2].get("text", "")).startswith(">= 15: out of reach")
           for sh in shapes_of(ov4) if sh[0] == "text"), \
    "an unreachable threshold must say so"
# One inside the range is still drawn as a line, as before.
ov5 = dv.OverlayCanvas(MASTER, padded, threshold=1)
set_size(ov5, 700, 260)
ov5._draw()
assert [sh for sh in shapes_of(ov5) if sh[0] == "line" and sh[2].get("dash")]

# Nothing to draw, or too small to draw: give up cleanly.
empty = dv.OverlayCanvas(MASTER, [])
set_size(empty, 700, 260)
empty._draw()
assert not shapes_of(empty)
ov2 = dv.OverlayCanvas(MASTER, series)
set_size(ov2, 50, 20)
ov2._draw()
assert not shapes_of(ov2)

# ---- nothing is drawn off the top of the canvas -----------------------

# The annotations above the plotting frame ("tail above N", "P(>= v)")
# hang from its top edge by a BOTTOM anchor, so the band above it must
# be at least one line of the caption font tall. It was 12 px against a
# 13 px line and the captions were clipped; at 150% font they would have
# been clipped by three times as much, so the band follows the font.
LINE = 13                             # what the stub font reports
for _kind, _coords, _kw in shapes_of(canvas(d6, xmax=3)):
    if _kind != "text":
        continue
    top = _coords[1] - (LINE if str(_kw.get("anchor", "")).startswith("s")
                        else LINE / 2)
    assert top >= 0, (_kw.get("text"), _coords, _kw.get("anchor"))


# ---- a forced X axis --------------------------------------------------

# Shortening the axis drops BARS and says so; it must never change the
# distribution, which the percentiles beside the chart still describe.
short = canvas(d6, xmax=3)
labels = [s[2]["text"] for s in shapes_of(short) if s[0] == "text"]
assert not any(lab in ("4", "5", "6") for lab in labels), labels
assert any(str(lab).startswith("tail above 3") for lab in labels), labels
# The bars that remain are redrawn wider, not left in place: the axis is
# rescaled, so the last one still ends at the right edge of the frame.
bars = [s for s in shapes_of(short) if s[0] == "rectangle"]
assert abs(bars[-1][1][2] - frame_of(short)[2]) < 2, bars[-1][1]
# Asking for more than the support is clamped, not honoured, and draws
# exactly what the automatic axis would have.
assert len([s for s in shapes_of(canvas(d6, xmax=999)) if s[0] == "rectangle"]) == \
    len([s for s in shapes_of(canvas(d6)) if s[0] == "rectangle"])

# ---- a forced FLOOR ---------------------------------------------------

# Raising the bottom of the axis drops the bars below it and says how
# much probability went with them, at the end it fell off: a narrowed
# window must never read as a smaller distribution.
floored = canvas(d6, xmin=3)
labels = [s[2]["text"] for s in shapes_of(floored) if s[0] == "text"]
assert not any(lab in ("1", "2") for lab in labels), labels
assert any(str(lab).startswith("below 3") for lab in labels), labels
# The note sits on the LEFT, opposite the upper-tail one, so the two can
# be shown together without overlapping. Checked by POSITION rather than
# by anchor: _note() clamps both into the canvas and therefore places
# them itself, with a west anchor either way.
def note_x(c):
    """{'below N': x, 'tail above M': x} of the two captions."""
    return {s[2]["text"].split(":")[0]: s[1][0]
            for s in shapes_of(c) if s[0] == "text"
            and s[2]["text"].startswith(("below ", "tail above "))}


assert "below 3" in note_x(floored)
both = canvas(d6, xmin=2, xmax=4)
sides = note_x(both)
assert set(sides) == {"below 2", "tail above 4"}, sides
assert sides["below 2"] < sides["tail above 4"], sides
assert sides["below 2"] >= 0 and sides["tail above 4"] >= 0, sides
# Neither is allowed to start off the canvas even when the chart is
# narrow enough that they cannot both fit whole.
narrow = note_x(canvas(d6, xmin=2, xmax=4, w=300, h=200))
assert all(x >= 0 for x in narrow.values()), narrow
# A floor above the ceiling collapses to it rather than drawing nothing.
assert [s for s in shapes_of(canvas(d6, xmin=9, xmax=4)) if s[0] == "rectangle"]

# ---- the plotting frame is never inverted -----------------------------

# The guard on the canvas size used to be a pair of constants (w < 60,
# h < 50) while the margins are set by the font: both ends could pass
# the guard and still come out reversed. At 200% font and h = 60 the
# frame had y1 < y0, so every bar had negative height and the
# probability scale was drawn upside down; at w = 61 the same happened
# sideways. The guard now reads the FRAME, so either it is big enough
# to draw or nothing is drawn.

for _size in (7, 9, 12, 16, 20, 24):
    set_caption(_size)
    for _w in (40, 61, 90, 141, 142, 300, 700, 1400):
        for _h in (20, 50, 55, 60, 72, 90, 300, 800):
            c = canvas(d6, w=_w, h=_h)
            if not shapes_of(c):          # too small to read: nothing drawn
                continue
            fx0, fy0, fx1, fy1 = frame_of(c)
            assert fx1 > fx0, (_size, _w, _h, "frame inverted sideways")
            assert fy1 > fy0, (_size, _w, _h, "frame inverted vertically")
            for _k, _c, _kw in shapes_of(c):
                if _k != "rectangle":
                    continue
                bx0, by0, bx1, by1 = _c
                assert bx1 >= bx0 and by1 >= by0, (_size, _w, _h,
                                                   "bar drawn inside out")
                assert by1 <= fy1 + 1e-9 and by0 >= fy0 - 1e-9, \
                    (_size, _w, _h, "bar outside the frame")

# The exact boundary, derived from the font rather than assumed: one
# pixel short of a usable frame draws nothing, one pixel over draws.
# Below it the old constant guard produced y1 < y0 and a chart mirrored
# top to bottom, which still looked like a reading.
for _size in (9, 20):
    set_caption(_size)
    _line = caption().metrics("linespace")
    _y0 = max(dv._PAD_T, _line + 4)
    _pad_b = max(dv._PAD_B, _line + 4 + dv._EDGE)
    _hmin = _y0 + dv._MIN_PLOT_H + _pad_b + 2     # + the highlight ring
    assert not shapes_of(canvas(d6, w=700, h=_hmin - 1)), (_size, _hmin)
    assert shapes_of(canvas(d6, w=700, h=_hmin)), (_size, _hmin)
    _x0 = dv._EDGE + caption().measure(max(dv._prob_labels(),
                                           key=caption().measure)) + dv._GAP
    _right = dv._GAP + caption().measure(
        max(dv._CUM_LABELS + [dv._CUM_CAPTION], key=caption().measure)) \
        + dv._EDGE
    _wmin = _x0 + dv._MIN_PLOT_W + _right + 2
    assert not shapes_of(canvas(d6, w=_wmin - 1, h=300)), (_size, _wmin)
    assert shapes_of(canvas(d6, w=_wmin, h=300)), (_size, _wmin)
set_caption(9)

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

# The bold twin is a NAMED font, it exists after being asked for, and it
# SURVIVES the wrapper that created it. tkinter.font.Font destroys the Tk
# font it created when its Python wrapper is collected, and nothing holds
# this one; Tk then reads the name as a family, fails to find that too,
# and falls back to the default - so the bug shows as text that is merely
# not bold rather than as an error. tkfont.names() is Tk's own answer to
# "does this font exist", so the check is the same on either toolkit.
assert ui.bold_font() == ui.BOLD_FONT
assert isinstance(ui.bold_font(), str)
gc.collect()
assert ui.BOLD_FONT in tkfont.names(), \
    "the bold font was created and then destroyed again"
assert tkfont.nametofont(ui.BOLD_FONT).cget("weight") == "bold"
# The twin follows TkDefaultFont rather than the scale, so it is right
# however the two are created and rescaled in relation to each other -
# including a window built before the scale was ever changed.
_base = tkfont.nametofont("TkDefaultFont")
for _size in (10, 17, 24, 10):
    _base.configure(size=_size)
    ui.sync_bold_font()
    assert tkfont.nametofont(ui.BOLD_FONT).cget("size") == _size
    assert tkfont.nametofont(ui.BOLD_FONT).cget("weight") == "bold"

# Selecting a series must re-font every cell of the table with a NAME,
# both the row it bolds and the rows it puts back to normal. Read with
# cget(), which is how one asks a real widget what it was configured to.
frame._which.set("gross")
frame._switch()
for _key, _cells in frame._stat_rows.items():
    for _cell in _cells:
        _f = str(_cell.cget("font"))
        assert _f == (ui.BOLD_FONT if _key == "gross" else "TkDefaultFont"), \
            (_key, _f)
        assert _f in tkfont.names(), (_key, _f, "not a named font")
frame._which.set("net")
frame._switch()

# ---- E: threshold marker, closed curve, degenerate inputs -------------

# With one value per bar the marker sits on the left edge of the bar for
# its own value, as it always did.
_t = canvas(d6, threshold=4)
_fx0, _fy0, _fx1, _fy1 = frame_of(_t)
_bins = ds.histogram(d6, max_bars=max(4, int(_fx1 - _fx0) // dv._MIN_BAR_PX))
assert _bins["width"] == 1
_bw = (_fx1 - _fx0) / len(_bins["bins"])
_mark = [s for s in shapes_of(_t) if s[0] == "line" and s[2].get("dash")]
assert len(_mark) == 1
assert abs(_mark[0][1][0] - (_fx0 + 4 * _bw)) < 1e-6, _mark[0][1]

# When several values share one bar the marker is interpolated INSIDE
# it: on its left edge it pointed at the bar's first value instead.
_wide = [0.0] + [1 / 40] * 40
_t = canvas(_wide, threshold=22, w=200, h=300)
_fx0, _fy0, _fx1, _fy1 = frame_of(_t)
_h = ds.histogram(_wide, max_bars=max(4, int(_fx1 - _fx0) // dv._MIN_BAR_PX))
assert _h["width"] > 1, _h["width"]
_bw = (_fx1 - _fx0) / len(_h["bins"])
_idx = next(i for i, (_lo, _hi, _p) in enumerate(_h["bins"]) if _hi >= 22)
_lo, _hi, _p = _h["bins"][_idx]
_mark = [s for s in shapes_of(_t) if s[0] == "line" and s[2].get("dash")][0]
_want = _fx0 + (_idx + (22 - _lo) / (_hi - _lo + 1)) * _bw
assert abs(_mark[1][0] - _want) < 1e-6, (_mark[1][0], _want)
assert _mark[1][0] > _fx0 + _idx * _bw, "marker still on the bar's edge"

# The cumulative curve reaches the scale it is read against. Without the
# closing point it stopped one bar short - a quarter of the width at the
# four-bar minimum.
_c = canvas(d6)
_fx0, _fy0, _fx1, _fy1 = frame_of(_c)
_curve = [s for s in shapes_of(_c)
          if s[0] == "line" and s[2].get("fill") == dv.CUM_LINE][0]
assert abs(max(_curve[1][0::2]) - _fx1) < 1e-6, max(_curve[1][0::2])
# ...and it lands on P(X >= top + 1) = 0, i.e. on the baseline.
assert abs(_curve[1][-1] - _fy1) < 1e-6, (_curve[1][-1], _fy1)

# A pin with no law is NOT drawn as a flat 0% curve, which would read as
# "this loadout achieves nothing" rather than "this was not computed".
_ov = dv.OverlayCanvas(MASTER, [{"name": "real", "pmf": [0.5, 0.5]},
                              {"name": "absent", "pmf": []}])
set_size(_ov, 700, 260)
_ov._draw()
_lines = [s for s in shapes_of(_ov)
          if s[0] == "line" and s[2].get("fill") in dv.OVERLAY_COLOURS]
assert len(_lines) == 1, "a series with no law must not be drawn"
_legend = [str(s[2]["text"]) for s in shapes_of(_ov) if s[0] == "text"]
assert any(t.startswith("absent") and "not computed" in t
           for t in _legend), _legend
assert any(s[0] == "text" and str(s[2]["text"]).startswith("absent")
           and s[2].get("fill") == dv.HINT for s in shapes_of(_ov))

# The upper Spinbox is never given a value below its own from_=1.
_single = dist_frame(dv.result_series([1.0]))
assert int(_single._xmax.get()) >= 1, _single._xmax.get()

# An empty series list is a broken caller, and says so.
try:
    dv.DistributionFrame(MASTER, [])
except ValueError as _e:
    assert "at least one series" in str(_e)
else:
    raise AssertionError("an empty series list must be rejected")

print("histogram canvas: OK (%d shapes, %s toolkit)"
      % (len(shapes_of(canvas(d6))), "real" if REAL else "stub"))
