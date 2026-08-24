"""The assisted-allocation dialog of the game assistant.

Shows what the attack has to take off the defending unit, the model by
model proposal that follows from the rules (see :mod:`allocation`), and
lets the player change the three things the program cannot know: the
ORDER models take damage in - there is no 'champion' flag in the
profiles, so the Shas'ui is kept alive by moving it down - whether a
PRECISION attack is being sent to the attached CHARACTER, which the
proposal never assumes because it is a choice and often a bad one, and,
when the table decided something odd, the resulting wounds themselves.

Nothing is written anywhere until Apply: the caller gets the final rows
and does the writing (in the game assistant, as a single undo step).
"""

import tkinter as tk
from tkinter import ttk

import allocation
import ui_utils as ui

# The '#' column is the position in the order the PLAYER chose, which
# is not the row order: the table is sorted by the order the damage
# really lands in (allocation.landing_order), and the two differ
# whenever the wounded-first rule or the character protection steps in.
# Without the column, Move up/down would sometimes appear to do nothing.
COLUMNS = (("pick", "#", 34, tk.E),
           ("before", "Wounds", 62, tk.E),
           ("damage", "Damage", 62, tk.E),
           ("after", "Left", 52, tk.E),
           ("status", "", 90, tk.W))

# Treeview column ids are positional ('#0' is the tree column), so they
# are derived rather than written out: adding a column must not silently
# move the one the double-click edits.
_AFTER_COL = "#%d" % (1 + [c[0] for c in COLUMNS].index("after"))

MANUAL_TAG = "manual"
DEAD_TAG = "dead"
PROTECT_TAG = "protected"


class AllocationDialog(tk.Toplevel):
    """copies: [{'iid', 'label', 'wounds', 'max'}] in table order;
    events: allocation.events_from_results(...); on_apply(rows) is
    called with the rows that changed."""

    def __init__(self, parent, defender_name, copies, events, on_apply):
        super().__init__(parent)
        self.title(f"Apply damage - {defender_name}")
        self.geometry("640x520")
        self.transient(parent)
        self.copies = list(copies)
        self.events = list(events)
        self.on_apply = on_apply
        self.order = list(range(len(self.copies)))
        self.manual = {}                  # iid -> wounds typed by hand
        # Rows whose CHARACTER protection the player has lifted, which
        # is the only way a PRECISION attack reaches the character: the
        # proposal never does it by itself.
        self.allowed = set()
        self.plan = None

        t = allocation.totals(self.events)
        ttk.Label(self, font=ui.bold_font(), text=(
            f"{t['events']} damaging attacks, {t['damage']} damage to "
            f"allocate onto {defender_name}")).pack(anchor=tk.W, padx=8,
                                                    pady=(8, 0))
        ttk.Label(self, foreground="#444444", text=self._events_line(t)
                  ).pack(anchor=tk.W, padx=8)
        self.hint_lbl = ttk.Label(self, foreground="#7a4a00",
                                  wraplength=600, justify=tk.LEFT)
        self.hint_lbl.pack(anchor=tk.W, padx=8, pady=(4, 4))

        # Everything below the tree is packed BEFORE it, against the
        # bottom, and therefore in reverse: pack() satisfies requested
        # sizes in packing order, so a tree with expand=True on a short
        # window would otherwise eat the space these three need - and
        # the buttons, packed last, would come out as captionless
        # slivers. side=BOTTOM reserves their height first.
        bar = ttk.Frame(self)
        bar.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=8)
        ttk.Button(bar, text="Move up",
                   command=lambda: self._move(-1)).pack(side=tk.LEFT)
        ttk.Button(bar, text="Move down",
                   command=lambda: self._move(1)).pack(side=tk.LEFT, padx=3)
        ttk.Button(bar, text="Allow character",
                   command=self._toggle_allowed).pack(side=tk.LEFT,
                                                      padx=3)
        ttk.Button(bar, text="Recompute",
                   command=self._reset).pack(side=tk.LEFT, padx=3)
        ttk.Button(bar, text="Cancel",
                   command=self.destroy).pack(side=tk.RIGHT)
        ttk.Button(bar, text="Apply",
                   command=self._apply).pack(side=tk.RIGHT, padx=3)

        ttk.Label(self, foreground="#666666", wraplength=600,
                  justify=tk.LEFT, text=(
                      "Rows are in the order the damage lands. '#' is "
                      "the order you chose, which Move up/down changes: "
                      "the rules can still put a wounded model first. "
                      "Double-click 'Left' to type a number yourself; "
                      "'Allow character' lets a PRECISION attack reach "
                      "an attached character.")).pack(side=tk.BOTTOM,
                                                      anchor=tk.W, padx=8)
        self.summary_lbl = ttk.Label(self, font=ui.bold_font())
        self.summary_lbl.pack(side=tk.BOTTOM, anchor=tk.W, padx=8,
                              pady=(4, 0))

        frame = ttk.Frame(self)
        frame.pack(fill=tk.BOTH, expand=True, padx=8)
        self.tree = ttk.Treeview(frame, columns=[c[0] for c in COLUMNS],
                                 show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="Model (damage lands top down)")
        self.tree.column("#0", width=240)
        for key, head, width, anchor in COLUMNS:
            self.tree.heading(key, text=head)
            self.tree.column(key, width=width, anchor=anchor,
                             stretch=(key == "status"))
        self.tree.tag_configure(DEAD_TAG, foreground="#a00000")
        self.tree.tag_configure(MANUAL_TAG, foreground="#00559b")
        self.tree.tag_configure(PROTECT_TAG, foreground="#777777")
        sb = ttk.Scrollbar(frame, orient=tk.VERTICAL,
                           command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree.bind("<Double-1>", self._edit_cell)

        self._recompute()

    # ---------- display ----------

    @staticmethod
    def _events_line(t) -> str:
        bits = []
        if t["plain_events"]:
            bits.append(f"{t['plain']} normal damage in "
                        f"{t['plain_events']} attacks")
        if t["dev_events"]:
            bits.append(f"{t['devastating']} devastating")
        if t["spill"]:
            bits.append(f"{t['spill']} mortal (spilling)")
        return "  |  ".join(bits) or "nothing to allocate"

    def _copies(self) -> list:
        """The copies as the arithmetic must see them: the character
        protection is lifted on the rows the player allowed."""
        out = []
        for c in self.copies:
            if c.get("protected") and c["iid"] in self.allowed:
                c = dict(c, protected=False)
            out.append(c)
        return out

    def _rows(self) -> list:
        """The proposal with the hand-typed values written over it."""
        rows = []
        for st in self.plan["state"]:
            st = dict(st)
            if st["iid"] in self.manual:
                st["after"] = self.manual[st["iid"]]
                st["damage"] = st["before"] - st["after"]
                st["dead"] = st["after"] <= 0 and st["before"] > 0
                st["manual"] = True
            rows.append(st)
        # Shown in the order the damage really lands, which the chosen
        # order only sometimes matches (see allocation.landing_order).
        index = {c["iid"]: i for i, c in enumerate(self.copies)}
        landing = allocation.landing_order(self.plan, self.order)
        return sorted(rows, key=lambda r: landing.index(index[r["iid"]]))

    def _recompute(self):
        copies = self._copies()
        self.plan = allocation.allocate(copies, self.events, self.order)
        self.hint_lbl.configure(text="\n".join(
            "\u2022 " + h for h in allocation.hints(
                self.events, copies, self.plan)))
        keep = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        base = {c["iid"]: bool(c.get("protected")) for c in self.copies}
        pick = {self.copies[i]["iid"]: n
                for n, i in enumerate(self.order, start=1)}
        for r in self._rows():
            tags = ()
            if r.get("manual"):
                tags = (MANUAL_TAG,)
            elif r["dead"]:
                tags = (DEAD_TAG,)
            elif r.get("protected"):
                tags = (PROTECT_TAG,)
            status = "DESTROYED" if r["dead"] else (
                "hand-typed" if r.get("manual") else
                ("wounded" if r["after"] < r["max"] else ""))
            # The marker says both that the row IS a character and
            # whether its protection is currently lifted: a player who
            # allowed one two clicks ago must not have to remember.
            mark = ""
            if base.get(r["iid"]):
                mark = ("  [CHARACTER - allowed]" if not r.get("protected")
                        else "  [CHARACTER]")
            self.tree.insert("", tk.END, iid=r["iid"],
                             text=r["label"] + mark,
                             values=(pick.get(r["iid"], ""),
                                     f"{r['before']}/{r['max']}",
                                     r["damage"] or "", r["after"], status),
                             tags=tags)
        keep = [i for i in keep if self.tree.exists(i)]
        if keep:
            self.tree.selection_set(keep)
        self._refresh_summary()

    def _refresh_summary(self):
        rows = self._rows()
        text = (f"{sum(1 for r in rows if r['dead'])} models destroyed, "
                f"{sum(r['damage'] for r in rows)} wounds removed")
        if self.manual:
            text += f"   ({len(self.manual)} rows typed by hand)"
        else:
            if self.plan["wasted"]:
                text += f", {self.plan['wasted']} wasted on destroyed models"
            if self.plan["leftover"]:
                text += f", {self.plan['leftover']} left over"
        self.summary_lbl.configure(text=text)

    # ---------- actions ----------

    def _move(self, delta):
        """Move the selected model up or down the allocation order. Any
        hand-typed value is dropped: it belonged to a different order."""
        sel = self.tree.selection()
        if not sel:
            return
        index = {c["iid"]: i for i, c in enumerate(self.copies)}
        i = index.get(sel[0])
        if i is None:
            return
        pos = self.order.index(i)
        new = pos + delta
        if not 0 <= new < len(self.order):
            return
        self.order[pos], self.order[new] = self.order[new], self.order[pos]
        self.manual = {}
        self._recompute()
        self.tree.selection_set(sel[0])

    def _toggle_allowed(self):
        """Lift (or restore) the CHARACTER protection on the selected
        row. Does nothing on a row that is not a character: there is
        nothing to lift, and silently allowing an ordinary model would
        be a rules change hidden behind a button."""
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        if not any(c["iid"] == iid and c.get("protected")
                   for c in self.copies):
            return
        self.allowed.symmetric_difference_update({iid})
        # The hand-typed values belonged to the previous allocation.
        self.manual = {}
        self._recompute()
        self.tree.selection_set(iid)

    def _reset(self):
        self.manual = {}
        self.allowed = set()
        self._recompute()

    def _edit_cell(self, event):
        """Double-click on 'Left' types the resulting wounds by hand."""
        iid = self.tree.identify_row(event.y)
        if not iid or self.tree.identify_column(event.x) != _AFTER_COL:
            return
        x, y, w, h = self.tree.bbox(iid, _AFTER_COL)
        old = str(self.tree.set(iid, "after"))
        box = tk.Entry(self.tree, width=5)
        box.insert(0, old)
        box.place(x=x, y=y, width=w, height=h)
        box.focus_set()
        done = {"yet": False}
        cap = next((c.get("max") or 1 for c in self.copies
                    if c["iid"] == iid), 1)

        def commit(_e=None):
            if done["yet"]:
                return
            done["yet"] = True
            text = box.get().strip()
            box.destroy()
            try:
                n = min(int(cap), max(0, int(text)))
            except ValueError:
                return
            self.manual[iid] = n
            self._recompute()
        box.bind("<Return>", commit)
        box.bind("<FocusOut>", commit)

    def _apply(self):
        """Hand back the rows whose wounds changed and close."""
        changed = [r for r in self._rows() if r["after"] != r["before"]]
        self.destroy()
        if changed and self.on_apply:
            self.on_apply(changed)
