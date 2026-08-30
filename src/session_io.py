"""Session save/load shared by the attack analyzer and the game assistant.

A session file is plain JSON (small, diffable, no extra dependency).
Each program uses its own extension - .w40kana for the attack analyzer,
.w40kgame for the game assistant - so the file dialogs never offer the
other program's sessions; the wrapper itself is identical:

    {"format": "w40k-session/1",
     "program": "attack_analyzer" | "game_assistant",
     "state": {...}}                # shape decided by the program

'state' always embeds the roster data itself, so a session reopens even
if the source JSON files have moved or changed. The 'program' field is
checked on load, because the two states are not interchangeable.

Tkinter is imported lazily inside the GUI helpers so that the file
format and the join-rebuilding logic stay importable (and testable)
headless.
"""

import json

FORMAT_TAG = "w40k-session/1"

# One extension per program: the two states are not interchangeable, so
# the file dialogs must not offer the other program's sessions in the
# first place (the 'program' field below is still the real guard).
PROGRAM_EXT = {"attack_analyzer": ".w40kana",
               "game_assistant": ".w40kgame"}
PROGRAM_LABEL = {"attack_analyzer": "Analyzer session",
                 "game_assistant": "Game session"}
EXT = ".w40k"                 # generic fallback for an unknown program


def ext_for(program: str) -> str:
    """File extension used by 'program' for its session files."""
    return PROGRAM_EXT.get(program, EXT)


def filetypes_for(program: str) -> list:
    """File dialog filter for 'program' sessions: ONLY that program's
    extension. No "All files" entry on purpose - it would put the other
    program's sessions back in the dialog through the filter dropdown,
    and a session saved without the right extension would then be
    invisible to its own Load. A file renamed by hand can still be
    passed to load(), which reports the mismatch."""
    return [(PROGRAM_LABEL.get(program, "W40k session"),
             "*" + ext_for(program))]


class SessionError(Exception):
    """Unusable session file: wrong format tag, wrong program, or no
    state."""


# ---------------- file format (no tkinter) ----------------


def save(path, program: str, state: dict):
    """Write one session file. 'state' must be JSON-serialisable."""
    payload = {"format": FORMAT_TAG, "program": program, "state": state}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1)


def load(path, program: str) -> dict:
    """Read a session file saved by 'program'; raises SessionError when
    the file is not a session of that program."""
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict) or payload.get("format") != FORMAT_TAG:
        raise SessionError(f"Not a {FORMAT_TAG} file.")
    if payload.get("program") != program:
        raise SessionError(
            f"This session was saved by '{payload.get('program')}', "
            f"not by '{program}'.")
    state = payload.get("state")
    if not isinstance(state, dict):
        raise SessionError("The session file carries no state.")
    return state


# ---------------- joins as plain records (no tkinter) ----------------


def _as_list(x):
    """None / one object / a list -> a list. A slot used to hold at most
    one helper and now holds several, so both shapes are accepted."""
    if x is None:
        return []
    return list(x) if isinstance(x, (list, tuple)) else [x]


def _names(helpers):
    """Helper names in the most compact form: None / one name / a list.
    Keeps session files written before multi-slot support readable, and
    keeps writing the old shape whenever a slot holds a single helper."""
    names = [u.name for u in _as_list(helpers)]
    return None if not names else (names[0] if len(names) == 1 else names)


def joined_records(joined) -> list:
    """[(combined, leaders, unit, supports)] -> [{'unit','leader',
    'support'}] with names only: the Unit objects are rebuilt from the
    roster on load, so nothing about the profiles is duplicated in the
    file. 'leaders'/'supports' may be a single Unit or a list."""
    return [{"unit": unit.name, "leader": _names(leaders),
             "support": _names(supports)}
            for _combined, leaders, unit, supports in joined]


def rebuild_joins(records, leaders, others, supports):
    """Inverse of joined_records against the current unit pools.
    Returns (joined, missing): 'joined' holds the (combined, leader,
    unit, support) tuples that could be rebuilt, 'missing' the labels of
    the records whose parts are gone or no longer compatible (a roster
    can legitimately change between sessions)."""
    def find(pool, name):
        return next((u for u in pool if u.name == name), None)

    joined, missing = [], []
    for rec in records or []:
        base = find(others, rec.get("unit"))
        want_l = _as_list(rec.get("leader"))
        want_s = _as_list(rec.get("support"))
        found_l = [find(leaders, n) for n in want_l]
        found_s = [find(supports, n) for n in want_s]
        label = " + ".join([x for x in [rec.get("unit")] if x]
                           + want_l + want_s)
        if base is None or None in found_l or None in found_s:
            missing.append(label)
            continue
        combined, ok = base, True
        for ld in found_l:
            if not combined.can_attach(ld):
                ok = False
                break
            combined = combined.attach_leader(ld)
        for sp in found_s if ok else []:
            if not combined.can_support(sp):
                ok = False
                break
            combined = combined.attach_support(sp)
        if not ok:
            missing.append(label)
            continue
        joined.append((combined, found_l, base, found_s))
    return joined, missing


# ---------------- GUI helpers (tkinter imported lazily) ----------------


def ask_save_or_load(parent, title="Session"):
    """Modal chooser behind the single Save/load button.
    Returns 'save', 'load' or None (cancelled)."""
    import tkinter as tk
    from tkinter import ttk
    import ui_utils as ui

    dlg = tk.Toplevel(parent)
    dlg.title(title)
    dlg.transient(parent)
    dlg.resizable(False, False)
    choice = {"value": None}
    ttk.Label(dlg, text="Save the current armies to a file, or load a "
                        "previously saved session?").pack(padx=12, pady=10)
    row = ttk.Frame(dlg)
    row.pack(pady=(0, 10))

    def pick(value):
        choice["value"] = value
        dlg.destroy()

    ui.tip(ttk.Button(row, text="Save session",
                      command=lambda: pick("save")),
           "Write the current state to a session file"
           ).pack(side=tk.LEFT, padx=6)
    ui.tip(ttk.Button(row, text="Load session",
                      command=lambda: pick("load")),
           "Read a session file back, replacing what is loaded now"
           ).pack(side=tk.LEFT, padx=6)
    ttk.Button(row, text="Cancel",
               command=dlg.destroy).pack(side=tk.LEFT, padx=6)
    dlg.grab_set()
    parent.wait_window(dlg)
    return choice["value"]


def run(parent, program: str, get_state, apply_state, title="Session"):
    """The whole one-button flow: ask save or load, pick the file, then
    save get_state() or feed the loaded state to apply_state(). Errors
    are reported in a message box. Returns the path used, or None.

    get_state() may return None to abort a save (e.g. nothing loaded)
    after showing its own message."""
    from tkinter import filedialog, messagebox

    what = ask_save_or_load(parent, title)
    if what is None:
        return None
    if what == "save":
        state = get_state()
        if state is None:
            return None
        path = filedialog.asksaveasfilename(
            title="Save session", defaultextension=ext_for(program),
            filetypes=filetypes_for(program), parent=parent)
        if not path:
            return None
        try:
            save(path, program, state)
        except OSError as exc:
            messagebox.showerror("Save failed", str(exc), parent=parent)
            return None
        return path
    path = filedialog.askopenfilename(
        title="Load session", filetypes=filetypes_for(program),
        parent=parent)
    if not path:
        return None
    try:
        state = load(path, program)
    except (OSError, ValueError, SessionError) as exc:
        messagebox.showerror("Load failed", str(exc), parent=parent)
        return None
    try:
        apply_state(state)
    except Exception as exc:                # malformed but well-tagged file
        messagebox.showerror("Load failed",
                             f"The session could not be restored: {exc}",
                             parent=parent)
        return None
    return path
