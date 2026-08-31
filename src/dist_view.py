"""Distribution views: a Tk canvas histogram, the panel that wraps it
with a statistics table and a "P(v >= N)" readout, and a survival-curve
canvas for comparing pinned analyses.

No new dependency: everything is drawn on a plain tk.Canvas from the
PMFs the analyzer already computed (see dist_stats for the maths). Both
canvases redraw on <Configure>, so a window can be resized.

Entry points for callers:
    result_series(net_pmf, gross_pmf=..., kills_pmf=..., ...)
        -> the list of series for one analysis result, which is what
           both of the following take.
    open_distribution(parent, title, series, note="")
        -> a standalone window.
    DistributionFrame(parent, series, note="")
        -> the same thing embedded in a page.
    OverlayCanvas(parent, series, threshold=N)
        -> one survival curve per pinned analysis, see comparison.py.
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
HINT = "#999999"              # a series that carries no law at all

# _PAD_T is a FLOOR, not the value used: the annotations above the frame
# ("tail above N", "P(>= v)") are drawn with a bottom anchor on its top
# edge, so the band has to be at least one line of the caption font tall
# or they are cut off by the top of the canvas - and the font scales.
#
# The other three are FALLBACKS, used only when the font cannot be
# measured (a stub in a headless test). What the margins have to hold is
# the scale labels, whose width is a property of the font and not a
# constant: as fixed numbers they clipped the leftmost scale, and every
# step of the font scale made it worse.
_PAD_L, _PAD_R, _PAD_T, _PAD_B = 52, 46, 12, 34
_MIN_BAR_PX = 11              # narrower than this and the bars merge
# The smallest plotting frame worth drawing, measured on the frame
# ITSELF and not on the canvas: the margins around it are now font-sized
# at both ends, so a limit expressed in canvas size cannot stay true to
# them. Width is the four bars _draw() always asks for; height is where
# the five grid lines stop being distinguishable.
_MIN_PLOT_W, _MIN_PLOT_H = 4 * _MIN_BAR_PX, 20

# Every top the probability axis can be rounded up to (see _nice_top).
_NICE_TOPS = (0.02, 0.05, 0.1, 0.2, 0.25, 0.5, 1.0)
_GAP = 5                      # scale label to the frame it labels
_EDGE = 3                     # scale label to the edge of the canvas
_CUM_CAPTION = "P(>= v)"
_CUM_LABELS = [f"{k * 25}%" for k in range(5)]


def _axis_decimals(top: float) -> int:
    """Decimals on the probability scale. A fine scale (top = 2%) would
    print '0% 1% 1% 2% 2%' at zero decimals, so the precision follows
    the tick step."""
    return 0 if top >= 0.2 else (1 if top >= 0.04 else 2)


def _prob_labels():
    """Every label the left probability scale can ever print.

    Finite, and that is the point: the top of the axis is one of
    _NICE_TOPS and the decimals follow from it, so this is the whole
    vocabulary of that scale. The margin can therefore be measured
    BEFORE the top is known - which it has to be, since the top comes
    out of a binning that needs the margin to have been chosen already.
    """
    return [f"{top * k / 4 * 100:.{_axis_decimals(top)}f}%"
            for top in _NICE_TOPS for k in range(5)]


def _measure(font, texts, fallback: int) -> int:
    """Width in pixels of the widest of 'texts'.

    Falls back to a constant rather than raising: a font that cannot be
    measured is a headless stub or a broken font name, and a chart drawn
    with slightly wrong margins beats a chart not drawn at all.
    """
    try:
        return max(font.measure(t) for t in texts)
    except Exception:
        return fallback


def _inner(canvas):
    """The DRAWABLE size of a canvas, its border excluded.

    winfo_width() / winfo_height() report the widget, border and
    highlight ring included, while canvas coordinate (0, 0) is the
    top-left corner of the area INSIDE them. Drawing out to
    winfo_width() therefore puts the last couple of pixels underneath
    the border, which is enough to shave the '%' off the end of the
    right-hand scale - and the whole of it once the font is scaled up.
    """
    try:
        inset = 2 * (int(canvas.cget("highlightthickness"))
                     + int(canvas.cget("borderwidth")))
    except Exception:
        inset = 0
    return canvas.winfo_width() - inset, canvas.winfo_height() - inset


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
        w, h = _inner(self)
        font = tkfont.nametofont("TkSmallCaptionFont")
        line = font.metrics("linespace")
        # Each margin is sized on what has to fit in it. The left scale
        # is drawn with an EAST anchor at x0 - _GAP, so it grows towards
        # the edge of the canvas and a fixed margin clipped it; the right
        # one is anchored WEST at x1 + _GAP and does the same outwards.
        x0 = _EDGE + _measure(font, _prob_labels(),
                              _PAD_L - _GAP - _EDGE) + _GAP
        x1 = w - (_GAP + _measure(font, _CUM_LABELS + [_CUM_CAPTION],
                                  _PAD_R - _GAP - _EDGE) + _EDGE)
        y0, y1 = max(_PAD_T, line + 4), h - max(_PAD_B, line + 4 + _EDGE)
        # Give up AFTER working out the frame, not before. A guard on the
        # canvas size cannot know the margins: between a left scale that
        # follows the font and a right one that does too, a canvas large
        # enough by any constant could still produce x1 < x0 or y1 < y0.
        # Every length downstream is then negative - bars grow upwards
        # out of the axis and the probability scale is drawn upside down
        # - and a mirrored chart is worse than no chart, because it still
        # looks like a reading.
        if x1 - x0 < _MIN_PLOT_W or y1 - y0 < _MIN_PLOT_H:
            return
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
            self._note(x1, y0 - 2, w, font, True,
                       f"tail above {hist['cut']}: "
                       f"{hist['cut_mass'] * 100:.2f}% (not plotted)")
        if hist["low"] is not None:
            self._note(x0, y0 - 2, w, font, False,
                       f"below {hist['low']}: "
                       f"{hist['low_mass'] * 100:.2f}% (not plotted)")

    def _note(self, x, y, w, font, right, text):
        """One of the two 'not plotted' captions, kept inside the canvas.

        They hang off the ends of the FRAME, but how wide they are is
        decided by the font and by the numbers in them, so the
        right-hand one used to be drawn starting at a negative x on a
        narrow chart - Tk then cut off its beginning, which is the half
        that says what the number means. Clamped, a caption too long for
        the canvas loses its END instead, and the end is '(not plotted)'.
        """
        span = _measure(font, [text], len(text) * 6)
        left = x - span if right else x
        self.create_text(max(_EDGE, min(left, w - span - _EDGE)), y,
                         anchor=tk.SW, fill=TEXT, font=font, text=text)

    def _axes(self, x0, y0, x1, y1, top, font):
        """Frame, horizontal grid and the left (probability) scale."""
        dec = _axis_decimals(top)
        for k in range(5):
            y = y1 - k * (y1 - y0) / 4
            self.create_line(x0, y, x1, y, fill=GRID if k else AXIS)
            self.create_text(x0 - _GAP, y, anchor=tk.E, fill=TEXT,
                             font=font,
                             text=f"{top * k / 4 * 100:.{dec}f}%")
        self.create_line(x0, y0, x0, y1, fill=AXIS)

    def _xlabels(self, bins, x0, y1, bw, font):
        """Value labels under the bars, thinned out so they never touch.

        How many fit is decided by MEASURING the labels actually about
        to be drawn: '10-14' at 200% is three times the width of '3' at
        100%, and a constant spacing had them overlapping at one end of
        that range and needlessly sparse at the other."""
        texts = [str(lo) if lo == hi else f"{lo}-{hi}"
                 for lo, hi, _p in bins]
        need = _measure(font, texts, 40) + _GAP
        step = max(1, int(round(need / max(bw, 1))))
        for i, (lo, hi, _p) in enumerate(bins):
            if i % step:
                continue
            self.create_text(x0 + (i + 0.5) * bw, y1 + 4, anchor=tk.N,
                             fill=TEXT, font=font,
                             text=str(lo) if lo == hi else f"{lo}-{hi}")

    def _threshold_marker(self, bins, thr, x0, y0, y1, bw, font):
        """Vertical line where the threshold value starts.

        Interpolated INSIDE the bar when several values share one: a bar
        labelled '10-14' spans five values, and putting the marker on
        its left edge drew ">= 12" at the position of 10. With one value
        per bar this reduces to the left edge, as before.

        The bar itself is coloured whenever it CAN reach the threshold,
        so a bar the marker cuts through is partly below it. Splitting
        the rectangle at the marker would be worse, not better: it would
        claim the mass inside the bar is spread evenly across its
        values, and it is not.
        """
        idx = next((i for i, (_lo, hi, _p) in enumerate(bins) if hi >= thr),
                   None)
        if idx is None:
            return
        lo, hi, _p = bins[idx]
        x = x0 + (idx + max(0, thr - lo) / (hi - lo + 1)) * bw
        self.create_line(x, y0, x, y1, fill=BAR_OVER, dash=(3, 2))
        self.create_text(x + 3, y0, anchor=tk.NW, fill=BAR_OVER, font=font,
                         text=f">= {thr}")

    def _cum_curve(self, bins, x0, y0, y1, bw, font):
        """P(X >= v) on a right-hand 0-100% scale.

        Sampled at the left edge of every bar, which is where the value
        that bar starts at sits, and closed with one more point at the
        right edge of the last one - P(X >= hi + 1). Without that last
        point the curve stopped a whole bar short of the scale it is
        read against, which is a quarter of the width when the axis is
        down to four bars.
        """
        pts = []
        for i, (lo, _hi, _p) in enumerate(bins):
            q = ds.tail_prob(self._pmf, lo)
            pts += [x0 + i * bw, y1 - q * (y1 - y0)]
        x1 = x0 + len(bins) * bw
        if bins:
            q = ds.tail_prob(self._pmf, bins[-1][1] + 1)
            pts += [x1, y1 - q * (y1 - y0)]
        if len(pts) >= 4:
            self.create_line(*pts, fill=CUM_LINE, width=2, smooth=False)
        for k in range(5):
            y = y1 - k * (y1 - y0) / 4
            self.create_text(x1 + _GAP, y, anchor=tk.W, fill=CUM_LINE,
                             font=font, text=_CUM_LABELS[k])
        self.create_text(x1 + _GAP, y0 - 2, anchor=tk.SW, fill=CUM_LINE,
                         font=font, text=_CUM_CAPTION)


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
    deliberately do NOT follow the same rule: a threshold is a QUESTION
    ("what are my odds of at least N") and is worth carrying back and
    forth, while an axis window is a view of one particular distribution
    and means nothing on another - 10 is the whole support of "models
    killed" and the first sixth of "gross damage". Switching series
    therefore resets the axis to that series' automatic cut, and
    switching back resets it again.

    Used both as the body of open_distribution()'s own window and
    embedded straight into the analyzer's result page, which is why it is
    a Frame and not a dialog: the combined figure is on screen without a
    gesture, and it is the SAME widget, so the two cannot drift apart.
    'note_wrap' is the only thing that differs - a wider page wants a
    wider paragraph.
    """

    def __init__(self, parent, series, note="", note_wrap=680):
        super().__init__(parent)
        if not series:
            # Every caller goes through result_series(), which always
            # returns at least the inflicted-wounds series, so an empty
            # list means the caller is broken. Say which caller, rather
            # than an IndexError three lines down.
            raise ValueError("DistributionFrame needs at least one series")
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
        self.tail_lbl = ttk.Label(row, text="", font=ui.bold_font())
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
        if note:
            self._build_note(side, note)

    #: The note box never grows past this many lines. It sits in the gap
    #: under the X-axis row, and that gap is three rows tall: a fourth
    #: would push the window past the height a 768-line screen has.
    NOTE_LINES = 3

    def _build_note(self, parent, note):
        """What this chart is OF: the weapon's printed characteristics
        and the target it was fired at.

        Pre-wrapped rather than left to 'wraplength', because the height
        has to be BOUNDED and a Label that wraps by itself grows as far
        as the text asks. Half the chart's width, which is the room
        beside the statistics table.
        """
        width = max(200, self._note_wrap // 2)
        try:
            font = tkfont.nametofont("TkDefaultFont")
            lines = []
            for para in note.split("\n"):
                lines += ui.wrap_lines(para, font, width, indent="")
        except tk.TclError:
            lines = note.split("\n")
        if len(lines) > self.NOTE_LINES:
            lines = lines[:self.NOTE_LINES]
            lines[-1] = lines[-1].rstrip(" .") + " ..."
        box = ttk.LabelFrame(parent, text="This chart")
        box.pack(anchor=tk.W, fill=tk.X, pady=(6, 0))
        ttk.Label(box, text="\n".join(lines), justify=tk.LEFT,
                  foreground=ui.HINT_COLOR).pack(anchor=tk.W, padx=4,
                                                 pady=(0, 2))

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
        """Bold the row of the series currently on the chart.

        Both fonts are NAMED - "TkDefaultFont" and its bold twin - so
        the cells follow the font scale. Written as a literal
        ("TkDefaultFont", 10, "bold") tuple they did not, and the table
        stayed at 10 pt under headings that grew (see ui_utils).
        """
        which = self._which.get()
        for key, cells in self._stat_rows.items():
            font = ui.bold_font() if key == which else "TkDefaultFont"
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
        to that series' support.

        The upper end is floored at 1, matching the Spinbox's own
        from_=1 and _xmax_value()'s clamp: default_xmax() returns 0 for
        a law with a single value, which would have written a number
        outside the range the widget declares.
        """
        pmf = self._series[self._which.get()]["pmf"]
        top = max(1, len(pmf) - 1)
        self.xmax_spin.configure(to=top)
        self.xmin_spin.configure(to=top)
        self._xmax.set(str(max(1, ds.default_xmax(pmf))))
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
                  models=None, attacks_pmf=None, effective_pmf=None,
                  self_pmf=None):
    """The series shown for one analysis result, in the order they are
    offered: the wounds actually inflicted first (the figure that
    decides whether the target dies), then the models killed, then the
    gross damage rolled - which includes what was wasted - then the two
    counts upstream of all of it, and last what the shooting cost the
    attacker.

    Attacks and effective attacks come next to last because they answer
    a different question ("did the dice show up") from the three above
    them ("did the target die"). Neither has a natural threshold, so the
    P(...) field starts empty for them.

    Self-inflicted damage is last because it answers a third question
    ("what did it cost me") and, like them, has no threshold here - the
    attacker's own wound total is not among the numbers this function is
    given. It appears only for a HAZARDOUS weapon, exactly as the
    Self-dmg column does, and it is the series that most needs a
    distribution: two hazardous weapons average 1.33 self-inflicted
    damage while the likeliest outcome is none at all, so the mean
    describes an outcome that does not happen.

    With it the table beside the chart is the whole row of the result
    table, distributions and all.
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
    if self_pmf is not None:
        out.append({"key": "self", "label": "self-inflicted damage",
                    "pmf": list(self_pmf), "unit": "self-inflicted damage",
                    "threshold": None})
    return out


def open_distribution(parent, title, series, note=""):
    """Modeless window with the distribution of one analysis result.
    Several can stay open at once, like the result pages they are
    opened from."""
    win = tk.Toplevel(parent)
    win.title(title)
    win.geometry("880x680")
    ttk.Label(win, text=title, font=ui.bold_font()).pack(
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

    The value axis runs to the highest value ANY of the series can
    actually reach, not to the end of the longest vector: the laws that
    come out of the allocation chain are sized on the target unit, so
    reading the axis off their length drew a chart whose right-hand
    part was empty by construction and squashed every curve into the
    left of it. When the threshold falls outside that range it is
    reported in words instead of drawn, because a marker silently
    dropped and a marker that never applied look the same.
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
        w, h = _inner(self)
        if not self._series:
            return
        font = tkfont.nametofont("TkSmallCaptionFont")
        line = font.metrics("linespace")
        # Same rule as the histogram: the left scale is anchored EAST and
        # grows towards the edge of the canvas, the value labels hang
        # below the frame by one line of the caption font. Both were
        # constants and both were clipped once the font was scaled up.
        x0 = _EDGE + _measure(font, _CUM_LABELS, 46 - _GAP - _EDGE) + _GAP
        x1, y0 = w - 12, 12
        y1 = h - max(30, line + 4 + _EDGE)
        if x1 - x0 < _MIN_PLOT_W or y1 - y0 < _MIN_PLOT_H:
            return
        # The top of the SUPPORT, not the end of the vector: see the
        # class docstring and dist_stats.support_top().
        vmax = max((ds.support_top(s["pmf"]) for s in self._series
                    if s["pmf"]), default=1) or 1
        for k in range(5):                      # grid and probability axis
            y = y1 - k * (y1 - y0) / 4
            self.create_line(x0, y, x1, y, fill=GRID if k else AXIS)
            self.create_text(x0 - _GAP, y, anchor=tk.E, fill=TEXT,
                             font=font, text=_CUM_LABELS[k])
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
        elif self._threshold is not None and self._threshold > vmax:
            # Off the right of the axis: no pin reaches it at all, which
            # is an ANSWER to the question the marker asks and must not
            # look like a marker that was forgotten.
            self.create_text(x1 - 6, y1 - 4, anchor=tk.SE, fill="#c0504d",
                             font=font,
                             text=f">= {self._threshold}: out of reach "
                                  f"(no curve passes {vmax})")
        for i, s in enumerate(self._series):
            colour = OVERLAY_COLOURS[i % len(OVERLAY_COLOURS)]
            label, pts = s["name"][:42], []
            if s["pmf"]:
                for v in range(vmax + 1):
                    q = ds.tail_prob(s["pmf"], v)
                    pts += [x0 + (x1 - x0) * (v / vmax),
                            y1 - q * (y1 - y0)]
            else:
                # No law at all - the analysis this pin came from never
                # ran the kill chain, say. Drawing tail_prob([], v) would
                # lay a flat 0% line along the axis, which reads as "this
                # loadout achieves nothing" instead of "this was not
                # computed". Say the second, in grey, and draw nothing.
                colour, label = HINT, label + " - not computed"
            if len(pts) >= 4:
                self.create_line(*pts, fill=colour, width=2)
            self.create_text(x1 - 6, y0 + 2 + i * (font.metrics("linespace")
                                                   + 2),
                             anchor=tk.NE, fill=colour, font=font,
                             text=label)
