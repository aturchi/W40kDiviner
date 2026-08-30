"""Army load / join / save dialog (shared by the analyzer and the editor).

When several armies are available - from several files, or one
multi-army file - this dialog lists them and offers the two ways of
combining them, plus the rename they both need:

- **Join into one** merges the ticked armies into a new named army.
  The originals leave the list and the result takes their place, so
  joins can be chained.
- **Save selected** writes the ticked armies to one file, each keeping
  its own identity. That is an action and not a list entry on purpose:
  the operation is flat and associative, so a file of files is the same
  file as the flat one, and what a list entry would need a name for is
  the path the save dialog already asks for. Save leaves the window
  open, so a session can write several files.
- **Rename** is what makes both joins usable: they reject duplicate army
  names, and real rosters collide.

The window stays open across saves and closes on Open/Import, whose
result is the union native dict (``self.result``; None on cancel).

Pure state in ArmyLoadState (testable without Tk); ArmyLoadDialog is the
thin GUI over it. The two name prompts go through _ask_name/_ask_path so
a test can drive the buttons without a modal.
"""

import os
import re
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog

import ui_utils as ui
from ui_utils import scrollable_listbox, toggle_select_hint
from army_load_core import ArmyLoadState

WARN_COLOR = ui.WARN_COLOR


class ArmyLoadDialog(tk.Toplevel):
    """Pick armies to import, optionally joining, renaming and saving them
    first. self.result is the union native dict to load, or None on
    cancel."""

    def __init__(self, parent, single_army_dicts, allow_save=False,
                 title="Load armies", open_label="Open"):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.grab_set()
        self.state = ArmyLoadState(single_army_dicts)
        self.result = None

        head = ("Select armies to import. Join merges the selected armies "
                "into one new army.")
        if allow_save:
            head = ("Select armies to work with. Join merges them into one "
                    "new army; Save writes the selected armies to a file "
                    "(two or more make a multi-army file).")
        ttk.Label(self, text=head, wraplength=430).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=6, pady=4)
        # MULTIPLE, not EXTENDED: a plain click toggles one army and
        # leaves the rest alone, so a subset is picked with the mouse
        # and no modifier key. The list is short and never wants a
        # range, which is the only thing EXTENDED offered here.
        lb_frame, self.listbox = scrollable_listbox(
            self, width=44, height=14, exportselection=False,
            selectmode=tk.MULTIPLE)
        lb_frame.grid(row=1, column=0, columnspan=2, sticky="nsew",
                      padx=6, pady=4)
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)
        self.listbox.bind("<<ListboxSelect>>", lambda _e: self._refresh_warning(),
                          add="+")

        toggle_select_hint(self).grid(row=2, column=0, columnspan=2,
                                      sticky="w", padx=6)
        # Says so as soon as a colliding pair is ticked, rather than only
        # when a join or a save is refused.
        self.warn = ttk.Label(self, text="", foreground=WARN_COLOR,
                              wraplength=430)
        self.warn.grid(row=3, column=0, columnspan=2, sticky="w", padx=6)

        bar = ttk.Frame(self)
        bar.grid(row=4, column=0, columnspan=2, pady=4)
        self.join_btn = ui.tip(
            ttk.Button(bar, text="Join into one\u2026",
                       command=self.cmd_join),
            "Merge the selected armies into ONE new army under a name you "
            "choose; units whose names collide keep their origin as a "
            "suffix. The originals leave the list, so joins can be chained")
        self.join_btn.pack(side=tk.LEFT, padx=4)
        self.rename_btn = ui.tip(
            ttk.Button(bar, text="Rename\u2026", command=self.cmd_rename),
            "Rename the selected army. Two armies sharing a name can "
            "neither be joined nor saved together")
        self.rename_btn.pack(side=tk.LEFT, padx=4)
        self.save_btn = None
        if allow_save:
            self.save_btn = ui.tip(
                ttk.Button(bar, text="Save selected\u2026",
                           command=self.cmd_save),
                "Write the selected armies to one file - two or more make "
                "a multi-army file. The window stays open, so several "
                "files can be written in a row")
            self.save_btn.pack(side=tk.LEFT, padx=4)
        self.open_btn = ui.tip(
            ttk.Button(bar, text=open_label, command=self.cmd_open),
            "Take the selected armies into the program and close this "
            "window")
        self.open_btn.pack(side=tk.LEFT, padx=12)
        ttk.Button(bar, text="Cancel",
                   command=self.destroy).pack(side=tk.LEFT, padx=4)
        self._refresh()

    # ---------- display ----------

    def _refresh(self):
        self.listbox.delete(0, tk.END)
        for name in self.state.names():
            self.listbox.insert(tk.END, name)
        self._refresh_warning()

    def _refresh_warning(self):
        dup = self.state.conflicts(self.listbox.curselection())
        self.warn.config(
            text="" if not dup else
            "Two of the selected armies share a name ("
            + ", ".join(dup) + "): rename one before joining or saving.")

    # ---------- prompts (seams: overridden in tests) ----------

    def _ask_name(self, title, prompt, initial):
        return simpledialog.askstring(title, prompt, initialvalue=initial,
                                      parent=self)

    def _ask_path(self, initialfile):
        return filedialog.asksaveasfilename(
            parent=self, title="Save selected armies", defaultextension=".json",
            initialfile=initialfile,
            filetypes=[("JSON", "*.json"), ("All files", "*.*")])

    @staticmethod
    def _suggest_filename(names):
        """A file name for the Save dialog, derived from what is being
        written: the army's own name for one, 'joined' for several."""
        base = names[0] if len(names) == 1 else "joined"
        slug = re.sub(r"[^A-Za-z0-9]+", "-", base).strip("-").lower()
        return f"{slug or 'armies'}.json"

    # ---------- commands ----------

    def cmd_join(self):
        sel = self.listbox.curselection()
        if len(sel) < 2:
            messagebox.showinfo("Join", "Select two or more armies to join.",
                                parent=self)
            return
        default = "+".join(self.state.names()[i] for i in sel)
        name = self._ask_name("Joined army name",
                              "Name for the joined army:", default)
        if name is None:
            return
        try:
            self.state.join(sel, name)
        except ValueError as exc:
            messagebox.showerror("Join failed", str(exc), parent=self)
            return
        self._refresh()

    def cmd_rename(self):
        sel = self.listbox.curselection()
        if len(sel) != 1:
            messagebox.showinfo("Rename", "Select exactly one army to rename.",
                                parent=self)
            return
        index = sel[0]
        name = self._ask_name("Rename army", "New name for this army:",
                              self.state.names()[index])
        if name is None:
            return
        try:
            self.state.rename(index, name)
        except ValueError as exc:
            messagebox.showerror("Rename failed", str(exc), parent=self)
            return
        self._refresh()
        self.listbox.selection_set(index)
        self._refresh_warning()

    def cmd_save(self):
        """Write the selected armies to one file, leaving the window open
        so several files can be produced in one session."""
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showinfo("Save", "Select the armies to save.",
                                parent=self)
            return
        dup = self.state.conflicts(sel)
        if dup:
            messagebox.showerror(
                "Save failed",
                "Two of the selected armies share a name ("
                + ", ".join(dup) + "). Rename one first: a file whose "
                "armies share a name cannot be joined or split again.",
                parent=self)
            return
        names = [self.state.names()[i] for i in sel]
        path = self._ask_path(self._suggest_filename(names))
        if not path:
            return
        try:
            armies, units, stamped = self.state.save(sel, path)
        except (ValueError, OSError) as exc:
            messagebox.showerror("Save failed", str(exc), parent=self)
            return
        extra = (f"\n{stamped} ability id(s) re-stamped for uniqueness."
                 if stamped else "")
        messagebox.showinfo(
            "Saved", f"{os.path.basename(path)}: {armies} army(ies), "
                     f"{units} units.{extra}", parent=self)

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
