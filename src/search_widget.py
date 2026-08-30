"""Shared Ctrl+F incremental search (all three GUIs).

attach_search(root, targets_fn) binds Ctrl+F on the whole window; the
dialog searches case-insensitively across the widgets returned by
targets_fn() (tk.Listbox and ttk.Treeview supported), cycling through
matches with Enter / "Next" (wrap-around) and closing with Esc.
Treeview matches are revealed (parents opened) and selected."""

import tkinter as tk
from tkinter import ttk

import ui_utils as ui


def _tree_items(tree):
    """All item iids of a Treeview, depth-first."""
    out = []

    def walk(parent):
        for iid in tree.get_children(parent):
            out.append(iid)
            walk(iid)
    walk("")
    return out


def _item_text(widget, key):
    if isinstance(widget, tk.Listbox):
        return widget.get(key)
    return " ".join([widget.item(key, "text")]
                    + [str(v) for v in widget.item(key, "values")])


def _reveal(widget, key):
    if isinstance(widget, tk.Listbox):
        widget.selection_clear(0, tk.END)
        widget.selection_set(key)
        widget.see(key)
    else:
        parent = widget.parent(key)
        while parent:
            widget.item(parent, open=True)
            parent = widget.parent(parent)
        widget.selection_set(key)
        widget.see(key)
    widget.event_generate("<<ListboxSelect>>"
                          if isinstance(widget, tk.Listbox)
                          else "<<TreeviewSelect>>")


class SearchDialog(tk.Toplevel):
    """Incremental find-in-list dialog: type to filter and jump to matching rows across the registered listboxes."""
    def __init__(self, parent, targets_fn):
        super().__init__(parent)
        self.title("Find")
        self.transient(parent)
        self.resizable(False, False)
        self.targets_fn = targets_fn
        self._pos = None              # (widget_index, item_index) of last hit
        self._last_query = ""
        ttk.Label(self, text="Find:").grid(row=0, column=0, padx=4, pady=6)
        self.entry = ttk.Entry(self, width=28)
        self.entry.grid(row=0, column=1, padx=2)
        self.entry.focus_set()
        ui.tip(ttk.Button(self, text="Next", command=self.cmd_next),
               "Jump to the next row matching the text (Enter does the "
               "same)").grid(row=0, column=2, padx=4)
        self.info = ttk.Label(self, text="")
        self.info.grid(row=1, column=0, columnspan=3, sticky=tk.W, padx=4)
        self.entry.bind("<Return>", lambda e: self.cmd_next())
        self.bind("<Escape>", lambda e: self.destroy())

    def cmd_next(self):
        query = self.entry.get().strip().lower()
        if not query:
            return
        if query != self._last_query:
            self._pos, self._last_query = None, query
        widgets = [w for w in self.targets_fn() if w.winfo_exists()]
        # flat (widget_index, key) sequence over every searchable row
        seq = []
        for wi, w in enumerate(widgets):
            keys = (range(w.size()) if isinstance(w, tk.Listbox)
                    else _tree_items(w))
            seq += [(wi, k) for k in keys]
        if not seq:
            self.info.config(text="Nothing to search")
            return
        start = 0
        if self._pos in seq:
            start = seq.index(self._pos) + 1
        order = seq[start:] + seq[:start]      # wrap-around
        for wi, key in order:
            if query in _item_text(widgets[wi], key).lower():
                _reveal(widgets[wi], key)
                self._pos = (wi, key)
                self.info.config(text="")
                return
        self._pos = None
        self.info.config(text=f"'{self.entry.get()}' not found")


def attach_search(root, targets_fn):
    """Bind Ctrl+F on 'root'; one dialog at a time (re-focused if open)."""
    holder = {"dlg": None}

    def open_search(_event=None):
        dlg = holder["dlg"]
        if dlg is not None and dlg.winfo_exists():
            dlg.lift()
            dlg.entry.focus_set()
        else:
            holder["dlg"] = SearchDialog(root, targets_fn)
        return "break"

    root.bind_all("<Control-f>", open_search)
    root.bind_all("<Control-F>", open_search)
