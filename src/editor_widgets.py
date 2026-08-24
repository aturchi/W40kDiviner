"""Reusable editor widgets.

PickerDialog: modal filterable list. Items are (label, payload) pairs;
special items (e.g. "<New empty unit>") can be pinned on top, exempt
from filtering. Rows are drawn in a one-column Treeview so a subset of
them can be rendered in bold ('bold' argument) to flag a suggested
choice without restricting the selection. The chosen payload ends up in
dialog.choice (None if cancelled). Payloads are returned as-is: callers
decide whether to clone them.
"""

import tkinter as tk
from tkinter import ttk

import ui_utils as ui

SUGGESTED_TAG = "suggested"


class PickerDialog(tk.Toplevel):
    """Modal, filterable list picker. Items are (label, payload) pairs; the chosen payload lands in self.choice (None if cancelled)."""
    def __init__(self, master, title, items, specials=(), bold=()):
        """items: [(label, payload)]; specials: [(label, payload)] pinned
        on top and always visible regardless of the filter text; bold:
        payloads (matched by IDENTITY, so unhashable dicts are fine) whose
        row is drawn in bold - a hint, never a restriction."""
        super().__init__(master)
        self.title(title)
        self.geometry("560x420")
        self.transient(master)
        self.choice = None
        self.specials = list(specials)
        self.items = list(items)
        self.bold = list(bold)
        self.filtered = []           # current (label, payload) shown

        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *a: self.refresh())
        entry = ttk.Entry(self, textvariable=self.filter_var)
        entry.pack(fill=tk.X, padx=6, pady=4)
        entry.focus_set()
        # The OK/Cancel row goes in FIRST, against the bottom: pack()
        # satisfies requested sizes in packing order, so an expanding
        # tree on a short window would leave it a few pixels tall and
        # its buttons captionless.
        row = ttk.Frame(self)
        row.pack(side=tk.BOTTOM, pady=4)
        ttk.Button(row, text="OK", command=self.cmd_ok).pack(side=tk.LEFT,
                                                             padx=4)
        ttk.Button(row, text="Cancel",
                   command=self.destroy).pack(side=tk.LEFT)

        frame = ttk.Frame(self)
        frame.pack(fill=tk.BOTH, expand=True, padx=6)
        self.tree = ttk.Treeview(frame, columns=("label",), show="",
                                 selectmode="browse")
        self.tree.column("label", anchor=tk.W, stretch=True)
        bar = ttk.Scrollbar(frame, orient=tk.VERTICAL,
                            command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar.set)
        bar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        # A NAMED font rather than a copy of TkDefaultFont: a copy has
        # to be kept alive on the instance (Tk destroys a font object
        # when it is collected, silently dropping the tag) AND it stops
        # following the font scale, because rescaling reconfigures the
        # named fonts and a copy is not one of them.
        self.tree.tag_configure(SUGGESTED_TAG, font=ui.bold_font())
        self.tree.bind("<Double-Button-1>", lambda e: self.cmd_ok())
        self.refresh()
        self.grab_set()

    def _is_bold(self, payload):
        """Identity test: payloads are often unhashable dicts."""
        return any(payload is b for b in self.bold)

    def refresh(self):
        text = self.filter_var.get().lower()
        self.filtered = self.specials + [
            (lab, p) for lab, p in self.items if text in lab.lower()]
        self.tree.delete(*self.tree.get_children())
        for i, (lab, p) in enumerate(self.filtered):
            self.tree.insert("", tk.END, iid=str(i), values=(lab,),
                             tags=(SUGGESTED_TAG,) if self._is_bold(p)
                             else ())

    def cmd_ok(self):
        sel = self.tree.selection()
        if sel:
            self.choice = self.filtered[int(sel[0])][1]
        self.destroy()
