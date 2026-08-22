"""The assisted-allocation dialog of the game assistant.

Shows what the attack has to take off the defending unit, the model by
model proposal that follows from the rules (see :mod:`allocation`), and
lets the player change the two things the program cannot know: the
ORDER models take damage in - there is no 'champion' flag in the
profiles, so the Shas'ui is kept alive by moving it down - and, when
the table decided something odd, the resulting wounds themselves.

Nothing is written anywhere until Apply: the caller gets the final rows
and does the writing (in the game assistant, as a single undo step).
"""

import tkinter as tk
from tkinter import ttk

import allocation

COLUMNS = (("before", "Wounds", 62, tk.E),
           ("damage", "Damage", 62, tk.E),
           ("after", "Left", 52, tk.E),
           ("status", "", 90, tk.W))

MANUAL_TAG = "manual"
DEAD_TAG = "dead"


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
        self.plan = None

        t = allocation.totals(self.events)
        ttk.Label(self, font=("TkDefaultFont", 10, "bold"), text=(
            f"{t['events']} damaging attacks, {t['damage']} damage to "
            f"allocate onto {defender_name}")).pack(anchor=tk.W, padx=8,
                                                    pady=(8, 0))
        ttk.Label(self, foreground="#444444", text=self._events_line(t)
                  ).pack(anchor=tk.W, padx=8)
        self.hint_lbl = ttk.Label(self, foreground="#7a4a00",
                                  wraplength=600, justify=tk.LEFT)
        self.hint_lbl.pack(anchor=tk.W, padx=8, pady=(4, 4))

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
        sb = ttk.Scrollbar(frame, orient=tk.VERTICAL,
                           command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree.bind("<Double-1>", self._edit_cell)

        self.summary_lbl = ttk.Label(self, font=("TkDefaultFont", 10,
                                                 "bold"))
        self.summary_lbl.pack(anchor=tk.W, padx=8, pady=(4, 0))
        ttk.Label(self, foreground="#666666", text=(
            "Move a model down to keep it alive; double-click 'Left' to "
            "type a number yourself.")).pack(anchor=tk.W, padx=8)

        bar = ttk.Frame(self)
        bar.pack(fill=tk.X, padx=8, pady=8)
        ttk.Button(bar, text="Move up",
                   command=lambda: self._move(-1)).pack(side=tk.LEFT)
        ttk.Button(bar, text="Move down",
                   command=lambda: self._move(1)).pack(side=tk.LEFT, padx=3)
        ttk.Button(bar, text="Recompute",
                   command=self._reset).pack(side=tk.LEFT, padx=3)
        ttk.Button(bar, text="Cancel",
                   command=self.destroy).pack(side=tk.RIGHT)
        ttk.Button(bar, text="Apply",
                   command=self._apply).pack(side=tk.RIGHT, padx=3)

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
        # shown in the order the damage lands, not in table order
        index = {c["iid"]: i for i, c in enumerate(self.copies)}
        return sorted(rows, key=lambda r: self.order.index(index[r["iid"]]))

    def _recompute(self):
        self.plan = allocation.allocate(self.copies, self.events,
                                        self.order)
        self.hint_lbl.configure(text="\n".join(
            "\u2022 " + h for h in allocation.hints(
                self.events, self.copies, self.plan)))
        keep = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for r in self._rows():
            tags = ()
            if r.get("manual"):
                tags = (MANUAL_TAG,)
            elif r["dead"]:
                tags = (DEAD_TAG,)
            status = "DESTROYED" if r["dead"] else (
                "hand-typed" if r.get("manual") else
                ("wounded" if r["after"] < r["max"] else ""))
            self.tree.insert("", tk.END, iid=r["iid"], text=r["label"],
                             values=(f"{r['before']}/{r['max']}",
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

    def _reset(self):
        self.manual = {}
        self._recompute()

    def _edit_cell(self, event):
        """Double-click on 'Left' types the resulting wounds by hand."""
        iid = self.tree.identify_row(event.y)
        if not iid or self.tree.identify_column(event.x) != "#3":
            return
        x, y, w, h = self.tree.bbox(iid, "#3")
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
