"""Undo / redo for the game assistant's table.

A model gets masked with the wrong row selected, or a wounds box gets a
typo, and there is currently no way back except remembering what the
number was. This module holds the history of those edits.

It is deliberately dumb about the table itself: an ACTION is a label
plus a list of CHANGES, and a change is only ``(side, row id, field,
old value, new value)``. Applying one is the caller's job, through a
setter it passes in - which keeps every piece of tkinter out of here,
and means undo and redo are the same code walking the same list in
opposite directions rather than two implementations that can disagree.

Two rules worth stating:

* **No-op changes are dropped** when the action is built, and an action
  left with no change at all is not pushed. Committing an entry box
  fires twice (Return, then FocusOut), and without this the stack would
  fill up with edits that change nothing - each of them one Ctrl-Z that
  appears to do nothing at all.
* **A new action clears the redo branch**, the usual convention: once
  the history has been rewritten, the future that was undone no longer
  belongs to it.

The stack is NOT saved in the session: it describes edits to a table
that a session load rebuilds from scratch, so its row ids would point
at rows that no longer exist.
"""

MAX_DEPTH = 100


def change(side, iid, field, old, new) -> dict:
    """One cell that changed. 'field' is whatever the caller's setter
    understands ('masked', 'wounds'); the values are stored as given."""
    return {"side": side, "iid": iid, "field": field,
            "old": old, "new": new}


def action(label, changes):
    """An action, or None when nothing actually changed. Changes whose
    old and new values are equal are dropped (see the module docstring)."""
    real = [c for c in changes if c["old"] != c["new"]]
    return {"label": str(label), "changes": real} if real else None


def apply_action(act: dict, setter, undo: bool = True) -> list:
    """Walk an action's changes through 'setter', which is called as
    ``setter(side, iid, field, value)`` and returns False when the row
    is gone. Undo replays the OLD values in reverse order, redo the NEW
    ones in the original order - reverse, because two changes to the
    same cell in one action must unwind in the order they were made.

    Returns the [(side, iid)] actually touched, so the caller can put
    them back in view."""
    changes = act.get("changes") or []
    key = "old" if undo else "new"
    touched = []
    for c in (reversed(changes) if undo else changes):
        if setter(c["side"], c["iid"], c["field"], c[key]) is not False:
            touched.append((c["side"], c["iid"]))
    return touched


class UndoStack:
    """Bounded undo history with a redo branch."""

    def __init__(self, limit: int = MAX_DEPTH):
        self.limit = max(1, int(limit))
        self._undo = []
        self._redo = []

    # ---------- writing ----------

    def push(self, act) -> bool:
        """Record an action (None is ignored, so the caller can pass the
        result of :func:`action` straight in). Clears the redo branch."""
        if not act or not act.get("changes"):
            return False
        self._undo.append(act)
        del self._undo[:-self.limit]
        self._redo = []
        return True

    def push_changes(self, label, changes) -> bool:
        return self.push(action(label, changes))

    def clear(self):
        """Forget everything. Called whenever the table is rebuilt from
        the roster (a load, a session restore): the row ids in the
        history would then point at rows that no longer mean the same."""
        self._undo, self._redo = [], []

    # ---------- moving ----------

    def undo(self):
        """Pop the last action onto the redo branch and return it (the
        caller applies its OLD values), or None."""
        if not self._undo:
            return None
        act = self._undo.pop()
        self._redo.append(act)
        return act

    def redo(self):
        """Reverse of :meth:`undo`; the caller applies the NEW values."""
        if not self._redo:
            return None
        act = self._redo.pop()
        self._undo.append(act)
        return act

    # ---------- reading ----------

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo_label(self) -> str:
        return self._undo[-1]["label"] if self._undo else ""

    def redo_label(self) -> str:
        return self._redo[-1]["label"] if self._redo else ""

    def __len__(self):
        return len(self._undo)


def rows_label(verb: str, n: int) -> str:
    """'mask 3 rows' / 'unmask 1 row': the wording of an action that hit
    a whole selection."""
    return f"{verb} {n} row" + ("" if n == 1 else "s")
