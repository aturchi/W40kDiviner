"""The attack log window of the game assistant.

A table of the attacks resolved so far (one row each) over the full
text of whichever row is selected; with nothing selected the pane shows
the running totals by defending unit, which is the thing actually asked
for across the table mid-game.

Everything shown here is produced by :mod:`attack_log`, which holds no
tkinter and is tested headless: this file only lays out widgets and
wires the buttons.
"""

import tkinter as tk
from tkinter import ttk, messagebox

import attack_log
import ui_utils as ui

# key, heading, width, anchor
COLUMNS = (("turn", "Turn", 46, tk.CENTER),
           ("time", "Time", 70, tk.CENTER),
           ("attacker", "Attacker", 180, tk.W),
           ("defender", "Defender", 180, tk.W),
           ("mode", "Mode", 90, tk.W),
           ("attacks", "Attacks", 62, tk.E),
           ("events", "Events", 58, tk.E),
           ("damage", "Damage", 62, tk.E),
           ("mortal", "of which MW", 84, tk.E),
           # Blank, not 0, when the allocation was never applied: the
           # two are different answers and the column must not merge
           # them.
           ("removed", "Removed", 70, tk.E))


class AttackLogWindow(tk.Toplevel):
    """Read-only view of an :class:`attack_log.AttackLog`, plus the few
    actions that edit it: start a new turn, delete a mis-clicked attack,
    clear the history, export."""

    def __init__(self, parent, log, on_change=None):
        super().__init__(parent)
        self.log = log
        self.on_change = on_change
        self.title("Attack log")
        self.geometry("940x580")

        bar = ttk.Frame(self)
        bar.pack(fill=tk.X, padx=6, pady=6)
        ttk.Button(bar, text="New turn",
                   command=self.cmd_new_turn).pack(side=tk.LEFT)
        self.turn_lbl = ttk.Label(bar, font=ui.bold_font())
        self.turn_lbl.pack(side=tk.LEFT, padx=8)
        ttk.Button(bar, text="Delete selected",
                   command=self.cmd_delete).pack(side=tk.LEFT, padx=3)
        ttk.Button(bar, text="Clear log",
                   command=self.cmd_clear).pack(side=tk.LEFT, padx=3)
        ttk.Button(bar, text="Close",
                   command=self.destroy).pack(side=tk.RIGHT)
        ttk.Button(bar, text="Save CSV...",
                   command=self.cmd_save_csv).pack(side=tk.RIGHT, padx=3)
        ttk.Button(bar, text="Save text...",
                   command=self.cmd_save_text).pack(side=tk.RIGHT, padx=3)
        ttk.Button(bar, text="Copy all",
                   command=self.cmd_copy).pack(side=tk.RIGHT, padx=3)

        pane = ttk.PanedWindow(self, orient=tk.VERTICAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))

        top = ttk.Frame(pane)
        pane.add(top, weight=3)
        self.tree = ttk.Treeview(top, columns=[c[0] for c in COLUMNS],
                                 show="tree headings", selectmode="extended")
        self.tree.heading("#0", text="#")
        self.tree.column("#0", width=50, anchor=tk.E, stretch=False)
        for key, head, width, anchor in COLUMNS:
            self.tree.heading(key, text=head)
            self.tree.column(key, width=width, anchor=anchor,
                             stretch=(key in ("attacker", "defender")))
        sb = ttk.Scrollbar(top, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._show_detail())

        bottom = ttk.Frame(pane)
        pane.add(bottom, weight=2)
        self.text = tk.Text(bottom, wrap=tk.NONE, height=12,
                            font=("TkFixedFont",))
        tsb = ttk.Scrollbar(bottom, orient=tk.VERTICAL,
                            command=self.text.yview)
        xsb = ttk.Scrollbar(bottom, orient=tk.HORIZONTAL,
                            command=self.text.xview)
        self.text.configure(yscrollcommand=tsb.set, xscrollcommand=xsb.set,
                            state=tk.DISABLED)
        # The lines are not wrapped (a wrapped context line would break
        # the alignment of the totals), so the pane needs both bars.
        xsb.pack(side=tk.BOTTOM, fill=tk.X)
        tsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.refresh()

    # ---------- display ----------

    @staticmethod
    def _removed_cell(entry) -> str:
        got = attack_log.allocation_totals(entry)
        if not got:
            return ""                     # never applied: not zero
        return (f"{got['removed']} ({got['killed']}\u2020)"
                if got["killed"] else str(got["removed"]))

    def refresh(self):
        """Rebuild the table from the log, keeping the selection where
        the rows it pointed at still exist."""
        keep = [iid for iid in self.tree.selection()]
        self.tree.delete(*self.tree.get_children())
        for e in self.log.entries:
            t = attack_log.entry_totals(e)
            mode = e.get("mode", "")
            if e.get("melee"):
                mode = f"{mode}: {e['melee']}"
            self.tree.insert("", tk.END, iid=str(e.get("seq")),
                             text=f"#{e.get('seq')}",
                             values=(e.get("turn"), e.get("time"),
                                     e.get("attacker"), e.get("defender"),
                                     mode, t["attacks"], t["events"],
                                     t["damage"], t["mortal"] or "",
                                     self._removed_cell(e)))
        keep = [iid for iid in keep if self.tree.exists(iid)]
        if keep:
            self.tree.selection_set(keep)
        else:
            children = self.tree.get_children()
            if children:
                self.tree.see(children[-1])
        self.turn_lbl.configure(text=f"Turn {self.log.turn}")
        self._show_detail()

    def _selected_entries(self) -> list:
        seqs = {int(iid) for iid in self.tree.selection()}
        return [e for e in self.log.entries
                if int(e.get("seq") or 0) in seqs]

    def _show_detail(self):
        """The selected attacks in full, or the running totals when
        nothing is selected."""
        picked = self._selected_entries()
        body = ("\n\n".join(attack_log.entry_text(e) for e in picked)
                if picked else attack_log.summary_text(self.log.entries))
        self.text.configure(state=tk.NORMAL)
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", body)
        self.text.configure(state=tk.DISABLED)

    def _changed(self):
        self.refresh()
        if self.on_change:
            self.on_change()

    # ---------- actions ----------

    def cmd_new_turn(self):
        """Advance the turn counter. It only groups the entries: the
        program has no turn concept of its own yet."""
        self.log.new_turn()
        self._changed()

    def cmd_delete(self):
        seqs = [int(iid) for iid in self.tree.selection()]
        if not seqs:
            messagebox.showinfo("Attack log", "Select the rows to delete.",
                                parent=self)
            return
        self.log.remove(seqs)
        self._changed()

    def cmd_clear(self):
        if not len(self.log):
            return
        if messagebox.askyesno("Attack log",
                               f"Delete all {len(self.log)} logged "
                               "attacks?", parent=self):
            self.log.clear()
            self._changed()

    def cmd_copy(self):
        self.clipboard_clear()
        self.clipboard_append(self.log.to_text())

    def cmd_save_text(self):
        ui.save_text(self, self.log.to_text(), title="Export attack log",
                     defaultextension=".txt",
                     filetypes=[("Text", "*.txt"), ("All files", "*.*")],
                     initialfile="attack_log.txt")

    def cmd_save_csv(self):
        ui.save_text(self, self.log.to_csv(), title="Export attack log",
                     defaultextension=".csv",
                     filetypes=[("CSV", "*.csv"), ("All files", "*.*")],
                     initialfile="attack_log.csv")


def open_log(parent, log, on_change=None, existing=None):
    """Open the log window, or bring the one already open to the front
    and refresh it (a second copy would show a stale table as soon as an
    attack was resolved). Returns the live window."""
    if existing is not None and existing.winfo_exists():
        existing.refresh()
        existing.deiconify()
        existing.lift()
        existing.focus_set()
        return existing
    return AttackLogWindow(parent, log, on_change)
