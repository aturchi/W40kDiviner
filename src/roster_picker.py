"""Roster file picker: a file chooser whose list TOGGLES on click.

Drop-in replacement for ``filedialog.askopenfilenames()`` at the three
places a roster is loaded (analyzer, game assistant, profile editor).
The native dialog could not be changed - see roster_picker_core - so the
window is ours: a Listbox in Tk's ``multiple`` mode, where one click
picks an entry and the next click drops it, with no modifier key. The
same mode the army list of army_load_dialog already uses.

Two panes. The LEFT one lists the current folder; the RIGHT one is the
basket, the files that will actually be loaded. They are not the same
thing: the basket keeps entries from folders you have since walked away
from, so a selection can be assembled across several folders - something
the native dialog cannot do at all. Ticking and unticking on the left
adds to and removes from the basket; the basket has its own Remove and
Clear for the entries whose folder is no longer on screen.

The native dialog is still one button away ("System dialog"), and what
it returns is ADDED to the basket rather than replacing it: it is the way
in for the paths this window does not make easy (network locations, a
name typed by hand, the platform's "recent places").

The basket lists FILE names, not army names: reading the armies out of a
5 MB roster on every click would stall the window, and the army names are
shown by the very next screen (the load/join dialog) anyway.
"""

import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import roster_picker_core as core
import ui_utils as ui
from ui_utils import scrollable_listbox, toggle_select_hint


class RosterPicker(tk.Toplevel):
    """Modal roster file chooser. ``self.result`` is the tuple of chosen
    paths, empty when the window was cancelled."""

    DIR_COLOR = "#1a4f8a"

    def __init__(self, parent, title="Load roster JSON", initialdir=None,
                 exts=core.DEFAULT_EXTS):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.geometry("780x470")
        self.result = ()
        self.state = core.RosterPickerState(initialdir, exts)
        self._rows = []              # display rows of the file list
        self._build()
        self._refresh_files()
        self._refresh_basket()
        self.bind("<Escape>", lambda _e: self.destroy())
        ui.modal_grab(self)

    # ---------- construction ----------

    def _build(self):
        self.columnconfigure(0, weight=3)
        self.columnconfigure(1, weight=2)
        self.rowconfigure(2, weight=1)

        top = ttk.Frame(self)
        top.grid(row=0, column=0, columnspan=2, sticky="ew", padx=6,
                 pady=(6, 2))
        top.columnconfigure(1, weight=1)
        ttk.Label(top, text="Folder:").grid(row=0, column=0, sticky="w")
        self.folder_var = tk.StringVar(value=self.state.folder)
        ttk.Entry(top, textvariable=self.folder_var,
                  state="readonly").grid(row=0, column=1, sticky="ew", padx=4)
        self.up_btn = ui.tip(ttk.Button(top, text="Up", width=4,
                                        command=self.cmd_up),
                             "Go to the folder above this one")
        self.up_btn.grid(row=0, column=2)
        self.browse_btn = ui.tip(
            ttk.Button(top, text="Browse\u2026", command=self.cmd_browse),
            "Jump straight to another folder")
        self.browse_btn.grid(row=0, column=3, padx=4)

        flt = ttk.Frame(self)
        flt.grid(row=1, column=0, columnspan=2, sticky="ew", padx=6)
        ttk.Label(flt, text="Filter:").pack(side=tk.LEFT)
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_a: self._on_filter())
        ttk.Entry(flt, textvariable=self.filter_var,
                  width=24).pack(side=tk.LEFT, padx=4)
        ttk.Label(flt, text="file names only - folders stay visible",
                  foreground=ui.HINT_COLOR).pack(side=tk.LEFT)

        left = ttk.LabelFrame(self, text="Files in this folder")
        left.grid(row=2, column=0, sticky="nsew", padx=(6, 3), pady=4)
        frame, self.files_lb = scrollable_listbox(
            left, height=14, exportselection=False, selectmode=tk.MULTIPLE)
        frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        # exportselection=False on BOTH lists: with the X selection left
        # on, picking in one Listbox silently clears the other.
        self.files_lb.bind("<<ListboxSelect>>", self._on_select, add="+")
        self.files_lb.bind("<Double-Button-1>", self._on_double, add="+")

        right = ttk.LabelFrame(self, text="Selected for loading")
        right.grid(row=2, column=1, sticky="nsew", padx=(3, 6), pady=4)
        frame2, self.basket_lb = scrollable_listbox(
            right, height=14, exportselection=False, selectmode=tk.MULTIPLE)
        frame2.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        row = ttk.Frame(right)
        row.pack(anchor=tk.W, padx=4, pady=(0, 4))
        self.remove_btn = ui.tip(
            ttk.Button(row, text="Remove", command=self.cmd_remove),
            "Take the selected entries out of the list on the right - the "
            "way to drop a file chosen in a folder you have left")
        self.remove_btn.pack(side=tk.LEFT)
        self.clear_btn = ui.tip(
            ttk.Button(row, text="Clear", command=self.cmd_clear),
            "Empty the list of files to load")
        self.clear_btn.pack(side=tk.LEFT, padx=6)

        toggle_select_hint(
            self, "double-click a folder to open it").grid(
            row=3, column=0, sticky="w", padx=8)
        self.count_lbl = ttk.Label(self, text="", foreground=ui.HINT_COLOR)
        self.count_lbl.grid(row=3, column=1, sticky="w", padx=8)

        bar = ttk.Frame(self)
        bar.grid(row=4, column=0, columnspan=2, sticky="e", padx=6, pady=6)
        self.open_btn = ui.tip(
            ttk.Button(bar, text="Open", command=self.cmd_open),
            "Load every file listed on the right, in that order")
        self.open_btn.pack(side=tk.LEFT, padx=4)
        self.system_btn = ui.tip(
            ttk.Button(bar, text="System dialog\u2026",
                       command=self.cmd_system),
            "Open the platform's own file dialog and ADD what it returns: "
            "for network places, recent files, or a name typed by hand")
        self.system_btn.pack(side=tk.LEFT, padx=4)
        ttk.Button(bar, text="Cancel",
                   command=self.destroy).pack(side=tk.LEFT, padx=4)

    # ---------- refresh ----------

    def _refresh_files(self):
        """Rebuild the folder list and tick the rows already in the basket
        (which is what makes walking back into a folder show what was
        chosen there before)."""
        self._rows = self.state.rows()
        chosen = set(self.state.in_folder())
        self.files_lb.delete(0, tk.END)
        for i, (kind, name, label) in enumerate(self._rows):
            self.files_lb.insert(tk.END, label)
            if kind == "dir":
                self.files_lb.itemconfig(i, foreground=self.DIR_COLOR)
            elif name in chosen:
                self.files_lb.selection_set(i)
        self.folder_var.set(self.state.folder)

    def _refresh_basket(self):
        self.basket_lb.delete(0, tk.END)
        for text in self.state.labels():
            self.basket_lb.insert(tk.END, text)
        self.count_lbl.config(text=self.state.summary())

    # ---------- events ----------

    def _on_filter(self):
        self.state.filter = self.filter_var.get()
        self._refresh_files()

    def _on_select(self, _event=None):
        """Sync the basket from the ticked rows of THIS folder.

        A directory row is untickable: it is cleared again straight away,
        so a stray click on one cannot end up in the basket.

        No re-entry guard: Tk raises <<ListboxSelect>> from the Listbox's
        own class bindings, i.e. from a real click, and not from the
        selection_set/selection_clear calls made here and in
        _refresh_files.
        """
        names, stray = [], []
        for i in self.files_lb.curselection():
            if i >= len(self._rows):
                continue
            kind, name, _label = self._rows[i]
            if kind == "file":
                names.append(name)
            else:
                stray.append(i)
        for i in stray:
            self.files_lb.selection_clear(i)
        self.state.set_folder_selection(names)
        self._refresh_basket()

    def _on_double(self, event):
        """A folder opens; a file loads. The two clicks of the double have
        already toggled that file on and off again, so it is put back into
        the basket explicitly - otherwise the gesture would open without
        the very file it was aimed at."""
        i = self.files_lb.nearest(event.y)
        if not 0 <= i < len(self._rows):
            return None
        kind, name, _label = self._rows[i]
        if kind == "dir":
            self._enter(name)
        else:
            self.state.add([os.path.join(self.state.folder, name)])
            self.cmd_open()
        return "break"

    # ---------- commands ----------

    def _enter(self, name):
        try:
            self.state.enter(name)
        except OSError as exc:
            messagebox.showerror("Folder", str(exc), parent=self)
            return
        self._refresh_files()

    def cmd_up(self):
        self._enter(core.PARENT)

    def cmd_browse(self):
        """Jump to any folder through the platform's folder chooser."""
        path = filedialog.askdirectory(parent=self, title="Choose a folder",
                                       initialdir=self.state.folder)
        if not path:
            return
        try:
            self.state.set_folder(path)
        except OSError as exc:
            messagebox.showerror("Folder", str(exc), parent=self)
            return
        self._refresh_files()

    def cmd_remove(self):
        """Drop the selected basket entries. Works on entries from any
        folder, which is why the basket needs a Remove of its own: an
        entry chosen three folders ago has no row to un-tick."""
        paths = self.state.basket()
        gone = [paths[i] for i in self.basket_lb.curselection()
                if i < len(paths)]
        if not gone:
            messagebox.showinfo("Remove", "Select the entries to remove.",
                                parent=self)
            return
        self.state.remove(gone)
        self._refresh_files()
        self._refresh_basket()

    def cmd_clear(self):
        if self.state.clear():
            self._refresh_files()
            self._refresh_basket()

    def cmd_system(self):
        """The platform's own file dialog, as an ADDITION to the basket.
        It is the way in for what this window does not make easy: network
        locations, a name typed by hand, the platform's recent places."""
        paths = filedialog.askopenfilenames(
            parent=self, title="Add roster files",
            initialdir=self.state.folder,
            filetypes=[("JSON", "*.json"), ("All files", "*.*")])
        if not paths:
            return
        self.state.add(paths)
        self._refresh_files()
        self._refresh_basket()

    def cmd_open(self):
        if not self.state.basket():
            messagebox.showinfo("Open", "Select at least one file.",
                                parent=self)
            return
        core.remember(self.state.folder)
        self.result = self.state.basket()
        self.destroy()


def ask_roster_files(parent, title="Load roster JSON", initialdir=None,
                     exts=core.DEFAULT_EXTS):
    """Ask for roster files -> tuple of paths, empty when cancelled.

    Same contract as ``filedialog.askopenfilenames()`` so the call sites
    keep their ``if not paths: return``."""
    dlg = RosterPicker(parent, title=title, initialdir=initialdir, exts=exts)
    parent.wait_window(dlg)
    return dlg.result
