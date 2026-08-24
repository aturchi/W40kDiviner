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
import ui_utils as ui

BAR_FILL = "#5b8ec4"
BAR_OVER = "#c0504d"          # bars at or above the threshold
BAR_EDGE = "#3d6a99"
AXIS = "#888888"
GRID = "#e2e2e2"
CUM_LINE = "#4f8a3d"
TEXT = "#333333"

# _PAD_T is a FLOOR, not the value used: the annotations above the frame
# ("tail above N", "P(>= v)") are drawn with a bottom anchor on its top
# edge, so the band has to be at least one line of the caption font tall
# or they are cut off by the top of the canvas - and the font scales.
_PAD_L, _PAD_R, _PAD_T, _PAD_B = 52, 46, 12, 34
_MIN_BAR_PX = 11              # narrower than this and the bars merge


class HistogramCanvas(tk.Canvas):
    """Bar chart of a PMF, with an optional cumulative P(X >= v) overlay
    and a threshold marker. Values are integers (damage points).

    'xmin' and 'xmax' are the first and last values plotted: None lets
    dist_stats choose (from zero, up to its own cut of the thin upper
    tail), a number forces that end of the axis. The mass left outside
    the window is annotated on the chart at whichever end it fell - the
    axis is a view of the distribution, never a filter on it."""

    def __init__(self, parent, pmf=None, threshold=None, cumulative=True,
                 xmax=None, xmin=None, **kw):
        kw.setdefault("background", "white")
        kw.setdefault("highlightthickness", 1)
        kw.setdefault("highlightbackground", "#cccccc")
        super().__init__(parent, **kw)
        self._pmf = list(pmf) if pmf else [1.0]
        self._threshold = threshold
        self._cumulative = cumulative
        self._xmax = xmax          # None = the automatic tail cut
        self._xmin = xmin          # None = from zero
        self.bind("<Configure>", lambda _e: self._draw())

    # ---------- public ----------

    def set_data(self, pmf=None, threshold=-1, cumulative=None, xmax=-1,
                 xmin=-1):
        """Update the drawing. threshold=-1, xmax=-1 and xmin=-1 mean
        "leave unchanged"; None is a meaningful value for all three (no
        marker, and an automatically chosen end of the axis)."""
        if pmf is not None:
            self._pmf = list(pmf) or [1.0]
        if threshold != -1:
            self._threshold = threshold
        if cumulative is not None:
            self._cumulative = bool(cumulative)
        if xmax != -1:
            self._xmax = xmax
        if xmin != -1:
            self._xmin = xmin
        self._draw()

    # ---------- drawing ----------

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 60 or h < 50:
            return
        font = tkfont.nametofont("TkSmallCaptionFont")
        x0, x1 = _PAD_L, w - _PAD_R
        y0, y1 = max(_PAD_T, font.metrics("linespace") + 4), h - _PAD_B
        max_bars = max(4, (x1 - x0) // _MIN_BAR_PX)
        hist = ds.histogram(self._pmf, max_bars=max_bars, cut=self._xmax,
                            low=self._xmin)
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
        # The mass outside the window, annotated at the end it fell off:
        # a narrowed axis must never look like a smaller distribution.
        if hist["cut"] is not None:
            self.create_text(
                x1, y0 - 2, anchor=tk.SE, fill=TEXT, font=font,
                text=f"tail above {hist['cut']}: "
                     f"{hist['cut_mass'] * 100:.2f}% (not plotted)")
        if hist["low"] is not None:
            self.create_text(
                x0, y0 - 2, anchor=tk.SW, fill=TEXT, font=font,
                text=f"below {hist['low']}: "
                     f"{hist['low_mass'] * 100:.2f}% (not plotted)")

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

    The two ends of the X axis are offered under the threshold, and
    deliberately
    does NOT follow the same rule: a threshold is a QUESTION ("what are
    my odds of at least N") and is worth carrying back and forth, while
    an axis length is a view of one particular distribution and means
    nothing on another - 10 is the whole support of "models killed" and
    the first sixth of "gross damage". Switching series therefore resets
    it to that series' automatic cut, and switching back resets it
    again.

    Used both as the body of open_distribution()'s own window and
    embedded straight into the analyzer's result page, which is why it is
    a Frame and not a dialog: the combined figure is on screen without a
    gesture, and it is the SAME widget, so the two cannot drift apart.
    'note_wrap' is the only thing that differs - a wider page wants a
    wider paragraph.
    """

    def __init__(self, parent, series, note="", note_wrap=680):
        super().__init__(parent)
        self._note_wrap = note_wrap
        self._series = {s["key"]: s for s in series}
        self._order = [s["key"] for s in series]
        self._thr = {s["key"]: ("" if s.get("threshold") is None
                                else str(int(s["threshold"])))
                     for s in series}
        self._which = tk.StringVar(value=self._order[0])
        self._cum = tk.BooleanVar(value=True)
        self._entry = tk.StringVar(value=self._thr[self._order[0]])
        self._xmax = tk.StringVar()
        self._xmin = tk.StringVar()
        self._build(note)
        self._reset_xmax()
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
                      wraplength=self._note_wrap).pack(anchor=tk.W, padx=6)

        self.canvas = HistogramCanvas(self, height=300)
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)

        # The statistics table is narrow and the space to its right was
        # empty, so the controls sit beside it rather than under it: the
        # window gets shorter by two rows, which is what a page already
        # too tall for a 768-line screen needed.
        bottom = ttk.Frame(self)
        bottom.pack(fill=tk.X, padx=6, pady=(2, 6))
        self._build_stat_table(bottom)
        side = ttk.Frame(bottom)
        side.pack(side=tk.LEFT, anchor=tk.N, padx=(24, 0))

        row = ttk.Frame(side)
        row.pack(anchor=tk.W)
        self.tail_prefix = ttk.Label(row, text="P(")
        self.tail_prefix.pack(side=tk.LEFT)
        ent = ttk.Entry(row, textvariable=self._entry, width=6)
        ent.pack(side=tk.LEFT)
        ttk.Label(row, text=") =").pack(side=tk.LEFT)
        self.tail_lbl = ttk.Label(row, text="",
                                  font=("TkDefaultFont", 10, "bold"))
        self.tail_lbl.pack(side=tk.LEFT, padx=4)
        ent.bind("<KeyRelease>", lambda _e: self._refresh())

        # The two ends of the X axis. Spinboxes rather than plain fields
        # because the useful range is known (0 .. the top of the
        # support) and a value outside it is not a question anyone is
        # asking.
        axis = ttk.Frame(side)
        axis.pack(anchor=tk.W, pady=(4, 0))
        ttk.Label(axis, text="X axis").pack(side=tk.LEFT, padx=(0, 4))
        self.xmin_spin = ttk.Spinbox(axis, from_=0, to=1, width=6,
                                     textvariable=self._xmin,
                                     command=self._refresh)
        self.xmin_spin.pack(side=tk.LEFT)
        ttk.Label(axis, text="to").pack(side=tk.LEFT, padx=4)
        self.xmax_spin = ttk.Spinbox(axis, from_=1, to=1, width=6,
                                     textvariable=self._xmax,
                                     command=self._refresh)
        self.xmax_spin.pack(side=tk.LEFT)
        for spin in (self.xmin_spin, self.xmax_spin):
            spin.bind("<KeyRelease>", lambda _e: self._refresh())

    #: statistic key -> heading, in the order the table shows them.
    STAT_COLUMNS = (("mean", "\u03bc"), ("sd", "sd"), ("lo", None),
                    ("median", "median"), ("hi", None), ("mode", "mode"),
                    ("max", "max"))

    def _build_stat_table(self, parent=None):
        """Every statistic of EVERY series, not just the one on the
        chart: the numbers do not depend on which radio is selected, and
        reading them off a table beats clicking through five charts to
        collect them. The selected row is shown in bold, so the chart
        and the table cannot be read as unrelated."""
        grid = ttk.Frame(parent if parent is not None else self)
        grid.pack(side=tk.LEFT, anchor=tk.N)
        lo_lab, hi_lab = ds.SPREAD_LABELS
        heads = [h if h is not None else (lo_lab if k == "lo" else hi_lab)
                 for k, h in self.STAT_COLUMNS]
        for col, head in enumerate([""] + heads):
            ttk.Label(grid, text=head, foreground=ui.HINT_COLOR).grid(
                row=0, column=col, sticky=tk.E, padx=(0, 8))
        self._stat_rows = {}
        for line, key in enumerate(self._order, start=1):
            cur = self._series[key]
            st = ds.stats(cur["pmf"])
            cells = [ttk.Label(grid, text=cur["label"])]
            cells[0].grid(row=line, column=0, sticky=tk.W, padx=(0, 8))
            for col, (stat, _h) in enumerate(self.STAT_COLUMNS, start=1):
                value = st[stat]
                text = (f"{value:.2f}" if stat in ("mean", "sd")
                        else str(value))
                cell = ttk.Label(grid, text=text)
                cell.grid(row=line, column=col, sticky=tk.E, padx=(0, 8))
                cells.append(cell)
            self._stat_rows[key] = cells
        self._highlight()

    def _highlight(self):
        """Bold the row of the series currently on the chart."""
        for key, cells in self._stat_rows.items():
            font = ("TkDefaultFont", 10,
                    "bold" if key == self._which.get() else "normal")
            for cell in cells:
                cell.configure(font=font)

    # ---------- state ----------

    def _switch(self):
        """Restore the threshold last used for the series being entered
        (the one being left was stored on every refresh), and reset the
        axis, which is not carried across series at all."""
        self._entry.set(self._thr.get(self._which.get(), ""))
        self._reset_xmax()
        self._highlight()
        self._refresh()

    def _reset_xmax(self):
        """Put both ends of the axis back to what the drawing would have
        chosen on its own for the current series, and bound the Spinboxes
        to that series' support."""
        pmf = self._series[self._which.get()]["pmf"]
        top = max(1, len(pmf) - 1)
        self.xmax_spin.configure(to=top)
        self.xmin_spin.configure(to=top)
        self._xmax.set(str(ds.default_xmax(pmf)))
        self._xmin.set("0")

    def _xmax_value(self, pmf):
        """The top of the axis to draw with, or None for the automatic
        one. The field is clamped on READ and never rewritten:
        correcting it under the cursor would fight whoever is halfway
        through typing a two-digit number."""
        try:
            value = int(self._xmax.get())
        except (TypeError, ValueError):
            return None
        return max(1, min(max(0, len(pmf) - 1), value))

    def _xmin_value(self, pmf):
        """The bottom of the axis, or None for zero. Clamped on read the
        same way, and dist_stats keeps it from crossing the top."""
        try:
            value = int(self._xmin.get())
        except (TypeError, ValueError):
            return None
        return max(0, min(max(0, len(pmf) - 1), value)) or None

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
                             cumulative=self._cum.get(),
                             xmax=self._xmax_value(pmf),
                             xmin=self._xmin_value(pmf))
        self.tail_prefix.config(text=f"P({cur['unit']} >= ")
        self.tail_lbl.config(
            text="-" if thr is None
            else f"{ds.tail_prob(pmf, thr) * 100:.1f}%")


def result_series(net_pmf, gross_pmf=None, kills_pmf=None, unit_wounds=None,
                  models=None, attacks_pmf=None, effective_pmf=None):
    """The series shown for one analysis result, in the order they are
    offered: the wounds actually inflicted first (the figure that
    decides whether the target dies), then the models killed, then the
    gross damage rolled - which includes what was wasted - and last the
    two counts upstream of all of it.

    Attacks and effective attacks come last because they answer a
    different question ("did the dice show up") from the three above
    them ("did the target die"), but they are here so that the window
    holds EVERY statistic of the weapon: with them the table beside the
    chart is the whole row of the result table, distributions and all.
    Neither has a natural threshold, so the P(...) field starts empty.
    """
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
    if attacks_pmf is not None:
        out.append({"key": "attacks", "label": "attacks",
                    "pmf": list(attacks_pmf), "unit": "attacks",
                    "threshold": None})
    if effective_pmf is not None:
        out.append({"key": "eff", "label": "effective attacks",
                    "pmf": list(effective_pmf), "unit": "effective attacks",
                    "threshold": None})
    return out


def open_distribution(parent, title, series, note=""):
    """Modeless window with the distribution of one analysis result.
    Several can stay open at once, like the result pages they are
    opened from."""
    win = tk.Toplevel(parent)
    win.title(title)
    win.geometry("880x680")
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
