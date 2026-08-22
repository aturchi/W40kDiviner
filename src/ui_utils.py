"""Shared Tkinter UI helpers.

- scrollable_listbox(): a Listbox packed next to auto-hiding scrollbars
  (vertical always, horizontal on request) that appear only when the
  content overflows.
- attach_yscroll() / attach_xscroll(): the same auto-hiding scrollbars for
  an existing yview/xview widget.
- wrap_lines(): word-wrap a string to a pixel width using a font's metrics.
- WrappedList(): a Listbox whose long rows wrap onto indented continuation
  lines while callers keep addressing whole records.
- make_resizable(): give a Toplevel a single weighted grid cell so its
  content expands when the window is enlarged.
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


def make_resizable(toplevel, child, minsize=None):
    """Let a Toplevel's content grow with the window: 'child' is grid-placed
    to fill the single weighted cell (row 0, col 0). Call after creating the
    main content frame of a dialog. Optional minsize=(w, h)."""
    toplevel.rowconfigure(0, weight=1)
    toplevel.columnconfigure(0, weight=1)
    child.grid(row=0, column=0, sticky="nsew")
    if minsize:
        toplevel.minsize(*minsize)


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
