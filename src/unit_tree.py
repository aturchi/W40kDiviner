"""The analyzer's unit tree: one row per unit, expandable.

Same gesture as the game assistant's table - select a row, mask it - so
there is one mental model for "switch this off" instead of two. What a
row means and what masking it does lives in :mod:`unit_mask`, which has
no widgets and is tested headless; this file renders the plan and turns
clicks into calls.

Two rows carry state: a WEAPON row (masked = count 0, and its count is
editable in place) and an ABILITY row (masked = 'enabled' False). Unit
and model rows are structure only. A collapsed unit row still says how
many of its rows are switched off, because an ability disabled three
analyses ago must not be invisible.

The units of two panels can share their weapon and ability objects (a
joined unit is built on the same objects as the plain one), so after any
change the caller is handed on_change() and is expected to refresh the
OTHER trees too.
"""

import tkinter as tk
from tkinter import ttk

import tree_ids
import unit_mask

MASK_TAG = "masked"
MASK_COLOR = "#999999"
INCOMPAT_TAG = "incompat"
INCOMPAT_COLOR = "#aaaaaa"
OFF_TAG = "hasoff"                  # unit row with something masked
OFF_COLOR = "#7a4a00"
SEP_TAG = "sep"


class UnitTree(ttk.Frame):
    """Treeview of the units of one analyzer panel."""

    def __init__(self, parent, multi=False, height=14, on_select=None,
                 on_change=None):
        super().__init__(parent)
        self.on_select = on_select
        self.on_change = on_change
        self.rows = []                    # [(label, Unit)]
        self._incompat = []               # per top-level row
        self._pre_click = None            # click-toggle bookkeeping

        self.tree = ttk.Treeview(
            self, columns=("value",), show="tree headings", height=height,
            selectmode=(tk.EXTENDED if multi else tk.BROWSE))
        self.tree.heading("#0", text="Unit / model / weapon / ability")
        self.tree.heading("value", text="Count")
        self.tree.column("#0", width=280)
        self.tree.column("value", width=64, anchor=tk.E, stretch=False)
        self.tree.tag_configure(MASK_TAG, foreground=MASK_COLOR)
        self.tree.tag_configure(INCOMPAT_TAG, foreground=INCOMPAT_COLOR)
        self.tree.tag_configure(OFF_TAG, foreground=OFF_COLOR)
        self.tree.tag_configure(SEP_TAG, foreground="#bbbbbb")
        sb = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._selected())
        self.tree.bind("<Double-1>", self._edit_cell)
        self.tree.bind("<Button-1>", self._click_press, add="+")
        self.tree.bind("<ButtonRelease-1>", self._click_release, add="+")

    # ---------- contents ----------

    def set_units(self, rows):
        """rows = [(label, Unit)]. Rebuilds the tree; the masked state is
        read back from the objects, so nothing has to be carried over."""
        self.rows = list(rows)
        self._incompat = [False] * len(self.rows)
        self.tree.delete(*self.tree.get_children())
        for i, (label, unit) in enumerate(self.rows):
            plan = unit_mask.unit_plan(unit)
            uid = self.tree.insert(
                "", tk.END, iid=tree_ids.unit_iid(i), text=label, open=False,
                values=(unit_mask.off_label(plan),),
                tags=((OFF_TAG,) if plan["off"] else ()))
            for m in plan["models"]:
                mid = self.tree.insert(
                    uid, tk.END, iid=tree_ids.model_iid(i, m["mi"]),
                    text=m["label"])
                for w in m["weapons"]:
                    self.tree.insert(
                        mid, tk.END,
                        iid=tree_ids.weapon_iid(i, m["mi"], w["wi"]),
                        text=w["label"], values=(w["count"],),
                        tags=((MASK_TAG,) if w["masked"] else ()))
            if plan["abilities"]:
                self.tree.insert(uid, tk.END,
                                 iid=tree_ids.abilities_sep_iid(i),
                                 text="\u2500" * 8 + " abilities "
                                      + "\u2500" * 8, tags=(SEP_TAG,))
                for a in plan["abilities"]:
                    self.tree.insert(
                        uid, tk.END, iid=tree_ids.ability_iid(i, a["key"]),
                        text=a["label"],
                        tags=((MASK_TAG,) if a["masked"] else ()))

    def refresh_states(self):
        """Re-read the masked state and the counts from the objects,
        without rebuilding: the open rows stay open and the selection
        stays put. Cheap enough to call on every tree after any change."""
        for i, (_label, unit) in enumerate(self.rows):
            plan = unit_mask.unit_plan(unit)
            uid = tree_ids.unit_iid(i)
            if not self.tree.exists(uid):
                continue
            self.tree.item(uid, values=(unit_mask.off_label(plan),),
                           tags=self._unit_tags(i, plan))
            for m in plan["models"]:
                for w in m["weapons"]:
                    iid = tree_ids.weapon_iid(i, m["mi"], w["wi"])
                    if self.tree.exists(iid):
                        self.tree.item(
                            iid, values=(w["count"],),
                            tags=((MASK_TAG,) if w["masked"] else ()))
            for a in plan["abilities"]:
                iid = tree_ids.ability_iid(i, a["key"])
                if self.tree.exists(iid):
                    self.tree.item(
                        iid, tags=((MASK_TAG,) if a["masked"] else ()))

    def _unit_tags(self, i, plan):
        """ONE tag per unit row: with two, which colour wins would be up
        to the theme. Incompatibility is about the join being attempted
        right now, so it comes first."""
        if i < len(self._incompat) and self._incompat[i]:
            return (INCOMPAT_TAG,)
        return (OFF_TAG,) if plan["off"] else ()

    def set_incompatible(self, flags):
        """Grey the top-level rows the selected helper cannot join."""
        self._incompat = [bool(f) for f in flags]
        for i, (_label, unit) in enumerate(self.rows):
            uid = tree_ids.unit_iid(i)
            if self.tree.exists(uid):
                self.tree.item(uid, tags=self._unit_tags(
                    i, unit_mask.unit_plan(unit)))

    # ---------- selection ----------

    def size(self) -> int:
        return len(self.rows)

    def unit_at(self, i):
        return self.rows[i][1] if 0 <= i < len(self.rows) else None

    def selected_indices(self) -> list:
        """Top-level indices of the selected rows, in tree order and
        without repetitions: selecting a weapon row selects its unit,
        exactly as in the game assistant."""
        out = []
        for iid in self.tree.selection():
            i = tree_ids.entry_index(iid)
            if i is not None and i not in out and i < len(self.rows):
                out.append(i)
        return sorted(out)

    def selected_units(self) -> list:
        return [self.rows[i][1] for i in self.selected_indices()]

    def _selected(self):
        if self.on_select:
            self.on_select()

    # Treeview keeps a clicked row selected forever: re-clicking an
    # already-selected row deselects it, as in the game assistant table.
    def _click_press(self, event):
        iid = self.tree.identify_row(event.y)
        self._pre_click = iid if iid in self.tree.selection() else None

    def _click_release(self, event):
        iid = self.tree.identify_row(event.y)
        if iid and iid == self._pre_click:
            self.tree.selection_remove(iid)

    # ---------- masking ----------

    def toggle_selected(self) -> int:
        """Mask/unmask every maskable selected row (weapons and
        abilities). Returns how many rows moved, so the caller can say
        something when a selection contained none."""
        moved = 0
        for iid in self.tree.selection():
            i, mi, wi, _ci = tree_ids.parse(iid)
            if wi is not None:
                w = unit_mask.weapon_at(self.unit_at(i), mi, wi)
                if w is not None:
                    moved += bool(unit_mask.set_weapon_masked(
                        w, not unit_mask.is_weapon_masked(w)))
                continue
            i, key = tree_ids.parse_ability(iid)
            if i is None:
                continue                  # unit, model or separator row
            ab = unit_mask.ability_at(self.unit_at(i), key)
            if ab is not None:
                moved += bool(unit_mask.set_ability_masked(
                    ab, not unit_mask.is_ability_masked(ab)))
        if moved:
            self._changed()
        return moved

    def _changed(self):
        self.refresh_states()
        if self.on_change:
            self.on_change()

    # ---------- editing a weapon count ----------

    def _edit_cell(self, event):
        """Double-click on the Count column of a weapon row edits it.
        0 is allowed and means the same as masking the row."""
        iid = self.tree.identify_row(event.y)
        if not iid or self.tree.identify_column(event.x) != "#1":
            return
        i, mi, wi, _ci = tree_ids.parse(iid)
        if wi is None:
            return
        weapon = unit_mask.weapon_at(self.unit_at(i), mi, wi)
        if weapon is None:
            return
        x, y, w, h = self.tree.bbox(iid, "#1")
        old = str(self.tree.set(iid, "value"))
        box = tk.Entry(self.tree, width=6)
        box.insert(0, old)
        box.place(x=x, y=y, width=w, height=h)
        box.focus_set()
        # Return commits and destroys the box, which then fires FocusOut:
        # the guard keeps the second call from touching a dead widget.
        done = {"yet": False}

        def commit(_e=None):
            if done["yet"]:
                return
            done["yet"] = True
            text = box.get().strip()
            box.destroy()
            try:
                n = max(0, int(text))
            except ValueError:
                return                    # not a number: keep the count
            if str(n) == old:
                return
            unit_mask.set_weapon_count(weapon, n)
            self._changed()
        box.bind("<Return>", commit)
        box.bind("<FocusOut>", commit)
