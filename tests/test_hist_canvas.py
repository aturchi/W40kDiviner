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
    def __init__(self, *_a, **_kw):
        self.shapes = []

    def __getattr__(self, _name):     # bind/pack/configure/delete/...
        return lambda *_a, **_kw: None


class _Canvas(_Widget):
    _w, _h = 700, 300             # class defaults: __getattr__ must not
                                  # turn a missing size into a lambda

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
ttk.Radiobutton = ttk.Checkbutton = _Widget
class _Font:
    """Only what the drawing code asks a font for."""

    def metrics(self, _what):
        return 13


font = types.ModuleType("tkinter.font")
font.nametofont = lambda _name: _Font()
tk.ttk, tk.font = ttk, font
sys.modules["tkinter"] = tk
sys.modules["tkinter.ttk"] = ttk
sys.modules["tkinter.font"] = font

import dist_stats as ds               # noqa: E402
import dist_view as dv                # noqa: E402


def canvas(pmf, threshold=None, cumulative=True, w=700, h=300):
    c = dv.HistogramCanvas(None, pmf, threshold, cumulative)
    c._w, c._h = w, h
    c._draw()
    return c


d6 = [0.0] + [1 / 6] * 6

# One bar per bin, all inside the plotting frame, none taller than it.
c = canvas(d6)
bars = [s for s in c.shapes if s[0] == "rect"]
bins = ds.histogram(d6, max_bars=max(4, (700 - dv._PAD_L - dv._PAD_R)
                                     // dv._MIN_BAR_PX))["bins"]
assert len(bars) == len(bins), (len(bars), len(bins))
y_top, y_bot = dv._PAD_T, 300 - dv._PAD_B
for _k, (bx0, by0, bx1, by1), _kw in bars:
    assert dv._PAD_L <= bx0 < bx1 <= 700 - dv._PAD_R, (bx0, bx1)
    assert y_top - 1e-9 <= by0 <= by1 <= y_bot + 1e-9, (by0, by1)

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

# Nothing to draw, or too small to draw: give up cleanly.
empty = dv.OverlayCanvas(None, [])
empty._w, empty._h = 700, 260
empty._draw()
assert not empty.shapes
ov2 = dv.OverlayCanvas(None, series)
ov2._w, ov2._h = 50, 20
ov2._draw()
assert not ov2.shapes

print("histogram canvas: OK (%d shapes)" % len(canvas(d6).shapes))
