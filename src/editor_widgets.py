"""Reusable editor widgets.

PickerDialog: modal filterable list. Items are (label, payload) pairs;
special items (e.g. "<New empty unit>") can be pinned on top, exempt
from filtering. The chosen payload ends up in dialog.choice (None if
cancelled). Payloads are returned as-is: callers decide whether to
clone them.
"""

import tkinter as tk
from tkinter import ttk
from ui_utils import scrollable_listbox


class PickerDialog(tk.Toplevel):
    """Modal, filterable list picker. Items are (label, payload) pairs; the chosen payload lands in self.choice (None if cancelled)."""
    def __init__(self, master, title, items, specials=()):
        """items: [(label, payload)]; specials: [(label, payload)] pinned
        on top and always visible regardless of the filter text."""
        super().__init__(master)
        self.title(title)
        self.geometry("560x420")
        self.transient(master)
        self.choice = None
        self.specials = list(specials)
        self.items = list(items)
        self.filtered = []           # current (label, payload) shown

        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *a: self.refresh())
        entry = ttk.Entry(self, textvariable=self.filter_var)
        entry.pack(fill=tk.X, padx=6, pady=4)
        entry.focus_set()
        lb_frame, self.listbox = scrollable_listbox(self)
        lb_frame.pack(fill=tk.BOTH, expand=True, padx=6)
        self.listbox.bind("<Double-Button-1>", lambda e: self.cmd_ok())
        row = ttk.Frame(self)
        row.pack(pady=4)
        ttk.Button(row, text="OK", command=self.cmd_ok).pack(side=tk.LEFT,
                                                             padx=4)
        ttk.Button(row, text="Cancel",
                   command=self.destroy).pack(side=tk.LEFT)
        self.refresh()
        self.grab_set()

    def refresh(self):
        text = self.filter_var.get().lower()
        self.filtered = self.specials + [
            (lab, p) for lab, p in self.items if text in lab.lower()]
        self.listbox.delete(0, tk.END)
        for lab, _p in self.filtered:
            self.listbox.insert(tk.END, lab)

    def cmd_ok(self):
        if self.listbox.curselection():
            self.choice = self.filtered[self.listbox.curselection()[0]][1]
        self.destroy()
