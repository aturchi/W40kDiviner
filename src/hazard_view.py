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
        self.items = list(items)
        self.result = hc.resolve(models, self.items)
        self.entry = hc.log_entry(self.items, self.result["rows"])
        self._done = False
        self.buttons = {}
        self._build(name)
        self.protocol("WM_DELETE_WINDOW", self._skip)
        self.grab_set()

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

    def _fill(self):
        rows = self.result["rows"]
        for item in self.items:
            bearer = item.get("bearer")
            # 'bearer' indexes the model list, and resolve() returns one
            # row per model in that same order, so it indexes the rows
            # too. None means the weapon could not be traced or its
            # whole group was already gone: the 06.02 sequence decides.
            where = ("the unit" if bearer is None
                     else rows[bearer]["label"])
            self.weapons.insert("", tk.END, text=item["label"],
                                values=(item["damage"], where))
        for row in rows:
            if row["after"] == row["before"]:
                continue
            tags = (DEAD_TAG,) if row["dead"] else (HURT_TAG,)
            self.models.insert(
                "", tk.END, iid=str(row["key"]),
                text=row["label"] + ("   (destroyed)" if row["dead"]
                                     else ""),
                values=(f"{row['before']} -> {row['after']}",),
                tags=tags)
        if self.result["leftover"]:
            self.models.insert(
                "", tk.END, text=f"{self.result['leftover']} mortal "
                "wounds with no model left to take them", values=("",))

    def _buttons(self):
        bar = ttk.Frame(self)
        bar.pack(fill=tk.X, padx=8, pady=8)
        self.buttons["apply"] = ttk.Button(bar, text="Apply",
                                           command=self._apply)
        self.buttons["apply"].pack(side=tk.RIGHT)
        self.buttons["skip"] = ttk.Button(bar, text="Skip",
                                          command=self._skip)
        self.buttons["skip"].pack(side=tk.RIGHT, padx=6)
        killed = self.entry["killed"]
        if killed:
            ttk.Label(bar, foreground=ALERT,
                      text=f"{killed} model{'' if killed == 1 else 's'} "
                           "of the attacking unit destroyed").pack(
                side=tk.LEFT)

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
