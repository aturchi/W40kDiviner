"""Army load / join dialog (attack analyzer, multi-file load).

When several files (or a multi-army file) are loaded, this dialog lists the
available armies, lets the user JOIN a selected subset into a new named
army (via native_format.join_raw), and IMPORT the checked armies. Joined
armies that are not checked at import time are simply discarded.

Pure state in ArmyLoadState (testable without Tk); ArmyLoadDialog is the
thin GUI over it.
"""

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

import native_format as nf
from ui_utils import scrollable_listbox
from army_load_core import ArmyLoadState


class ArmyLoadDialog(tk.Toplevel):
    """Pick armies to import, optionally joining a selected subset first.
    self.result is the union native dict to load, or None on cancel."""

    def __init__(self, parent, single_army_dicts):
        super().__init__(parent)
        self.title("Load armies")
        self.transient(parent)
        self.grab_set()
        self.state = ArmyLoadState(single_army_dicts)
        self.result = None

        ttk.Label(self, text="Select armies to import. Select two or more "
                  "and press Join to merge them into a new army.").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=6, pady=4)
        lb_frame, self.listbox = scrollable_listbox(
            self, width=44, height=14, exportselection=False,
            selectmode=tk.EXTENDED)
        lb_frame.grid(row=1, column=0, columnspan=2, sticky="nsew",
                      padx=6, pady=4)
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        bar = ttk.Frame(self)
        bar.grid(row=2, column=0, columnspan=2, pady=4)
        ttk.Button(bar, text="Join selected",
                   command=self.cmd_join).pack(side=tk.LEFT, padx=4)
        ttk.Button(bar, text="Open",
                   command=self.cmd_open).pack(side=tk.LEFT, padx=12)
        ttk.Button(bar, text="Cancel",
                   command=self.destroy).pack(side=tk.LEFT, padx=4)
        self._refresh()

    def _refresh(self):
        self.listbox.delete(0, tk.END)
        for name in self.state.names():
            self.listbox.insert(tk.END, name)

    def cmd_join(self):
        sel = self.listbox.curselection()
        if len(sel) < 2:
            messagebox.showinfo("Join", "Select two or more armies to join.",
                                parent=self)
            return
        default = "+".join(self.state.names()[i] for i in sel)
        name = simpledialog.askstring(
            "Joined army name", "Name for the joined army:",
            initialvalue=default, parent=self)
        if name is None:
            return
        try:
            self.state.join(sel, name)
        except ValueError as exc:
            messagebox.showerror("Join failed", str(exc), parent=self)
            return
        self._refresh()

    def cmd_open(self):
        sel = self.listbox.curselection()
        try:
            data = self.state.build(sel)
        except ValueError as exc:
            messagebox.showerror("Open failed", str(exc), parent=self)
            return
        if data is None:
            messagebox.showinfo("Open", "Select at least one army to import.",
                                parent=self)
            return
        self.result = data
        self.destroy()
