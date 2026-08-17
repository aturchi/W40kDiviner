"""Selective-merge dialog for the profile editor "Merge JSON" feature.

Opens on a WORKING COPY of the current army (``army1``) and a frozen
snapshot of the second file's army (``army2``); every accept/merge/delete
mutates only the working copy, the diff is recomputed live against the
snapshot, and the window stays open until the user commits with *Finish*
or discards with *Cancel*. On Finish the merged working copy is exposed in
``self.result`` (``None`` on Cancel), which the caller reads after
``wait_window`` - the same pattern as :class:`editor_widgets.PickerDialog`.

Three colour-coded boxes: box 1 is a plain scrollable listbox, boxes 2/3
and the inspector are :class:`ui_utils.WrappedList`, so their long lines
wrap inside the window instead of running past its edge.

* box 1 - every unit across both armies; select green/red rows to enable
  Merge/Delete, select a single blue (modified) row to populate...
* box 2 - its non-ability changes (stats, flags, keywords, whole
  model/weapon add/remove), and
* box 3 - its ability changes.

All diff/apply logic lives in :mod:`profile_diff`; this module is pure UI.
"""

import copy
import tkinter as tk
from tkinter import ttk

from ui_utils import scrollable_listbox, multi_select_hint, WrappedList
import profile_diff as pd


class MergeDialog(tk.Toplevel):
    """Modal three-box merge window. Result in ``self.result`` after close
    (the merged working army on Finish, ``None`` on Cancel)."""

    def __init__(self, master, army1, army2, name1="v1", name2="v2"):
        super().__init__(master)
        self.title(f"Merge JSON:  {name1}  \u2190  {name2}")
        self.geometry("1040x700")
        self.transient(master)
        self.army1 = army1           # WORKING copy - mutated by accepts
        self.army2 = army2           # frozen snapshot - read only
        self.result = None           # set to army1 on Finish
        self._rows = []              # current box-1 UnitRow list
        self._box2, self._box3 = [], []   # current Change lists
        self._sel_unit = None        # name of the unit shown in box 2/3
        self._work_unit = None       # working-copy dict of that unit
        self._build()
        self._reload_units()
        self.grab_set()

    # ---------- construction ----------

    def _build(self):
        root = ttk.Frame(self, padding=6)
        root.pack(fill=tk.BOTH, expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=2)       # box-1 area
        root.rowconfigure(4, weight=3)       # box-2/3 area
        root.rowconfigure(5, weight=2)       # inspector (box-3 detail)

        # Colour legend (also carries the text prefix, so it reads without
        # relying on colour).
        legend = ttk.Frame(root)
        legend.grid(row=0, column=0, sticky="w", pady=(0, 4))
        for tag, text in [("identical", "identical"), ("added", "new (merge)"),
                          ("removed", "removed (delete)"),
                          ("changed", "modified")]:
            tk.Label(legend, text=pd.PREFIX[tag] + text,
                     fg=pd.COLORS[tag]).pack(side=tk.LEFT, padx=6)
        # All three boxes are multi-select (Merge/Delete/Accept selected
        # act on the whole selection): one reminder next to the legend.
        multi_select_hint(legend).pack(side=tk.LEFT, padx=(18, 0))

        # Box 1: units of both armies.
        ttk.Label(root, text="Units").grid(row=1, column=0, sticky="w")
        b1 = ttk.Frame(root)
        b1.grid(row=2, column=0, sticky="nsew")
        b1.columnconfigure(0, weight=1)
        b1.rowconfigure(0, weight=1)
        ufr, self.units_lb = scrollable_listbox(
            b1, selectmode=tk.EXTENDED, exportselection=False)
        ufr.grid(row=0, column=0, sticky="nsew")
        self.units_lb.bind("<<ListboxSelect>>", self._on_units_select)
        ubtn = ttk.Frame(b1)
        ubtn.grid(row=0, column=1, sticky="n", padx=4)
        self.merge_btn = ttk.Button(ubtn, text="Merge selected",
                                    state=tk.DISABLED,
                                    command=self._merge_selected)
        self.merge_btn.pack(fill=tk.X, pady=2)
        self.delete_btn = ttk.Button(ubtn, text="Delete selected",
                                     state=tk.DISABLED,
                                     command=self._delete_selected)
        self.delete_btn.pack(fill=tk.X, pady=2)

        ttk.Separator(root).grid(row=3, column=0, sticky="ew", pady=6)

        # Box 2 (non-ability) + box 3 (abilities), side by side.
        det = ttk.Frame(root)
        det.grid(row=4, column=0, sticky="nsew")
        det.columnconfigure(0, weight=1)
        det.columnconfigure(1, weight=1)
        det.rowconfigure(0, weight=1)
        self.box2_lb = self._detail_column(
            det, 0, "Stats / flags / keywords",
            self._accept_box2_sel, self._accept_box2_all)
        self.box3_lb = self._detail_column(
            det, 1, "Abilities",
            self._accept_box3_sel, self._accept_box3_all)
        # Clicking a change updates the read-only inspector below, tracking
        # the LAST-clicked row in whichever detail box was touched last.
        self.box2_lb.bind_select(
            lambda e: self._show_inspector(self._box2, self.box2_lb))
        self.box3_lb.bind_select(
            lambda e: self._show_inspector(self._box3, self.box3_lb))

        # Inspector (box-3 detail): for a selected MODIFIED item - chiefly a
        # replaced ability - the field-level differences (read only; accept
        # stays whole-item in box 2/3). New/removed items have nothing to
        # inspect.
        insp = ttk.Frame(root)
        insp.grid(row=5, column=0, sticky="nsew")
        insp.columnconfigure(0, weight=1)
        insp.rowconfigure(1, weight=1)
        ttk.Label(insp, text="Differences of selected modified item"
                  ).grid(row=0, column=0, sticky="w")
        self.detail_lb = WrappedList(insp, exportselection=False)
        self.detail_lb.frame.grid(row=1, column=0, sticky="nsew")

        # Bottom bar: status + commit/discard.
        bottom = ttk.Frame(root)
        bottom.grid(row=6, column=0, sticky="ew", pady=(6, 0))
        bottom.columnconfigure(0, weight=1)
        self.status = ttk.Label(bottom, text="")
        self.status.grid(row=0, column=0, sticky="w")
        ttk.Button(bottom, text="Finish",
                   command=self._finish).grid(row=0, column=1, padx=4)
        ttk.Button(bottom, text="Cancel",
                   command=self._cancel).grid(row=0, column=2)
        self.protocol("WM_DELETE_WINDOW", self._cancel)

    def _detail_column(self, parent, col, title, on_sel, on_all):
        """Build one detail box (label + coloured multi-select WrappedList +
        Accept selected / Accept all). Returns the WrappedList."""
        frame = ttk.Frame(parent)
        frame.grid(row=0, column=col, sticky="nsew", padx=4)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        ttk.Label(frame, text=title).grid(row=0, column=0, sticky="w")
        lb = WrappedList(frame, selectmode=tk.EXTENDED,
                         exportselection=False)
        lb.frame.grid(row=1, column=0, sticky="nsew")
        btns = ttk.Frame(frame)
        btns.grid(row=2, column=0, sticky="w", pady=3)
        ttk.Button(btns, text="Accept selected",
                   command=on_sel).pack(side=tk.LEFT)
        ttk.Button(btns, text="Accept all",
                   command=on_all).pack(side=tk.LEFT, padx=4)
        return lb

    # ---------- rendering ----------

    @staticmethod
    def _fill(lb, records):
        """Populate the box-1 listbox with .display strings coloured by
        .color. Boxes 2/3 and the inspector use WrappedList.fill instead,
        which wraps long rows."""
        lb.delete(0, tk.END)
        for i, rec in enumerate(records):
            lb.insert(tk.END, rec.display)
            lb.itemconfig(i, foreground=rec.color)

    def _reload_units(self):
        """Recompute the top-level diff, refill box 1, keep the previously
        shown unit selected when it is still modified, and refresh the
        detail boxes. Called after every mutation."""
        self._rows = pd.diff_army(self.army1, self.army2)
        self._fill(self.units_lb, self._rows)
        if self._sel_unit is not None:
            for i, r in enumerate(self._rows):
                if r.name == self._sel_unit and r.status == "modified":
                    self.units_lb.selection_set(i)
                    break
        self._update_status()
        self._on_units_select()

    def _update_status(self):
        from collections import Counter
        c = Counter(r.status for r in self._rows)
        self.status.config(
            text=f"{c.get('identical', 0)} identical  |  "
                 f"{c.get('added', 0)} new  |  {c.get('removed', 0)} removed"
                 f"  |  {c.get('modified', 0)} modified")

    # ---------- box 1: units ----------

    def _on_units_select(self, _event=None):
        """Enable Merge/Delete by the selection's colours; show the detail
        of a single selected modified unit (else clear the detail boxes)."""
        sel = [self._rows[i] for i in self.units_lb.curselection()]
        self.merge_btn.config(
            state=tk.NORMAL if any(r.status == "added" for r in sel)
            else tk.DISABLED)
        self.delete_btn.config(
            state=tk.NORMAL if any(r.status == "removed" for r in sel)
            else tk.DISABLED)
        modified = [r for r in sel if r.status == "modified"]
        if len(modified) == 1:
            self._sel_unit = modified[0].name
            self._work_unit = modified[0].unit1     # ref into working army1
            self._box2, self._box3 = pd.diff_unit(modified[0].unit1,
                                                  modified[0].unit2)
            self.box2_lb.fill(self._box2)
            self.box3_lb.fill(self._box3)
            self.detail_lb.clear()             # inspector waits for a click
        else:
            self._clear_detail()

    def _clear_detail(self):
        self._sel_unit = self._work_unit = None
        self._box2, self._box3 = [], []
        self.box2_lb.clear()
        self.box3_lb.clear()
        self.detail_lb.clear()

    def _show_inspector(self, records, lb):
        """Fill the read-only inspector with the field-level differences of
        the last-clicked MODIFIED row: a replaced ability shows its internal
        diff (what changed inside), a changed scalar its single old->new
        line. New/removed rows have nothing to inspect - box left empty."""
        self.detail_lb.clear()
        if lb.size() == 0 or self._work_unit is None:
            return
        idx = lb.active()                     # record of the last-clicked row
        if idx is None or not 0 <= idx < len(records):
            return
        ch = records[idx]
        if ch.op == "replaced":
            old = pd.current_item(self._work_unit, ch)
            self.detail_lb.fill(pd.diff_detail(old or {}, ch.payload or {}))
        elif ch.op == "changed":
            self.detail_lb.fill([ch])

    def _merge_selected(self):
        """Add every selected green (v2-only) unit into the working army."""
        for r in [self._rows[i] for i in self.units_lb.curselection()]:
            if r.status == "added":
                pd.merge_unit(self.army1, r.unit2)
        self._reload_units()

    def _delete_selected(self):
        """Remove every selected red (v1-only) unit from the working army."""
        for r in [self._rows[i] for i in self.units_lb.curselection()]:
            if r.status == "removed":
                pd.delete_unit(self.army1, r.name)
        self._reload_units()

    # ---------- box 2 / box 3: accept changes ----------

    def _accept(self, changes):
        """Apply a set of Change records to the working unit, then re-diff.
        Order-independent: locators are semantic (see profile_diff)."""
        if not changes or self._work_unit is None:
            return
        for ch in changes:
            pd.apply_change(self._work_unit, ch)
        self._reload_units()

    def _accept_box2_sel(self):
        self._accept([self._box2[i] for i in self.box2_lb.selection()])

    def _accept_box2_all(self):
        self._accept(list(self._box2))

    def _accept_box3_sel(self):
        self._accept([self._box3[i] for i in self.box3_lb.selection()])

    def _accept_box3_all(self):
        self._accept(list(self._box3))

    # ---------- commit / discard ----------

    def _finish(self):
        self.result = self.army1
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()
