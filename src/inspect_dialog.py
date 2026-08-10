"""Interactive inspect window (analyzer + game assistant).

Shows a unit's full profile and, at the bottom, a checkbox per ability
that toggles its 'enabled' flag live. The toggles act on the ability
DICTS passed in, so the caller decides persistence:

- game assistant passes the roster's native dicts -> the change sticks
  for the session (rebuilt units re-read the same dicts), but is not
  saved to file;
- analyzer passes the loaded unit's ability dicts -> same, session-only.

Neither writes to disk: only the profile editor persists 'enabled'.
"""

import tkinter as tk
from tkinter import ttk

import leader_core as lc
from leader_core import (iter_ability_dicts as _iter_ability_dicts,  # noqa: F401
                         ability_dicts_of_unit)  # noqa: F401


def open_inspect(parent, unit_obj, ability_dicts=None, on_toggle=None):
    """Open the inspect window for a Unit object. When ability_dicts is
    given (list of native ability dicts), an enable/disable checkbox is
    shown per ability; on_toggle() is called after each change so the
    caller can refresh anything that depends on it."""
    win = tk.Toplevel(parent)
    win.title(f"Inspect - {unit_obj.name}")

    txt = tk.Text(win, wrap=tk.WORD, width=86, height=26)
    txt.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
    txt.insert(tk.END, lc.unit_inspect_text(unit_obj))
    txt.configure(state=tk.DISABLED)

    if not ability_dicts:
        return win

    frame = ttk.LabelFrame(win, text="Abilities (uncheck to disable for "
                                     "this session)")
    frame.pack(fill=tk.BOTH, expand=False, padx=6, pady=(0, 6))
    canvas = tk.Canvas(frame, height=160)
    sb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=canvas.yview)
    inner = ttk.Frame(canvas)
    inner.bind("<Configure>",
               lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=inner, anchor="nw")
    canvas.configure(yscrollcommand=sb.set)
    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    sb.pack(side=tk.RIGHT, fill=tk.Y)

    for scope, ab in _iter_ability_dicts_from_list(ability_dicts):
        var = tk.BooleanVar(value=bool(ab.get("enabled", True)))

        def _cb(a=ab, v=var):
            a["enabled"] = bool(v.get())
            if on_toggle is not None:
                on_toggle()

        desc = (ab.get("description") or "<no description>")[:60]
        ttk.Checkbutton(inner, variable=var,
                        text=f"[{scope}] {desc}",
                        command=_cb).pack(anchor=tk.W, padx=4)
    return win


def _iter_ability_dicts_from_list(ability_dicts):
    """ability_dicts may be a native unit dict or a pre-built list of
    (scope, dict) pairs; normalise to pairs."""
    if isinstance(ability_dicts, dict):
        yield from _iter_ability_dicts(ability_dicts)
    else:
        for item in ability_dicts:
            if isinstance(item, tuple):
                yield item
            else:
                yield ("ability", item)
