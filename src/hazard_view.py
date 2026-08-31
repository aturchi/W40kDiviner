"""The HAZARDOUS closing step, as a window.

Nothing is decided here: hazard_close works out who owes what and where
it lands, and this only draws it and asks whether to write it down. The
outcome is computed ONCE, when the window opens, and shown in full
before the player commits to it - the tests were rolled long ago, inside
the resolver, so there is nothing left to be surprised by and every
reason to show the whole result up front.

Skip is a real answer, not a way out of a modal. A player who has
already taken the wounds off by hand, or who is about to argue about the
rule with an opponent, presses Skip and the table is left alone; the
attack log still records what was owed either way, because a log that
only recorded the damage the player accepted would not be a record of
the attack.
"""

import tkinter as tk
from tkinter import ttk

import hazard_close as hc
import ui_utils as ui

DEAD_TAG = "dead"
HURT_TAG = "hurt"

# The sibling window keeps its own palette rather than importing one;
# these are the same two values it uses, for the same two meanings.
DIM = "#8a8a8a"
ALERT = "#a00000"


class HazardWindow(tk.Toplevel):
    """items/models as hazard_close takes them; on_apply(rows, entry) is
    called with the models to write back and the log field, or with
    ([], entry) when the player skips."""

    def __init__(self, master, items, models, name, on_apply):
        super().__init__(master)
        self.title(f"Hazardous - {name}")
        self.transient(master)
        self.on_apply = on_apply
        self.records = models
        self.items = list(items)
        self._recompute()
        self._done = False
        self.buttons = {}
        self._build(name)
        self.protocol("WM_DELETE_WINDOW", self._skip)
        ui.modal_grab(self)

    def _recompute(self):
        """Work the closing step out again from the items as they now
        stand. Cheap enough to redo on every change, which is why aim()
        hands back a copy instead of mutating: there is never a
        half-applied state to get out of."""
        self.result = hc.resolve(self.records, self.items)
        self.entry = hc.log_entry(self.items, self.result["rows"])

    # ---------- layout ----------

    def _build(self, name):
        owed = hc.total(self.items)
        head = ttk.Label(
            self, text=f"{name} owes {owed} mortal "
            f"wound{'' if owed == 1 else 's'} from HAZARDOUS.")
        head.pack(anchor=tk.W, padx=8, pady=(8, 0))
        ttk.Label(
            self, foreground=ui.HINT_COLOR, wraplength=520, justify=tk.LEFT,
            text="The tests are rolled after the unit has resolved all "
                 "of its attacks, so they are settled here rather than "
                 "weapon by weapon. Each lands on the model carrying "
                 "the weapon and spills to the rest of the unit if that "
                 "model is destroyed."
        ).pack(anchor=tk.W, padx=8, pady=(2, 6))

        panes = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        panes.pack(fill=tk.BOTH, expand=True, padx=8)
        panes.add(self._weapon_panel(panes), weight=1)
        panes.add(self._model_panel(panes), weight=1)
        self._w_iid = {}
        self._fill()
        self._buttons()

    def _weapon_panel(self, parent):
        frame = ttk.Frame(parent)
        self.weapons = ttk.Treeview(frame, columns=("dmg", "bearer"),
                                    height=6)
        self.weapons.heading("#0", text="Weapon that failed")
        self.weapons.heading("dmg", text="MW")
        self.weapons.heading("bearer", text="Lands on")
        self.weapons.column("dmg", width=44, anchor=tk.E, stretch=False)
        self.weapons.column("bearer", width=170)
        self.weapons.pack(fill=tk.BOTH, expand=True)
        return frame

    def _model_panel(self, parent):
        frame = ttk.Frame(parent)
        self.models = ttk.Treeview(frame, columns=("w",), height=6)
        self.models.heading("#0", text="Model")
        self.models.heading("w", text="Wounds")
        self.models.column("w", width=90, anchor=tk.CENTER, stretch=False)
        self.models.tag_configure(DEAD_TAG, foreground=DIM)
        self.models.tag_configure(HURT_TAG, font=ui.bold_font())
        self.models.pack(fill=tk.BOTH, expand=True)
        return frame

    def _refill(self):
        """Redraw both panels from the current items.

        The selection is put back: the row ids are stable across a
        redraw, and losing them would mean the player had to pick the
        weapon again to press Use the sequence after Send here.
        """
        keep = (self.weapons.selection(), self.models.selection())
        self.weapons.delete(*self.weapons.get_children(""))
        self.models.delete(*self.models.get_children(""))
        self._w_iid = {}
        self._fill()
        for tree, sel in zip((self.weapons, self.models), keep):
            back = [i for i in sel if tree.exists(i)]
            if back:
                tree.selection_set(*back)
        killed = self.entry["killed"]
        self.tally.configure(
            text=f"{killed} model{'' if killed == 1 else 's'} of the "
                 "attacking unit destroyed" if killed else "")

    def _aim(self):
        """Point the selected weapon's wounds at the selected model.

        The rules put these wherever any mortal wound goes, so this is
        a CHOICE and not a correction: the sequence stays the default
        and Clear puts it back.
        """
        w = self._picked(self.weapons, self._w_iid)
        m = self._picked(self.models, self._m_iid)
        if w is None or m is None:
            return
        self.items = hc.aim(self.items, w, m)
        self._recompute()
        self._refill()

    def _clear_aim(self):
        w = self._picked(self.weapons, self._w_iid)
        if w is None:
            return
        self.items = hc.aim(self.items, w, None)
        self._recompute()
        self._refill()

    @staticmethod
    def _picked(tree, table):
        sel = tree.selection()
        return table.get(sel[0]) if sel else None

    def _fill(self):
        rows = self.result["rows"]
        for item in self.items:
            bearer = item.get("bearer")
            # 'bearer' indexes the model list, and resolve() returns one
            # row per model in that same order, so it indexes the rows
            # too. None means the weapon could not be traced or its
            # whole group was already gone: the 06.02 sequence decides.
            target = item.get("target")
            if target is not None:
                where = rows[target]["label"]
            elif bearer is None:
                where = "the unit"
            else:
                where = f"the unit  (from {rows[bearer]['label']})"
            self.weapons.insert("", tk.END, iid=f"w{len(self._w_iid)}",
                                text=item["label"],
                                values=(item["damage"], where))
            self._w_iid[f"w{len(self._w_iid)}"] = len(self._w_iid)
        # EVERY model, not only the ones that change: the player picks
        # a target from this panel, so a model the sequence happens to
        # miss still has to be there to be pointed at.
        self._m_iid = {}
        for n, row in enumerate(rows):
            if row["dead"]:
                tags, note = (DEAD_TAG,), "   (destroyed)"
            elif row["after"] != row["before"]:
                tags, note = (HURT_TAG,), ""
            else:
                tags, note = (), ""
            iid = self.models.insert(
                "", tk.END, iid=f"m{n}", text=row["label"] + note,
                values=(f"{row['before']} -> {row['after']}",),
                tags=tags)
            if row["before"] > 0:
                self._m_iid[iid] = n
        if self.result["leftover"]:
            self.models.insert(
                "", tk.END, text=f"{self.result['leftover']} mortal "
                "wounds with no model left to take them", values=("",))

    def _buttons(self):
        aim = ttk.Frame(self)
        aim.pack(fill=tk.X, padx=8, pady=(4, 0))
        self.buttons["aim"] = ttk.Button(aim, text="Send here",
                                         command=self._aim)
        ui.tip(self.buttons["aim"],
               "Start the selected weapon's self-inflicted wounds on the "
               "selected model instead of where the rules would put them")
        self.buttons["aim"].pack(side=tk.LEFT)
        self.buttons["clear"] = ttk.Button(aim, text="Use the sequence",
                                           command=self._clear_aim)
        ui.tip(self.buttons["clear"],
               "Drop the aiming and let the wounds fall in the order the "
               "rules give")
        self.buttons["clear"].pack(side=tk.LEFT, padx=6)
        ttk.Label(aim, foreground=DIM, wraplength=460, justify=tk.LEFT,
                  text="Pick a weapon on the left and a model on the "
                       "right to choose where its wounds start. Left "
                       "alone they go where any mortal wound goes."
                  ).pack(side=tk.LEFT, padx=6)
        bar = ttk.Frame(self)
        bar.pack(fill=tk.X, padx=8, pady=8)
        self.buttons["apply"] = ttk.Button(bar, text="Apply",
                                           command=self._apply)
        ui.tip(self.buttons["apply"],
               "Take these self-inflicted wounds on the attacking unit")
        self.buttons["apply"].pack(side=tk.RIGHT)
        self.buttons["skip"] = ttk.Button(bar, text="Skip",
                                          command=self._skip)
        ui.tip(self.buttons["skip"],
               "Leave the attacking unit untouched (the wounds were "
               "already accounted for elsewhere)")
        self.buttons["skip"].pack(side=tk.RIGHT, padx=6)
        self.tally = ttk.Label(bar, foreground=ALERT)
        self.tally.pack(side=tk.LEFT)
        killed = self.entry["killed"]
        self.tally.configure(
            text=f"{killed} model{'' if killed == 1 else 's'} of the "
                 "attacking unit destroyed" if killed else "")

    # ---------- the two answers ----------

    def _apply(self):
        # 'after' is never negative: the allocation takes min(pool, what
        # the model has left) at every step, so it stops at zero rather
        # than going through it. Clamping here would be a guard that can
        # never fire, which reads as though it could.
        self._finish([{"key": r["key"], "wounds": r["after"],
                       "dead": r["dead"]}
                      for r in hc.changed(self.result["rows"])])

    def _skip(self):
        self._finish([])

    def _finish(self, rows):
        # Both buttons and the window manager's close box come here, so
        # the callback has to fire exactly once however the window went
        # away: applying the same wounds twice would take them off the
        # table twice.
        if self._done:
            return
        self._done = True
        self.on_apply(rows, self.entry)
        self.destroy()
