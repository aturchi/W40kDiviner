"""Damage distribution view: a Tk canvas histogram plus the dialog that
wraps it with percentiles and a "P(damage >= N)" readout.

No new dependency: the bars are drawn on a plain tk.Canvas from the PMF
the analyzer already computed (see dist_stats for the maths). The canvas
redraws itself on <Configure>, so the window can be resized.

Entry point for callers:
    open_distribution(parent, title, net_pmf, gross_pmf=..., threshold=N)
"""

import tkinter as tk
from tkinter import ttk
from tkinter import font as tkfont

import dist_stats as ds

BAR_FILL = "#5b8ec4"
BAR_OVER = "#c0504d"          # bars at or above the threshold
BAR_EDGE = "#3d6a99"
AXIS = "#888888"
GRID = "#e2e2e2"
CUM_LINE = "#4f8a3d"
TEXT = "#333333"

_PAD_L, _PAD_R, _PAD_T, _PAD_B = 52, 46, 12, 34
_MIN_BAR_PX = 11              # narrower than this and the bars merge


class HistogramCanvas(tk.Canvas):
    """Bar chart of a PMF, with an optional cumulative P(X >= v) overlay
    and a threshold marker. Values are integers (damage points)."""

    def __init__(self, parent, pmf=None, threshold=None, cumulative=True,
                 **kw):
        kw.setdefault("background", "white")
        kw.setdefault("highlightthickness", 1)
        kw.setdefault("highlightbackground", "#cccccc")
        super().__init__(parent, **kw)
        self._pmf = list(pmf) if pmf else [1.0]
        self._threshold = threshold
        self._cumulative = cumulative
        self.bind("<Configure>", lambda _e: self._draw())

    # ---------- public ----------

    def set_data(self, pmf=None, threshold=-1, cumulative=None):
        """Update the drawing. threshold=-1 means "leave unchanged" (None
        is a meaningful value: no marker)."""
        if pmf is not None:
            self._pmf = list(pmf) or [1.0]
        if threshold != -1:
            self._threshold = threshold
        if cumulative is not None:
            self._cumulative = bool(cumulative)
        self._draw()

    # ---------- drawing ----------

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 60 or h < 50:
            return
        font = tkfont.nametofont("TkSmallCaptionFont")
        x0, x1 = _PAD_L, w - _PAD_R
        y0, y1 = _PAD_T, h - _PAD_B
        max_bars = max(4, (x1 - x0) // _MIN_BAR_PX)
        hist = ds.histogram(self._pmf, max_bars=max_bars)
        bins = hist["bins"]
        peak = max((p for _lo, _hi, p in bins), default=0.0) or 1.0
        # Round the top of the axis up to a tidy percentage.
        top = _nice_top(peak)

        self._axes(x0, y0, x1, y1, top, font)
        span = max(1, len(bins))
        bw = (x1 - x0) / span
        thr = self._threshold
        for i, (lo, hi, p) in enumerate(bins):
            bx0 = x0 + i * bw
            bx1 = bx0 + bw
            by = y1 - (p / top) * (y1 - y0)
            over = thr is not None and hi >= thr
            self.create_rectangle(bx0 + 1, by, bx1 - 1, y1,
                                  fill=BAR_OVER if over else BAR_FILL,
                                  outline=BAR_EDGE)
        self._xlabels(bins, x0, y1, bw, font)
        if thr is not None:
            self._threshold_marker(bins, thr, x0, y0, y1, bw, font)
        if self._cumulative:
            self._cum_curve(bins, x0, y0, y1, bw, font)
        if hist["cut"] is not None:
            self.create_text(
                x1, y0 - 2, anchor=tk.SE, fill=TEXT, font=font,
                text=f"tail above {hist['cut']}: "
                     f"{hist['cut_mass'] * 100:.2f}% (not plotted)")

    def _axes(self, x0, y0, x1, y1, top, font):
        """Frame, horizontal grid and the left (probability) scale."""
        # A fine scale (top = 2%) would print "0% 1% 1% 2% 2%" at zero
        # decimals: pick the precision from the tick step.
        dec = 0 if top >= 0.2 else (1 if top >= 0.04 else 2)
        for k in range(5):
            y = y1 - k * (y1 - y0) / 4
            self.create_line(x0, y, x1, y, fill=GRID if k else AXIS)
            self.create_text(x0 - 5, y, anchor=tk.E, fill=TEXT, font=font,
                             text=f"{top * k / 4 * 100:.{dec}f}%")
        self.create_line(x0, y0, x0, y1, fill=AXIS)

    def _xlabels(self, bins, x0, y1, bw, font):
        """Value labels under the bars, thinned out so they never touch."""
        step = max(1, int(round(46 / max(bw, 1))))
        for i, (lo, hi, _p) in enumerate(bins):
            if i % step:
                continue
            self.create_text(x0 + (i + 0.5) * bw, y1 + 4, anchor=tk.N,
                             fill=TEXT, font=font,
                             text=str(lo) if lo == hi else f"{lo}-{hi}")

    def _threshold_marker(self, bins, thr, x0, y0, y1, bw, font):
        """Vertical line at the first bar that reaches the threshold."""
        idx = next((i for i, (_lo, hi, _p) in enumerate(bins) if hi >= thr),
                   None)
        if idx is None:
            return
        x = x0 + idx * bw
        self.create_line(x, y0, x, y1, fill=BAR_OVER, dash=(3, 2))
        self.create_text(x + 3, y0, anchor=tk.NW, fill=BAR_OVER, font=font,
                         text=f">= {thr}")

    def _cum_curve(self, bins, x0, y0, y1, bw, font):
        """P(X >= v) on a right-hand 0-100% scale, sampled at the left
        edge of every bar."""
        pts = []
        for i, (lo, _hi, _p) in enumerate(bins):
            q = ds.tail_prob(self._pmf, lo)
            pts += [x0 + i * bw, y1 - q * (y1 - y0)]
        if len(pts) >= 4:
            self.create_line(*pts, fill=CUM_LINE, width=2, smooth=False)
        x1 = x0 + len(bins) * bw
        for k in range(5):
            y = y1 - k * (y1 - y0) / 4
            self.create_text(x1 + 5, y, anchor=tk.W, fill=CUM_LINE,
                             font=font, text=f"{k * 25}%")
        self.create_text(x1 + 5, y0 - 2, anchor=tk.SW, fill=CUM_LINE,
                         font=font, text="P(>= v)")


def _nice_top(peak: float) -> float:
    """Round a peak probability up to a readable axis maximum."""
    for step in (0.02, 0.05, 0.1, 0.2, 0.25, 0.5, 1.0):
        if peak <= step:
            return step
    return 1.0


class DistributionFrame(ttk.Frame):
    """Histogram + statistics + threshold readout for one or more
    series (net damage, gross damage, models killed...). Each series
    keeps its OWN threshold, so switching back and forth does not lose
    the number the user typed.

    series = [{'key','label','pmf','unit','threshold'}]; 'unit' is the
    noun used in the readout ("damage", "models killed").
    """

    def __init__(self, parent, series, note=""):
        super().__init__(parent)
        self._series = {s["key"]: s for s in series}
        self._order = [s["key"] for s in series]
        self._thr = {s["key"]: ("" if s.get("threshold") is None
                                else str(int(s["threshold"])))
                     for s in series}
        self._which = tk.StringVar(value=self._order[0])
        self._cum = tk.BooleanVar(value=True)
        self._entry = tk.StringVar(value=self._thr[self._order[0]])
        self._build(note)
        self._refresh()

    # ---------- construction ----------

    def _build(self, note):
        top = ttk.Frame(self)
        top.pack(fill=tk.X, padx=6, pady=(6, 2))
        if len(self._order) > 1:
            ttk.Label(top, text="Show:").pack(side=tk.LEFT)
            for key in self._order:
                ttk.Radiobutton(top, text=self._series[key]["label"],
                                value=key, variable=self._which,
                                command=self._switch).pack(side=tk.LEFT,
                                                           padx=(2, 8))
        ttk.Checkbutton(top, text="cumulative", variable=self._cum,
                        command=self._refresh).pack(side=tk.LEFT, padx=8)
        if note:
            ttk.Label(self, text=note, foreground="#666666",
                      wraplength=680).pack(anchor=tk.W, padx=6)

        self.canvas = HistogramCanvas(self, height=240)
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)

        self.stat_lbl = ttk.Label(self, text="",
                                  font=("TkDefaultFont", 10, "bold"))
        self.stat_lbl.pack(anchor=tk.W, padx=6)

        row = ttk.Frame(self)
        row.pack(fill=tk.X, padx=6, pady=(2, 6))
        self.tail_prefix = ttk.Label(row, text="P(")
        self.tail_prefix.pack(side=tk.LEFT)
        ent = ttk.Entry(row, textvariable=self._entry, width=6)
        ent.pack(side=tk.LEFT)
        ttk.Label(row, text=") =").pack(side=tk.LEFT)
        self.tail_lbl = ttk.Label(row, text="",
                                  font=("TkDefaultFont", 10, "bold"))
        self.tail_lbl.pack(side=tk.LEFT, padx=4)
        ent.bind("<KeyRelease>", lambda _e: self._refresh())

    # ---------- state ----------

    def _switch(self):
        """Restore the threshold last used for the series being entered
        (the one being left was stored on every refresh)."""
        self._entry.set(self._thr.get(self._which.get(), ""))
        self._refresh()

    def _threshold(self):
        try:
            return max(0, int(self._entry.get()))
        except (TypeError, ValueError):
            return None

    def _refresh(self):
        key = self._which.get()
        cur = self._series[key]
        pmf, thr = cur["pmf"], self._threshold()
        self._thr[key] = self._entry.get()
        self.canvas.set_data(pmf=pmf, threshold=thr,
                             cumulative=self._cum.get())
        self.stat_lbl.config(text=ds.summary_line(pmf, cur["unit"]))
        self.tail_prefix.config(text=f"P({cur['unit']} >= ")
        self.tail_lbl.config(
            text="-" if thr is None
            else f"{ds.tail_prob(pmf, thr) * 100:.1f}%")


def result_series(net_pmf, gross_pmf=None, kills_pmf=None, unit_wounds=None,
                  models=None):
    """The series shown for one analysis result, in the order they are
    offered: the wounds actually inflicted first (the figure that
    decides whether the target dies), then the models killed, then the
    gross damage rolled - which includes what was wasted."""
    out = [{"key": "net", "label": "wounds inflicted",
            "pmf": list(net_pmf), "unit": "wounds",
            "threshold": unit_wounds}]
    if kills_pmf is not None:
        out.append({"key": "kills", "label": "models killed",
                    "pmf": list(kills_pmf), "unit": "models killed",
                    "threshold": models})
    if gross_pmf is not None:
        out.append({"key": "gross", "label": "gross damage",
                    "pmf": list(gross_pmf), "unit": "damage",
                    "threshold": unit_wounds})
    return out


def open_distribution(parent, title, series, note=""):
    """Modeless window with the distribution of one analysis result.
    Several can stay open at once, like the result pages they are
    opened from."""
    win = tk.Toplevel(parent)
    win.title(title)
    win.geometry("760x460")
    ttk.Label(win, text=title, font=("TkDefaultFont", 10, "bold")).pack(
        anchor=tk.W, padx=6, pady=(6, 0))
    frame = DistributionFrame(win, series, note=note)
    frame.pack(fill=tk.BOTH, expand=True)
    ttk.Button(win, text="Close", command=win.destroy).pack(pady=(0, 6))
    return win


# ---------------- comparison overlay ----------------

OVERLAY_COLOURS = ("#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e",
                   "#8c564b", "#17becf", "#7f7f7f")


class OverlayCanvas(tk.Canvas):
    """P(X >= v) of several distributions on one chart.

    Bars cannot be stacked readably, but the survival curves can: the
    curve that stays above the others dominates it everywhere, which is
    exactly the question 'is this loadout better' asks. A vertical
    marker shows the threshold - usually the target unit's wounds - so
    the reader can see where each curve crosses it.
    """

    def __init__(self, parent, series=None, threshold=None, **kw):
        kw.setdefault("background", "white")
        kw.setdefault("highlightthickness", 1)
        kw.setdefault("highlightbackground", "#cccccc")
        super().__init__(parent, **kw)
        self._series = list(series or [])
        self._threshold = threshold
        self.bind("<Configure>", lambda _e: self._draw())

    def set_data(self, series=None, threshold=-1):
        if series is not None:
            self._series = list(series)
        if threshold != -1:
            self._threshold = threshold
        self._draw()

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 80 or h < 60 or not self._series:
            return
        font = tkfont.nametofont("TkSmallCaptionFont")
        x0, x1, y0, y1 = 46, w - 12, 12, h - 30
        vmax = max((len(s["pmf"]) - 1 for s in self._series if s["pmf"]),
                   default=1) or 1
        for k in range(5):                      # grid and probability axis
            y = y1 - k * (y1 - y0) / 4
            self.create_line(x0, y, x1, y, fill=GRID if k else AXIS)
            self.create_text(x0 - 5, y, anchor=tk.E, fill=TEXT, font=font,
                             text=f"{k * 25}%")
        self.create_line(x0, y0, x0, y1, fill=AXIS)
        for k in range(6):                      # value axis
            v = round(vmax * k / 5)
            x = x0 + (x1 - x0) * (v / vmax)
            self.create_text(x, y1 + 4, anchor=tk.N, fill=TEXT, font=font,
                             text=str(v))
        if self._threshold is not None and 0 <= self._threshold <= vmax:
            x = x0 + (x1 - x0) * (self._threshold / vmax)
            self.create_line(x, y0, x, y1, fill="#c0504d", dash=(3, 2))
            self.create_text(x + 3, y0, anchor=tk.NW, fill="#c0504d",
                             font=font, text=f">= {self._threshold}")
        for i, s in enumerate(self._series):
            colour = OVERLAY_COLOURS[i % len(OVERLAY_COLOURS)]
            pts = []
            for v in range(vmax + 1):
                q = ds.tail_prob(s["pmf"], v)
                pts += [x0 + (x1 - x0) * (v / vmax),
                        y1 - q * (y1 - y0)]
            if len(pts) >= 4:
                self.create_line(*pts, fill=colour, width=2)
            self.create_text(x1 - 6, y0 + 2 + i * (font.metrics("linespace")
                                                   + 2),
                             anchor=tk.NE, fill=colour, font=font,
                             text=s["name"][:42])
