"""Shared Tkinter UI helpers.

- scrollable_listbox(): a Listbox packed next to a vertical scrollbar that
  auto-hides when everything fits and appears when the list overflows.
- attach_yscroll(): same auto-hiding scrollbar for an existing yview widget.
- make_resizable(): give a Toplevel a single weighted grid cell so its
  content expands when the window is enlarged.
- multi_select_hint(): the shared "Ctrl+click" reminder label used by every
  dialog holding a multi-selection list.

Kept dependency-free (tkinter only) so every GUI module can reuse it
instead of wiring scrollbars by hand.
"""

import sys
import tkinter as tk
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


def scrollable_listbox(parent, **listbox_kwargs):
    """Create a Listbox with an auto-hiding vertical scrollbar inside a new
    frame. Returns (frame, listbox); pack/grid the FRAME where the listbox
    would have gone, and use the listbox as usual. The scrollbar shows only
    when the list overflows its height."""
    frame = ttk.Frame(parent)
    lb = tk.Listbox(frame, **listbox_kwargs)
    attach_yscroll(lb, frame)
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
