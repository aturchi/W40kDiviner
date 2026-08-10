"""String-list edit dialog (keywords, leadership) for the profile
editor. Combines the configured vocabulary (keywords_config) with free
text, so every list property of the JSON is editable from the GUI.
self.result is the new list, or None on cancel."""

import tkinter as tk
from tkinter import ttk
from ui_utils import scrollable_listbox

from keywords_config import vocabulary_for  # noqa: F401
# (re-exported: profile_editor imports it from list_dialog)


class StringListDialog(tk.Toplevel):
    """Modal editor for a list of strings (keywords, leadership, support). Combines the configured vocabulary with free text; self.result is the new list or None on cancel."""
    def __init__(self, parent, title, current, vocabulary):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.grab_set()
        self.result = None
        self.items = list(current or [])

        lb_frame, self.listbox = scrollable_listbox(
            self, width=34, height=12, exportselection=False,
            selectmode=tk.EXTENDED)
        lb_frame.grid(row=0, column=0, columnspan=3, padx=6, pady=6,
                      sticky="nsew")
        self.rowconfigure(0, weight=1)
        for c in range(3):
            self.columnconfigure(c, weight=1)
        self.entry = ttk.Combobox(self, width=26,
                                  values=sorted(vocabulary or []))
        self.entry.grid(row=1, column=0, padx=6, sticky=tk.W)
        ttk.Button(self, text="Add",
                   command=self.cmd_add).grid(row=1, column=1)
        ttk.Button(self, text="Remove",
                   command=self.cmd_remove).grid(row=1, column=2, padx=4)
        ttk.Button(self, text="OK",
                   command=self.cmd_ok).grid(row=2, column=1, pady=8)
        ttk.Button(self, text="Cancel",
                   command=self.destroy).grid(row=2, column=2, pady=8)
        self.entry.bind("<Return>", lambda e: self.cmd_add())
        self._refresh()

    def _refresh(self):
        self.listbox.delete(0, tk.END)
        for it in self.items:
            self.listbox.insert(tk.END, it)

    def cmd_add(self):
        val = self.entry.get().strip()
        if val and val not in self.items:
            self.items.append(val)
            self._refresh()
        self.entry.set("")

    def cmd_remove(self):
        sel = self.listbox.curselection()
        for i in sorted(sel, reverse=True):
            del self.items[i]
        if sel:
            self._refresh()

    def cmd_ok(self):
        self.result = self.items
        self.destroy()
