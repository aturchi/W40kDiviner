"""Shared Tkinter UI helpers.

- scrollable_listbox(): a Listbox packed next to auto-hiding scrollbars
  (vertical always, horizontal on request) that appear only when the
  content overflows.
- ScrollableFrame(): a container whose contents scroll vertically when the
  window is too short to show them, with the same auto-hiding scrollbar.
- wheel_units(): the wheel-notch decoding behind it (X11 / Windows / macOS).
- attach_yscroll() / attach_xscroll(): the same auto-hiding scrollbars for
  an existing yview/xview widget.
- wrap_lines(): word-wrap a string to a pixel width using a font's metrics.
- WrappedList(): a Listbox whose long rows wrap onto indented continuation
  lines while callers keep addressing whole records.
- multi_select_hint(): the shared "Ctrl+click" reminder label used by every
  dialog holding a multi-selection list.
- save_text(): the shared "ask for a file name and write this text"
  dialog behind every export (CSV tables, attack log, cheat sheets).

Kept dependency-free (tkinter only) so every GUI module can reuse it
instead of wiring scrollbars by hand.
"""

import sys
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import font as tkfont
from tkinter import ttk

# Modifier key used to extend a selection: Command on macOS, Control
# everywhere else. Shift+click extends to a range on all platforms.
_MULTI_KEY = "Cmd" if sys.platform == "darwin" else "Ctrl"
MULTI_SELECT_HINT = (f"{_MULTI_KEY}+click to select more than one entry, "
                     "Shift+click for a range")
HINT_COLOR = "#666666"


class _AutoScrollbar(ttk.Scrollbar):
    """A vertical scrollbar that hides itself (grid_remove) while the whole
    view is visible and re-appears when it is not. Must be managed by grid
    (it calls grid()/grid_remove() on itself)."""

    def set(self, lo, hi):
        """Show the scrollbar only when the view does not fully fit (grid it),
        otherwise remove it; then defer to the normal Scrollbar.set."""
        if float(lo) <= 0.0 and float(hi) >= 1.0:
            self.grid_remove()
        else:
            self.grid()
        super().set(lo, hi)


def attach_yscroll(widget, container, row=0, column=0):
    """Add an auto-hiding vertical scrollbar to 'widget' (anything with
    yview / yscrollcommand, e.g. a Listbox, Text or Treeview). 'widget' and
    the scrollbar are grid-placed inside 'container': widget at (row,
    column), scrollbar at (row, column+1). The container's row/column
    weights are set so the widget expands. Returns the scrollbar."""
    sb = _AutoScrollbar(container, orient=tk.VERTICAL, command=widget.yview)
    widget.configure(yscrollcommand=sb.set)
    widget.grid(row=row, column=column, sticky="nsew")
    sb.grid(row=row, column=column + 1, sticky="ns")
    container.rowconfigure(row, weight=1)
    container.columnconfigure(column, weight=1)
    return sb


def attach_xscroll(widget, container, row=1, column=0):
    """Add an auto-hiding HORIZONTAL scrollbar to 'widget' (anything with
    xview / xscrollcommand). Meant to sit under a widget already placed by
    attach_yscroll, hence the default row=1: the bar spans the widget's
    column only, so it does not run under the vertical bar. It appears just
    when a line is too long for the window - which is the only time a
    non-wrapping widget hides text. Returns the scrollbar."""
    sb = _AutoScrollbar(container, orient=tk.HORIZONTAL, command=widget.xview)
    widget.configure(xscrollcommand=sb.set)
    sb.grid(row=row, column=column, sticky="ew")
    return sb


def scrollable_listbox(parent, *, xscroll=True, **listbox_kwargs):
    """Create a Listbox with auto-hiding scrollbars inside a new frame.
    Returns (frame, listbox); pack/grid the FRAME where the listbox would
    have gone, and use the listbox as usual. Each scrollbar shows only when
    the content overflows in its direction; pass xscroll=False for a list
    that wraps its rows instead (see WrappedList)."""
    frame = ttk.Frame(parent)
    lb = tk.Listbox(frame, **listbox_kwargs)
    attach_yscroll(lb, frame)
    if xscroll:
        attach_xscroll(lb, frame)
    return frame, lb


def wheel_units(event) -> int:
    """Wheel notches as a scroll direction: +1 per notch DOWN, -1 per notch
    UP, 0 when the event carries no movement.

    Tk reports a wheel in three different ways and every one of them has to
    be handled here: X11 sends Button-4 (up) and Button-5 (down) with no
    delta at all, Windows sends <MouseWheel> with a delta in multiples of
    120, and macOS sends <MouseWheel> with a small delta (often 1). The
    sign is inverted on the way out because a wheel turned UP scrolls the
    view towards the TOP, which is a NEGATIVE yview_scroll."""
    num = getattr(event, "num", 0)
    if num == 4:
        return -1
    if num == 5:
        return +1
    delta = getattr(event, "delta", 0) or 0
    if not delta:
        return 0
    notches = int(delta / 120) if abs(delta) >= 120 else (1 if delta > 0
                                                          else -1)
    return -notches


class ScrollableFrame(ttk.Frame):
    """A container whose contents scroll VERTICALLY when they do not fit.

    Pack or grid the ScrollableFrame where a plain Frame would have gone
    and put the children into '.body'. The scrollbar is the auto-hiding one
    used everywhere else, so on a screen tall enough for the whole content
    it is not drawn at all and the layout is exactly what it was.

    Only the height is negotiable: the canvas follows the body's REQUESTED
    WIDTH, so nothing ever has to be scrolled sideways to be read. A setup
    column that reflowed horizontally would lose the alignment of every row
    in it, and the height was the only thing that ever overflowed.

    Mouse-wheel support is NOT automatic. Tk delivers a wheel event to the
    widget under the pointer and then to that widget's bind tags - never to
    its parent - so a wheel over a checkbutton inside the body would not
    reach the canvas. Call bind_wheel() once, after the body has been
    populated; a widget created later needs its own call.
    """

    WHEEL_LINES = 3                     # rows scrolled per wheel notch
    _WHEEL_EVENTS = ("<MouseWheel>",    # Windows and macOS
                     "<Button-4>", "<Button-5>")   # X11
    # Widgets that scroll themselves: the wheel over them is theirs.
    _SELF_SCROLLING = (tk.Listbox, tk.Text, tk.Canvas, ttk.Treeview)

    def __init__(self, parent, height=120, **kw):
        super().__init__(parent, **kw)
        # A deliberately small requested height: the canvas is stretched by
        # its geometry manager anyway (the hosts pack the panel with
        # fill=Y), while asking for the full content height would push the
        # toplevel's requested size back up to the very size this class
        # exists to stop requiring on a short screen.
        self.canvas = tk.Canvas(self, height=height, borderwidth=0,
                                highlightthickness=0)
        # A tk.Canvas does not follow the ttk theme, so the strip left
        # below shorter-than-the-window content would be a differently
        # coloured band. Copy the themed frame background onto it.
        background = ttk.Style(self).lookup("TFrame", "background")
        if background:
            self.canvas.configure(background=background)
        self.body = ttk.Frame(self.canvas)
        self._item = self.canvas.create_window((0, 0), window=self.body,
                                               anchor=tk.NW)
        attach_yscroll(self.canvas, self)
        self._width = 0
        self.body.bind("<Configure>", self._on_body, add="+")
        self.canvas.bind("<Configure>", self._on_canvas, add="+")
        self._bind_one(self.canvas)     # wheel over the empty area below

    # ---------- geometry ----------

    def _on_body(self, _event=None):
        """The content changed size: refresh the scroll region and follow
        the body's requested width."""
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        want = self.body.winfo_reqwidth()
        if want != self._width:
            self._width = want
            self.canvas.configure(width=want)

    def _on_canvas(self, event=None):
        """Stretch the body to the canvas width, so its children align to
        the panel instead of to their own natural width."""
        width = (event.width if event is not None
                 else self.canvas.winfo_width())
        self.canvas.itemconfigure(self._item, width=width)

    # ---------- mouse wheel ----------

    def _bind_one(self, widget):
        for seq in self._WHEEL_EVENTS:
            widget.bind(seq, self._on_wheel, add="+")

    def bind_wheel(self, widget=None):
        """Bind the wheel over the body and everything inside it."""
        widget = self.body if widget is None else widget
        if not isinstance(widget, self._SELF_SCROLLING):
            self._bind_one(widget)
        for child in widget.winfo_children():
            self.bind_wheel(child)

    def _on_wheel(self, event):
        """Scroll the panel, and stop there.

        'break' is returned even when there is nothing to scroll: a ttk
        Spinbox has a wheel binding of its own that CHANGES ITS VALUE, and
        silently editing the battle round because the pointer happened to
        be over that box would be a worse bug than a wheel that does
        nothing."""
        lo, hi = self.canvas.yview()
        if float(lo) > 0.0 or float(hi) < 1.0:
            self.canvas.yview_scroll(wheel_units(event) * self.WHEEL_LINES,
                                     "units")
        return "break"


def multi_select_hint(parent, extra=""):
    """Small grey label reminding that a list accepts multiple selections
    (Ctrl+click, Cmd+click on macOS). Returns the Label WITHOUT geometry
    management, so the caller pack()s or grid()s it where it fits; 'extra'
    appends a dialog-specific note."""
    text = MULTI_SELECT_HINT + (f" - {extra}" if extra else "")
    return ttk.Label(parent, text=text, foreground=HINT_COLOR)


def save_text(parent, body, title="Export", defaultextension=".csv",
              filetypes=None, initialfile=None):
    """Ask for a file name and write 'body' to it. Returns the path, or
    None when the dialog was cancelled or the write failed (the error is
    reported to the user, never swallowed).

    'body' may be a callable taking the chosen path, for exports whose
    FORMAT follows the extension the user typed (a cheat sheet saved as
    .txt is not the same bytes as one saved as .html).

    One place for every export in the three programs: the file dialog,
    the encoding and the error box were being written out again at each
    call site, and only some of them caught OSError."""
    path = filedialog.asksaveasfilename(
        parent=parent, title=title, defaultextension=defaultextension,
        initialfile=initialfile,
        filetypes=filetypes or [("All files", "*.*")])
    if not path:
        return None
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body(path) if callable(body) else body)
    except OSError as exc:
        messagebox.showerror(title, str(exc), parent=parent)
        return None
    return path


def wrap_lines(text, font, pixels, indent="      "):
    """Word-wrap 'text' to 'pixels' using 'font' metrics -> list of lines,
    continuation lines prefixed with 'indent' so a wrapped row still reads
    as one entry. A single word longer than the width is left whole (the
    horizontal scrollbar takes care of it) rather than cut mid-word."""
    text = str(text)
    if pixels <= 0 or font.measure(text) <= pixels:
        return [text]
    lines, cur = [], ""
    for word in text.split(" "):
        cand = f"{cur} {word}" if cur else word
        if cur and font.measure(cand) > pixels:
            lines.append(cur)
            cur = indent + word
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return lines


class WrappedList:
    """A Listbox whose long rows WRAP instead of running past the window.

    Tk's Listbox has no word wrap: one record is one line, and anything
    wider than the window is simply not readable. This wrapper renders a
    record over as many indented lines as needed and keeps the mapping both
    ways, so callers keep speaking in RECORD indices: selection() and
    active() return indices into the records passed to fill(), and clicking
    any line of a record selects all of its lines.

    Records need a '.display' string and may carry a '.color'.
    Re-wraps by itself when the widget is resized.
    """

    INDENT = "      "

    def __init__(self, parent, **listbox_kwargs):
        # no horizontal scrollbar here: wrapping is what replaces it
        self.frame, self.listbox = scrollable_listbox(
            parent, xscroll=False, **listbox_kwargs)
        self._records = []
        self._line_of = []        # listbox line -> record index
        self._lines_of = []       # record index -> [listbox lines]
        self._font = tkfont.Font(font=self.listbox.cget("font"))
        self._width = 0           # width the current wrap was computed for
        self._syncing = False     # guards the selection-extension re-entry
        self.listbox.bind("<Configure>", self._on_configure, add="+")
        self.listbox.bind("<<ListboxSelect>>", self._extend_selection, add="+")

    # ---------- public API (record indices) ----------

    def fill(self, records):
        """Show 'records', replacing whatever was there."""
        self._records = list(records)
        self._render()

    def clear(self):
        self.fill([])

    def size(self):
        """Number of RECORDS (not of listbox lines)."""
        return len(self._records)

    def selection(self):
        """Indices of the selected records, in order, without duplicates."""
        out = []
        for line in self.listbox.curselection():
            i = self._line_of[line] if line < len(self._line_of) else None
            if i is not None and i not in out:
                out.append(i)
        return out

    def active(self):
        """Index of the record holding the last-clicked line, or None."""
        line = self.listbox.index(tk.ACTIVE)
        if 0 <= line < len(self._line_of):
            return self._line_of[line]
        return None

    def bind_select(self, callback):
        """Run 'callback' after a selection change. Bound with add='+' so it
        runs AFTER the internal handler that extends the selection to whole
        records - the callback therefore sees the completed selection."""
        self.listbox.bind("<<ListboxSelect>>", callback, add="+")

    # ---------- rendering ----------

    def _wrap_width(self):
        """Pixels available for text inside the listbox (0 before mapping,
        which means 'do not wrap yet')."""
        w = self.listbox.winfo_width()
        return max(0, w - 8) if w > 1 else 0

    def _render(self):
        """(Re)build the listbox lines from the records."""
        self._width = self._wrap_width()
        self.listbox.delete(0, tk.END)
        self._line_of, self._lines_of = [], []
        for i, rec in enumerate(self._records):
            mine = []
            for line in wrap_lines(getattr(rec, "display", str(rec)),
                                   self._font, self._width, self.INDENT):
                idx = self.listbox.size()
                self.listbox.insert(tk.END, line)
                colour = getattr(rec, "color", None)
                if colour:
                    self.listbox.itemconfig(idx, foreground=colour)
                self._line_of.append(i)
                mine.append(idx)
            self._lines_of.append(mine)

    def _on_configure(self, _event=None):
        """Re-wrap after a resize, keeping the current selection. Ignores
        small changes so typing/scrolling does not rebuild the list."""
        if abs(self._wrap_width() - self._width) < 8 or not self._records:
            return
        keep = self.selection()
        self._render()
        self._syncing = True
        try:
            for i in keep:
                for line in self._lines_of[i]:
                    self.listbox.selection_set(line)
        finally:
            self._syncing = False

    def _extend_selection(self, _event=None):
        """Grow the raw line selection to whole records, so a record is
        never half-selected when only one of its lines was clicked."""
        if self._syncing:
            return
        self._syncing = True
        try:
            for i in self.selection():
                for line in self._lines_of[i]:
                    self.listbox.selection_set(line)
        finally:
            self._syncing = False
