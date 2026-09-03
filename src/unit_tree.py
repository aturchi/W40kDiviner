"""The analyzer's unit tree: one row per unit, expandable.

Same gesture as the game assistant's table - select a row, mask it - so
there is one mental model for "switch this off" instead of two. What a
row means and what masking it does lives in :mod:`unit_mask`, which has
no widgets and is tested headless; this file renders the plan and turns
clicks into calls.

Two rows carry state of their own: a WEAPON row (masked = count 0, and
its count is editable in place) and an ABILITY row (masked = 'enabled'
False). A MODEL row and a UNIT row are bulk gestures over the weapons
below them - "this sergeant does not shoot" is one click, not six - and
carry no state: they READ as masked when every weapon under them is.
Selecting a parent and one of its children together is not a
contradiction to resolve, it is a redundancy: the parent acts and the
child is skipped, so the gesture cannot half-undo itself.

Every row still says how many of its rows are switched off, because an
ability disabled three analyses ago must not be invisible.

The units of two panels can share their weapon and ability objects when
the same plain unit is picked in both (e.g. the same army loaded on both
sides), so after any change the caller is handed on_change() and is
expected to refresh the OTHER trees too. A [JOINED] entry does NOT share
with anything else, plain row or other entry: it is built from its own
independent copies (see Unit._attach), because a unit is never removed
from the pool when it joins and the same bodyguard or leader can end up
in several entries at once.
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
                tags=self._unit_tags(i, plan))
            for m in plan["models"]:
                mid = self.tree.insert(
                    uid, tk.END, iid=tree_ids.model_iid(i, m["mi"]),
                    text=m["label"],
                    values=(unit_mask.off_count_label(m["off"]),),
                    tags=self._model_tags(m))
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
                mid = tree_ids.model_iid(i, m["mi"])
                if self.tree.exists(mid):
                    self.tree.item(
                        mid, values=(unit_mask.off_count_label(m["off"]),),
                        tags=self._model_tags(m))
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
        right now, so it comes first; then "everything below is off",
        which is a stronger statement than "something is"."""
        if i < len(self._incompat) and self._incompat[i]:
            return (INCOMPAT_TAG,)
        if plan.get("masked"):
            return (MASK_TAG,)
        return (OFF_TAG,) if plan["off"] else ()

    @staticmethod
    def _model_tags(m):
        if m.get("masked"):
            return (MASK_TAG,)
        return (OFF_TAG,) if m.get("off") else ()

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
        """Mask/unmask every maskable selected row. Returns how many
        WEAPON and ABILITY rows moved, so the caller can say something
        when a selection contained none.

        A unit row acts on every weapon below it, a model row on its
        own; a child of a row already acted upon is skipped, or the
        parent's gesture would be half undone by the child's. Abilities
        are never touched by a parent row (see the module docstring), so
        an ability row is always its own gesture.
        """
        sel = list(self.tree.selection())
        moved, done_units, done_models = 0, set(), set()
        for iid in sel:                      # units first
            i, mi, wi, _ci = tree_ids.parse(iid)
            if i is None or mi is not None or wi is not None:
                continue
            unit = self.unit_at(i)
            if unit is None:
                continue
            moved += unit_mask.set_unit_masked(
                unit, not unit_mask.is_unit_masked(unit))
            done_units.add(i)
        for iid in sel:                      # then models
            i, mi, wi, _ci = tree_ids.parse(iid)
            if mi is None or wi is not None or i in done_units:
                continue
            unit = self.unit_at(i)
            if unit is None:
                continue
            moved += unit_mask.set_model_masked(
                unit, mi, not unit_mask.is_model_masked(unit, mi))
            done_models.add((i, mi))
        for iid in sel:                      # then the leaves
            i, mi, wi, _ci = tree_ids.parse(iid)
            if wi is not None:
                if i in done_units or (i, mi) in done_models:
                    continue
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
